"""After an update, the dashboard asks once whether to count this installation."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.user import AdminRole
from tests.test_v210_bug_bounty import _totp_user

ASK = 'class="alert alert-info telemetry-ask"'


async def _dashboard(acting_as, user) -> str:  # type: ignore[no-untyped-def]
    client, act = acting_as
    act(user)
    return (await client.get("/admin/dashboard")).text


@pytest.fixture
def unlocked(monkeypatch: pytest.MonkeyPatch) -> None:
    """The switch decides: no demo, no review stack, no TELEMETRY_ENABLED."""
    monkeypatch.setattr(settings, "demo_mode", False)
    monkeypatch.setattr(settings, "local_review_login", False)
    monkeypatch.setattr(settings, "telemetry_enabled", None)


@pytest.mark.asyncio
async def test_asked_once_per_version(
    acting_as, db_session: AsyncSession, unlocked: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = await _totp_user(db_session, AdminRole.admin)
    first = await _dashboard(acting_as, admin)
    assert ASK in first
    assert "https://openwhistle.net/en/docs/install-count/" in first
    assert 'action="/admin/system/telemetry"' in first
    assert ASK not in await _dashboard(acting_as, admin)  # once is enough

    monkeypatch.setattr(settings, "app_version", "99.0.0")  # the next update
    assert ASK in await _dashboard(acting_as, admin)


@pytest.mark.asyncio
async def test_not_asked_while_counting(
    acting_as, db_session: AsyncSession, unlocked: None
) -> None:
    from app.services.telemetry import ensure_state

    state = await ensure_state(db_session)
    state.enabled = True
    await db_session.commit()
    try:
        admin = await _totp_user(db_session, AdminRole.admin)
        assert ASK not in await _dashboard(acting_as, admin)
    finally:
        state.enabled = False
        await db_session.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("lock", ["demo_mode", "telemetry_off", "telemetry_on"])
async def test_not_asked_where_the_environment_decides(
    acting_as, db_session: AsyncSession, unlocked: None, monkeypatch: pytest.MonkeyPatch, lock: str
) -> None:
    if lock == "demo_mode":
        monkeypatch.setattr(settings, "demo_mode", True)
    else:
        monkeypatch.setattr(settings, "telemetry_enabled", lock == "telemetry_on")
    admin = await _totp_user(db_session, AdminRole.admin)
    assert ASK not in await _dashboard(acting_as, admin)


@pytest.mark.asyncio
async def test_not_asked_who_cannot_switch_it(
    acting_as, db_session: AsyncSession, unlocked: None
) -> None:
    manager = await _totp_user(db_session, AdminRole.case_manager)
    assert ASK not in await _dashboard(acting_as, manager)
