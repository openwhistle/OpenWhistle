"""Attachment storage abstraction — DB BLOB (default) or S3-compatible object storage.

Backend is selected by STORAGE_BACKEND env var:
  "db"  — store binary data in the attachments.data column (default, no extra deps)
  "s3"  — store in S3-compatible bucket; attachments.data is NULL, storage_key is set

boto3 is called via asyncio.to_thread so the async API is not blocked.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

log = logging.getLogger(__name__)


class StorageObjectNotFoundError(Exception):
    """Raised when an attachment's stored object is missing from the backend.

    Lets the download handlers return a clean 404 instead of surfacing a raw
    backend error as a 500 (e.g. the S3 object was deleted out-of-band).
    """


class StorageBackend:
    """Thin protocol that both backends implement."""

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        raise NotImplementedError

    async def get(self, key: str) -> bytes:
        raise NotImplementedError

    async def delete(self, key: str) -> None:
        raise NotImplementedError


class DBStorageBackend(StorageBackend):
    """No-op backend: data is stored directly in the Attachment.data column."""

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        pass  # data passed through the model directly

    async def get(self, key: str) -> bytes:
        raise NotImplementedError("DB backend reads data from the ORM model, not this method")

    async def delete(self, key: str) -> None:
        pass  # cascade delete handles cleanup


class S3StorageBackend(StorageBackend):
    """Store attachments in an S3-compatible bucket using boto3 (sync, thread-pool wrapped)."""

    def __init__(
        self,
        bucket: str,
        prefix: str,
        region: str,
        access_key: str,
        secret_key: str,
        endpoint_url: str | None,
    ) -> None:
        self._bucket = bucket
        self._prefix = prefix.rstrip("/") + "/"
        self._region = region
        self._access_key = access_key
        self._secret_key = secret_key
        self._endpoint_url = endpoint_url or None

    def _client(self) -> Any:
        import boto3  # noqa: PLC0415

        kwargs: dict[str, Any] = {
            "region_name": self._region,
            "aws_access_key_id": self._access_key,
            "aws_secret_access_key": self._secret_key,
        }
        if self._endpoint_url:
            kwargs["endpoint_url"] = self._endpoint_url
        return boto3.client("s3", **kwargs)

    def _full_key(self, key: str) -> str:
        return f"{self._prefix}{key}"

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        client = self._client()
        full_key = self._full_key(key)
        await asyncio.to_thread(
            client.put_object,
            Bucket=self._bucket,
            Key=full_key,
            Body=data,
            ContentType=content_type,
        )
        log.info("Stored attachment in S3: %s", full_key)

    async def get(self, key: str) -> bytes:
        from botocore.exceptions import ClientError  # noqa: PLC0415

        client = self._client()
        full_key = self._full_key(key)
        try:
            response = await asyncio.to_thread(
                client.get_object, Bucket=self._bucket, Key=full_key
            )
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in {"NoSuchKey", "NoSuchBucket", "404", "AccessDenied"}:
                raise StorageObjectNotFoundError(full_key) from exc
            raise  # a genuine backend/connectivity error stays a 5xx
        body: bytes = await asyncio.to_thread(response["Body"].read)
        return body

    async def delete(self, key: str) -> None:
        client = self._client()
        full_key = self._full_key(key)
        await asyncio.to_thread(
            client.delete_object, Bucket=self._bucket, Key=full_key
        )
        log.info("Deleted attachment from S3: %s", full_key)


_backend: StorageBackend | None = None


def get_storage_backend() -> StorageBackend:
    global _backend
    if _backend is not None:
        return _backend

    from app.config import settings

    if settings.storage_backend == "s3":
        _backend = S3StorageBackend(
            bucket=settings.s3_bucket_name,
            prefix=settings.s3_prefix,
            region=settings.s3_region,
            access_key=settings.s3_access_key_id,
            secret_key=settings.s3_secret_access_key,
            endpoint_url=settings.s3_endpoint_url or None,
        )
    else:
        _backend = DBStorageBackend()

    return _backend


def generate_storage_key(filename: str) -> str:
    """Generate a unique, non-guessable S3 object key for an attachment."""
    return f"{uuid.uuid4()}/{filename}"
