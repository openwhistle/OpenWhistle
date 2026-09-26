"""FastAPI application factory with startup migration check."""

import asyncio
import logging
import subprocess
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exception_handlers import (
    http_exception_handler as _default_http_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings
from app.csrf import CSRFMiddleware
from app.i18n import get_lang, make_translator
from app.logging_config import configure_logging
from app.middleware import SecurityMiddleware
from app.redis_client import close_redis

# A generic, localised message per status code an HTML page may show for a
# raised HTTPException — never the raw exc.detail, which can carry internal
# detail (e.g. "Case number not found") not meant for a reporter/admin's screen.
_HTML_ERROR_DETAIL_KEYS: dict[int, str] = {
    400: "error.detail.400",
    401: "error.detail.401",
    403: "error.detail.403",
    404: "error.detail.404",
    409: "error.detail.409",
    422: "error.detail.422",
}

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


def _log_rekey_task_result(task: asyncio.Task[None]) -> None:
    """Done-callback for the background S3 re-key task.

    A bare create_task() swallows a failing task's exception until something
    awaits it — which nothing does here, so surface it. Only the exception
    type is logged, never its message: a legacy storage_key is a filename and
    could end up inside some other exception's text.
    """
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("Background S3 re-key task failed: %s", type(exc).__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    if not settings.encryption_key:
        logger.warning(
            "ENCRYPTION_KEY is not set: SECRET_KEY is used for both session signing and "
            "encryption. On an existing install do not just set it (data would become "
            "unreadable): see 'Rotating the encryption key' in the documentation."
        )
    from app.services.encryption import (  # noqa: PLC0415
        UNREADABLE_DATA_MESSAGE,
        configured_keys_read_existing_data,
    )

    if not await configured_keys_read_existing_data():
        msg = f"Refusing to start, nothing was written. {UNREADABLE_DATA_MESSAGE}"
        logger.error(msg)
        raise RuntimeError(msg)
    _run_alembic_upgrade()

    if settings.multi_tenancy_enabled:
        # Only once set up: a fresh install creates the default org in the setup wizard.
        from app.api.wizard import _is_setup_complete  # noqa: PLC0415
        from app.database import AsyncSessionLocal  # noqa: PLC0415
        from app.services.report import (  # noqa: PLC0415
            active_default_org_id,
            default_org_missing_message,
        )

        async with AsyncSessionLocal() as db:
            if await _is_setup_complete(db) and await active_default_org_id(db) is None:
                msg = f"Refusing to start. {default_org_missing_message()}"
                logger.error(msg)
                raise RuntimeError(msg)

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

    if settings.local_review_login:
        logger.warning(
            "LOCAL_REVIEW_LOGIN is enabled: /admin/login shows a one-click button that "
            "signs in as the seeded demo admin with no password or MFA check. This must "
            "never run against a real database — see docs-tech/local-review.md."
        )

    rekey_task = None
    if settings.storage_backend == "s3":
        from app.services.attachment import run_s3_rekey  # noqa: PLC0415

        rekey_task = asyncio.create_task(run_s3_rekey())
        rekey_task.add_done_callback(_log_rekey_task_result)

    from app.services.notifications import batching_enabled  # noqa: PLC0415
    from app.services.telemetry import locked_by as telemetry_locked_by  # noqa: PLC0415

    scheduler = None
    if (
        settings.reminder_enabled
        or settings.retention_enabled
        or settings.update_check_enabled
        or batching_enabled()
        or telemetry_locked_by() not in ("demo", "env_off")
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

        from app.services.telemetry import schedule as schedule_telemetry  # noqa: PLC0415

        # Registered even while the in-app switch is off: it is read on every tick.
        if schedule_telemetry(scheduler):
            logger.info("Installation-count job registered (hourly; sends only with consent).")

        scheduler.start()

    yield

    if rekey_task is not None:
        rekey_task.cancel()

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

    @application.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> Response:
        """A browser navigating to an HTML route gets the styled, localised
        error page; an API/JSON client keeps the plain `{"detail": ...}` body
        it always got (this replaces FastAPI's own default handler, which
        always returned JSON — see the 404 on a stale /admin/reports/<id>)."""
        if "text/html" not in request.headers.get("accept", ""):
            return await _default_http_exception_handler(request, exc)

        from app.templating import render

        t = make_translator(get_lang(request))
        key = _HTML_ERROR_DETAIL_KEYS.get(exc.status_code, "error.detail.generic")
        return render(
            request,
            "error.html",
            {"status_code": exc.status_code, "detail": t(key)},
            status_code=exc.status_code,
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
