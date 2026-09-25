"""Issue #45 — a missing S3 object must yield 404, not an unhandled 500."""

from __future__ import annotations

import logging
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


def test_s3_without_the_extra_names_it() -> None:
    with patch.dict("sys.modules", {"boto3": None}), \
         pytest.raises(RuntimeError, match="'s3' extra"):
        _s3_backend()._client()


# ── Task 17 fix round 1: a legacy (filename-bearing) key must never reach a
# log line or an exception message ──────────────────────────────────────────

_FILENAME_KEY = "Max_Mustermann_evidence.pdf"


@pytest.mark.asyncio
async def test_s3_get_missing_object_message_has_no_filename(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The raised exception's message — which can end up in logs via str(exc)
    — must not carry the legacy key, even though it names a person.
    """
    client = MagicMock()
    client.get_object.side_effect = ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
    with (
        caplog.at_level(logging.INFO, logger="app.services.storage"),
        patch("boto3.client", return_value=client),
        pytest.raises(StorageObjectNotFoundError) as exc_info,
    ):
        await _s3_backend().get(_FILENAME_KEY)

    assert "Max_Mustermann" not in str(exc_info.value)
    assert "Max_Mustermann" not in caplog.text


@pytest.mark.asyncio
async def test_s3_delete_logs_no_filename(caplog: pytest.LogCaptureFixture) -> None:
    """delete() must log that an object was deleted, without the key itself:
    a re-key deletes the *old* (filename-bearing) key once the copy succeeds.
    """
    client = MagicMock()
    with (
        caplog.at_level(logging.INFO, logger="app.services.storage"),
        patch("boto3.client", return_value=client),
    ):
        await _s3_backend().delete(_FILENAME_KEY)

    assert "Max_Mustermann" not in caplog.text
    assert any("Deleted attachment from S3" in record.message for record in caplog.records)


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


# ── Task 17 fix round 2: read_attachment()'s LookupError must not carry a
# not-yet-rekeyed legacy row's storage_key, which is the original filename ──


@pytest.mark.asyncio
async def test_read_attachment_lookup_error_has_no_filename(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.models.attachment import Attachment
    from app.services import storage
    from app.services.attachment import read_attachment
    from app.services.report import create_report

    report, _ = await create_report(db_session, "financial_fraud", "Legacy S3 lookup test.")
    # A per-test-unique key: this row is committed to the shared test DB, and
    # rekey_legacy_objects() elsewhere scans the *whole* attachments table, so
    # reusing the exact literal _FILENAME_KEY here would collide with that
    # test's own row of the same key once both are committed in one session.
    legacy_key = f"Max_Mustermann_evidence-{uuid.uuid4().hex}.pdf"
    att = Attachment(
        id=uuid.uuid4(),
        report_id=report.id,
        filename="x",
        content_type="application/pdf",
        size=3,
        data=None,
        storage_key=legacy_key,
    )
    db_session.add(att)
    await db_session.commit()

    monkeypatch.setattr(storage, "get_storage_backend", lambda: _RaisingBackend())
    with pytest.raises(LookupError) as exc_info:
        await read_attachment(db_session, att)

    assert "Max_Mustermann" not in str(exc_info.value)
    assert str(exc_info.value) == str(att.id)
