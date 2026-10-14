"""/branding/<sha>.png: the hash is the name, nothing else is served (spec: Resolution)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import branding

pytestmark = pytest.mark.usefixtures("clean_branding")


async def test_a_stored_image_is_served_as_png(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    sha = await branding.store_image(db_session, b"\x89PNG-served")
    await db_session.commit()
    response = await client.get(f"/branding/{sha}.png")
    assert response.status_code == 200 and response.content == b"\x89PNG-served"
    assert response.headers["content-type"] == "image/png"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"


async def test_an_unknown_hash_is_404(client: AsyncClient) -> None:
    assert (await client.get(f"/branding/{'0' * 64}.png")).status_code == 404


async def test_anything_but_a_hash_is_404(client: AsyncClient) -> None:
    for path in ("/branding/..%2Fsecret.png", "/branding/ABC.png", f"/branding/{'a' * 63}.png"):
        assert (await client.get(path)).status_code == 404
