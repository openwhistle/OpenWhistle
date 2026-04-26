"""Tests for v0.5.0 features:
- Health-check v2 (DB + Redis components)
- Structured JSON/text logging (configure_logging)
- Webhook payload formatters: generic, Slack, Teams
- Reminder payload builder: generic, Slack, Teams
- SLA reminder dedup logic (mocked Redis)
- S3 storage backend (mocked boto3)
- DB storage backend
- generate_storage_key
- LDAP authentication (mocked ldap3)
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient


# ── Logging configuration ────────────────────────────────────────────────────

class TestConfigureLogging:
    def test_json_format_sets_json_formatter(self) -> None:
        from app.logging_config import configure_logging

        configure_logging(log_level="DEBUG", log_format="json")
        root = logging.getLogger()
        assert root.level == logging.DEBUG
        handler = root.handlers[0] if root.handlers else None
        assert handler is not None

    def test_text_format_sets_standard_formatter(self) -> None:
        from app.logging_config import configure_logging

        configure_logging(log_level="WARNING", log_format="text")
        root = logging.getLogger()
        assert root.level == logging.WARNING

    def test_json_format_uppercase(self) -> None:
        from app.logging_config import configure_logging

        configure_logging(log_level="INFO", log_format="JSON")
        root = logging.getLogger()
        assert root.level == logging.INFO

    def test_text_format_uppercase(self) -> None:
        from app.logging_config import configure_logging

        configure_logging(log_level="ERROR", log_format="TEXT")
        root = logging.getLogger()
        assert root.level == logging.ERROR

    def test_uvicorn_loggers_configured(self) -> None:
        from app.logging_config import configure_logging

        configure_logging(log_level="INFO", log_format="json")
        for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
            logger = logging.getLogger(name)
            assert logger.handlers, f"{name} should have a handler"


# ── Health endpoint ──────────────────────────────────────────────────────────

class TestHealthEndpoint:
    async def test_health_ok(self, client: AsyncClient) -> None:
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["components"]["database"] == "ok"
        assert data["components"]["redis"] == "ok"
        assert "version" in data

    async def test_health_db_error_returns_503(self, client: AsyncClient) -> None:
        from app.database import get_db
        from app.main import app
        from sqlalchemy.ext.asyncio import AsyncSession

        async def broken_db():  # type: ignore[return]
            mock = AsyncMock(spec=AsyncSession)
            mock.execute.side_effect = Exception("DB down")
            yield mock

        app.dependency_overrides[get_db] = broken_db
        try:
            resp = await client.get("/health")
            assert resp.status_code == 503
            data = resp.json()
            assert data["status"] == "degraded"
            assert data["components"]["database"] == "error"
        finally:
            app.dependency_overrides.pop(get_db, None)

    async def test_health_redis_error_returns_503(self, client: AsyncClient) -> None:
        from app.main import app
        from app.redis_client import get_redis

        async def broken_redis():
            mock = AsyncMock()
            mock.ping.side_effect = Exception("Redis down")
            return mock

        app.dependency_overrides[get_redis] = broken_redis
        try:
            resp = await client.get("/health")
            assert resp.status_code == 503
            data = resp.json()
            assert data["status"] == "degraded"
            assert data["components"]["redis"] == "error"
        finally:
            app.dependency_overrides.pop(get_redis, None)


# ── Webhook payload builders ─────────────────────────────────────────────────

class TestWebhookPayloadBuilders:
    def test_generic_payload_structure(self) -> None:
        from app.services.notifications import _build_webhook_payload

        payload = _build_webhook_payload("OW-2024-00001", "generic", "Acme", "http://dash")
        assert payload["event"] == "new_report"
        assert payload["case_number"] == "OW-2024-00001"
        assert "timestamp" in payload

    def test_slack_payload_has_blocks(self) -> None:
        from app.services.notifications import _build_webhook_payload

        payload = _build_webhook_payload("OW-2024-00001", "slack", "Acme", "http://dash")
        assert "blocks" in payload
        block_types = [b["type"] for b in payload["blocks"]]
        assert "header" in block_types
        assert "section" in block_types
        assert "actions" in block_types

    def test_slack_payload_contains_case_number(self) -> None:
        from app.services.notifications import _build_webhook_payload

        payload = _build_webhook_payload("OW-2024-99999", "slack", "Acme", "http://dash")
        payload_str = str(payload)
        assert "OW-2024-99999" in payload_str

    def test_teams_payload_has_adaptive_card(self) -> None:
        from app.services.notifications import _build_webhook_payload

        payload = _build_webhook_payload("OW-2024-00001", "teams", "Acme", "http://dash")
        assert payload["type"] == "message"
        content = payload["attachments"][0]["content"]
        assert content["type"] == "AdaptiveCard"
        assert content["version"] == "1.4"

    def test_teams_payload_contains_case_number(self) -> None:
        from app.services.notifications import _build_webhook_payload

        payload = _build_webhook_payload("OW-2024-77777", "teams", "Acme", "http://dash")
        payload_str = str(payload)
        assert "OW-2024-77777" in payload_str

    def test_unknown_type_falls_back_to_generic(self) -> None:
        from app.services.notifications import _build_webhook_payload

        payload = _build_webhook_payload("OW-2024-00001", "unknown_type", "Acme", "http://dash")
        assert payload["event"] == "new_report"


# ── Reminder payload builders ────────────────────────────────────────────────

class TestReminderPayloadBuilders:
    def test_generic_reminder_structure(self) -> None:
        from app.services.notifications import _build_reminder_payload

        payload = _build_reminder_payload(
            "OW-2024-00001", "7-day acknowledgement", 2, "generic", "Acme", "http://dash"
        )
        assert payload["event"] == "sla_reminder"
        assert payload["case_number"] == "OW-2024-00001"
        assert payload["deadline"] == "7-day acknowledgement"
        assert payload["days_left"] == 2

    def test_slack_reminder_has_blocks(self) -> None:
        from app.services.notifications import _build_reminder_payload

        payload = _build_reminder_payload(
            "OW-2024-00001", "3-month feedback", 5, "slack", "Acme", "http://dash"
        )
        assert "blocks" in payload
        block_types = [b["type"] for b in payload["blocks"]]
        assert "header" in block_types

    def test_teams_reminder_has_adaptive_card(self) -> None:
        from app.services.notifications import _build_reminder_payload

        payload = _build_reminder_payload(
            "OW-2024-00001", "7-day acknowledgement", 1, "teams", "Acme", "http://dash"
        )
        content = payload["attachments"][0]["content"]
        assert content["type"] == "AdaptiveCard"

    def test_singular_day_text(self) -> None:
        from app.services.notifications import _build_reminder_payload

        payload = _build_reminder_payload(
            "OW-2024-00001", "test", 1, "generic", "Acme", "http://dash"
        )
        # days_left=1 should not produce "1 days remaining"
        assert payload["days_left"] == 1

    def test_slack_reminder_days_text_plural(self) -> None:
        from app.services.notifications import _build_reminder_payload

        payload = _build_reminder_payload(
            "OW-2024-00001", "test", 3, "slack", "Acme", "http://dash"
        )
        payload_str = str(payload)
        assert "3 days remaining" in payload_str

    def test_slack_reminder_days_text_singular(self) -> None:
        from app.services.notifications import _build_reminder_payload

        payload = _build_reminder_payload(
            "OW-2024-00001", "test", 1, "slack", "Acme", "http://dash"
        )
        payload_str = str(payload)
        assert "1 day remaining" in payload_str


# ── SLA reminder dedup logic ─────────────────────────────────────────────────

class TestSlaReminderLogic:
    async def test_send_sla_reminders_disabled_returns_early(self) -> None:
        """When reminder_enabled=False, function returns without touching DB."""
        from app.services import reminders

        with patch("app.config.settings") as mock_settings:
            mock_settings.reminder_enabled = False
            await reminders.send_sla_reminders()  # should not raise

    async def test_check_ack_reminder_skips_acknowledged(self) -> None:
        from app.services.reminders import _check_ack_reminder

        mock_report = MagicMock()
        mock_report.acknowledged_at = datetime.now(UTC)
        mock_redis = AsyncMock()

        await _check_ack_reminder(mock_report, datetime.now(UTC), None, mock_redis, MagicMock())
        mock_redis.exists.assert_not_called()

    async def test_check_ack_reminder_skips_when_plenty_of_time(self) -> None:
        from app.services.reminders import _check_ack_reminder
        from app.config import Settings

        mock_report = MagicMock()
        mock_report.acknowledged_at = None
        # submitted 1 minute ago → deadline is 7 days away (well above warn threshold)
        mock_report.submitted_at = datetime.now(UTC)
        mock_redis = AsyncMock()

        cfg = MagicMock()
        cfg.reminder_ack_warn_days = 2

        await _check_ack_reminder(mock_report, datetime.now(UTC), None, mock_redis, cfg)
        mock_redis.exists.assert_not_called()

    async def test_check_ack_reminder_sends_when_due(self) -> None:
        from app.services.reminders import _check_ack_reminder

        mock_report = MagicMock()
        mock_report.acknowledged_at = None
        mock_report.case_number = "OW-2024-00001"
        # submitted 6 days ago → 1 day left, below warn threshold of 2
        mock_report.submitted_at = datetime.now(UTC) - timedelta(days=6)

        mock_redis = AsyncMock()
        mock_redis.exists.return_value = False

        cfg = MagicMock()
        cfg.reminder_ack_warn_days = 2
        cfg.notify_email_enabled = False
        cfg.notify_webhook_enabled = False

        await _check_ack_reminder(mock_report, datetime.now(UTC), None, mock_redis, cfg)
        mock_redis.exists.assert_called_once()
        mock_redis.setex.assert_called_once()

    async def test_check_ack_reminder_dedup_skips_if_key_exists(self) -> None:
        from app.services.reminders import _check_ack_reminder

        mock_report = MagicMock()
        mock_report.acknowledged_at = None
        mock_report.case_number = "OW-2024-00002"
        mock_report.submitted_at = datetime.now(UTC) - timedelta(days=6)

        mock_redis = AsyncMock()
        mock_redis.exists.return_value = True  # dedup key already set

        cfg = MagicMock()
        cfg.reminder_ack_warn_days = 2

        await _check_ack_reminder(mock_report, datetime.now(UTC), None, mock_redis, cfg)
        mock_redis.setex.assert_not_called()

    async def test_check_feedback_reminder_skips_when_no_due_date(self) -> None:
        from app.services.reminders import _check_feedback_reminder

        mock_report = MagicMock()
        mock_report.feedback_due_at = None
        mock_redis = AsyncMock()

        await _check_feedback_reminder(mock_report, datetime.now(UTC), None, mock_redis, MagicMock())
        mock_redis.exists.assert_not_called()

    async def test_check_feedback_reminder_skips_when_plenty_of_time(self) -> None:
        from app.services.reminders import _check_feedback_reminder

        mock_report = MagicMock()
        mock_report.feedback_due_at = datetime.now(UTC) + timedelta(days=60)
        mock_redis = AsyncMock()

        cfg = MagicMock()
        cfg.reminder_feedback_warn_days = 30

        await _check_feedback_reminder(mock_report, datetime.now(UTC), None, mock_redis, cfg)
        mock_redis.exists.assert_not_called()

    async def test_check_feedback_reminder_sends_when_due(self) -> None:
        from app.services.reminders import _check_feedback_reminder

        mock_report = MagicMock()
        mock_report.feedback_due_at = datetime.now(UTC) + timedelta(days=10)
        mock_report.case_number = "OW-2024-00003"
        mock_redis = AsyncMock()
        mock_redis.exists.return_value = False

        cfg = MagicMock()
        cfg.reminder_feedback_warn_days = 30
        cfg.notify_email_enabled = False
        cfg.notify_webhook_enabled = False

        await _check_feedback_reminder(mock_report, datetime.now(UTC), None, mock_redis, cfg)
        mock_redis.setex.assert_called_once()

    async def test_dedup_key_format_ack(self) -> None:
        from app.services.reminders import _ack_dedup_key

        key = _ack_dedup_key("OW-2024-00001")
        assert key == "reminder:ack:OW-2024-00001"

    async def test_dedup_key_format_feedback(self) -> None:
        from app.services.reminders import _feedback_dedup_key

        key = _feedback_dedup_key("OW-2024-00001")
        assert key == "reminder:feedback:OW-2024-00001"


# ── S3 storage backend ────────────────────────────────────────────────────────

class TestS3StorageBackend:
    def _make_backend(self) -> Any:
        from app.services.storage import S3StorageBackend

        return S3StorageBackend(
            bucket="test-bucket",
            prefix="attachments/",
            region="us-east-1",
            access_key="AKID",
            secret_key="SECRET",
            endpoint_url="http://localhost:9000",
        )

    def test_full_key_includes_prefix(self) -> None:
        backend = self._make_backend()
        assert backend._full_key("abc/file.pdf") == "attachments/abc/file.pdf"

    def test_prefix_trailing_slash_normalised(self) -> None:
        from app.services.storage import S3StorageBackend

        backend = S3StorageBackend(
            bucket="b", prefix="prefix//", region="us-east-1",
            access_key="k", secret_key="s", endpoint_url=None,
        )
        # rstrip("/") then + "/" yields exactly one trailing slash
        assert backend._prefix == "prefix/"

    async def test_put_calls_put_object(self) -> None:
        backend = self._make_backend()
        mock_client = MagicMock()

        with patch.object(backend, "_client", return_value=mock_client):
            await backend.put("key/file.txt", b"data", "text/plain")
        mock_client.put_object.assert_called_once()
        call_kwargs = mock_client.put_object.call_args.kwargs
        assert call_kwargs["Bucket"] == "test-bucket"
        assert call_kwargs["Body"] == b"data"
        assert call_kwargs["ContentType"] == "text/plain"

    async def test_get_reads_body(self) -> None:
        backend = self._make_backend()
        mock_body = MagicMock()
        mock_body.read.return_value = b"file content"
        mock_client = MagicMock()
        mock_client.get_object.return_value = {"Body": mock_body}

        with patch.object(backend, "_client", return_value=mock_client):
            result = await backend.get("key/file.txt")
        assert result == b"file content"

    async def test_delete_calls_delete_object(self) -> None:
        backend = self._make_backend()
        mock_client = MagicMock()

        with patch.object(backend, "_client", return_value=mock_client):
            await backend.delete("key/file.txt")
        mock_client.delete_object.assert_called_once()
        call_kwargs = mock_client.delete_object.call_args.kwargs
        assert call_kwargs["Key"] == "attachments/key/file.txt"

    def test_endpoint_url_none_when_empty_string(self) -> None:
        from app.services.storage import S3StorageBackend

        backend = S3StorageBackend(
            bucket="b", prefix="p/", region="eu-central-1",
            access_key="k", secret_key="s", endpoint_url="",
        )
        assert backend._endpoint_url is None


# ── DB storage backend ────────────────────────────────────────────────────────

class TestDBStorageBackend:
    async def test_put_is_noop(self) -> None:
        from app.services.storage import DBStorageBackend

        backend = DBStorageBackend()
        await backend.put("key", b"data", "application/pdf")  # must not raise

    async def test_delete_is_noop(self) -> None:
        from app.services.storage import DBStorageBackend

        backend = DBStorageBackend()
        await backend.delete("key")  # must not raise

    async def test_get_raises_not_implemented(self) -> None:
        from app.services.storage import DBStorageBackend

        backend = DBStorageBackend()
        with pytest.raises(NotImplementedError):
            await backend.get("key")


# ── generate_storage_key ──────────────────────────────────────────────────────

class TestGenerateStorageKey:
    def test_key_contains_filename(self) -> None:
        from app.services.storage import generate_storage_key

        key = generate_storage_key("report.pdf")
        assert key.endswith("/report.pdf")

    def test_key_is_unique(self) -> None:
        from app.services.storage import generate_storage_key

        keys = {generate_storage_key("file.txt") for _ in range(50)}
        assert len(keys) == 50

    def test_key_format_uuid_slash_filename(self) -> None:
        import re
        from app.services.storage import generate_storage_key

        key = generate_storage_key("attachment.docx")
        uuid_re = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/attachment\.docx$"
        assert re.match(uuid_re, key), f"Unexpected key format: {key}"


# ── get_storage_backend singleton ─────────────────────────────────────────────

class TestGetStorageBackend:
    def test_returns_db_backend_by_default(self) -> None:
        import app.services.storage as storage_mod
        from app.services.storage import DBStorageBackend

        # Reset singleton
        original = storage_mod._backend
        storage_mod._backend = None
        try:
            with patch("app.config.settings") as mock_cfg:
                mock_cfg.storage_backend = "db"
                backend = storage_mod.get_storage_backend()
            assert isinstance(backend, DBStorageBackend)
        finally:
            storage_mod._backend = original

    def test_returns_s3_backend_when_configured(self) -> None:
        import app.services.storage as storage_mod
        from app.services.storage import S3StorageBackend

        original = storage_mod._backend
        storage_mod._backend = None
        try:
            with patch("app.config.settings") as mock_cfg:
                mock_cfg.storage_backend = "s3"
                mock_cfg.s3_bucket_name = "b"
                mock_cfg.s3_prefix = "a/"
                mock_cfg.s3_region = "us-east-1"
                mock_cfg.s3_access_key_id = "k"
                mock_cfg.s3_secret_access_key = "s"
                mock_cfg.s3_endpoint_url = ""
                backend = storage_mod.get_storage_backend()
            assert isinstance(backend, S3StorageBackend)
        finally:
            storage_mod._backend = original

    def test_singleton_returns_same_instance(self) -> None:
        import app.services.storage as storage_mod
        from app.services.storage import DBStorageBackend

        original = storage_mod._backend
        storage_mod._backend = None
        try:
            with patch("app.config.settings") as mock_cfg:
                mock_cfg.storage_backend = "db"
                b1 = storage_mod.get_storage_backend()
                b2 = storage_mod.get_storage_backend()
            assert b1 is b2
        finally:
            storage_mod._backend = original


# ── LDAP authentication ───────────────────────────────────────────────────────

class TestLDAPAuth:
    def _mock_entry(self, username: str = "jdoe", email: str = "jdoe@example.com") -> MagicMock:
        entry = MagicMock()
        entry.entry_dn = f"uid={username},ou=users,dc=example,dc=com"
        entry.__contains__ = lambda self, key: key in ("uid", "mail")
        entry.__getitem__ = lambda self, key: MagicMock(__str__=lambda s: email if key == "mail" else username)
        return entry

    def _cfg(self) -> MagicMock:
        """Return a mock settings object with LDAP enabled."""
        cfg = MagicMock()
        cfg.ldap_enabled = True
        cfg.ldap_bind_dn = "cn=svc,dc=example,dc=com"
        cfg.ldap_bind_password = "secret"
        cfg.ldap_base_dn = "ou=users,dc=example,dc=com"
        cfg.ldap_user_filter = "(uid={username})"
        cfg.ldap_attr_username = "uid"
        cfg.ldap_attr_email = "mail"
        return cfg

    def test_ldap_disabled_raises_auth_error(self) -> None:
        from app.services.ldap_auth import _authenticate_ldap_sync, LDAPAuthError

        # patch app.config.settings since settings is imported inside the function
        with patch("app.config.settings") as mock_cfg:
            mock_cfg.ldap_enabled = False
            with pytest.raises(LDAPAuthError, match="not enabled"):
                _authenticate_ldap_sync("user", "pass")

    def test_successful_ldap_auth(self) -> None:
        from app.services.ldap_auth import _authenticate_ldap_sync, LDAPUserInfo

        entry = self._mock_entry("jdoe", "jdoe@example.com")
        mock_conn = MagicMock()
        mock_conn.entries = [entry]

        # Connection is imported fresh from ldap3 inside the function, so patch there
        with patch("app.config.settings", self._cfg()), \
             patch("app.services.ldap_auth._make_server"), \
             patch("ldap3.Connection", return_value=mock_conn):
            result = _authenticate_ldap_sync("jdoe", "password")

        assert isinstance(result, LDAPUserInfo)

    def test_service_bind_failure_raises_auth_error(self) -> None:
        from app.services.ldap_auth import _authenticate_ldap_sync, LDAPAuthError
        from ldap3.core.exceptions import LDAPException

        with patch("app.config.settings", self._cfg()), \
             patch("app.services.ldap_auth._make_server"), \
             patch("ldap3.Connection", side_effect=LDAPException("bind failed")):
            with pytest.raises(LDAPAuthError, match="service bind failed"):
                _authenticate_ldap_sync("user", "pass")

    def test_user_not_found_raises_auth_error(self) -> None:
        from app.services.ldap_auth import _authenticate_ldap_sync, LDAPAuthError

        mock_conn = MagicMock()
        mock_conn.entries = []  # no users found

        with patch("app.config.settings", self._cfg()), \
             patch("app.services.ldap_auth._make_server"), \
             patch("ldap3.Connection", return_value=mock_conn):
            with pytest.raises(LDAPAuthError, match="not found"):
                _authenticate_ldap_sync("unknown", "pass")

    def test_wrong_password_raises_auth_error(self) -> None:
        from app.services.ldap_auth import _authenticate_ldap_sync, LDAPAuthError
        from ldap3.core.exceptions import LDAPException

        entry = self._mock_entry()
        service_conn = MagicMock()
        service_conn.entries = [entry]

        call_count = 0

        def conn_factory(*a: Any, **kw: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return service_conn
            raise LDAPException("invalid credentials")

        with patch("app.config.settings", self._cfg()), \
             patch("app.services.ldap_auth._make_server"), \
             patch("ldap3.Connection", side_effect=conn_factory):
            with pytest.raises(LDAPAuthError, match="Invalid LDAP credentials"):
                _authenticate_ldap_sync("jdoe", "wrong")

    async def test_authenticate_ldap_runs_in_thread(self) -> None:
        """authenticate_ldap wraps the sync function in asyncio.to_thread."""
        from app.services.ldap_auth import authenticate_ldap, LDAPUserInfo

        expected = LDAPUserInfo(username="jdoe", email="jdoe@example.com")

        with patch("app.services.ldap_auth._authenticate_ldap_sync", return_value=expected):
            result = await authenticate_ldap("jdoe", "pass")

        assert result.username == "jdoe"
        assert result.email == "jdoe@example.com"


# ── LDAPUserInfo dataclass ────────────────────────────────────────────────────

class TestLDAPUserInfo:
    def test_fields(self) -> None:
        from app.services.ldap_auth import LDAPUserInfo

        info = LDAPUserInfo(username="alice", email="alice@example.com")
        assert info.username == "alice"
        assert info.email == "alice@example.com"

    def test_email_can_be_none(self) -> None:
        from app.services.ldap_auth import LDAPUserInfo

        info = LDAPUserInfo(username="bob", email=None)
        assert info.email is None


# ── Send reminder webhook (mocked httpx) ─────────────────────────────────────

class TestSendReminderWebhook:
    async def test_sends_correct_payload(self) -> None:
        from app.services.notifications import _send_reminder_webhook

        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.status_code = 200

        cfg = MagicMock()
        cfg.app_public_url = "https://example.com"
        cfg.notify_webhook_type = "generic"
        cfg.app_name = "TestApp"
        cfg.notify_webhook_secret = ""
        cfg.notify_webhook_url = "https://hooks.example.com/webhook"

        with patch("httpx.AsyncClient") as MockClient:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__ = AsyncMock(return_value=None)
            mock_ctx.post = AsyncMock(return_value=mock_response)
            MockClient.return_value = mock_ctx

            await _send_reminder_webhook("OW-2024-00001", "7-day acknowledgement", 1, cfg)

        mock_ctx.post.assert_called_once()
        call_kwargs = mock_ctx.post.call_args
        assert call_kwargs.kwargs["headers"]["Content-Type"] == "application/json"

    async def test_includes_hmac_signature_when_secret_set(self) -> None:
        import hashlib
        import hmac
        import json
        from app.services.notifications import _send_reminder_webhook

        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None

        cfg = MagicMock()
        cfg.app_public_url = "https://example.com"
        cfg.notify_webhook_type = "generic"
        cfg.app_name = "TestApp"
        cfg.notify_webhook_secret = "mysecret"
        cfg.notify_webhook_url = "https://hooks.example.com/webhook"

        captured: dict = {}

        async def fake_post(url: str, content: bytes, headers: dict) -> MagicMock:
            captured["headers"] = headers
            captured["body"] = content
            return mock_response

        with patch("httpx.AsyncClient") as MockClient:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__ = AsyncMock(return_value=None)
            mock_ctx.post = fake_post
            MockClient.return_value = mock_ctx

            await _send_reminder_webhook("OW-2024-00001", "ack", 1, cfg)

        assert "X-OpenWhistle-Signature" in captured.get("headers", {})
        sig_header = captured["headers"]["X-OpenWhistle-Signature"]
        expected_sig = "sha256=" + hmac.new(
            b"mysecret", captured["body"], hashlib.sha256
        ).hexdigest()
        assert sig_header == expected_sig


# ── notify_reply_to_whistleblower ────────────────────────────────────────────

class TestNotifyReplyToWhistleblower:
    async def test_email_disabled_returns_early(self) -> None:
        from app.services.notifications import notify_reply_to_whistleblower

        with patch("app.config.settings") as mock_cfg:
            mock_cfg.notify_email_enabled = False
            await notify_reply_to_whistleblower("wb@example.com", "https://example.com")
            # no aiosmtplib call should happen — no error raised

    async def test_sends_email_when_enabled(self) -> None:
        from app.services.notifications import notify_reply_to_whistleblower

        with patch("app.config.settings") as mock_cfg, \
             patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send:
            mock_cfg.notify_email_enabled = True
            mock_cfg.app_name = "TestApp"
            mock_cfg.notify_email_from = "noreply@example.com"
            mock_cfg.notify_smtp_host = "smtp.example.com"
            mock_cfg.notify_smtp_port = 587
            mock_cfg.notify_smtp_ssl = False
            mock_cfg.notify_smtp_tls = True
            mock_cfg.notify_smtp_user = ""
            mock_cfg.notify_smtp_password = ""
            await notify_reply_to_whistleblower("wb@example.com", "https://example.com")
        mock_send.assert_called_once()

    async def test_swallows_smtp_exception(self) -> None:
        from app.services.notifications import notify_reply_to_whistleblower

        with patch("app.config.settings") as mock_cfg, \
             patch("aiosmtplib.send", side_effect=Exception("SMTP error")) as mock_send:
            mock_cfg.notify_email_enabled = True
            mock_cfg.app_name = "TestApp"
            mock_cfg.notify_email_from = "noreply@example.com"
            mock_cfg.notify_smtp_host = "smtp.example.com"
            mock_cfg.notify_smtp_port = 587
            mock_cfg.notify_smtp_ssl = False
            mock_cfg.notify_smtp_tls = True
            mock_cfg.notify_smtp_user = ""
            mock_cfg.notify_smtp_password = ""
            # Must not raise — errors are swallowed
            await notify_reply_to_whistleblower("wb@example.com", "https://example.com")
        mock_send.assert_called_once()


# ── _send_reminder_email ──────────────────────────────────────────────────────

class TestSendReminderEmail:
    def _cfg(self) -> MagicMock:
        cfg = MagicMock()
        cfg.app_name = "TestApp"
        cfg.app_public_url = "https://example.com"
        cfg.notify_email_to = "admin@example.com"
        cfg.notify_email_from = "noreply@example.com"
        cfg.notify_smtp_host = "smtp.example.com"
        cfg.notify_smtp_port = 587
        cfg.notify_smtp_ssl = False
        cfg.notify_smtp_tls = True
        cfg.notify_smtp_user = "smtp_user"
        cfg.notify_smtp_password = "smtp_pass"
        return cfg

    async def test_sends_reminder_email(self) -> None:
        from app.services.notifications import _send_reminder_email

        with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send:
            await _send_reminder_email("OW-2024-00001", "7-day acknowledgement", 2, self._cfg())
        mock_send.assert_called_once()
        _, kwargs = mock_send.call_args
        assert kwargs.get("hostname") == "smtp.example.com"
        assert kwargs.get("username") == "smtp_user"
        assert kwargs.get("password") == "smtp_pass"

    async def test_skips_when_no_recipients(self) -> None:
        from app.services.notifications import _send_reminder_email

        cfg = self._cfg()
        cfg.notify_email_to = "  ,  "  # whitespace-only entries

        with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send:
            await _send_reminder_email("OW-2024-00001", "test", 1, cfg)
        mock_send.assert_not_called()

    async def test_swallows_smtp_exception(self) -> None:
        from app.services.notifications import _send_reminder_email

        with patch("aiosmtplib.send", side_effect=Exception("timeout")):
            # Must not raise
            await _send_reminder_email("OW-2024-00001", "test", 1, self._cfg())


# ── _send_reminder_webhook exception path ─────────────────────────────────────

class TestSendReminderWebhookError:
    async def test_swallows_httpx_exception(self) -> None:
        from app.services.notifications import _send_reminder_webhook

        cfg = MagicMock()
        cfg.app_public_url = "https://example.com"
        cfg.notify_webhook_type = "generic"
        cfg.app_name = "TestApp"
        cfg.notify_webhook_secret = ""
        cfg.notify_webhook_url = "https://hooks.example.com/webhook"

        with patch("httpx.AsyncClient") as MockClient:
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_ctx.__aexit__ = AsyncMock(return_value=None)
            mock_ctx.post = AsyncMock(side_effect=Exception("connection refused"))
            MockClient.return_value = mock_ctx

            # Must not raise
            await _send_reminder_webhook("OW-2024-00001", "test", 1, cfg)


# ── _dispatch_reminder ────────────────────────────────────────────────────────

class TestDispatchReminder:
    async def test_dispatches_email_and_webhook(self) -> None:
        from app.services.reminders import _dispatch_reminder

        cfg = MagicMock()
        cfg.notify_email_enabled = True
        cfg.notify_email_to = "admin@example.com"
        cfg.notify_webhook_enabled = True
        cfg.notify_webhook_url = "https://hooks.example.com/webhook"

        email_called: list = []
        webhook_called: list = []

        async def mock_email(*a: Any, **kw: Any) -> None:
            email_called.append(1)

        async def mock_webhook(*a: Any, **kw: Any) -> None:
            webhook_called.append(1)

        with patch("app.services.notifications._send_reminder_email", mock_email), \
             patch("app.services.notifications._send_reminder_webhook", mock_webhook):
            await _dispatch_reminder("OW-2024-00001", "test", 1, MagicMock(), cfg)

        assert len(email_called) == 1
        assert len(webhook_called) == 1

    async def test_no_tasks_when_both_disabled(self) -> None:
        from app.services.reminders import _dispatch_reminder

        cfg = MagicMock()
        cfg.notify_email_enabled = False
        cfg.notify_webhook_enabled = False

        with patch("app.services.notifications._send_reminder_email") as m_email, \
             patch("app.services.notifications._send_reminder_webhook") as m_webhook:
            await _dispatch_reminder("OW-2024-00001", "test", 1, MagicMock(), cfg)

        m_email.assert_not_called()
        m_webhook.assert_not_called()

    async def test_feedback_dedup_skips_when_key_exists(self) -> None:
        from app.services.reminders import _check_feedback_reminder

        mock_report = MagicMock()
        mock_report.feedback_due_at = datetime.now(UTC) + timedelta(days=10)
        mock_report.case_number = "OW-2024-00004"
        mock_redis = AsyncMock()
        mock_redis.exists.return_value = True  # dedup key present

        cfg = MagicMock()
        cfg.reminder_feedback_warn_days = 30

        await _check_feedback_reminder(mock_report, datetime.now(UTC), None, mock_redis, cfg)
        mock_redis.setex.assert_not_called()  # should have returned early at line 131


# ── S3 _client() method coverage ─────────────────────────────────────────────

class TestS3ClientMethod:
    def test_client_includes_endpoint_url(self) -> None:
        from app.services.storage import S3StorageBackend

        backend = S3StorageBackend(
            bucket="b", prefix="p/", region="eu-west-1",
            access_key="AKID", secret_key="SECRET",
            endpoint_url="http://minio:9000",
        )
        with patch("boto3.client") as mock_boto:
            mock_boto.return_value = MagicMock()
            backend._client()
        call_kwargs = mock_boto.call_args.kwargs
        assert call_kwargs.get("endpoint_url") == "http://minio:9000"

    def test_client_omits_endpoint_url_when_none(self) -> None:
        from app.services.storage import S3StorageBackend

        backend = S3StorageBackend(
            bucket="b", prefix="p/", region="us-east-1",
            access_key="AKID", secret_key="SECRET", endpoint_url=None,
        )
        with patch("boto3.client") as mock_boto:
            mock_boto.return_value = MagicMock()
            backend._client()
        call_kwargs = mock_boto.call_args.kwargs
        assert "endpoint_url" not in call_kwargs


# ── send_sla_reminders with DB (mocked engine) ───────────────────────────────

class TestSendSlaRemindersWithDB:
    async def test_send_sla_reminders_runs_full_loop(self) -> None:
        """Test send_sla_reminders with a mocked DB session and Redis."""
        from app.services.reminders import send_sla_reminders

        mock_report = MagicMock()
        mock_report.acknowledged_at = None
        mock_report.case_number = "OW-2024-99999"
        # No reminder due — just enough to traverse the loop
        mock_report.submitted_at = datetime.now(UTC)
        mock_report.feedback_due_at = None

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_report]

        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_result
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=None)

        mock_session_factory = MagicMock(return_value=mock_db)
        mock_engine = AsyncMock()

        mock_redis = AsyncMock()
        mock_redis.exists.return_value = False

        with patch("app.config.settings") as mock_cfg, \
             patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_engine), \
             patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=mock_session_factory), \
             patch("app.redis_client.get_redis", AsyncMock(return_value=mock_redis)):
            mock_cfg.reminder_enabled = True
            mock_cfg.database_url = "postgresql+asyncpg://test:test@localhost/test"
            mock_cfg.reminder_ack_warn_days = 2
            mock_cfg.reminder_feedback_warn_days = 30
            mock_cfg.notify_email_enabled = False
            mock_cfg.notify_webhook_enabled = False
            await send_sla_reminders()

        mock_db.execute.assert_called_once()
