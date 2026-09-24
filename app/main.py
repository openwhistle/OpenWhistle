"""FastAPI application factory with startup migration check."""

import logging
import subprocess
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.csrf import CSRFMiddleware
from app.logging_config import configure_logging
from app.middleware import SecurityMiddleware
from app.redis_client import close_redis

configure_logging(settings.log_level, settings.log_format)

logger = logging.getLogger(__name__)


def _run_alembic_upgrade() -> None:
    """Run alembic upgrade head — blocks startup if migrations fail.

    This ensures ALL migrations are applied on every start, not just the last one.
    Alembic upgrade head is idempotent: it only runs missing migrations.
    """
    logger.info("Running database migrations (alembic upgrade head)…")
    result = subprocess.run(  # noqa: S603
        ["alembic", "upgrade", "head"],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        logger.error("Alembic migration FAILED:\n%s", result.stderr)
        print(result.stderr, file=sys.stderr)
        msg = "Database migration failed — refusing to start. Fix migrations before deploying."
        raise RuntimeError(msg)
    logger.info("Database migrations applied successfully.")
    if result.stdout:
        logger.info(result.stdout)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    if not settings.encryption_key:
        logger.warning(
            "ENCRYPTION_KEY is not set: SECRET_KEY is used for both session signing and "
            "encryption. See 'Rotating the encryption key' in the documentation."
        )
    _run_alembic_upgrade()

    if not settings.demo_mode:
        from app.api.wizard import _is_setup_complete  # noqa: PLC0415
        from app.database import AsyncSessionLocal  # noqa: PLC0415
        from app.redis_client import get_redis  # noqa: PLC0415
        from app.services.setup_token import ensure_setup_token  # noqa: PLC0415

        async with AsyncSessionLocal() as db:
            if not await _is_setup_complete(db):
                await ensure_setup_token(await get_redis())

    if settings.demo_mode:
        from app.services.demo_seed import seed_demo_data

        await seed_demo_data()
        logger.info("Demo data seeded.")

    from app.services.notifications import batching_enabled  # noqa: PLC0415

    scheduler = None
    if (
        settings.reminder_enabled
        or settings.retention_enabled
        or settings.update_check_enabled
        or batching_enabled()
    ):
        from apscheduler.schedulers.asyncio import AsyncIOScheduler  # noqa: PLC0415

        scheduler = AsyncIOScheduler()

        if settings.reminder_enabled:
            from app.services.reminders import send_sla_reminders  # noqa: PLC0415

            scheduler.add_job(
                send_sla_reminders, "interval", minutes=30, id="sla_reminders"
            )
            logger.info("SLA reminder scheduler registered (interval: 30 min).")

        if settings.retention_enabled:
            from app.services.retention import run_retention_cleanup  # noqa: PLC0415

            scheduler.add_job(
                run_retention_cleanup, "cron", hour=3, minute=0, id="retention_cleanup"
            )
            logger.info("Data retention scheduler registered (daily at 03:00 UTC).")

        if batching_enabled():
            from datetime import UTC, datetime  # noqa: PLC0415

            from app.services.notifications import deliver_notification_digest  # noqa: PLC0415

            # Aligned to a fixed origin, so every replica fires at the same moment.
            scheduler.add_job(
                deliver_notification_digest, "interval",
                minutes=settings.notification_batch_minutes,
                start_date=datetime(2026, 1, 1, tzinfo=UTC), id="notification_digest",
            )
            logger.info(
                "Notification digest registered (every %d min).",
                settings.notification_batch_minutes,
            )

        if settings.update_check_enabled:
            from app.services.version_check import refresh_update_check  # noqa: PLC0415

            scheduler.add_job(
                refresh_update_check, "cron", hour=4, minute=0, id="update_check"
            )
            # Populate the cache once at startup so the System page has data
            # before the first daily run.
            scheduler.add_job(refresh_update_check, id="update_check_startup")
            logger.info("Update-check scheduler registered (daily at 04:00 UTC).")

        scheduler.start()

    yield

    if scheduler is not None:
        scheduler.shutdown(wait=False)

    await close_redis()


def create_app() -> FastAPI:
    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    application.add_middleware(SecurityMiddleware)
    application.add_middleware(CSRFMiddleware)

    @application.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> HTMLResponse:
        from app.templating import render

        return render(
            request,
            "error.html",
            {"status_code": 422, "detail": "The submitted form data was invalid."},
            status_code=422,
        )

    application.mount(
        "/static",
        StaticFiles(directory="app/static"),
        name="static",
    )

    from app.api.admin import router as admin_router
    from app.api.auth import router as auth_router
    from app.api.reports import router as reports_router
    from app.api.wizard import router as wizard_router

    application.include_router(reports_router)
    application.include_router(auth_router)
    application.include_router(admin_router)
    application.include_router(wizard_router)

    return application


app = create_app()
