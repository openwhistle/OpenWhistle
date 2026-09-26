"""LOCAL_REVIEW_LOGIN: one-click admin login for the release Chrome check.

Security-sensitive — this is an admin login with no password and no MFA
check, gated only by a config flag. Every guard has a test that fails
without it:
  - refuses to start (DEMO_MODE=false + LOCAL_REVIEW_LOGIN=true)
  - the route is 404, not 403, when the flag is off
  - a successful local-review login writes an audit row and a real session
  - never true outside the local review / e2e stack
  - the release Chrome check's page list stays in sync with actual routes
    and with docs/**/*.html
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import pytest
from fastapi.responses import HTMLResponse
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.routing import Route

from app.config import Settings, settings
from app.models.audit import AuditLog
from app.models.user import AdminUser
from app.services.audit import AuditAction
from app.services.auth import hash_password
from app.services.demo_seed import DEMO_ADMIN_USERNAME

ROOT = Path(__file__).parents[1]


# ── Settings guard: refuses to start ─────────────────────────────────────────


def test_local_review_login_requires_demo_mode() -> None:
    with pytest.raises(ValidationError):
        Settings(secret_key="x" * 32, local_review_login=True, demo_mode=False)  # type: ignore[call-arg]


def test_local_review_login_allowed_with_demo_mode() -> None:
    s = Settings(secret_key="x" * 32, local_review_login=True, demo_mode=True)  # type: ignore[call-arg]
    assert s.local_review_login is True


# ── Loud startup warning ─────────────────────────────────────────────────────


def test_main_warns_loudly_when_local_review_login_is_enabled() -> None:
    src = (ROOT / "app/main.py").read_text()
    assert re.search(
        r"if settings\.local_review_login:\s*\n\s*logger\.warning\(", src
    ), "app/main.py must log a WARNING at startup when LOCAL_REVIEW_LOGIN is enabled"


# ── The route: 404 when off, real login when on ──────────────────────────────


async def test_local_review_login_route_404_when_disabled(client: AsyncClient) -> None:
    assert settings.local_review_login is False  # test default (conftest sets DEMO_MODE=false)
    resp = await client.post("/admin/local-review-login", follow_redirects=False)
    assert resp.status_code == 404


async def test_local_review_login_signs_in_with_full_session_and_audit_row(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "local_review_login", True)

    user = AdminUser(
        id=uuid.uuid4(),
        username=DEMO_ADMIN_USERNAME,
        password_hash=hash_password("irrelevant-for-this-route"),
        totp_secret="JBSWY3DPEHPK3PXP",
        totp_enabled=True,
    )
    db_session.add(user)
    await db_session.commit()

    get_resp = await client.get("/admin/login")
    assert "login.local_review.button" not in get_resp.text  # locale key resolved, never raw
    csrf = get_resp.cookies.get("ow_csrf")

    resp = await client.post(
        "/admin/local-review-login",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["location"] == "/admin/dashboard"
    assert "ow_session" in resp.cookies

    dashboard = await client.get("/admin/dashboard")
    assert dashboard.status_code == 200

    row = (
        await db_session.execute(
            select(AuditLog).where(AuditLog.action == AuditAction.AUTH_LOCAL_REVIEW_LOGIN)
        )
    ).scalar_one()
    assert row.admin_username == DEMO_ADMIN_USERNAME


async def test_local_review_login_route_rejects_bad_csrf_before_signing_in(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "local_review_login", True)

    await client.get("/admin/login")  # sets the ow_csrf cookie
    resp = await client.post(
        "/admin/local-review-login",
        data={"csrf_token": "not-the-real-token"},
        follow_redirects=False,
    )
    assert resp.status_code == 403


async def test_login_page_shows_the_button_only_when_enabled(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    resp = await client.get("/admin/login")
    assert "local-review-login" not in resp.text

    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "local_review_login", True)
    resp2 = await client.get("/admin/login")
    assert "local-review-login" in resp2.text
    assert "Enter the local review" in resp2.text


# ── Never true outside the local review / e2e stack ─────────────────────────


_NEVER_TRUE_FILES = [
    "docker-compose.prod.yml",
    "docker-compose.yml",
    "charts/openwhistle/values.yaml",
    "charts/openwhistle/templates/configmap.yaml",
    "ansible/roles/openwhistle/templates/env.j2",
    "ansible/roles/openwhistle/defaults/main.yml",
]


@pytest.mark.parametrize("relpath", _NEVER_TRUE_FILES)
def test_local_review_login_never_true_outside_e2e_stack(relpath: str) -> None:
    for line in (ROOT / relpath).read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or "LOCAL_REVIEW_LOGIN" not in stripped.upper():
            continue
        assert re.search(r"\bfalse\b", stripped, re.I), f"{relpath}: {stripped!r}"


def test_local_review_login_commented_false_in_ansible_env_j2() -> None:
    text = (ROOT / "ansible/roles/openwhistle/templates/env.j2").read_text()
    assert re.search(r"^#\s*LOCAL_REVIEW_LOGIN=false\b", text, re.M), (
        "env.j2 must list LOCAL_REVIEW_LOGIN commented at its false default"
    )
    assert not re.search(r"^LOCAL_REVIEW_LOGIN=", text, re.M), "must never be a live var"


def test_local_review_login_true_only_in_e2e_compose() -> None:
    text = (ROOT / "docker-compose.e2e.yml").read_text()
    assert re.search(r'LOCAL_REVIEW_LOGIN:\s*"true"', text)


# ── Release Chrome check: the page list stays in sync ────────────────────────

# SSO callback: not a standalone page (requires a live IdP redirect with a
# state/code it did not issue), so it is not part of the reviewable page list.
_EXCLUDED_APP_PAGES = {"/admin/oidc/callback"}


def _walk_routes(router: object) -> list[Route]:
    """Recurse through both a plain Starlette Router (Mount, `.routes`) and
    this app's route-grouping wrapper (`.original_router`) to find every
    concrete Route, regardless of how include_router nested it."""
    out: list[Route] = []
    for r in getattr(router, "routes", []):
        inner = getattr(r, "original_router", None)
        if inner is not None:
            out += _walk_routes(inner)
        elif isinstance(r, Route):
            out.append(r)
    return out


def _app_html_pages() -> set[str]:
    from app.main import app

    pages = set()
    for r in _walk_routes(app):
        if not r.methods or "GET" not in r.methods or not r.include_in_schema:
            continue
        if getattr(r, "response_class", None) is not HTMLResponse:
            continue
        if r.path in _EXCLUDED_APP_PAGES:
            continue
        pages.add(r.path)
    return pages


def _docs_html_pages() -> set[str]:
    return {
        str(p.relative_to(ROOT)).replace("\\", "/") for p in (ROOT / "docs").rglob("*.html")
    }


_PATH_TOKEN = re.compile(r"`(/[^`\s]*|docs/[^`\s]*\.html)`")


def _documented_pages() -> set[str]:
    text = (ROOT / "docs-tech/local-review.md").read_text()
    return {m.group(1) for m in _PATH_TOKEN.finditer(text)}


def test_local_review_page_matrix_covers_every_app_page() -> None:
    missing = _app_html_pages() - _documented_pages()
    assert not missing, f"docs-tech/local-review.md is missing app page(s): {sorted(missing)}"


def test_local_review_page_matrix_covers_every_docs_site_page() -> None:
    missing = _docs_html_pages() - _documented_pages()
    assert not missing, f"docs-tech/local-review.md is missing docs/ page(s): {sorted(missing)}"


def test_release_md_names_the_chrome_check_before_the_release_pr() -> None:
    text = (ROOT / "docs-tech/release.md").read_text()
    chrome_at = text.index("Chrome check")
    pr_at = text.index("Release PR")
    assert chrome_at < pr_at
    assert "local-review.md" in text
