"""Defects found by the bug bounty after v2.2.1, each reproduced before it was fixed."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

# ── The lockout must not say when the reporter signed in ───────────────────


@pytest.mark.asyncio
async def test_a_correct_pin_leaves_the_lockout_as_it_was(
    client: object, db_session: AsyncSession
) -> None:
    """A correct PIN cleared the case's failure counter. Anyone who knows a case number
    (every admin does) could lock it with wrong PINs and probe again: the lock gone meant
    the reporter had signed in, to the minute of the probe. A correct PIN gets in
    whatever the counter says, so it no longer touches it."""
    from app.config import settings
    from app.redis_client import get_redis
    from app.services.report import authenticate_whistleblower, create_report

    redis = await get_redis()
    report, pin = await create_report(db_session, "financial_fraud", "Probed for its sign-in.")
    for _ in range(settings.max_access_attempts + 1):
        _, locked = await authenticate_whistleblower(db_session, redis, report.case_number, "x")
    assert locked > 0

    found, _ = await authenticate_whistleblower(db_session, redis, report.case_number, pin)
    assert found is not None  # the reporter still gets in

    _, locked_after = await authenticate_whistleblower(db_session, redis, report.case_number, "x")
    assert locked_after > 0


# ── nginx clears every header the app knows to carry an address ─────────────


def test_nginx_clears_every_header_the_app_strips() -> None:
    """2.2.1 taught the app seven more address headers (Fastly, Envoy, Azure, App Engine,
    ingress-nginx, Cloudflare IPv6); the bundled nginx kept clearing the first seven only,
    while its comment said no IP data could reach the app "under any circumstances"."""
    import re
    from pathlib import Path

    from app.middleware import _IP_REVEAL_HEADERS

    conf = (Path(__file__).parents[1] / "nginx/snippets/proxy-headers.conf").read_text()
    cleared = {h.lower() for h in re.findall(r'^proxy_set_header\s+(\S+)\s+"";', conf, re.M)}
    assert set(_IP_REVEAL_HEADERS) <= cleared, sorted(set(_IP_REVEAL_HEADERS) - cleared)


# ── Deactivating an account ends its sessions ───────────────────────────────


@pytest.mark.asyncio
async def test_a_reactivated_account_does_not_get_its_old_sessions_back(
    acting_as, db_session: AsyncSession
) -> None:
    """Deactivation refused the account's sessions while it lasted but left them in
    Redis: reactivated within the hour, a browser it was signed in on (left at a desk,
    taken) was signed in again (measured: 200). A reset authenticator already ends them."""
    from app.models.user import AdminRole
    from app.redis_client import get_redis
    from app.services.auth import create_access_token, store_session
    from tests.test_v210_bug_bounty import _totp_user

    client, act = acting_as
    admin = await _totp_user(db_session, AdminRole.superadmin)
    user = await _totp_user(db_session)
    user.must_change_password = False
    await db_session.commit()
    token = create_access_token(str(user.id), role=user.role.value)
    await store_session(await get_redis(), str(user.id), token)
    client.cookies.set("ow_session", token)
    # /admin/account reads the session itself; acting_as replaces get_current_admin only.
    assert (await client.get("/admin/account")).status_code == 200

    act(admin)
    assert (
        await client.post(f"/admin/users/{user.id}/deactivate", follow_redirects=False)
    ).status_code == 302
    assert (
        await client.post(f"/admin/users/{user.id}/reactivate", follow_redirects=False)
    ).status_code == 302
    resp = await client.get("/admin/account", follow_redirects=False)
    assert resp.status_code != 200, resp.status_code
