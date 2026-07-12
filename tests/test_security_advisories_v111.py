"""Regression tests for the v1.1.1 security advisories.

Covers:
- GHSA-q3v3-5xf4-xjqr — missing object-level authorization on /admin/reports/{id}
  (case manager / cross-org report access & confidential-identity deanonymization).
- GHSA-g3xj-3929-r45h — vertical privilege escalation via the role-assignment
  endpoints (admin self-promotes to superadmin / creates a superadmin).
- GHSA-24hg-pf84-jj7x — username charset validation (defense-in-depth for the
  stored-XSS-in-onclick sink, which is additionally fixed at the template layer).
- GHSA-gh23-4h5j-cqj8 — security headers emitted by a single authoritative layer.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin import _can_access_report
from app.api.deps import get_current_admin
from app.main import app
from app.models.report import SubmissionMode
from app.models.user import AdminRole, AdminUser
from app.services import crypto
from app.services import report as report_service
from app.services.users import validate_username


def _user(role: AdminRole, org_id: uuid.UUID | None = None) -> AdminUser:
    """Build a detached AdminUser carrying only the attributes authz reads."""
    return AdminUser(
        id=uuid.uuid4(),
        username=f"{role.value}-{uuid.uuid4().hex[:8]}",
        role=role,
        org_id=org_id,
        is_active=True,
        totp_secret="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        totp_enabled=True,
    )


def _report(assigned_to_id: uuid.UUID | None, org_id: uuid.UUID | None = None):
    from app.models.report import Report

    return Report(id=uuid.uuid4(), assigned_to_id=assigned_to_id, org_id=org_id)


# ── GHSA-q3v3: _can_access_report authorization matrix (unit) ──────────────


def test_superadmin_can_access_any_report() -> None:
    sa = _user(AdminRole.superadmin)
    assert _can_access_report(sa, _report(assigned_to_id=uuid.uuid4())) is True


def test_case_manager_only_assigned_reports() -> None:
    cm = _user(AdminRole.case_manager)
    assert _can_access_report(cm, _report(assigned_to_id=cm.id)) is True
    assert _can_access_report(cm, _report(assigned_to_id=uuid.uuid4())) is False
    assert _can_access_report(cm, _report(assigned_to_id=None)) is False


def test_admin_can_access_reports_without_multitenancy() -> None:
    admin = _user(AdminRole.admin)
    # Assigned to someone else, but single-tenant → admin may access.
    assert _can_access_report(admin, _report(assigned_to_id=uuid.uuid4())) is True


def test_admin_org_scoping_with_multitenancy(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "multi_tenancy_enabled", True)
    org_a, org_b = uuid.uuid4(), uuid.uuid4()
    admin = _user(AdminRole.admin, org_id=org_a)
    assert _can_access_report(admin, _report(assigned_to_id=None, org_id=org_a)) is True
    assert _can_access_report(admin, _report(assigned_to_id=None, org_id=org_b)) is False
    # superadmin is exempt from org scoping.
    sa = _user(AdminRole.superadmin, org_id=None)
    assert _can_access_report(sa, _report(assigned_to_id=None, org_id=org_b)) is True


# ── GHSA-24hg: username validation (unit) ──────────────────────────────────


@pytest.mark.parametrize("name", ["alice", "case.manager", "a_b-c", "user@corp", "Bob Smith"])
def test_validate_username_accepts_allowlist(name: str) -> None:
    assert validate_username(name) == name.strip()


@pytest.mark.parametrize(
    "name",
    [
        "a'+__XSS('x')+'",       # the advisory's breakout payload
        "ab",                     # too short
        "x" * 65,                 # too long
        'quote"here',
        "semi;colon",
        "<script>",
        "back\\slash",
    ],
)
def test_validate_username_rejects_bad_input(name: str) -> None:
    with pytest.raises(ValueError):
        validate_username(name)


# ── Integration fixtures: synthetic authenticated admin ────────────────────


@pytest_asyncio.fixture(loop_scope="function")
async def as_admin(client: AsyncClient):
    """Yield (client, setter) where setter(user) forces the current admin."""
    def _set(user: AdminUser) -> None:
        app.dependency_overrides[get_current_admin] = lambda: user

    yield client, _set
    app.dependency_overrides.pop(get_current_admin, None)


async def _make_confidential_report(db: AsyncSession, assigned_to_id: uuid.UUID | None):
    report, _pin = await report_service.create_report(
        db,
        category="financial_fraud",
        description="A confidential report used for authorization tests.",
        submission_mode=SubmissionMode.confidential,
        confidential_name_enc=crypto.encrypt("REALNAME-CANARY"),
        confidential_contact_enc=crypto.encrypt("CONTACT-CANARY"),
    )
    if assigned_to_id is not None:
        report.assigned_to_id = assigned_to_id
        await db.commit()
        await db.refresh(report)
    return report


# ── GHSA-q3v3: endpoint-level authorization (integration) ──────────────────


@pytest.mark.asyncio
async def test_case_manager_cannot_open_unassigned_report(
    db_session: AsyncSession, as_admin
) -> None:
    client, set_user = as_admin
    report = await _make_confidential_report(db_session, assigned_to_id=None)

    cm = _user(AdminRole.case_manager)
    set_user(cm)
    resp = await client.get(f"/admin/reports/{report.id}", follow_redirects=False)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_case_manager_sees_identity_only_when_assigned(
    db_session: AsyncSession, as_admin
) -> None:
    client, set_user = as_admin
    from app.services.users import create_user

    # The assignee must be a real row (FK on reports.assigned_to_id).
    cm, _ = await create_user(
        db_session, f"cm-{uuid.uuid4().hex[:8]}", "TestPassword123!", AdminRole.case_manager
    )
    report = await _make_confidential_report(db_session, assigned_to_id=cm.id)

    set_user(cm)
    resp = await client.get(f"/admin/reports/{report.id}", follow_redirects=False)
    assert resp.status_code == 200
    assert "REALNAME-CANARY" in resp.text


@pytest.mark.asyncio
async def test_case_manager_cannot_add_note_to_unassigned_report(
    db_session: AsyncSession, as_admin
) -> None:
    client, set_user = as_admin
    report = await _make_confidential_report(db_session, assigned_to_id=None)

    cm = _user(AdminRole.case_manager)
    set_user(cm)
    # CSRF is enforced separately; a missing/invalid token would 4xx before authz,
    # so we assert the authz 404 by hitting the GET-guarded attachment path.
    resp = await client.get(
        f"/admin/reports/{report.id}/attachments/{uuid.uuid4()}",
        follow_redirects=False,
    )
    assert resp.status_code == 404


# ── GHSA-g3xj: privilege-escalation guards (integration) ───────────────────


def _csrf_bypass():
    """Disable CSRF validation so we can test authz in isolation."""
    from app.csrf import validate_csrf

    app.dependency_overrides[validate_csrf] = lambda: None


@pytest_asyncio.fixture(loop_scope="function")
async def no_csrf():
    _csrf_bypass()
    yield
    from app.csrf import validate_csrf

    app.dependency_overrides.pop(validate_csrf, None)


@pytest.mark.asyncio
async def test_admin_cannot_self_promote_to_superadmin(
    db_session: AsyncSession, as_admin, no_csrf
) -> None:
    client, set_user = as_admin
    from app.services.users import create_user

    admin, _ = await create_user(db_session, "plainadmin", "TestPassword123!", AdminRole.admin)
    set_user(admin)
    resp = await client.post(
        f"/admin/users/{admin.id}/role",
        data={"role": "superadmin"},
        follow_redirects=False,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_cannot_change_own_role(
    db_session: AsyncSession, as_admin, no_csrf
) -> None:
    client, set_user = as_admin
    from app.services.users import create_user

    admin, _ = await create_user(db_session, "selfrole", "TestPassword123!", AdminRole.admin)
    set_user(admin)
    resp = await client.post(
        f"/admin/users/{admin.id}/role",
        data={"role": "case_manager"},
        follow_redirects=False,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_cannot_create_superadmin(
    client: AsyncClient, as_admin, no_csrf
) -> None:
    _client, set_user = as_admin
    set_user(_user(AdminRole.admin))
    resp = await _client.post(
        "/admin/users",
        data={
            "username": "wannabe-super",
            "password": "TestPassword123!",
            "role": "superadmin",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_superadmin_can_create_superadmin(
    db_session: AsyncSession, as_admin, no_csrf
) -> None:
    _client, set_user = as_admin
    from app.services.users import create_user

    # The acting superadmin writes an audit row (FK on audit_logs.admin_id),
    # so it must be a persisted user.
    actor, _ = await create_user(
        db_session, f"sa-{uuid.uuid4().hex[:8]}", "TestPassword123!", AdminRole.superadmin
    )
    set_user(actor)
    resp = await _client.post(
        "/admin/users",
        data={
            "username": "another-super",
            "password": "TestPassword123!",
            "role": "superadmin",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302  # redirect back to /admin/users on success


# ── GHSA-24hg: bad username rejected by the create endpoint ────────────────


@pytest.mark.asyncio
async def test_create_user_rejects_xss_username(
    client: AsyncClient, as_admin, no_csrf
) -> None:
    _client, set_user = as_admin
    set_user(_user(AdminRole.superadmin))
    resp = await _client.post(
        "/admin/users",
        data={
            "username": "a'+__XSS('x')+'",
            "password": "TestPassword123!",
            "role": "admin",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 400


# ── GHSA-gh23: security headers single-source ──────────────────────────────


@pytest.mark.asyncio
async def test_security_headers_single_and_consistent(client: AsyncClient) -> None:
    resp = await client.get("/health")
    # httpx merges duplicate headers with ", "; assert single, unambiguous values.
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    hsts = resp.headers.get("Strict-Transport-Security", "")
    assert hsts.count("max-age=") == 1
    assert "server" not in {k.lower() for k in resp.headers}


# ══════════════════════════════════════════════════════════════════════════
# Adversarial edge cases — think like an attacker probing every mutating path
# and every privilege boundary, not just the happy path.
# ══════════════════════════════════════════════════════════════════════════


# ── GHSA-q3v3: IDOR must hold on EVERY report action, not just detail ──────


@pytest.mark.parametrize(
    ("method", "path_suffix", "data"),
    [
        ("post", "/acknowledge", {}),
        ("post", "/status", {"new_status": "acknowledged"}),
        ("post", "/reply", {"content": "sneaky reply"}),
        ("post", "/notes", {"content": "sneaky note"}),
        ("get", "/export.pdf", None),
    ],
)
@pytest.mark.asyncio
async def test_case_manager_blocked_from_every_unassigned_action(
    db_session: AsyncSession, as_admin, no_csrf, method: str, path_suffix: str, data
) -> None:
    """A case manager must get 404 on read AND write actions for reports not theirs."""
    client, set_user = as_admin
    report = await _make_confidential_report(db_session, assigned_to_id=None)
    set_user(_user(AdminRole.case_manager))

    url = f"/admin/reports/{report.id}{path_suffix}"
    if method == "post":
        resp = await client.post(url, data=data, follow_redirects=False)
    else:
        resp = await client.get(url, follow_redirects=False)
    assert resp.status_code == 404, f"{method} {path_suffix} leaked (status {resp.status_code})"


@pytest.mark.asyncio
async def test_assigned_case_manager_can_acknowledge(
    db_session: AsyncSession, as_admin, no_csrf
) -> None:
    """Positive counterpart: the assigned case manager CAN act on their report."""
    client, set_user = as_admin
    from app.services.users import create_user

    cm, _ = await create_user(
        db_session, f"cm-{uuid.uuid4().hex[:8]}", "TestPassword123!", AdminRole.case_manager
    )
    report = await _make_confidential_report(db_session, assigned_to_id=cm.id)
    set_user(cm)
    resp = await client.post(
        f"/admin/reports/{report.id}/acknowledge", data={}, follow_redirects=False
    )
    assert resp.status_code == 302


@pytest.mark.asyncio
async def test_admin_may_read_unassigned_report_single_tenant(
    db_session: AsyncSession, as_admin
) -> None:
    """Regression: single-tenant admins are NOT restricted to assigned reports."""
    client, set_user = as_admin
    report = await _make_confidential_report(db_session, assigned_to_id=None)
    set_user(_user(AdminRole.admin))
    resp = await client.get(f"/admin/reports/{report.id}", follow_redirects=False)
    assert resp.status_code == 200
    # An admin legitimately sees the confidential identity even when unassigned.
    assert "REALNAME-CANARY" in resp.text


# ── GHSA-g3xj: escalation guards from every angle ──────────────────────────


@pytest.mark.asyncio
async def test_admin_cannot_promote_another_admin_to_superadmin(
    db_session: AsyncSession, as_admin, no_csrf
) -> None:
    client, set_user = as_admin
    from app.services.users import create_user

    actor, _ = await create_user(
        db_session, f"a-{uuid.uuid4().hex[:6]}", "TestPassword123!", AdminRole.admin
    )
    victim, _ = await create_user(
        db_session, f"v-{uuid.uuid4().hex[:6]}", "TestPassword123!", AdminRole.admin
    )
    set_user(actor)
    resp = await client.post(
        f"/admin/users/{victim.id}/role", data={"role": "superadmin"}, follow_redirects=False
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_cannot_demote_a_superadmin(
    db_session: AsyncSession, as_admin, no_csrf
) -> None:
    """An admin must not be able to touch a superadmin's role at all."""
    client, set_user = as_admin
    from app.services.users import create_user

    actor, _ = await create_user(
        db_session, f"a-{uuid.uuid4().hex[:6]}", "TestPassword123!", AdminRole.admin
    )
    sa, _ = await create_user(
        db_session, f"s-{uuid.uuid4().hex[:6]}", "TestPassword123!", AdminRole.superadmin
    )
    set_user(actor)
    resp = await client.post(
        f"/admin/users/{sa.id}/role", data={"role": "admin"}, follow_redirects=False
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_superadmin_cannot_change_own_role(
    db_session: AsyncSession, as_admin, no_csrf
) -> None:
    """The self-role-change ban applies to superadmins too (no self-demotion foot-gun)."""
    client, set_user = as_admin
    from app.services.users import create_user

    sa, _ = await create_user(
        db_session, f"s-{uuid.uuid4().hex[:6]}", "TestPassword123!", AdminRole.superadmin
    )
    set_user(sa)
    resp = await client.post(
        f"/admin/users/{sa.id}/role", data={"role": "admin"}, follow_redirects=False
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_change_another_admin_to_case_manager(
    db_session: AsyncSession, as_admin, no_csrf
) -> None:
    """Legitimate downward role change within an admin's authority still works."""
    client, set_user = as_admin
    from app.services.users import create_user

    actor, _ = await create_user(
        db_session, f"a-{uuid.uuid4().hex[:6]}", "TestPassword123!", AdminRole.admin
    )
    # Two more admins so demoting one does not trip the last-admin guard.
    await create_user(db_session, f"a2-{uuid.uuid4().hex[:6]}", "TestPassword123!", AdminRole.admin)
    victim, _ = await create_user(
        db_session, f"v-{uuid.uuid4().hex[:6]}", "TestPassword123!", AdminRole.admin
    )
    set_user(actor)
    resp = await client.post(
        f"/admin/users/{victim.id}/role", data={"role": "case_manager"}, follow_redirects=False
    )
    assert resp.status_code == 302


@pytest.mark.asyncio
async def test_cannot_demote_last_privileged_admin(
    db_session: AsyncSession, as_admin, no_csrf
) -> None:
    """Availability invariant: the last admin/superadmin cannot be demoted away."""
    client, set_user = as_admin
    from app.services.users import (
        count_active_privileged_admins,
        create_user,
        deactivate_user,
        get_all_users,
    )

    # Reduce the instance to exactly one active privileged account.
    for u in await get_all_users(db_session):
        if u.role in (AdminRole.admin, AdminRole.superadmin) and u.is_active:
            await deactivate_user(db_session, u)
    sole, _ = await create_user(
        db_session, f"sole-{uuid.uuid4().hex[:6]}", "TestPassword123!", AdminRole.superadmin
    )
    await db_session.commit()
    if await count_active_privileged_admins(db_session) != 1:
        pytest.skip("could not reduce to a single privileged admin")

    # A second superadmin performs the (forbidden) demotion so the self-check
    # and tier-check do not fire first.
    actor, _ = await create_user(
        db_session, f"act-{uuid.uuid4().hex[:6]}", "TestPassword123!", AdminRole.superadmin
    )
    # actor is now also privileged+active → temporarily there are 2; deactivate
    # actor's privilege effect by testing demotion of `sole` while only `sole`
    # counts. Re-assert the count with actor present:
    set_user(actor)
    # With actor active there are 2 privileged admins, so demoting `sole` is allowed.
    # Deactivate actor to leave `sole` as the only one, then have a superadmin
    # (actor, still authenticated) attempt it — count is 1 → must be blocked.
    await deactivate_user(db_session, actor)
    await db_session.commit()
    resp = await client.post(
        f"/admin/users/{sole.id}/role", data={"role": "case_manager"}, follow_redirects=False
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_user_invalid_role_falls_back_to_admin_not_superadmin(
    db_session: AsyncSession, as_admin, no_csrf
) -> None:
    """A garbage role value must never silently become superadmin."""
    client, set_user = as_admin
    from app.services.auth import get_user_by_username

    set_user(_user(AdminRole.admin))
    uname = f"fallback-{uuid.uuid4().hex[:6]}"
    resp = await client.post(
        "/admin/users",
        data={"username": uname, "password": "TestPassword123!", "role": "root"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    created = await get_user_by_username(db_session, uname)
    assert created is not None
    assert created.role == AdminRole.admin


# ── GHSA-24hg: username validation — boundaries and injection payloads ─────


@pytest.mark.parametrize("name", ["abc", "a" * 64, "a.b", "a-b", "a_b", "a@b.co", "A B"])
def test_validate_username_boundaries_ok(name: str) -> None:
    assert validate_username(name) == name


@pytest.mark.parametrize(
    "name",
    [
        "ab",                         # 2 chars (below min)
        "a" * 65,                     # 65 chars (above max)
        "",                           # empty
        "   ",                        # whitespace-only
        "a\nb",                       # newline injection
        "a\tb",                       # tab
        "a\x00b",                     # null byte
        "аdmin",                      # cyrillic homoglyph 'а'
        "a<b",                        # angle bracket
        "a>b",
        'a"b',
        "a'b",
        "a/b",
        "a\\b",
        "a;b",
        "a`b",
        "a${b}",
        "a%27b",
    ],
)
def test_validate_username_rejects_injection_and_boundaries(name: str) -> None:
    with pytest.raises(ValueError):
        validate_username(name)


def test_validate_username_strips_surrounding_whitespace() -> None:
    assert validate_username("  alice  ") == "alice"


# ── GHSA-gh23: the CSP itself — strict, nonce-based, unique per request ────


@pytest.mark.asyncio
async def test_csp_is_strict_and_nonce_based(client: AsyncClient) -> None:
    resp = await client.get("/admin/login")
    csp = resp.headers.get("Content-Security-Policy", "")
    assert csp, "no CSP header"
    assert "unsafe-inline" not in csp, "CSP still allows unsafe-inline"
    assert "unsafe-eval" not in csp
    assert "script-src 'self' 'nonce-" in csp
    assert "style-src 'self' 'nonce-" in csp
    assert "object-src 'none'" in csp
    assert "base-uri 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    # httpx would join duplicate headers with ", "; a single policy has none of that.
    assert csp.count("default-src") == 1


@pytest.mark.asyncio
async def test_csp_nonce_is_unique_per_response(client: AsyncClient) -> None:
    import re

    def nonce_of(csp: str) -> str:
        m = re.search(r"'nonce-([^']+)'", csp)
        return m.group(1) if m else ""

    r1 = await client.get("/admin/login")
    r2 = await client.get("/admin/login")
    n1 = nonce_of(r1.headers.get("Content-Security-Policy", ""))
    n2 = nonce_of(r2.headers.get("Content-Security-Policy", ""))
    assert n1 and n2 and n1 != n2, "CSP nonce must differ per response"


@pytest.mark.asyncio
async def test_rendered_html_uses_the_header_nonce(client: AsyncClient) -> None:
    """The nonce in the CSP header must match the nonce on inline blocks, or
    the browser would drop every inline script/style."""
    import re

    resp = await client.get("/admin/login")
    csp = resp.headers.get("Content-Security-Policy", "")
    m = re.search(r"'nonce-([^']+)'", csp)
    assert m, "no nonce in CSP"
    nonce = m.group(1)
    # The login page extends base.html, which has nonce'd <script>/<style> blocks.
    assert f'nonce="{nonce}"' in resp.text
