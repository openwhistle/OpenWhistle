"""The footer: the operator's legal links, no public version number (2.4.0)."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, settings
from app.models.user import AdminRole
from app.templating import static_url, templates
from tests.test_v210_bug_bounty import _totp_user

PUBLIC = ["/submit", "/status", "/external-reporting", "/admin/login"]


def _footer(html: str) -> str:
    return html[html.index("<footer") :]


@pytest.fixture
def operator(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(templates.env.globals, "is_demo", False)


async def test_the_footer_links_the_operators_legal_pages(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, operator: None
) -> None:
    monkeypatch.setitem(templates.env.globals, "privacy_policy_url", "https://acme.example/privacy")
    monkeypatch.setitem(templates.env.globals, "legal_notice_url", "https://acme.example/legal")
    footer = _footer((await client.get("/submit")).text)
    assert '<a href="https://acme.example/privacy" rel="noopener noreferrer">Privacy</a>' in footer
    legal = '<a href="https://acme.example/legal" rel="noopener noreferrer">Legal notice</a>'
    assert legal in footer


async def test_without_a_url_the_link_is_left_out(client: AsyncClient, operator: None) -> None:
    footer = _footer((await client.get("/submit")).text)
    assert "Privacy" not in footer and "Legal notice" not in footer


@pytest.mark.parametrize("value", ["javascript:alert(1)", "data:text/html,x", "//acme.example/p"])
def test_a_footer_link_must_be_a_web_address(value: str) -> None:
    with pytest.raises(ValidationError):
        Settings(secret_key="x" * 64, privacy_policy_url=value)


@pytest.mark.parametrize("path", PUBLIC)
async def test_a_public_page_names_no_version(client: AsyncClient, path: str) -> None:
    """A release number on a public page tells an attacker which known flaws to try
    (OWASP ASVS 4.0.3 14.3.3). It was in the footer and in every asset URL."""
    html = (await client.get(path)).text
    assert settings.app_version not in html
    assert "footer-version" not in html


async def test_health_names_no_version(client: AsyncClient) -> None:
    """GlobaLeaks kept it out of its footer and still served it from a public API."""
    body = (await client.get("/health")).json()
    assert "version" not in body and body["status"] == "ok"


def test_an_asset_url_carries_the_files_hash() -> None:
    url = static_url("css/site.css")
    expected = hashlib.sha256(Path("app/static/css/site.css").read_bytes()).hexdigest()[:12]
    assert url == f"/static/css/site.css?v={expected}"


async def test_a_signed_in_admin_sees_the_version(
    acting_as: Any,
    db_session: AsyncSession,
) -> None:
    client, act = acting_as
    act(await _totp_user(db_session, AdminRole.case_manager))
    footer = _footer((await client.get("/admin/dashboard")).text)
    assert re.search(r'class="footer-version">v' + re.escape(settings.app_version) + "<", footer)


async def test_the_dashboard_says_the_privacy_notice_is_missing(
    acting_as: Any,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "demo_mode", False)
    client, act = acting_as
    act(await _totp_user(db_session, AdminRole.superadmin))
    assert 'id="privacy-notice-missing"' in (await client.get("/admin/dashboard")).text
    monkeypatch.setattr(settings, "privacy_policy_url", "https://acme.example/privacy")
    assert 'id="privacy-notice-missing"' not in (await client.get("/admin/dashboard")).text
