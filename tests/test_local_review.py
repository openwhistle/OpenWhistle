"""LOCAL_REVIEW_LOGIN: one-click admin login for the release Chrome check.

Security-sensitive — this is an admin login with no password and no MFA
check, so the flag cannot be the only barrier. Every guard below has a test that fails without it:
  - refuses to start (DEMO_MODE=false + LOCAL_REVIEW_LOGIN=true)
  - the route is 404, not 403 or 405, for every HTTP method, when the flag
    is off or the second barrier fails
  - a second barrier independent of the flag: no proxy header, loopback
    Host — including a malformed one, which must not crash the check
  - a successful local-review login writes an audit row and a real session,
    but only after the demo admin's is_active is checked
  - a bad CSRF token leaves no session and no audit row
  - never true anywhere git tracks except the review override
  - the release Chrome check's page/template list stays in sync with actual
    routes, `app/templates/**/*.html`, and `docs/**/*.html`, and cannot pass
    on an empty walk
"""

from __future__ import annotations

import logging
import re
import subprocess
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.responses import HTMLResponse
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request as StarletteRequest
from starlette.routing import Route

from app.config import Settings, settings
from app.models.audit import AuditLog
from app.models.user import AdminUser
from app.services.audit import AuditAction
from app.services.auth import hash_password
from app.services.demo_seed import DEMO_ADMIN_USERNAME

ROOT = Path(__file__).parents[1]

# A local browser's Host header. The test client's own default (base_url=
# "https://test") sends Host: test, which is not loopback and must fail the
# second barrier — every test that needs the barrier to pass sends this.
_LOCALHOST = {"host": "localhost"}


async def _count_local_review_audit_rows(db: AsyncSession) -> int:
    return await db.scalar(
        select(func.count()).select_from(AuditLog).where(
            AuditLog.action == AuditAction.AUTH_LOCAL_REVIEW_LOGIN
        )
    ) or 0


async def _delete_demo_admin(db: AsyncSession) -> None:
    """The demo admin's username is a fixed constant the route looks up by
    name — it cannot be randomised per test the way most fixtures here avoid
    collisions, so a test that seeds it must remove it again, or a second
    test seeding it in the same (uncleaned, session-shared) test database
    hits a unique-constraint violation."""
    await db.execute(delete(AdminUser).where(AdminUser.username == DEMO_ADMIN_USERNAME))
    await db.commit()


# ── Settings guard: refuses to start ─────────────────────────────────────────


def test_local_review_login_requires_demo_mode() -> None:
    # A loopback, plain-HTTP stack, so only the missing DEMO_MODE can refuse it.
    with pytest.raises(ValidationError, match="DEMO_MODE"):
        Settings(
            secret_key="x" * 32, local_review_login=True, demo_mode=False,
            app_public_url="http://localhost:4009", secure_cookies=False,
        )


def test_local_review_login_allowed_with_demo_mode() -> None:
    s = Settings(
        secret_key="x" * 32, local_review_login=True, demo_mode=True, secure_cookies=False
    )
    assert s.local_review_login is True


@pytest.mark.parametrize(
    ("url", "secure"),
    [("https://demo.openwhistle.net", False), ("http://localhost", True),
     ("http://10.0.0.5:4009", False)],
)
def test_local_review_login_refused_outside_a_plain_loopback_stack(url: str, secure: bool) -> None:
    """The public demo has DEMO_MODE too: only a loopback, plain-HTTP stack may enable it."""
    with pytest.raises(ValidationError, match="loopback"):
        Settings(
            secret_key="x" * 32, local_review_login=True, demo_mode=True,
            app_public_url=url, secure_cookies=secure,
        )


# ── Loud startup warning — runs the real lifespan, not a source regex ───────


async def test_lifespan_warns_loudly_when_local_review_login_is_enabled(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from fastapi import FastAPI

    from app.main import lifespan

    mock_settings = MagicMock()
    mock_settings.demo_mode = True
    mock_settings.local_review_login = True

    async def mock_seed() -> None:
        return None

    with (
        patch("app.main._run_alembic_upgrade"),
        patch("app.main.close_redis", new_callable=AsyncMock),
        patch("app.main.settings", mock_settings),
        patch("app.services.demo_seed.seed_demo_data", new=mock_seed),
        caplog.at_level(logging.WARNING, logger="app.main"),
    ):
        app_tmp = FastAPI()
        async with lifespan(app_tmp):
            pass

    assert any("LOCAL_REVIEW_LOGIN is enabled" in r.message for r in caplog.records)


# ── Second barrier: request-shape check, independent of the flag ────────────


def _request_with_headers(headers: dict[str, str]) -> StarletteRequest:
    scope = {
        "type": "http",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
    }
    return StarletteRequest(scope)


@pytest.mark.parametrize(
    "host",
    [
        "localhost",
        "LOCALHOST",  # case-insensitive
        "localhost:4009",
        "127.0.0.1",
        "127.0.0.1:4009",
        "[::1]",
        "[::1]:4009",
    ],
)
def test_local_review_reachable_accepts_every_loopback_host_form(host: str) -> None:
    from app.api.auth import _local_review_reachable

    assert _local_review_reachable(_request_with_headers({"host": host})) is True


@pytest.mark.parametrize("host", ["example.com", "demo.openwhistle.net", "127.0.0.1.evil.com", ""])
def test_local_review_reachable_rejects_non_loopback_host(host: str) -> None:
    from app.api.auth import _local_review_reachable

    assert _local_review_reachable(_request_with_headers({"host": host})) is False


@pytest.mark.parametrize("host", ["[::1].evil.com", "[::1", "[", "not[valid]host", "[::1]]"])
def test_local_review_reachable_treats_malformed_bracketed_host_as_unreachable(host: str) -> None:
    """`urlsplit` raises `ValueError` for an unmatched/misplaced
    IPv6 bracket instead of returning an unparsed hostname — unparsable is
    not loopback, so this must return False, not propagate the exception
    (which would reach the client as an uncaught 500)."""
    from app.api.auth import _local_review_reachable

    assert _local_review_reachable(_request_with_headers({"host": host})) is False


@pytest.mark.parametrize(
    "header", ["x-forwarded-proto", "x-forwarded-for", "x-real-ip", "forwarded", "via"]
)
def test_local_review_reachable_rejects_any_proxy_header(header: str) -> None:
    from app.api.auth import _local_review_reachable

    headers = {"host": "localhost", header: "anything"}
    assert _local_review_reachable(_request_with_headers(headers)) is False


# ── The route: 404 for every method when off, second barrier when on ───────


async def test_local_review_login_route_404_when_disabled(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The flag alone: demo mode on and a loopback Host (the barrier passes),
    so only the setting check stands between this POST and the CSRF check."""
    assert settings.local_review_login is False  # test default (conftest sets DEMO_MODE=false)
    monkeypatch.setattr(settings, "demo_mode", True)
    resp = await client.post(
        "/admin/local-review-login", headers=_LOCALHOST, follow_redirects=False
    )
    assert resp.status_code == 404


async def test_local_review_login_404_when_no_demo_admin_exists(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Flag on, barrier passes, CSRF valid, but nothing was seeded: 404, not
    an AttributeError 500 on a missing user."""
    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "local_review_login", True)
    await _delete_demo_admin(db_session)
    csrf = (await client.get("/admin/login", headers=_LOCALHOST)).cookies.get("ow_csrf")
    resp = await client.post(
        "/admin/local-review-login",
        data={"csrf_token": csrf},
        headers=_LOCALHOST,
        follow_redirects=False,
    )
    assert resp.status_code == 404
    assert "ow_session" not in resp.cookies


_NON_POST_METHODS = ["GET", "HEAD", "PUT", "DELETE", "PATCH", "OPTIONS"]


@pytest.mark.parametrize("method", _NON_POST_METHODS)
async def test_local_review_login_route_404_for_every_method_when_disabled(
    client: AsyncClient, method: str
) -> None:
    resp = await client.request(method, "/admin/local-review-login", follow_redirects=False)
    assert resp.status_code == 404


@pytest.mark.parametrize("method", _NON_POST_METHODS)
async def test_local_review_login_route_404_for_every_method_when_enabled(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, method: str
) -> None:
    """Every method but POST is 404, not the 405 Starlette's default route
    matching gives a path that has *some* handler for a different method —
    a per-method decorator for only GET/HEAD/POST leaves
    PUT/DELETE/PATCH/OPTIONS answering 405. One
    `api_route` registered for every method, 404 for anything but an
    allowed POST, closes it regardless of which method is tried."""
    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "local_review_login", True)
    resp = await client.request(
        method, "/admin/local-review-login", headers=_LOCALHOST, follow_redirects=False
    )
    assert resp.status_code == 404


@pytest.mark.parametrize("header", ["x-forwarded-proto", "via"])
async def test_local_review_login_404_with_any_proxy_header(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, header: str
) -> None:
    """Only these two of the five ever reach the route over real HTTP:
    `SecurityMiddleware` (app/middleware.py) already strips `X-Forwarded-For`,
    `X-Real-IP` and `Forwarded` from every request, unconditionally, before
    any handler sees them — a pre-existing whistleblower-IP-privacy feature,
    not something this route adds. `_local_review_reachable` still checks all
    five (defense in depth, and correct if that stripping ever changes); the
    other three are proven at the function level instead, in
    `test_local_review_reachable_rejects_any_proxy_header` below, since a
    live request can no longer carry them this far to prove it end-to-end."""
    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "local_review_login", True)
    headers = {**_LOCALHOST, header: "anything"}
    resp = await client.post("/admin/local-review-login", headers=headers, follow_redirects=False)
    assert resp.status_code == 404


@pytest.mark.parametrize("host", ["example.com", "demo.openwhistle.net"])
async def test_local_review_login_404_with_non_loopback_host(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, host: str
) -> None:
    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "local_review_login", True)
    resp = await client.post(
        "/admin/local-review-login", headers={"host": host}, follow_redirects=False
    )
    assert resp.status_code == 404


@pytest.mark.parametrize("host", ["[::1].evil.com", "[::1", "not[valid]host"])
async def test_local_review_login_404_not_500_with_malformed_host(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, host: str
) -> None:
    """A malformed Host must not crash the route with a 500. The
    setting check alone doesn't short-circuit this (`or` only skips
    `_local_review_reachable` when the setting itself is already off), so
    the malformed Host must reach the barrier here to prove it does not
    crash, not just that a disabled route still 404s regardless."""
    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "local_review_login", True)
    resp = await client.post(
        "/admin/local-review-login", headers={"host": host}, follow_redirects=False
    )
    assert resp.status_code == 404


@pytest.mark.parametrize("host", ["[::1].evil.com", "[::1"])
async def test_login_page_does_not_crash_with_malformed_host(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, host: str
) -> None:
    """Same crash, reached through the button's own visibility check
    (`_login_ctx` → `_local_review_reachable`) rather than the route."""
    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "local_review_login", True)
    resp = await client.get("/admin/login", headers={"host": host})
    assert resp.status_code == 200
    assert "local-review-login" not in resp.text


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

    try:
        get_resp = await client.get("/admin/login", headers=_LOCALHOST)
        assert "login.local_review.button" not in get_resp.text  # locale key, never raw
        assert "local-review-login-btn" in get_resp.text
        csrf = get_resp.cookies.get("ow_csrf")

        resp = await client.post(
            "/admin/local-review-login",
            data={"csrf_token": csrf},
            headers=_LOCALHOST,
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert resp.headers["location"] == "/admin/dashboard"
        assert "ow_session" in resp.cookies

        dashboard = await client.get("/admin/dashboard", headers=_LOCALHOST)
        assert dashboard.status_code == 200

        row = (
            await db_session.execute(
                select(AuditLog).where(AuditLog.action == AuditAction.AUTH_LOCAL_REVIEW_LOGIN)
            )
        ).scalar_one()
        assert row.admin_username == DEMO_ADMIN_USERNAME
    finally:
        await _delete_demo_admin(db_session)


async def test_local_review_login_deactivated_admin_redirects_without_audit_row(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """is_active is checked before the audit write, so a deactivated demo
    admin never gets a 'signed in via local review' row for a login that
    did not happen."""
    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "local_review_login", True)

    user = AdminUser(
        id=uuid.uuid4(),
        username=DEMO_ADMIN_USERNAME,
        password_hash=hash_password("irrelevant-for-this-route"),
        totp_secret="JBSWY3DPEHPK3PXP",
        totp_enabled=True,
        is_active=False,
    )
    db_session.add(user)
    await db_session.commit()

    try:
        before = await _count_local_review_audit_rows(db_session)
        get_resp = await client.get("/admin/login", headers=_LOCALHOST)
        csrf = get_resp.cookies.get("ow_csrf")
        resp = await client.post(
            "/admin/local-review-login",
            data={"csrf_token": csrf},
            headers=_LOCALHOST,
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert resp.headers["location"] == "/admin/login"
        assert "ow_session" not in resp.cookies
        assert await _count_local_review_audit_rows(db_session) == before
    finally:
        await _delete_demo_admin(db_session)


async def test_local_review_login_route_rejects_bad_csrf_before_signing_in(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "local_review_login", True)

    before = await _count_local_review_audit_rows(db_session)
    await client.get("/admin/login", headers=_LOCALHOST)  # sets the ow_csrf cookie
    resp = await client.post(
        "/admin/local-review-login",
        data={"csrf_token": "not-the-real-token"},
        headers=_LOCALHOST,
        follow_redirects=False,
    )
    assert resp.status_code == 403
    assert "ow_session" not in resp.cookies
    assert await _count_local_review_audit_rows(db_session) == before


async def test_login_page_shows_the_button_only_when_flag_and_barrier_pass(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    resp = await client.get("/admin/login")
    assert "local-review-login" not in resp.text

    # Barrier passes, flag off: still hidden.
    monkeypatch.setattr(settings, "demo_mode", True)
    resp_flag_off = await client.get("/admin/login", headers=_LOCALHOST)
    assert "local-review-login" not in resp_flag_off.text

    monkeypatch.setattr(settings, "local_review_login", True)

    # Default test Host ("test", from the client's base_url) is not loopback:
    # flag on, barrier fails, still hidden.
    resp_bad_host = await client.get("/admin/login")
    assert "local-review-login" not in resp_bad_host.text

    # A proxy header hides it even with a loopback Host.
    resp_proxy = await client.get(
        "/admin/login", headers={**_LOCALHOST, "x-forwarded-proto": "https"}
    )
    assert "local-review-login" not in resp_proxy.text

    resp_ok = await client.get("/admin/login", headers=_LOCALHOST)
    assert "local-review-login" in resp_ok.text
    assert "Enter the local review" in resp_ok.text


# ── Never true anywhere git tracks, except the review override ──────────────

# Restricted to deployment/config file *shapes* (compose, Helm values, Ansible
# templates and example env files) — a `.py`/`.md` source or doc references
# the setting by its Python name (`settings.local_review_login`) or discusses
# it in prose constantly; neither is a place that can *set* it for a real
# deployment, so scanning them only produces false positives on the regex
# below, which is built for `KEY: value` / `KEY=value` shapes, not code.
_SCANNABLE_SUFFIXES = (".yml", ".yaml", ".j2", ".example")
_SCANNABLE_PREFIXES = (".env",)
_ALLOWLIST_EXACT = {"docker-compose.review.yml"}
_ASSIGNMENT = re.compile(r"LOCAL_REVIEW_LOGIN[\"']?\s*[:=]\s*[\"']?([A-Za-z]+)")


def _git_tracked_files() -> list[str]:
    result = subprocess.run(  # noqa: S603
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True  # noqa: S607
    )
    return result.stdout.splitlines()


def _is_scannable_config_file(relpath: str) -> bool:
    name = Path(relpath).name
    return name.endswith(_SCANNABLE_SUFFIXES) or name.startswith(_SCANNABLE_PREFIXES)


def test_local_review_login_literal_false_or_absent_everywhere_except_allowlist() -> None:
    """Every git-tracked deployment/config file, not a fixed guess list: a
    mention must be commented out, or its value must
    literally be `false` — rejects `${LOCAL_REVIEW_LOGIN:-false}` (lets
    `.env` pass `true` through) and `LOCAL_REVIEW_LOGIN=true # not false`
    (a trailing comment does not change the real value)."""
    violations = []
    for relpath in _git_tracked_files():
        if relpath in _ALLOWLIST_EXACT or not _is_scannable_config_file(relpath):
            continue
        path = ROOT / relpath
        if not path.is_file():
            continue
        try:
            text = path.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or "LOCAL_REVIEW_LOGIN" not in stripped.upper():
                continue
            m = _ASSIGNMENT.search(stripped)
            if not m or m.group(1).lower() != "false":
                violations.append(f"{relpath}: {stripped!r}")
    assert not violations


def test_local_review_login_commented_false_in_ansible_env_j2() -> None:
    text = (ROOT / "ansible/roles/openwhistle/templates/env.j2").read_text()
    assert re.search(r"^#\s*LOCAL_REVIEW_LOGIN=false\b", text, re.M), (
        "env.j2 must list LOCAL_REVIEW_LOGIN commented at its false default"
    )
    assert not re.search(r"^LOCAL_REVIEW_LOGIN=", text, re.M), "must never be a live var"


def test_local_review_login_true_only_in_review_override() -> None:
    review_text = (ROOT / "docker-compose.review.yml").read_text()
    assert re.search(r'LOCAL_REVIEW_LOGIN:\s*"true"', review_text)
    # And the plain e2e stack (CI's own file) never mentions it at all.
    e2e_text = (ROOT / "docker-compose.e2e.yml").read_text()
    assert "LOCAL_REVIEW_LOGIN" not in e2e_text.upper()


def test_review_override_binds_the_app_port_to_loopback_only() -> None:
    text = (ROOT / "docker-compose.review.yml").read_text()
    assert "127.0.0.1:4009:4009" in text
    # A plain (non-`!override`) `ports:` list is *merged*, not replaced, by
    # Compose across files — the base file's "4009:4009" (every interface)
    # would stay active too. `!override` is required for this to actually be
    # loopback-only once merged with docker-compose.e2e.yml.
    assert re.search(r"ports:\s*!override", text)


def test_review_setup_profile_is_a_fresh_install_without_the_review_login() -> None:
    """The app-setup profile exists to show /setup and the login page an
    operator sees: demo seeding would complete setup and hide both."""
    text = (ROOT / "docker-compose.review.yml").read_text()
    block = text.split("\n  app-setup:\n", 1)[1].split("\n  db-setup:\n", 1)[0]
    assert 'profiles: ["setup"]' in block
    assert 'DEMO_MODE: "false"' in block
    assert "LOCAL_REVIEW_LOGIN" not in block
    assert re.search(r'SETUP_TOKEN: "[^"]{32,}"', block)
    assert '"127.0.0.1:4010:4009"' in block


def test_review_override_button_has_a_distinct_id_and_non_primary_class() -> None:
    html = (ROOT / "app/templates/login.html").read_text()
    assert 'id="local-review-login-btn"' in html
    assert "btn-primary" not in html.split('id="local-review-login-btn"')[1].split("</button>")[0]


# ── Release Chrome check: the page/template list stays in sync ──────────────

# SSO callback: not a standalone page (requires a live IdP redirect with a
# state/code it did not issue), so it is not part of the reviewable page list.
_EXCLUDED_APP_PAGES = {"/admin/oidc/callback"}
# Layout and partials: included by another template, never rendered on their
# own, so they carry no route or matrix row of their own.
_EXCLUDED_TEMPLATES = {"base.html"}


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


def _app_templates() -> set[str]:
    templates_root = ROOT / "app/templates"
    return {
        str(p.relative_to(templates_root)).replace("\\", "/")
        for p in templates_root.rglob("*.html")
        if not p.name.startswith("_") and p.name not in _EXCLUDED_TEMPLATES
    }


_BACKTICK_TOKEN = re.compile(r"`([^`]+)`")


def _matrix_table_tokens() -> set[str]:
    """Every backtick-quoted token found only on genuine markdown table rows
    (a line starting with '|') in the page matrix — not a stray backtick
    path in running prose elsewhere in the file (an absolute filesystem
    path, a shell command). Deliberately '|', not '| `': some rows use a
    non-path placeholder in the first cell for a POST-rendered page, with
    the real path/template token in a later cell instead."""
    text = (ROOT / "docs-tech/local-review.md").read_text()
    tokens: set[str] = set()
    for line in text.splitlines():
        if not line.strip().startswith("|"):
            continue
        tokens.update(_BACKTICK_TOKEN.findall(line))
    return tokens


def test_local_review_page_matrix_covers_every_app_page() -> None:
    pages = _app_html_pages()
    assert len(pages) >= 17, f"only {len(pages)} app pages found — the route walk may be broken"
    assert {"/", "/submit", "/admin/dashboard"} <= pages
    missing = pages - _matrix_table_tokens()
    assert not missing, f"docs-tech/local-review.md is missing app page(s): {sorted(missing)}"


def test_local_review_page_matrix_covers_every_docs_site_page() -> None:
    pages = _docs_html_pages()
    assert len(pages) >= 9, f"only {len(pages)} docs/ pages found — the glob may be broken"
    missing = pages - _matrix_table_tokens()
    assert not missing, f"docs-tech/local-review.md is missing docs/ page(s): {sorted(missing)}"


def test_local_review_page_matrix_covers_every_app_template() -> None:
    templates = _app_templates()
    assert len(templates) >= 15, (
        f"only {len(templates)} templates found — the glob may be broken"
    )
    missing = templates - _matrix_table_tokens()
    assert not missing, f"docs-tech/local-review.md is missing template(s): {sorted(missing)}"


def test_release_md_names_the_chrome_check_before_the_release_pr() -> None:
    """The numbered step itself, not just the diagram: dropping the section
    while the mermaid box still says "Chrome check" must fail."""
    text = (ROOT / "docs-tech/release.md").read_text()
    steps = re.findall(r"^## \d+\. (.+)$", text, re.M)
    assert "Chrome check" in steps and "Release PR" in steps, steps
    assert steps.index("Chrome check") < steps.index("Release PR"), steps
    section = next(s for s in text.split("\n## ") if re.match(r"\d+\. Chrome check\n", s))
    assert "docs-tech/local-review.md" in section


@pytest.mark.parametrize(
    "header",
    ["x-client-ip", "x-cluster-client-ip", "true-client-ip", "cf-connecting-ip",
     "x-forwarded-for", "x-real-ip", "forwarded", "x-forwarded-proto", "via"],
)
def test_every_proxy_header_the_middleware_knows_makes_local_review_unreachable(
    header: str,
) -> None:
    """One list for both places: a header the IP middleware treats as proxy-added
    must also hide the one-click login."""
    from app.api.auth import _local_review_reachable

    request = _request_with_headers({"host": "localhost", header: "203.0.113.7"})
    assert _local_review_reachable(request) is False
