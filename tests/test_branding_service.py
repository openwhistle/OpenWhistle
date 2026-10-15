"""Resolution order and the image store (spec: Resolution)."""

from __future__ import annotations

import uuid

import pytest
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.branding import BrandImage
from app.redis_client import get_redis
from app.services import branding

pytestmark = pytest.mark.usefixtures("clean_branding")


def test_without_rows_the_environment_decides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "app_name", "Env Name")
    monkeypatch.setattr(settings, "brand_primary_color", "#123456")
    monkeypatch.setattr(settings, "brand_logo_url", "/static/env.png")
    brand = branding.resolve({}, None)
    got = (brand.name, brand.primary_color, brand.logo_url)
    assert got == ("Env Name", "#123456", "/static/env.png")


def test_an_org_field_beats_the_default_and_an_empty_one_falls_back() -> None:
    org = uuid.uuid4()
    snap = {
        "default": {"name": "Default", "primary_color": "#111111", "logo_light": "a" * 64},
        str(org): {"name": "Org", "primary_color": None, "logo_light": None},
    }
    brand = branding.resolve(snap, org)
    assert brand.name == "Org"
    assert brand.primary_color == "#111111"
    assert brand.logo_url == f"/branding/{'a' * 64}.png"


def test_the_dark_logo_comes_from_the_row_whose_light_logo_is_shown() -> None:
    org = uuid.uuid4()
    snap = {
        "default": {"logo_light": "a" * 64, "logo_dark": "b" * 64},
        str(org): {"logo_light": "c" * 64, "logo_dark": None},
    }
    brand = branding.resolve(snap, org)
    assert brand.logo_url.endswith("c" * 64 + ".png") and brand.logo_dark_url == ""


def test_a_stored_colour_that_is_not_hex_falls_back_to_the_default() -> None:
    assert branding.resolve({"default": {"primary_color": "red"}}, None).primary_color == "#0c7253"


async def test_the_snapshot_reflects_a_save_after_invalidate(db_session: AsyncSession) -> None:
    redis: Redis = await get_redis()
    await branding.invalidate(redis)
    assert "default" not in await branding.snapshot(redis)
    row = await branding.row_for(db_session, None)
    row.name = "Saved"
    await db_session.commit()
    assert "default" not in await branding.snapshot(redis)  # still cached
    await branding.invalidate(redis)
    assert (await branding.snapshot(redis))["default"]["name"] == "Saved"


async def test_a_shared_image_survives_its_removal_elsewhere(db_session: AsyncSession) -> None:
    from app.models.organisation import Organisation

    org = Organisation(id=uuid.uuid4(), name="Org", slug=f"org-{uuid.uuid4().hex[:6]}")
    db_session.add(org)
    sha = await branding.store_image(db_session, b"\x89PNG-shared")
    default = await branding.row_for(db_session, None)
    own = await branding.row_for(db_session, org.id)
    default.logo_light = own.logo_light = sha
    await db_session.commit()
    own.logo_light = None
    await branding.drop_orphan_images(db_session)
    await db_session.commit()
    assert await branding.image(db_session, sha) == b"\x89PNG-shared"
    default.logo_light = None
    await branding.drop_orphan_images(db_session)
    await db_session.commit()
    assert await db_session.scalar(select(func.count()).select_from(BrandImage)) == 0


async def test_a_load_that_began_before_a_save_leaves_no_stale_snapshot(
    db_session: AsyncSession,
) -> None:
    redis: Redis = await get_redis()
    await branding.invalidate(redis)
    version = await redis.get(branding.VERSION_KEY)
    stale = await branding._load()  # a page view reads the rows ...
    row = await branding.row_for(db_session, None)
    row.name = "Saved"
    await db_session.commit()
    await branding.invalidate(redis)  # ... a save lands meanwhile ...
    await branding._store(redis, version, stale)  # ... and the slow view caches what it read
    assert (await branding.snapshot(redis))["default"]["name"] == "Saved"


async def test_an_unreachable_redis_logs_one_line_not_a_traceback(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from types import SimpleNamespace

    async def down() -> Redis:
        raise ConnectionError("redis is down")

    monkeypatch.setattr("app.redis_client.get_redis", down)
    request = SimpleNamespace(state=SimpleNamespace())
    with caplog.at_level("WARNING", logger="app.services.branding"):
        await branding.load_branding(request)  # type: ignore[arg-type]
    assert request.state.branding_snapshot == {}
    [record] = caplog.records
    assert record.exc_info is None and "redis is down" in record.getMessage()
