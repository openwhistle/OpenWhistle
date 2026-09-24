"""v1.6.0 design: the findings of the assessment, pinned in rendered HTML and sources."""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import pyotp
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import AdminRole, AdminUser
from app.services.auth import hash_password

ROOT = Path(__file__).parents[1]
TEMPLATES = ROOT / "app/templates"
_PASSWORD = "V160-Design-Password"  # noqa: S105


async def _login(client: AsyncClient, db: AsyncSession, role: AdminRole) -> None:
    secret = pyotp.random_base32()
    user = AdminUser(
        id=uuid.uuid4(),
        username=f"des_{uuid.uuid4().hex[:8]}",
        password_hash=hash_password(_PASSWORD),
        totp_secret=secret,
        totp_enabled=True,
        role=role,
    )
    db.add(user)
    await db.commit()
    await client.get("/admin/login")
    r = await client.post(
        "/admin/login",
        data={
            "username": user.username,
            "password": _PASSWORD,
            "csrf_token": client.cookies.get("ow_csrf"),
        },
    )
    temp = re.search(r'name="temp_token" value="([^"]+)"', r.text)
    assert temp
    await client.post(
        "/admin/login/mfa",
        data={
            "csrf_token": client.cookies.get("ow_csrf"),
            "temp_token": temp.group(1),
            "totp_code": pyotp.TOTP(secret).now(),
        },
    )


def test_admin_navigation_lives_in_one_template() -> None:
    owners = [p.name for p in (TEMPLATES / "admin").glob("*.html") if "admin-nav" in p.read_text()]
    assert owners == ["_layout.html"]
    assert not [
        p.name
        for p in (TEMPLATES / "admin").glob("*.html")
        if "block nav_links" in p.read_text() and p.name != "_layout.html"
    ]


@pytest.mark.asyncio
async def test_case_manager_sees_only_pages_they_may_open(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login(client, db_session, AdminRole.case_manager)
    html = (await client.get("/admin/dashboard")).text
    nav = html.split('class="admin-nav"', 1)[1].split("</nav>", 1)[0]
    for forbidden in ("/admin/users", "/admin/audit-log", "/admin/system", "/admin/categories"):
        assert forbidden not in nav
    assert "/admin/dashboard" in nav


@pytest.mark.asyncio
async def test_admin_sees_configuration_and_administration(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login(client, db_session, AdminRole.admin)
    nav = (await client.get("/admin/users")).text.split('class="admin-nav"', 1)[1]
    for link in ("/admin/users", "/admin/audit-log", "/admin/system", "/admin/categories"):
        assert link in nav
    assert "/admin/organisations" not in nav.split("</nav>", 1)[0]


@pytest.mark.asyncio
async def test_footer_and_demo_banner_use_lists_not_middots(client: AsyncClient) -> None:
    html = (await client.get("/submit")).text
    footer = html.split('<footer', 1)[1]
    assert "&middot;" not in footer and "·" not in footer
    assert 'class="footer-links"' in footer


@pytest.mark.asyncio
async def test_theme_toggle_is_an_icon_with_a_translated_name(client: AsyncClient) -> None:
    client.cookies.set("ow-lang", "de")
    html = (await client.get("/submit")).text
    button = html.split('id="theme-toggle"', 1)[1].split("</button>", 1)[0]
    assert "<svg" in button and "◑" not in button
    assert 'aria-pressed="false"' in button
    assert 'aria-label="Dunkelmodus"' in button


def test_site_js_has_no_english_ui_strings() -> None:
    js = (ROOT / "app/static/js/site.js").read_text()
    for text in ("Light", "Dark", "Please wait", "Switch to"):
        assert text not in js, text


_PICTOGRAPH = re.compile(
    "[⌀-⏿■-◿☀-➿⬀-⯿\U0001f000-\U0001faff]"
    r"|&#(?:9[0-9]{3}|1[0-9]{4}|12[0-9]{4});"
)


def test_no_emoji_or_symbol_glyphs_as_icons() -> None:
    hits = {
        str(p.relative_to(ROOT)): _PICTOGRAPH.findall(p.read_text())
        for p in [*TEMPLATES.rglob("*.html"), ROOT / "app/static/js/site.js"]
    }
    assert not {k: v for k, v in hits.items() if v}, hits


def test_selected_mode_card_uses_the_accent() -> None:
    css = (ROOT / "app/static/css/site.css").read_text()
    rule = re.search(r"\.mode-card:has\(input:checked\)\s*\{([^}]*)\}", css)
    assert rule and "var(--accent)" in rule.group(1) and "var(--ink)" not in rule.group(1)


def test_forced_colors_keep_the_selected_mode_card_visible() -> None:
    css = (ROOT / "app/static/css/site.css").read_text()
    start = css.index("@media (forced-colors: active)")
    depth = 0
    end = start
    for i, ch in enumerate(css[start:], start=start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    block = css[start:end]
    assert ".mode-card:has(input:checked)" in block


def test_footer_css_has_no_stale_bare_tag_selectors() -> None:
    """Regression guard for the Task 23 fix-round-1 finding: `.footer p` and
    `.footer ul` are bare-tag selectors that match the current footer markup
    (a <p class="footer-brand"> and a <ul class="footer-links">) at the same
    specificity as the intended `.footer-brand`/`.footer-links` rules, so
    whichever is declared later in the file silently wins. Neither selector
    may exist in site.css."""
    css = (ROOT / "app/static/css/site.css").read_text()
    hits = re.findall(r"\.footer\s+(?:p|ul)\b", css)
    assert not hits, hits


@pytest.mark.asyncio
async def test_submit_page_has_the_short_reassurance_for_phones(client: AsyncClient) -> None:
    html = (await client.get("/submit")).text
    assert 'class="mobile-reassure"' in html


def test_footer_inner_is_declared_once() -> None:
    """Regression guard for the Task 25 controller finding: two `.footer-inner`
    rule blocks (one setting margin/padding/max-width, one setting display/flex
    layout) used to live far apart in the file, silently relying on source
    order for the cascade to merge them. Merged into a single block."""
    css = (ROOT / "app/static/css/site.css").read_text()
    hits = re.findall(r"^\.footer-inner\s*\{", css, flags=re.MULTILINE)
    assert len(hits) == 1, hits


def test_token_class_never_breaks_a_case_number_or_pin() -> None:
    css = (ROOT / "app/static/css/site.css").read_text()
    rule = re.search(r"\.token\s*\{([^}]*)\}", css)
    assert rule
    body = rule.group(1)
    assert "white-space: nowrap" in body
    assert "word-break: normal" in body


def test_case_number_and_pin_get_the_token_class() -> None:
    success_html = (TEMPLATES / "submit_success.html").read_text()
    assert success_html.count('class="token"') == 2
    status_html = (TEMPLATES / "status.html").read_text()
    assert 'class="mono token"' in status_html


@pytest.mark.asyncio
async def test_dashboard_cells_carry_labels_for_the_phone_layout(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.services.report import create_report

    await create_report(db_session, "corruption", "Table label test report text.")
    await _login(client, db_session, AdminRole.admin)
    html = (await client.get("/admin/dashboard")).text
    assert 'class="table-stack"' in html
    assert 'class="stack-status" data-label=' in html


@pytest.mark.asyncio
async def test_stacked_dashboard_table_keeps_its_table_semantics(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Regression guard for the Task 26 fix-round-1 finding: at <=640px the
    table-stack CSS sets table/tbody to display:block and tr to display:grid,
    which strips the implicit table/rowgroup/row/cell ARIA roles some browsers
    derive from display. Explicit roles restore them."""
    from app.services.report import create_report

    await create_report(db_session, "corruption", "ARIA role test report text.")
    await _login(client, db_session, AdminRole.admin)
    html = (await client.get("/admin/dashboard")).text
    assert 'role="table"' in html
    assert 'role="cell"' in html


def test_users_and_audit_tables_also_stack() -> None:
    users_html = (TEMPLATES / "admin/users.html").read_text()
    assert 'class="table-stack"' in users_html
    assert 'class="stack-primary"' in users_html
    assert 'class="stack-status"' in users_html
    assert 'class="stack-action"' in users_html

    audit_html = (TEMPLATES / "admin/audit_log.html").read_text()
    assert 'class="table-stack"' in audit_html
    assert 'stack-primary' in audit_html
    assert 'stack-status' in audit_html


def _media_768_blocks(css: str) -> list[str]:
    blocks = []
    for match in re.finditer(r"@media \(max-width: 768px\)\s*\{", css):
        start = match.end() - 1
        depth = 0
        end = start
        for i, ch in enumerate(css[start:], start=start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        blocks.append(css[start:end])
    return blocks


def test_split_layout_has_only_one_active_phone_breakpoint() -> None:
    """Regression guard for the Task 25 fix-round-1 finding: a
    `@media (max-width: 768px)` block and a `@media (max-width: 900px)` block
    both declared `.split-layout`/`.split-main`/`.split-sidebar` layout, and
    since the 900px block always applies wherever the 768px one does, the
    768px declarations were dead code. None of the 768px blocks may redeclare
    `.split-layout`, `.split-main` max-width/padding, or `.split-sidebar`
    padding — the 900px block owns that layout now."""
    css = (ROOT / "app/static/css/site.css").read_text()
    for block in _media_768_blocks(css):
        assert not re.search(r"\.split-layout\s*\{", block), block
        main = re.search(r"\.split-main\s*\{([^}]*)\}", block)
        if main:
            assert "max-width" not in main.group(1) and "padding" not in main.group(1), main.group(1)
        sidebar = re.search(r"\.split-sidebar\s*\{([^}]*)\}", block)
        if sidebar:
            assert "padding" not in sidebar.group(1), sidebar.group(1)


def test_credential_value_dead_css_removed() -> None:
    """Regression guard for the Task 25 fix-round-1 finding: `.credential-value`
    was unreferenced by any template. It must not exist in site.css."""
    css = (ROOT / "app/static/css/site.css").read_text()
    assert ".credential-value" not in css


def test_eyebrows_are_the_exception() -> None:
    count = sum(
        len(re.findall(r'class="(?:page|sidebar)-eyebrow"', p.read_text()))
        for p in TEMPLATES.rglob("*.html")
    )
    assert count <= 5, count


def test_panel_headers_and_labels_are_not_shouted() -> None:
    css = (ROOT / "app/static/css/site.css").read_text()
    for selector in (".panel-header", ".card-title", ".detail-label"):
        for body in re.findall(re.escape(selector) + r"[^{]*\{([^}]*)\}", css):
            assert "uppercase" not in body, selector


def test_panel_headers_are_headings_not_divs() -> None:
    """A `.panel-header` div is only legitimate as a layout wrapper around block
    content (a toolbar), and even then must carry its label in a nested
    `.panel-header-title` heading -- it may never stand in for a heading itself."""
    for p in TEMPLATES.rglob("*.html"):
        text = p.read_text()
        for m in re.finditer(r'<div class="panel-header[^"]*"', text):
            end = text.find("</div>", m.end())
            assert end != -1, (p, m.group(0))
            assert 'class="panel-header-title"' in text[m.end() : end], (p, m.group(0))


def test_panel_header_headings_contain_only_phrasing_content() -> None:
    """An <h2>/<h3> may contain phrasing content only. A panel header that needs
    to wrap block-level content (a toolbar, a form, a list) stays a <div>, with
    just its label text in a nested <h2 class="panel-header-title">."""
    forbidden = re.compile(r"<(?:div|form|select|button|ul)\b", re.IGNORECASE)
    for p in TEMPLATES.rglob("*.html"):
        text = p.read_text()
        for m in re.finditer(r'<h[23] class="panel-header[^"]*"[^>]*>', text):
            end = text.find("</h2>", m.end())
            if end == -1:
                end = text.find("</h3>", m.end())
            assert end != -1, (p, m.group(0))
            assert not forbidden.search(text[m.end() : end]), (p, m.group(0))


def _strip_token_blocks(css: str) -> str:
    """Remove every :root / [data-theme="dark"] block from ``css``.

    Uses re.sub, which deletes each match where it stands. An earlier
    version of this helper did ``"".join(re.findall(...))`` and then a
    single ``css.replace(joined, "")`` — a no-op whenever there is more than
    one match with non-adjacent text between them (i.e. always, since real
    CSS always has other rules between :root and [data-theme="dark"]), which
    silently checked the *whole* file instead of excluding the token
    blocks. See test_token_block_exclusion_actually_strips_the_blocks.
    """
    return re.sub(r'(?::root|\[data-theme="?dark"?\])[^{]*\{[^}]*\}', "", css)


def test_token_block_exclusion_actually_strips_the_blocks() -> None:
    inside_only = (
        ':root {\n  --muted-on-dark: #a1a1aa;\n}\n'
        '[data-theme="dark"] {\n  --muted-on-dark: #a1a1aa;\n}\n'
        '.thing { color: var(--muted-on-dark); }\n'
    )
    # both raw hexes are inside a token block: nothing should leak "outside".
    assert "#a1a1aa" not in _strip_token_blocks(inside_only)

    leaking = inside_only + ".footer { color: #a1a1aa; }\n"
    # a genuine outside occurrence must still be caught.
    assert "#a1a1aa" in _strip_token_blocks(leaking)


def test_design_fix_list_is_closed() -> None:
    css = (ROOT / "app/static/css/site.css").read_text()
    outside = _strip_token_blocks(css)
    assert "#a1a1aa" not in outside.lower() and "#9ca3af" not in outside.lower()
    html = "".join(p.read_text() for p in TEMPLATES.rglob("*.html"))
    assert "progress-steps" not in html + css
    assert "submit-progress" not in html + css  # one stepper, named .stepper
    assert not re.search(r"stat-card-(?:link|active)\b|stat-number\b", html + css)


def test_brand_secondary_colour_is_gone() -> None:
    for path in ("app/config.py", "app/templating.py", "app/templates/base.html",
                 "docker-compose.prod.yml", "docs/docs.html", "README.md",
                 "charts/openwhistle/values.yaml", "charts/openwhistle/templates/configmap.yaml"):
        text = (ROOT / path).read_text().lower().replace("-", "_")
        assert "brand_secondary" not in text, path


def test_public_site_uses_the_app_token_names() -> None:
    for page in [*(ROOT / "docs").glob("*.html"), *(ROOT / "docs").glob("*/*.html")]:
        text = page.read_text()
        for legacy in ("--gold", "--seal-green", "--font-serif"):
            assert legacy not in text, (page.name, legacy)


def test_docs_warn_callouts_do_not_converge_on_the_accent() -> None:
    """Regression guard: folding --gold and --seal-green onto one --accent
    token must not leave a "warning" callout coloured identically to the
    brand accent (or to a "note"/"info" callout). .callout-warn and
    .val-warn must use their own --warning token."""
    for name in (
        "docs.html",
        "blog/hinschg-compliance-leitfaden.html",
        "blog/interne-meldestelle-einrichten.html",
        "blog/whistleblower-software-vergleich.html",
    ):
        text = (ROOT / "docs" / name).read_text()
        assert "--warning" in text, name
        for selector in (".callout-warn", ".val-warn"):
            for body in re.findall(re.escape(selector) + r"[^{]*\{([^}]*)\}", text):
                assert "var(--accent)" not in body, (name, selector, body)


def _relative_luminance(hex_color: str) -> float:
    hex_color = hex_color.lstrip("#")

    def channel(c: str) -> float:
        v = int(c, 16) / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(hex_color[i : i + 2]) for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast_ratio(hex_a: str, hex_b: str) -> float:
    """WCAG 2.1 contrast ratio between two hex colours."""
    la, lb = _relative_luminance(hex_a), _relative_luminance(hex_b)
    la, lb = max(la, lb), min(la, lb)
    return (la + 0.05) / (lb + 0.05)


def test_docs_warning_colour_meets_contrast() -> None:
    """Each docs page's --warning must read against its --bg-base at >= 4.5:1
    (WCAG AA, normal text) in both themes — a warning colour nobody can read
    is not a fix. Regression guard for the round-1 finding that the restored
    former-gold light value (#c8972e, ~2.5:1 on the blog pages) was too low."""
    for name in (
        "docs.html",
        "blog/hinschg-compliance-leitfaden.html",
        "blog/interne-meldestelle-einrichten.html",
        "blog/whistleblower-software-vergleich.html",
    ):
        text = (ROOT / "docs" / name).read_text()
        light_block = re.search(r":root\s*\{([^}]*)\}", text)
        dark_block = re.search(r'\[data-theme="dark"\]\s*\{([^}]*)\}', text)
        assert light_block and dark_block, name
        for theme, block in (("light", light_block), ("dark", dark_block)):
            warning = re.search(r"--warning:\s*(#[0-9a-fA-F]{6})", block.group(1))
            bg_base = re.search(r"--bg-base:\s*(#[0-9a-fA-F]{6})", block.group(1))
            assert warning and bg_base, (name, theme)
            ratio = _contrast_ratio(warning.group(1), bg_base.group(1))
            assert ratio >= 4.5, (name, theme, warning.group(1), bg_base.group(1), ratio)
