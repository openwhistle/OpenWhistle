"""v1.6.0 design: the findings of the assessment, pinned in rendered HTML and sources."""

from __future__ import annotations

import re
import uuid
from html.parser import HTMLParser
from pathlib import Path

import pyotp
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import AdminRole, AdminUser
from app.services.auth import hash_password


async def _search(client: AsyncClient, q: str, **form: str):  # type: ignore[no-untyped-def]
    """Dashboard search: POST, so the term never sits in a URL."""
    return await client.post(
        "/admin/dashboard", data={"q": q, "csrf_token": client.cookies.get("ow_csrf"), **form}
    )

ROOT = Path(__file__).parents[1]
TEMPLATES = ROOT / "app/templates"
_PASSWORD = "V160-Design-Password"  # noqa: S105


async def _login(
    client: AsyncClient, db: AsyncSession, role: AdminRole, org_id: uuid.UUID | None = None
) -> AdminUser:
    secret = pyotp.random_base32()
    user = AdminUser(
        id=uuid.uuid4(),
        username=f"des_{uuid.uuid4().hex[:8]}",
        password_hash=hash_password(_PASSWORD),
        totp_secret=secret,
        totp_enabled=True,
        role=role,
        org_id=org_id,
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
    return user


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


@pytest.mark.asyncio
async def test_submit_page_h1_precedes_the_sidebar_heading_in_reading_order(
    client: AsyncClient,
) -> None:
    """The desktop layout still puts the sidebar on the left (CSS grid
    placement), but in DOM/reading order the page's own <h1> must come before
    the sidebar's <h2 class="sidebar-title"> -- a screen reader or a phone
    (where the layout stacks) should meet the page's own heading first."""
    html = (await client.get("/submit")).text
    assert html.index("<h1>") < html.index('class="sidebar-title"')


def test_footer_inner_is_declared_once() -> None:
    """Regression guard for the Task 25 controller finding: two `.footer-inner`
    rule blocks (one setting margin/padding/max-width, one setting display/flex
    layout) used to live far apart in the file, silently relying on source
    order for the cascade to merge them. Merged into a single block."""
    css = (ROOT / "app/static/css/site.css").read_text()
    hits = re.findall(r"^\.footer-inner\s*\{", css, flags=re.MULTILINE)
    assert len(hits) == 1, hits


def test_token_class_wraps_only_at_the_explicit_hyphen_breaks() -> None:
    """Superseded by the X13 fix: `white-space: nowrap` (the original guard
    against a case number/PIN breaking) is exactly what made the PIN scroll
    behind the copy button instead of wrapping (task X13). `.token` may now
    wrap, but only at the `<wbr>` the server inserts after each hyphen
    (wbr_after_hyphens in app/templating.py) — no automatic mid-word break."""
    css = (ROOT / "app/static/css/site.css").read_text()
    rule = re.search(r"\.token\s*\{([^}]*)\}", css)
    assert rule
    body = rule.group(1)
    assert "white-space: nowrap" not in body
    assert "overflow-wrap: normal" in body
    assert "word-break: normal" in body


def test_case_number_and_pin_get_the_token_class() -> None:
    success_html = (TEMPLATES / "submit_success.html").read_text()
    assert success_html.count('class="token"') == 2
    status_html = (TEMPLATES / "status.html").read_text()
    assert 'class="mono token"' in status_html


def test_case_number_and_pin_wrap_only_at_hyphens() -> None:
    """Both identifiers on the success screen go through `wbr_after_hyphens`
    (app/templating.py), which inserts a `<wbr>` after each hyphen so a long
    PIN or case number wraps, if it must, only at a group boundary — never
    inside a group, and (together with `.token` allowing wrapping, see
    test_token_class_wraps_only_at_the_explicit_hyphen_breaks) never behind
    a scrollbar or the copy button (Chrome review finding, task X13)."""
    success_html = (TEMPLATES / "submit_success.html").read_text()
    assert success_html.count("| wbr_after_hyphens") == 2


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


def test_split_layout_keeps_the_sidebar_beside_the_form_on_desktop() -> None:
    """submit.html puts the form before the sidebar so phones read it first.
    On the desktop grid both must sit in row 1: with only `grid-column` set,
    auto-placement dropped the sidebar into a second row under the form (found
    by the 1.6.0 Chrome check at 1920 px)."""
    css = (ROOT / "app/static/css/site.css").read_text()
    for selector in (r"\.split-main", r"\.split-sidebar"):
        top_level = re.search(r"(?m)^" + selector + r"\s*\{([^}]*)\}", css)
        assert top_level, selector
        assert re.search(r"grid-row:\s*1;", top_level.group(1)), (selector, top_level.group(1))


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
            rules = main.group(1)
            assert "max-width" not in rules and "padding" not in rules, rules
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


_VOID_ELEMENTS = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
})


class _PanelHeaderDivChecker(HTMLParser):
    """Walks real element nesting (not string search, which can't tell a wrapper's
    own closing tag from an inner element's) to check every `<div class="panel-header
    ...">`: it must contain a nested `.panel-header-title` heading, and any text that
    is a *direct* child of the wrapper (not text inside a nested element, e.g. the
    toolbar) must be whitespace only -- a div standing in for a heading by holding
    its label as direct text is exactly the pattern this guards against."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[dict] = []
        self.violations: list[str] = []

    def _classes(self, attrs: list[tuple[str, str | None]]) -> list[str]:
        for name, value in attrs:
            if name == "class" and value:
                return value.split()
        return []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = self._classes(attrs)
        if "panel-header-title" in classes:
            for frame in self.stack:
                if frame["is_ph_div"]:
                    frame["has_title"] = True
        if tag in _VOID_ELEMENTS:
            return
        self.stack.append({
            "tag": tag,
            "is_ph_div": tag == "div" and "panel-header" in classes,
            "has_title": False,
            "bad_text": False,
        })

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in _VOID_ELEMENTS:
            self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if self.stack and self.stack[-1]["is_ph_div"] and data.strip():
            self.stack[-1]["bad_text"] = True

    def handle_endtag(self, tag: str) -> None:
        if not self.stack:
            return
        frame = self.stack.pop()
        if frame["is_ph_div"]:
            if not frame["has_title"]:
                self.violations.append("div.panel-header has no nested .panel-header-title")
            if frame["bad_text"]:
                self.violations.append(
                    "div.panel-header holds text directly, not via .panel-header-title"
                )


def test_panel_headers_are_headings_not_divs() -> None:
    """A `.panel-header` div is only legitimate as a layout wrapper around block
    content (a toolbar), and even then must carry its label in a nested
    `.panel-header-title` heading -- it may never stand in for a heading itself."""
    for p in TEMPLATES.rglob("*.html"):
        checker = _PanelHeaderDivChecker()
        checker.feed(p.read_text())
        assert not checker.violations, (p, checker.violations)


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
                 "docker-compose.yml", "docker-compose.e2e.yml", "docker-compose.prod.yml",
                 "docs/docs.html", "README.md", ".env.example",
                 "charts/openwhistle/values.yaml", "charts/openwhistle/templates/configmap.yaml",
                 "charts/openwhistle/templates/secret.yaml",
                 "ansible/roles/openwhistle/templates/env.j2",
                 "ansible/roles/openwhistle/defaults/main.yml"):
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
        "blog/was-ist-neu-in-1-6.html",
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
        "blog/was-ist-neu-in-1-6.html",
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


def _pill_counts(html: str) -> dict[str, int]:
    """Status value -> the count shown in its filter pill (a link, or a form during a search)."""
    link = r'&status=(\w+)[^"]*"[^>]*>'
    form = r'name="status" value="(\w+)">(?:<input[^>]*>)*<button[^>]*>'
    return {
        (m.group(1) or m.group(2)): int(m.group(3))
        for m in re.finditer(
            rf'(?:{link}|{form})[^<]*<span class="filter-pill-count">(\d+)</span>', html
        )
    }


@pytest.mark.asyncio
async def test_dashboard_counts_live_in_the_filter_pills(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _login(client, db_session, AdminRole.admin)
    html = (await client.get("/admin/dashboard")).text
    assert "stat-card" not in html and "stats-row" not in html
    assert html.count('class="filter-pill-count"') == 4
    assert set(_pill_counts(html)) == {"received", "in_review", "pending_feedback", "closed"}
    active = re.findall(r'<a [^>]*class="filter-pill filter-pill-active"[^>]*>', html)
    # Two independent filter dimensions (status/my-cases and location) can each have an
    # active pill at once, so "page" (a single current page) would be wrong here; "true"
    # is the correct aria-current token for a set of independent toggles. "page" stays
    # reserved for real navigation/pagination (see admin/_layout.html, the pagination span).
    assert active and all('aria-current="true"' in a for a in active)
    inactive = re.findall(r'<a [^>]*class="filter-pill"[^>]*>', html)
    assert inactive and not any("aria-current" in a for a in inactive)


@pytest.mark.asyncio
async def test_case_manager_pill_counts_only_their_cases(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.services.report import create_report

    user = await _login(client, db_session, AdminRole.case_manager)
    mine, _ = await create_report(db_session, "corruption", "Pill count: assigned to me.")
    await create_report(db_session, "corruption", "Pill count: somebody else's case.")
    mine.assigned_to_id = user.id
    await db_session.commit()
    counts = _pill_counts((await client.get("/admin/dashboard")).text)
    assert counts == {"received": 1, "in_review": 0, "pending_feedback": 0, "closed": 0}
    stats = (await client.get("/admin/stats")).text
    assert '<div class="stat-card__number">1</div>' in stats


@pytest.mark.asyncio
async def test_org_admin_pill_counts_only_their_org(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import settings
    from app.models.organisation import Organisation
    from app.services.report import create_report

    monkeypatch.setattr(settings, "multi_tenancy_enabled", True)
    orgs = [Organisation(id=uuid.uuid4(), name=n, slug=f"{n}-{uuid.uuid4().hex[:6]}") for n in "ab"]
    db_session.add_all(orgs)
    await db_session.commit()
    await _login(client, db_session, AdminRole.admin, org_id=orgs[0].id)
    ours, _ = await create_report(db_session, "corruption", "Pill count: our organisation.")
    theirs, _ = await create_report(db_session, "corruption", "Pill count: other organisation.")
    ours.org_id, theirs.org_id = orgs[0].id, orgs[1].id
    await db_session.commit()
    counts = _pill_counts((await client.get("/admin/dashboard")).text)
    assert counts == {"received": 1, "in_review": 0, "pending_feedback": 0, "closed": 0}


@pytest.mark.asyncio
async def test_status_pills_keep_and_count_within_the_location_and_search(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.models.location import Location
    from app.services.report import create_report

    await _login(client, db_session, AdminRole.admin)
    loc = Location(id=uuid.uuid4(), name="Pill HQ", code=f"P{uuid.uuid4().hex[:5]}")
    db_session.add(loc)
    await db_session.commit()
    await create_report(
        db_session, "corruption", "Pill count: at the location.", location_id=loc.id
    )
    html = (await _search(client, "abc", location_id=str(loc.id))).text
    # The count is what the pill's link shows: within the chosen location.
    assert _pill_counts(html)["received"] == 1
    # During a search every pill is a POST form carrying the location and the term.
    pills = re.findall(r'<form method="post"[^>]*class="dash-nav-form">(.*?)</form>', html, re.S)
    status_pills = [p for p in pills if 'name="status"' in p or 'name="my_cases"' in p]
    assert len(status_pills) == 5
    for form in status_pills:
        assert f'name="location_id" value="{loc.id}"' in form, form
        assert 'name="q" value="abc"' in form, form


def _panel_of(html: str, needle: str) -> str:
    """The title of the `.panel` holding ``needle``."""
    pos = html.index(needle)
    starts = [m.start() for m in re.finditer(r'class="panel[ "]', html[:pos])]
    assert starts, needle
    start = starts[-1]
    title = re.search(r'<h2 class="panel-header[^"]*">\s*([^<&]+)', html[start:pos])
    return title.group(1).strip() if title else ""


@pytest.mark.asyncio
async def test_case_page_has_at_most_five_panels(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.models.report import SubmissionMode
    from app.services.crypto import encrypt
    from app.services.report import create_report

    user = await _login(client, db_session, AdminRole.admin)
    report, _ = await create_report(
        db_session, "corruption", "Panel count test report text.",
        submission_mode=SubmissionMode.confidential,
        confidential_name_enc=encrypt("Panel Name"), confidential_contact_enc=encrypt("Panel"),
    )
    report.assigned_to_id = user.id
    await db_session.commit()
    html = (await client.get(f"/admin/reports/{report.id}")).text
    assert len(re.findall(r'class="panel[ "]', html)) <= 5
    assert '<details class="danger-zone"' in html
    assert 'class="panel panel-primary"' in html
    placed = {
        f'action="/admin/reports/{report.id}/identity"': "Actions",
        f'formaction="/admin/reports/{report.id}/export.pdf"': "Actions",
        f'href="/admin/reports/{report.id}/export.pdf"': "Actions",
        'id="audit"': "History",
        f'action="/admin/reports/{report.id}/links"': "History",
        f'action="/admin/reports/{report.id}/request-delete"': "Actions",
        f'action="/admin/reports/{report.id}/status"': "Actions",
        f'action="/admin/reports/{report.id}/reply"': "Communication thread",
        'class="report-description"': "Initial report",
    }
    for needle, panel in placed.items():
        assert _panel_of(html, needle) == panel, needle
    assert "Panel Name" not in html


@pytest.mark.asyncio
async def test_case_page_strings_are_translated_and_script_safe(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.services.report import create_report

    await _login(client, db_session, AdminRole.admin)
    report, _ = await create_report(db_session, "corruption", "Translated strings test report.")
    client.cookies.set("ow-lang", "fr")
    html = (await client.get(f"/admin/reports/{report.id}")).text
    script = html.split("function confirmStatusChange", 1)[1].split("</script>", 1)[0]
    # French prompts carry apostrophes; HTML-escaped inside JS they would show as "&#39;".
    assert "&#39;" not in script and "confirm(\"" in script
    assert "(actuel)" in html and "(current)" not in html


def test_primary_panel_stripe_leaves_the_accent_to_the_primary_action() -> None:
    css = (ROOT / "app/static/css/site.css").read_text()
    bodies = re.findall(r"\.panel-primary\s*\{([^}]*)\}", css)
    assert bodies and all("--accent" not in b for b in bodies)
    assert all("var(--ink)" in b for b in bodies)


@pytest.mark.asyncio
async def test_every_action_section_has_a_title(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.services.report import create_report

    await _login(client, db_session, AdminRole.admin)
    report, _ = await create_report(db_session, "corruption", "Action titles test report.")
    html = (await client.get(f"/admin/reports/{report.id}")).text
    sections = re.findall(r'<section class="action-section">(.*?)</section>', html, re.S)
    assert len(sections) >= 4
    assert all('<h3 class="action-title">' in s for s in sections)


# ── Task X5: every template's user-visible text goes through t(), and every
# class used in a template is a real CSS class or a documented JS hook. ─────

_JINJA_MACRO = re.compile(r"\{%-?\s*macro\b.*?-?%\}.*?\{%-?\s*endmacro\s*-?%\}", re.DOTALL)
_JINJA_EXPR = re.compile(r"\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\}", re.DOTALL)
_LANGUAGE_WORD = re.compile(r"[A-Za-z\u00C0-\u00D6\u00D8-\u00F6\u00F8-\u00FF]{2,}")

_CHECKED_ATTRS = {"title", "aria-label", "placeholder", "data-confirm", "value", "alt"}
# Elements whose text/attrs are identifiers or data, not UI language, and so are exempt:
# a <code> (env var names, hashes, case-number placeholders), and anything carrying one
# of these two classes (the app's own "this is a mono/identifier value" convention, plus
# demo-cred-value: the literal demo credential text, e.g. "demo" -- a data value, not copy).
_NON_LANGUAGE_CLASSES = {"mono", "demo-cred-value"}
# The brand name, as ONE word, is the only allowed literal (explicitly named by the brief).
# "open" and "whistle" are NOT allow-listed as bare words -- a hardcoded "Open" or "Whistle"
# used generically elsewhere must still fail this test.
_ALLOWED_WORDS = {"openwhistle"}
# The one place the name is split across tags for styling -- base.html's nav-brand wraps
# the seal and `<span>Open<strong>Whistle</strong></span>` -- is exempt by ELEMENT (this
# class), not by allow-listing "open"/"whistle" as words anywhere in any template.
_BRAND_MARK_CLASSES = {"nav-brand"}
# categories.html's label_en/label_de placeholders demonstrate the exact language required
# for that specific bilingual data field (an English example, a German example) -- they are
# a data example, not UI chrome, and stay put regardless of the admin's own UI language.
_EXAMPLE_DATA_PLACEHOLDER_IDS = {"cat-label-en", "cat-label-de"}


class _UntranslatedTextChecker(HTMLParser):
    """Flags literal, translatable words in text nodes and in a short list of
    user-visible attributes (title, aria-label, placeholder, data-confirm, alt, and
    value -- but only on an <input type="submit"|"button">, where value IS the
    visible label; a <button>'s value attribute is never rendered)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.violations: list[str] = []
        self._tag_stack: list[tuple[bool, bool, bool, bool]] = []
        self._skip_depth = 0
        self._nonlang_depth = 0
        self._external_link_depth = 0
        self._brand_depth = 0

    def _check(self, raw: str, where: str) -> None:
        stripped = _JINJA_EXPR.sub(" ", raw)
        for m in _LANGUAGE_WORD.finditer(stripped):
            word = m.group(0)
            if word.lower() in _ALLOWED_WORDS:
                continue
            self.violations.append(f"{where}={word!r} in {raw.strip()[:80]!r}")

    def _handle_attrs(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._skip_depth or self._brand_depth:
            return
        attrs_dict = dict(attrs)
        elem_id = attrs_dict.get("id")
        is_button_value = tag == "input" and attrs_dict.get("type") in ("submit", "button")
        for name, val in attrs_dict.items():
            if name not in _CHECKED_ATTRS or not val:
                continue
            if name == "value" and not is_button_value:
                continue
            if name == "placeholder" and elem_id in _EXAMPLE_DATA_PLACEHOLDER_IDS:
                continue
            self._check(val, f"@{name}")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        classes = set((attrs_dict.get("class") or "").split())
        href = attrs_dict.get("href") or ""
        opens_skip = tag in ("script", "style")
        opens_nonlang = tag == "code" or bool(_NON_LANGUAGE_CLASSES & classes)
        # External reference text (an https:// citation, a URL shown as its own link
        # text) is a citation/URL label, not UI copy -- e.g. the HinSchG footer link,
        # the EUR-Lex / gesetze-im-internet.de citations on the telephone-channel page.
        opens_external = tag == "a" and href.startswith(("http://", "https://"))
        opens_brand = bool(_BRAND_MARK_CLASSES & classes)
        self._skip_depth += opens_skip
        self._nonlang_depth += opens_nonlang
        self._external_link_depth += opens_external
        self._brand_depth += opens_brand
        self._tag_stack.append((opens_skip, opens_nonlang, opens_external, opens_brand))
        self._handle_attrs(tag, attrs)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._handle_attrs(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if not self._tag_stack:
            return
        opens_skip, opens_nonlang, opens_external, opens_brand = self._tag_stack.pop()
        self._skip_depth -= opens_skip
        self._nonlang_depth -= opens_nonlang
        self._external_link_depth -= opens_external
        self._brand_depth -= opens_brand

    def handle_data(self, data: str) -> None:
        if (
            self._skip_depth
            or self._nonlang_depth
            or self._external_link_depth
            or self._brand_depth
        ):
            return
        self._check(data, "text")


def test_no_untranslated_literal_text_in_templates() -> None:
    """Every user-visible string is a locale key: no literal English (or any other
    language) text sits outside t(...) in text nodes or in title/aria-label/alt/
    placeholder/data-confirm/button-value attributes. Caught two untranslated admin
    pages (organisations.html, users.html) plus smaller misses across the sweep."""
    for p in sorted(TEMPLATES.rglob("*.html")):
        raw = p.read_text()
        preprocessed = _JINJA_EXPR.sub(" ", _JINJA_MACRO.sub(" ", raw))
        checker = _UntranslatedTextChecker()
        checker.feed(preprocessed)
        assert not checker.violations, (p, checker.violations)


_DYNAMIC_CLASS_TOKEN = "\x00DYNAMIC\x00"


def _static_class_tokens(class_attr_value: str) -> list[str]:
    """The literal class names in a `class="..."` value: a `{{ expr }}` (a computed
    class, e.g. `badge-{{ status }}`) fuses into one token that is then dropped
    entirely -- it cannot be checked statically. A `{% if %}...{% endif %}` control
    tag is removed but the literal text it wraps (e.g. a conditionally-applied
    class name) is kept, since that text is a real, checkable class name."""
    value = _JINJA_MACRO.sub(" ", class_attr_value)
    value = re.sub(r"\{\{.*?\}\}", _DYNAMIC_CLASS_TOKEN, value, flags=re.DOTALL)
    value = re.sub(r"\{%.*?%\}", " ", value, flags=re.DOTALL)
    return [t for t in value.split() if _DYNAMIC_CLASS_TOKEN not in t]


class _ClassUsageChecker(HTMLParser):
    def __init__(self, known_classes: set[str]) -> None:
        super().__init__(convert_charrefs=True)
        self.known_classes = known_classes
        self.unknown: list[str] = []

    def _check(self, attrs: list[tuple[str, str | None]]) -> None:
        for name, val in attrs:
            if name == "class" and val:
                for cls in _static_class_tokens(val):
                    if cls not in self.known_classes:
                        self.unknown.append(cls)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._check(attrs)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._check(attrs)


# JS hook classes with no CSS rule of their own (styling for all three lives on
# selectors composed with another class, e.g. ".session-expiry-expired-state
# .session-expiry-icon" -- so the bare hook class itself still needs listing here
# for any file that used ONLY the hook name; kept explicit and short, per the brief).
_JS_HOOK_CLASSES = {
    "session-expiry-expired-state",  # site.js: classList.add/remove
    "session-expiry-actions",  # site.js: querySelector('.session-expiry-actions')
    "session-expiry-body",  # site.js: querySelector('.session-expiry-body')
}


def test_every_template_class_exists_in_css_or_is_a_documented_js_hook() -> None:
    """Every class in `class="..."` (its static parts; a `{{ expr }}` computed class
    is skipped, see `_static_class_tokens`) is defined in site.css, in that same
    template's OWN page-scoped <style> block (an established pattern here, e.g.
    users.html's `.usr-*`), or is a documented JS hook. Scoped per file -- a class
    defined in one template's <style> does not satisfy another template, so a typo
    that happens to collide with an unrelated page's own scoped name would still be
    caught. Caught BEM-style classes (btn--secondary, badge--green, stats-grid, ...)
    that don't exist in site.css at all -- the real names are single-dash
    (btn-secondary, badge-closed, stats-row)."""
    css = (ROOT / "app/static/css/site.css").read_text()
    css_no_comments = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    css_known = set(re.findall(r"\.([a-zA-Z_][\w-]*)", css_no_comments))
    css_known |= _JS_HOOK_CLASSES

    for p in sorted(TEMPLATES.rglob("*.html")):
        text = p.read_text()
        local_known = set(css_known)
        for style_body in re.findall(r"<style[^>]*>(.*?)</style>", text, re.DOTALL):
            style_no_comments = re.sub(r"/\*.*?\*/", "", style_body, flags=re.DOTALL)
            local_known |= set(re.findall(r"\.([a-zA-Z_][\w-]*)", style_no_comments))
        checker = _ClassUsageChecker(local_known)
        checker.feed(text)
        assert not checker.unknown, (p, sorted(set(checker.unknown)))


# ── Fix round 1: regression tests for the organisations CSRF bug ───────────────


@pytest.mark.asyncio
async def test_organisation_create_and_deactivate_succeed_with_valid_csrf(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Regression test for the organisations CSRF bug (review round 1, Important #2):
    the page used to post an undefined `{{ csrf_token }}` (always rendered empty), so
    every real submission would 403 in production. With `request.state.csrf_token` a
    real double-submit token now lets both the create and the deactivate route through,
    and each one's DB effect actually happens."""
    from sqlalchemy import select

    from app.models.organisation import Organisation

    await _login(client, db_session, AdminRole.superadmin)
    await client.get("/admin/organisations")  # ensures the ow_csrf cookie is set
    csrf_token = client.cookies.get("ow_csrf")
    slug = f"csrf-ok-{uuid.uuid4().hex[:8]}"

    create_resp = await client.post(
        "/admin/organisations",
        data={"name": "CSRF Regression Org", "slug": slug, "csrf_token": csrf_token},
        follow_redirects=False,
    )
    assert create_resp.status_code == 302

    result = await db_session.execute(select(Organisation).where(Organisation.slug == slug))
    org = result.scalar_one()
    assert org.is_active

    deactivate_resp = await client.post(
        f"/admin/organisations/{org.id}/deactivate",
        data={"csrf_token": csrf_token},
        follow_redirects=False,
    )
    assert deactivate_resp.status_code == 302
    await db_session.refresh(org)
    assert org.is_active is False


@pytest.mark.asyncio
async def test_organisation_create_and_deactivate_fail_without_valid_csrf(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The other half of the CSRF regression: a missing or wrong token must still be
    rejected (403) and must not touch the database, on both routes."""
    from sqlalchemy import select

    from app.models.organisation import Organisation

    await _login(client, db_session, AdminRole.superadmin)
    await client.get("/admin/organisations")
    slug = f"csrf-fail-{uuid.uuid4().hex[:8]}"

    missing_token_resp = await client.post(
        "/admin/organisations", data={"name": "Should Not Exist", "slug": slug}
    )
    assert missing_token_resp.status_code == 422  # required Form field missing entirely

    wrong_token_resp = await client.post(
        "/admin/organisations",
        data={"name": "Should Not Exist", "slug": slug, "csrf_token": "wrong-token"},
    )
    assert wrong_token_resp.status_code == 403

    result = await db_session.execute(select(Organisation).where(Organisation.slug == slug))
    assert result.scalar_one_or_none() is None

    default_result = await db_session.execute(
        select(Organisation).where(Organisation.slug == "default")
    )
    default_org = default_result.scalar_one()
    was_active = default_org.is_active
    deactivate_resp = await client.post(
        f"/admin/organisations/{default_org.id}/deactivate",
        data={"csrf_token": "wrong-token"},
    )
    assert deactivate_resp.status_code == 403
    await db_session.refresh(default_org)
    assert default_org.is_active == was_active


@pytest.mark.asyncio
async def test_organisation_deactivate_is_a_danger_action(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Ruling (review round 1, Important #3): organisations have no reactivate route,
    so deactivating one is one-way -- the button must use the real DESIGN.md danger
    class, and the confirm prompt must say the action cannot be undone, in every
    locale (spot-checked here in French)."""
    from app.models.organisation import Organisation

    org = Organisation(
        id=uuid.uuid4(), name="Danger Button Org", slug=f"danger-btn-{uuid.uuid4().hex[:8]}"
    )
    db_session.add(org)
    await db_session.commit()

    await _login(client, db_session, AdminRole.superadmin)
    client.cookies.set("ow-lang", "fr")
    html = (await client.get("/admin/organisations")).text
    row = html.split(org.slug, 1)[1].split("</tr>", 1)[0]
    assert 'class="btn btn-danger btn-sm"' in row
    assert "irréversible" in row


def test_every_docs_font_face_url_resolves_to_a_real_file() -> None:
    """Regression guard: docs/blog's four articles and its index declared
    @font-face rules for Spectral/Source Serif 4 that pointed at files which
    did not exist anywhere in the repo (fetched once in commit fc47183, then
    deleted by an unrelated redesign, commit 241e926, that never touched the
    older blog scaffold) -- every browser silently fell back to the declared
    Georgia/serif fallback, so nothing visibly broke, but nothing was
    actually self-hosted either. This scans every @font-face in every HTML
    file under docs/ and asserts its url()'s local path exists on disk."""
    url_re = re.compile(r"url\(\s*['\"]?([^'\")\s]+)['\"]?\s*\)")
    font_face_re = re.compile(r"@font-face\s*\{[^}]*\}", re.DOTALL)
    checked = 0
    for page in (ROOT / "docs").rglob("*.html"):
        text = page.read_text(encoding="utf-8")
        for block in font_face_re.findall(text):
            for m in url_re.finditer(block):
                src = m.group(1)
                if src.startswith(("http://", "https://", "data:")):
                    continue
                resolved = (page.parent / src).resolve()
                assert resolved.is_file(), f"{page.relative_to(ROOT)}: {src} does not exist"
                checked += 1
    assert checked, "no @font-face url() found under docs/ -- test target moved?"


def _unwrap_at_rules(css: str) -> str:
    """Flatten @media { ... } blocks so a flat rule scan also sees the rules
    inside them (font-face/family/weight declarations never live under any
    other at-rule on these pages)."""
    out: list[str] = []
    i, n = 0, len(css)
    while i < n:
        m = re.match(r"@media[^{]*\{", css[i:])
        if m and not css[i:].startswith("@font-face"):
            start = i + m.end()
            depth, j = 1, start
            while j < n and depth:
                if css[j] == "{":
                    depth += 1
                elif css[j] == "}":
                    depth -= 1
                j += 1
            out.append(_unwrap_at_rules(css[start : j - 1]))
            i = j
        else:
            out.append(css[i])
            i += 1
    return "".join(out)


def _norm_weight(w: str) -> int | str:
    w = w.strip().lower()
    mapped = {"normal": 400, "bold": 700}
    if w in mapped:
        return mapped[w]
    try:
        return int(w)
    except ValueError:
        return w


def _norm_style(s: str) -> str:
    s = s.strip().lower()
    return s if s in ("italic", "oblique") else "normal"


def _resolve_family(famval: str, varmap: dict[str, str]) -> str | None:
    m = re.match(r"var\((--font-[a-zA-Z-]+)\)", famval)
    if m:
        return varmap.get(m.group(1))
    return famval.split(",")[0].strip().strip("'\"")


# A selector whose real font context comes from a nested/descendant
# relationship a flat CSS rule scan can't see (e.g. an inline <em> inside a
# paragraph that itself sets an explicit weight, or a code-comment span
# inside a code block whose ancestor overrides font-family to the mono
# stack) -- keyed by the exact relative page path, since the same class name
# can sit under a different real ancestor on a different page.
_ANCESTOR_OVERRIDES: dict[str, dict[str, str]] = {
    "docs/index.html": {
        ".hero-subline em": ".hero-subline",  # inherits its weight (300), not body's default
        ".hero-headline .accent-emphasis": ".hero-headline",  # inherits its weight (700)
        ".t-comment": ".terminal-body",  # ancestor sets font-family: var(--font-mono)
    },
    "docs/de/index.html": {
        ".hero-subline em": ".hero-subline",
        ".hero-headline .accent-emphasis": ".hero-headline",
        ".t-comment": ".terminal-body",
    },
    "docs/docs.html": {
        ".t-comment": ".code-block pre code",  # ancestor sets font-family: var(--font-mono)
    },
}


def test_every_docs_page_font_usage_has_a_matching_font_face() -> None:
    """Regression guard (review round 2): the blog scaffold's CSS asks for
    Spectral weight 600 (`.nav-logo`, `.article-body h3`, blog index's
    `.footer-logo`) but only 400/700 were shipped -- the browser silently
    synthesized a faux-bold instead of using the real weight. Same root
    cause as the missing-font-file bug the previous round fixed (a font
    family self-hosted on the page but not with every face the page's own
    CSS actually asks for), so it needed the same kind of guard: for every
    docs/ page, every (font-family, font-weight, font-style) its CSS
    declares (in the same rule, or inherited from body/an explicit ancestor
    override above) for a family the page self-hosts at all must have a
    matching @font-face -- not just "the url resolves" (the previous
    round's guard), but "the exact face used exists"."""
    font_face_re = re.compile(r"@font-face\s*\{([^}]*)\}", re.DOTALL)
    fam_re = re.compile(r"font-family:\s*['\"]?([^'\";]+)['\"]?")
    weight_re = re.compile(r"font-weight:\s*([^;]+);")
    style_re = re.compile(r"font-style:\s*([^;]+);")
    var_re = re.compile(r"(--font-[a-zA-Z-]+)\s*:\s*([^;]+);")
    rule_re = re.compile(r"([^{}]+)\{([^{}]*)\}", re.DOTALL)

    checked_pages = 0
    for page in sorted((ROOT / "docs").rglob("*.html")):
        rel = str(page.relative_to(ROOT))
        html = page.read_text(encoding="utf-8")
        style = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", html, re.DOTALL))
        if not style.strip():
            continue
        style = _unwrap_at_rules(style)

        faces: set[tuple[str, int | str, str]] = set()
        for block in font_face_re.findall(style):
            fam_m = fam_re.search(block)
            if not fam_m:
                continue
            w_m, s_m = weight_re.search(block), style_re.search(block)
            faces.add(
                (
                    fam_m.group(1).strip(),
                    _norm_weight(w_m.group(1)) if w_m else 400,
                    _norm_style(s_m.group(1)) if s_m else "normal",
                )
            )
        if not faces:
            continue
        checked_pages += 1
        hosted_families = {f for f, _w, _s in faces}
        varmap = {
            name: val.split(",")[0].strip().strip("'\"") for name, val in var_re.findall(style)
        }
        rest = font_face_re.sub("", style)
        ancestors = _ANCESTOR_OVERRIDES.get(rel, {})

        rules: dict[str, dict[str, object]] = {}
        for sel, decl in rule_re.findall(rest):
            sel_clean = sel.strip().replace("\n", " ")
            fam_m, w_m, s_m = fam_re.search(decl), weight_re.search(decl), style_re.search(decl)
            rules[sel_clean] = {
                "family": _resolve_family(fam_m.group(1).strip(), varmap) if fam_m else None,
                "weight": _norm_weight(w_m.group(1)) if w_m else None,
                "style": _norm_style(s_m.group(1)) if s_m else None,
            }

        def resolve(
            sel: str,
            seen: frozenset[str] = frozenset(),
            rules: dict[str, dict[str, object]] = rules,
            ancestors: dict[str, str] = ancestors,
        ) -> tuple[str | None, int | str, str]:
            r = rules.get(sel, {})
            fam, w, s = r.get("family"), r.get("weight"), r.get("style")
            parent = ancestors.get(sel, "body" if sel != "body" else None)
            if (fam is None or w is None) and parent and parent not in seen:
                pfam, pw, _ps = resolve(parent, seen | {sel}, rules, ancestors)
                fam = fam or pfam
                w = w if w is not None else pw
            return fam, (w if w is not None else 400), (s or "normal")

        for sel, r in rules.items():
            if r["family"] is None and r["weight"] is None and r["style"] is None:
                continue
            fam, w, s = resolve(sel)
            if fam not in hosted_families:
                continue
            if (fam, w, s) in faces:
                continue
            raise AssertionError(
                f"{rel}: {sel!r} uses {fam} weight={w} style={s}, "
                f"but no matching @font-face exists (has: {sorted(faces)})"
            )
    assert checked_pages, "no docs/ page with @font-face declarations found -- test target moved?"


@pytest.mark.asyncio
async def test_case_manager_statistics_cover_only_their_cases(db_session: AsyncSession) -> None:
    """/admin/stats: category breakdown and SLA rate, not only the status counts."""
    from app.services.report import create_report, get_dashboard_stats

    manager = AdminUser(
        id=uuid.uuid4(), username=f"stats_{uuid.uuid4().hex[:8]}", password_hash=None,
        totp_secret=pyotp.random_base32(), totp_enabled=True, role=AdminRole.case_manager,
    )
    db_session.add(manager)
    mine, _ = await create_report(db_session, "corruption", "A case assigned to the manager.")
    mine.assigned_to_id = manager.id
    await create_report(db_session, "corruption", "A case assigned to nobody at all.")
    await db_session.commit()

    stats = await get_dashboard_stats(db_session, assigned_to_id=manager.id)
    assert stats["total_reports"] == 1
    assert stats["by_category"] == {"corruption": 1}


@pytest.mark.asyncio
async def test_new_user_role_select_defaults_to_the_least_privileged_role(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The "Add new user" role <select> used to default to whatever `AdminRole`
    declared first (superadmin) because no <option> carried `selected` — a new
    account silently got the most privileged role unless the operator noticed
    and changed it. It must default to case_manager, and least-to-most
    privileged is also the on-screen option order (admin/users.html)."""
    await _login(client, db_session, AdminRole.admin)
    html = (await client.get("/admin/users")).text
    select_html = html.split('id="new-role"', 1)[1].split("</select>", 1)[0]
    options = re.findall(
        r'<option value="([a-z_]+)"\s*(selected)?[^>]*>', select_html
    )
    assert [value for value, _ in options] == ["case_manager", "admin", "superadmin"]
    selected = [value for value, sel in options if sel]
    assert selected == ["case_manager"], options


def test_every_admin_role_has_a_badge_color() -> None:
    """admin/users.html and dashboard.html render `badge-{{ role.value }}` —
    `role.label.superadmin` shipping without `.badge-superadmin` would leave a
    superadmin's badge with no colour (the same class of gap as the missing
    locale key)."""
    css = (Path(__file__).parents[1] / "app/static/css/site.css").read_text()
    for role in AdminRole:
        # At line start: the dark-theme override alone is not the rule.
        assert re.search(rf"^\.badge-{role.value} \{{", css, re.M), f".badge-{role.value} missing"


@pytest.mark.asyncio
async def test_dashboard_and_case_page_show_the_category_in_german(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The dashboard row and case page header used to render `report.category`
    through `| replace('_', ' ') | title` — always English-shaped ("Financial
    Fraud") regardless of the admin's UI language, even though categories
    carry a `label_de` ("Finanzbetrug", seeded by migration 001)."""
    from app.services.report import create_report

    await _login(client, db_session, AdminRole.admin)
    report, _ = await create_report(db_session, "financial_fraud", "x" * 20)
    client.cookies.set("ow-lang", "de")

    dashboard_html = (await client.get("/admin/dashboard")).text
    assert "Finanzbetrug" in dashboard_html
    assert "Financial Fraud" not in dashboard_html

    case_html = (await client.get(f"/admin/reports/{report.id}")).text
    assert "Finanzbetrug" in case_html
    assert "Financial Fraud" not in case_html


@pytest.mark.asyncio
async def test_linked_reports_and_stats_show_the_category_in_german(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The case page's linked-report list and /admin/stats read the same
    label map as the case header; both used to print English."""
    from app.services.report import create_report, link_cases

    user = await _login(client, db_session, AdminRole.admin)
    report, _ = await create_report(db_session, "corruption", "x" * 20)
    other, _ = await create_report(db_session, "financial_fraud", "y" * 20)
    await link_cases(db_session, report, other, user)
    await db_session.commit()
    client.cookies.set("ow-lang", "de")

    links = (await client.get(f"/admin/reports/{report.id}")).text
    assert re.search(r'report-link-category">\s*Finanzbetrug', links)
    stats = (await client.get("/admin/stats")).text
    assert "Finanzbetrug" in stats
    assert "Financial Fraud" not in stats


@pytest.mark.asyncio
async def test_both_pdf_exports_print_the_category_in_german(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Both PDF routes pass the admin-language label to the generator; the
    PDF used to print the raw slug."""
    from tests.test_pdf_service import _pdf_text
    from tests.test_v160_privacy import _REASON, _confidential_report

    user = await _login(client, db_session, AdminRole.admin)
    report = await _confidential_report(db_session, assigned=user)
    client.cookies.set("ow-lang", "de")

    plain = await client.get(f"/admin/reports/{report.id}/export.pdf")
    with_identity = await client.post(
        f"/admin/reports/{report.id}/export.pdf",
        data={"reason": _REASON, "csrf_token": client.cookies.get("ow_csrf")},
    )
    for resp in (plain, with_identity):
        assert resp.headers["content-type"].startswith("application/pdf")
        text = _pdf_text(resp.content)
        assert "Korruption" in text, text
        assert "corruption" not in text


def test_dashboard_table_action_column_is_pinned_and_status_badge_wraps() -> None:
    """Reproduced by rendering the dashboard with a `pending_feedback` report
    (its German status badge, "Rückmeldung ausstehend", is unbreakable —
    `.badge` is `white-space: nowrap` — and alone widens the 8-column table
    past `.table-wrapper`'s 1064px viewport at both 1440 and 1920px, where the
    admin-shell caps content width at 1440px regardless of screen size). The
    wrapper's `overflow-x: auto` already contains that, but its default scroll
    position hid the last column — the row's "Ansehen" action — off the right
    edge, unreachable without knowing to scroll a table that shows no
    scrollbar hint. Confirmed with Playwright against the rendered HTML
    (dashboard's `<td class="stack-action">` / `<a class="btn">`
    `getBoundingClientRect().right` exceeded the panel's before this fix, and
    stayed within it after — see task-X10-report.md).

    This guard pins the fix in source: the action column must stay visible
    regardless of scroll position (`position: sticky; right: 0`), and the
    status badge must be allowed to wrap so the common case does not need to
    scroll at all."""
    css = (Path(__file__).parents[1] / "app/static/css/site.css").read_text()
    assert re.search(
        r"\.table-stack td\.stack-action[^{]*\{[^}]*position:\s*sticky[^}]*right:\s*0",
        css,
        re.DOTALL,
    ), "the dashboard table's action column must stay pinned to the right edge"
    assert re.search(
        r"\.table-stack \.stack-status \.badge\s*\{[^}]*white-space:\s*normal",
        css,
        re.DOTALL,
    ), "the dashboard table's status badge must be allowed to wrap"


_TABLE_STACK_TEMPLATES = sorted(
    p for p in (TEMPLATES / "admin").glob("*.html") if 'class="table-stack"' in p.read_text()
)


@pytest.mark.parametrize("tpl", _TABLE_STACK_TEMPLATES, ids=lambda p: p.name)
def test_table_stack_sticky_action_column_is_paired_header_and_data(tpl: Path) -> None:
    """The sticky-action CSS (`.table-stack td.stack-action,
    .table-stack th.stack-action-header`) used to be `.table-stack
    th:last-child` — every `.table-stack` table's last header, regardless of
    whether that table has an action column at all. admin/audit_log.html's
    last column is "Detail" (real content, td class `aud-detail-cell`, not
    `stack-action`): the positional selector pinned its header to the right
    edge while its own data column scrolled normally underneath it, a real
    header/data desync this diff did not intend. A table opts in with the
    class on both cells or neither — never one without the other."""
    html = tpl.read_text()
    has_header = "stack-action-header" in html
    has_data = 'class="stack-action"' in html
    assert has_header == has_data, (
        f"{tpl.name}: stack-action-header present={has_header}, "
        f"stack-action (td) present={has_data} — must match"
    )


# ── Second Chrome check (task X13) ──────────────────────────────────────────


def test_submit_eyebrow_is_neutral_across_locales() -> None:
    """Chrome review finding: the wizard eyebrow said "VERTRAULICHE MELDUNG" /
    "CONFIDENTIAL REPORT" even after the reporter chose "Anonym" — a neutral
    eyebrow that does not clash with whichever submission mode is selected."""
    import json

    expected = {
        "en": "Secure report",
        "de": "Sichere Meldung",
        "fr": "Signalement sécurisé",
        "pt-br": "Denúncia segura",
    }
    for lang, value in expected.items():
        data = json.loads((ROOT / "app/locales" / f"{lang}.json").read_text())
        assert data["submit.eyebrow"] == value, lang
        # Must not restate the confidential mode's own name (DESIGN.md: an
        # eyebrow must not say what a heading/label right below it already
        # says), regardless of language.
        assert "confidential" not in data["submit.eyebrow"].lower()
        assert "vertraulich" not in data["submit.eyebrow"].lower()
        assert "confidentie" not in data["submit.eyebrow"].lower()


def test_blog_1_6_release_date_is_2026_09_26() -> None:
    """Chrome review finding: the article was dated 25 September while the
    actual release is the 26th — every date on the page, the sitemap and the
    JSON-LD must agree with the real release date."""
    text = (ROOT / "docs/blog/was-ist-neu-in-1-6.html").read_text()
    assert "25. September 2026" not in text
    assert "2026-09-25" not in text
    assert "26. September 2026" in text
    assert text.count('"2026-09-26"') >= 2  # datePublished and dateModified
    assert 'content="2026-09-26"' in text  # article:published_time / modified_time

    sitemap = (ROOT / "docs/sitemap.xml").read_text()
    article_block = re.search(
        r"<loc>https://openwhistle\.net/blog/was-ist-neu-in-1-6\.html</loc>.*?</url>",
        sitemap,
        re.DOTALL,
    )
    assert article_block, "sitemap entry for the 1.6 blog article not found"
    assert "<lastmod>2026-09-26</lastmod>" in article_block.group(0)
