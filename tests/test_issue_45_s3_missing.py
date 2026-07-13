"""Issue #45 — a missing S3 object must yield 404, not an unhandled 500."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from botocore.exceptions import ClientError
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin
from app.main import app
from app.models.user import AdminRole, AdminUser
from app.services.storage import S3StorageBackend, StorageObjectNotFoundError


def _s3_backend() -> S3StorageBackend:
    return S3StorageBackend(
        bucket="b", prefix="p/", region="r", access_key="k", secret_key="s", endpoint_url=None
    )


@pytest.mark.asyncio
async def test_s3_get_missing_object_raises_not_found() -> None:
    client = MagicMock()
    client.get_object.side_effect = ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
    with patch("boto3.client", return_value=client), pytest.raises(StorageObjectNotFoundError):
        await _s3_backend().get("some/key")


@pytest.mark.asyncio
async def test_s3_get_other_error_propagates() -> None:
    """A genuine backend error must NOT be masked as not-found (stays a 5xx)."""
    client = MagicMock()
    client.get_object.side_effect = ClientError({"Error": {"Code": "InternalError"}}, "GetObject")
    with patch("boto3.client", return_value=client), pytest.raises(ClientError):
        await _s3_backend().get("some/key")


# ── Handler maps the missing-object error to 404 ───────────────────────────


class _RaisingBackend:
    async def get(self, key: str) -> bytes:
        raise StorageObjectNotFoundError(key)


@pytest_asyncio.fixture(loop_scope="function")
async def as_admin(client: AsyncClient):
    admin = AdminUser(
        id=uuid.uuid4(),
        username="dl-admin",
        role=AdminRole.admin,
        is_active=True,
        totp_secret="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        totp_enabled=True,
    )
    app.dependency_overrides[get_current_admin] = lambda: admin
    yield client
    app.dependency_overrides.pop(get_current_admin, None)


@pytest.mark.asyncio
async def test_admin_download_missing_s3_object_returns_404(
    db_session: AsyncSession, as_admin: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.models.attachment import Attachment
    from app.services import storage
    from app.services.report import create_report

    report, _ = await create_report(db_session, "financial_fraud", "S3 missing object test.")
    att = Attachment(
        id=uuid.uuid4(),
        report_id=report.id,
        filename="evidence.pdf",
        content_type="application/pdf",
        size=3,
        data=None,
        storage_key="k/evidence.pdf",
    )
    db_session.add(att)
    await db_session.commit()

    monkeypatch.setattr(storage, "get_storage_backend", lambda: _RaisingBackend())
    resp = await as_admin.get(
        f"/admin/reports/{report.id}/attachments/{att.id}", follow_redirects=False
    )
    assert resp.status_code == 404
