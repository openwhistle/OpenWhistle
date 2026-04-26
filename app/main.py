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
    _run_alembic_upgrade()

    if settings.demo_mode:
        from app.services.demo_seed import seed_demo_data

        await seed_demo_data()
        logger.info("Demo data seeded.")

    scheduler = None
    if settings.reminder_enabled:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler  # noqa: PLC0415

        from app.services.reminders import send_sla_reminders  # noqa: PLC0415

        scheduler = AsyncIOScheduler()
        scheduler.add_job(send_sla_reminders, "interval", minutes=30, id="sla_reminders")
        scheduler.start()
        logger.info("SLA reminder scheduler started (interval: 30 min).")

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
