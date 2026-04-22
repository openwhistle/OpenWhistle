"""FastAPI application factory with startup migration check."""

import logging
import subprocess
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.csrf import CSRFMiddleware
from app.middleware import SecurityMiddleware
from app.redis_client import close_redis

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

    yield

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
