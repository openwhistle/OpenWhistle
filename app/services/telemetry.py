"""Installation count — voluntary, off by default, modelled on easywall's.

Once a day, if an admin agreed, one request leaves the host:

    GET https://telemetry.wdkro.de/v1/openwhistle/count?id=<32 hex>&v=<version>

``id`` is 16 random bytes made here on first use and kept in the database;
``v`` is the running version. Nothing else: no hostname, no address, no count
of reports, users or organisations, no configuration. It answers how many
installations exist and on which version, and nothing about any of them.

Consent is read on every attempt, so switching it off stops the next report
without a restart. ``TELEMETRY_ENABLED`` in the environment overrides the
in-app answer, and a demo or local-review instance is never counted.
"""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.telemetry import TelemetryState

log = logging.getLogger(__name__)

# Module-level so tests point it at a local server; nothing else may change it.
TELEMETRY_ENDPOINT = "https://telemetry.wdkro.de/v1/openwhistle/count"
TIMEOUT_SECONDS: float = 10

# A success is good for a day; the job wakes hourly to ask whether a day passed.
INTERVAL = timedelta(hours=24)
TICK_HOURS = 1
# Largest random delay before the first report, so installations upgraded
# together do not all arrive in the same minute.
MAX_SPREAD_SECONDS = 3600

# Taken per attempt and never released: across all replicas at most one
# attempt per ~hour, and a failure is retried at the next tick, not in a loop.
LOCK_KEY = "openwhistle:job_lock:telemetry"
_LOCK_TTL_SECONDS = 55 * 60


def locked_by() -> str | None:
    """Why the in-app switch does not decide: "demo", "env_off", "env_on" or None."""
    if settings.demo_mode or settings.local_review_login:
        return "demo"
    if settings.telemetry_enabled is False:
        return "env_off"
    if settings.telemetry_enabled is True:
        return "env_on"
    return None


def is_enabled(state: TelemetryState | None) -> bool:
    lock = locked_by()
    if lock is not None:
        return lock == "env_on"
    return state is not None and state.enabled


def new_installation_id() -> str:
    """Random, not derived: a hash of the hostname could be recomputed by anyone
    who knows the host, which would turn a count into a lookup."""
    return secrets.token_hex(16)


async def get_state(db: AsyncSession) -> TelemetryState:
    """The single row, created switched off with a new identifier on first use.
    Flushes only; the caller commits."""
    await db.execute(
        insert(TelemetryState)
        .values(id=1, enabled=False, installation_id=new_installation_id())
        .on_conflict_do_nothing(index_elements=["id"])
    )
    state = await db.scalar(
        select(TelemetryState).where(TelemetryState.id == 1)
        .execution_options(populate_existing=True)
    )
    assert state is not None  # noqa: S101 — inserted just above
    return state


def report_url(installation_id: str) -> str:
    """The full request, as the System page shows it."""
    return f"{TELEMETRY_ENDPOINT}?id={installation_id}&v={settings.app_version}"


async def send_report(installation_id: str) -> bool:
    """One GET, two parameters. A redirect is refused: the documentation names
    exactly one destination. Any failure is a debug line and False."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, follow_redirects=False) as client:
            resp = await client.get(
                TELEMETRY_ENDPOINT,
                params={"id": installation_id, "v": settings.app_version},
                headers={"User-Agent": f"openwhistle/{settings.app_version}"},
            )
    except Exception as exc:  # noqa: BLE001 — a count must never cost the operator an error
        log.debug("Installation count not sent: %s", type(exc).__name__)
        return False
    if not resp.is_success:
        log.debug("Installation count not accepted: HTTP %s", resp.status_code)
        return False
    return True


def _due(state: TelemetryState, now: datetime) -> bool:
    return state.last_sent_at is None or now - state.last_sent_at >= INTERVAL


async def report_if_due(db: AsyncSession, redis: Redis) -> bool:
    """Send one report if consent is in place and a day passed since the last
    success. True only when a report was accepted (and recorded)."""
    if locked_by() in ("demo", "env_off"):
        return False
    state = await get_state(db)
    await db.commit()
    if not is_enabled(state) or not _due(state, datetime.now(UTC)):
        return False

    try:
        if not await redis.set(LOCK_KEY, "1", nx=True, ex=_LOCK_TTL_SECONDS):
            return False  # another replica has this hour's attempt
    except Exception as exc:  # noqa: BLE001
        log.debug("Installation count skipped, no lock: %s", type(exc).__name__)
        return False

    # Read again under the lock: another replica may have just reported.
    await db.refresh(state)
    if not is_enabled(state) or not _due(state, datetime.now(UTC)):
        return False
    if not await send_report(state.installation_id):
        # Not recorded: a host offline for a week reports on the day it is back.
        return False
    state.last_sent_at = datetime.now(UTC)
    await db.commit()
    return True


async def run_telemetry_job() -> None:
    """The hourly scheduler job, on its own connections."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: PLC0415
    from sqlalchemy.pool import NullPool  # noqa: PLC0415

    engine = create_async_engine(settings.database_url, poolclass=NullPool, hide_parameters=True)
    redis = Redis.from_url(settings.redis_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            await report_if_due(db, redis)
    except Exception as exc:  # noqa: BLE001
        log.debug("Installation count skipped: %s", type(exc).__name__)
    finally:
        await redis.aclose()
        await engine.dispose()


def schedule(scheduler: Any) -> bool:
    """Register the hourly job unless nothing could ever be sent. The first run
    waits a random part of an hour."""
    if locked_by() in ("demo", "env_off"):
        return False
    first = datetime.now(UTC) + timedelta(seconds=secrets.randbelow(MAX_SPREAD_SECONDS))
    scheduler.add_job(
        run_telemetry_job, "interval", hours=TICK_HOURS, next_run_time=first, id="telemetry"
    )
    return True
