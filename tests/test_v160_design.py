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
