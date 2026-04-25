"""Tests for the admin notification service (email + webhook)."""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─── helpers ──────────────────────────────────────────────────────────────────


def _make_settings(**overrides: object) -> MagicMock:
    cfg = MagicMock()
    cfg.app_name = "OpenWhistle"
    cfg.app_public_url = "https://example.com"
    cfg.notify_email_enabled = False
    cfg.notify_email_to = ""
    cfg.notify_email_from = "openwhistle@example.com"
    cfg.notify_smtp_host = "smtp.example.com"
    cfg.notify_smtp_port = 587
    cfg.notify_smtp_user = ""
    cfg.notify_smtp_password = ""
    cfg.notify_smtp_tls = True
    cfg.notify_smtp_ssl = False
    cfg.notify_webhook_enabled = False
    cfg.notify_webhook_url = ""
    cfg.notify_webhook_secret = ""
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


# ─── notify_new_report dispatcher ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_notify_skips_when_both_disabled() -> None:
    """Neither channel should fire when both are disabled."""
    with (
        patch("app.services.notifications._send_email", new_callable=AsyncMock) as mock_mail,
        patch("app.services.notifications._send_webhook", new_callable=AsyncMock) as mock_hook,
        patch("app.services.notifications.log"),
        patch("app.config.settings", _make_settings()),
    ):
        from app.services.notifications import notify_new_report

        await notify_new_report("OW-2026-00001")

    mock_mail.assert_not_called()
    mock_hook.assert_not_called()


@pytest.mark.asyncio
async def test_notify_dispatches_email_only() -> None:
    cfg = _make_settings(notify_email_enabled=True, notify_email_to="admin@example.com")
    with (
        patch("app.services.notifications._send_email", new_callable=AsyncMock) as mock_mail,
        patch("app.services.notifications._send_webhook", new_callable=AsyncMock) as mock_hook,
        patch("app.config.settings", cfg),
    ):
        from app.services import notifications as svc
        await svc.notify_new_report("OW-2026-00001")

    mock_mail.assert_awaited_once()
    mock_hook.assert_not_called()


@pytest.mark.asyncio
async def test_notify_dispatches_webhook_only() -> None:
    cfg = _make_settings(
        notify_webhook_enabled=True,
        notify_webhook_url="https://hooks.example.com/notify",
    )
    with (
        patch("app.services.notifications._send_email", new_callable=AsyncMock) as mock_mail,
        patch("app.services.notifications._send_webhook", new_callable=AsyncMock) as mock_hook,
        patch("app.config.settings", cfg),
    ):
        from app.services import notifications as svc
        await svc.notify_new_report("OW-2026-00001")

    mock_mail.assert_not_called()
    mock_hook.assert_awaited_once()


@pytest.mark.asyncio
async def test_notify_dispatches_both_channels() -> None:
    cfg = _make_settings(
        notify_email_enabled=True,
        notify_email_to="admin@example.com",
        notify_webhook_enabled=True,
        notify_webhook_url="https://hooks.example.com/notify",
    )
    with (
        patch("app.services.notifications._send_email", new_callable=AsyncMock) as mock_mail,
        patch("app.services.notifications._send_webhook", new_callable=AsyncMock) as mock_hook,
        patch("app.config.settings", cfg),
    ):
        from app.services import notifications as svc
        await svc.notify_new_report("OW-2026-00001")

    mock_mail.assert_awaited_once()
    mock_hook.assert_awaited_once()


# ─── email channel ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_email_calls_aiosmtplib() -> None:
    cfg = _make_settings(
        notify_email_enabled=True,
        notify_email_to="a@example.com, b@example.com",
        notify_email_from="ow@example.com",
    )
    mock_send = AsyncMock(return_value=(None, "OK"))

    with patch("aiosmtplib.send", mock_send):
        from app.services.notifications import _send_email
        await _send_email("OW-2026-00001", cfg)

    mock_send.assert_awaited_once()
    call_kwargs = mock_send.call_args
    # Recipients passed to aiosmtplib.send
    assert call_kwargs.kwargs.get("recipients") == ["a@example.com", "b@example.com"]


@pytest.mark.asyncio
async def test_send_email_subject_contains_app_name() -> None:
    cfg = _make_settings(
        notify_email_to="admin@example.com",
        app_name="AcmeCorp Whistleblower",
    )
    captured_msg = {}

    async def fake_send(msg: object, *, recipients: list[str], **kw: object) -> tuple[None, str]:
        captured_msg["msg"] = msg
        return (None, "OK")

    with patch("aiosmtplib.send", fake_send):
        from app.services.notifications import _send_email
        await _send_email("OW-2026-00042", cfg)

    subject = captured_msg["msg"]["Subject"]
    assert "AcmeCorp Whistleblower" in subject


@pytest.mark.asyncio
async def test_send_email_body_contains_case_number_not_content() -> None:
    """Email must include the case number but must not expose any report content."""
    cfg = _make_settings(notify_email_to="admin@example.com")
    captured_msg = {}

    async def fake_send(msg: object, *, recipients: list[str], **kw: object) -> tuple[None, str]:
        captured_msg["msg"] = msg
        return (None, "OK")

    with patch("aiosmtplib.send", fake_send):
        from app.services.notifications import _send_email
        await _send_email("OW-2026-00099", cfg)

    # Get plain-text part
    msg = captured_msg["msg"]
    plain = next(
        part.get_payload(decode=True).decode()
        for part in msg.walk()
        if part.get_content_type() == "text/plain"
    )
    assert "OW-2026-00099" in plain
    assert "description" not in plain.lower()
    assert "category" not in plain.lower()


@pytest.mark.asyncio
async def test_send_email_swallows_smtp_exception() -> None:
    """SMTP failure must not propagate — report submission must not be blocked."""
    cfg = _make_settings(notify_email_to="admin@example.com")

    async def failing_send(*a: object, **kw: object) -> None:
        raise ConnectionRefusedError("SMTP server unavailable")

    with patch("aiosmtplib.send", failing_send):
        from app.services.notifications import _send_email
        # Should not raise
        await _send_email("OW-2026-00001", cfg)


@pytest.mark.asyncio
async def test_send_email_skips_empty_recipient_list() -> None:
    cfg = _make_settings(notify_email_to="  ,  , ")
    mock_send = AsyncMock()

    with patch("aiosmtplib.send", mock_send):
        from app.services.notifications import _send_email
        await _send_email("OW-2026-00001", cfg)

    mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_send_email_uses_ssl_when_configured() -> None:
    cfg = _make_settings(
        notify_email_to="admin@example.com",
        notify_smtp_ssl=True,
        notify_smtp_tls=False,
    )
    captured_kw: dict[str, object] = {}

    async def fake_send(msg: object, *, recipients: list[str], **kw: object) -> tuple[None, str]:
        captured_kw.update(kw)
        return (None, "OK")

    with patch("aiosmtplib.send", fake_send):
        from app.services.notifications import _send_email
        await _send_email("OW-2026-00001", cfg)

    assert captured_kw.get("use_tls") is True
    assert captured_kw.get("start_tls") is False


# ─── webhook channel ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_webhook_posts_json_payload() -> None:
    cfg = _make_settings(notify_webhook_url="https://hooks.example.com/notify")
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("httpx.AsyncClient", return_value=mock_client):
        from app.services.notifications import _send_webhook
        await _send_webhook("OW-2026-00001", cfg)

    mock_client.post.assert_awaited_once()
    call_args = mock_client.post.call_args
    url = call_args.args[0]
    body_bytes: bytes = call_args.kwargs["content"]
    payload = json.loads(body_bytes)

    assert url == "https://hooks.example.com/notify"
    assert payload["event"] == "new_report"
    assert payload["case_number"] == "OW-2026-00001"
    assert "timestamp" in payload
    # Privacy: no report description or category in payload
    assert "description" not in payload
    assert "category" not in payload


@pytest.mark.asyncio
async def test_send_webhook_includes_hmac_signature_when_secret_set() -> None:
    secret = "super-secret"
    cfg = _make_settings(
        notify_webhook_url="https://hooks.example.com/notify",
        notify_webhook_secret=secret,
    )
    captured_headers: dict[str, str] = {}
    captured_body: bytes = b""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()

    async def fake_post(url: str, *, content: bytes, headers: dict[str, str]) -> MagicMock:
        captured_headers.update(headers)
        nonlocal captured_body
        captured_body = content
        return mock_response

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(side_effect=fake_post)

    with patch("httpx.AsyncClient", return_value=mock_client):
        from app.services.notifications import _send_webhook
        await _send_webhook("OW-2026-00001", cfg)

    assert "X-OpenWhistle-Signature" in captured_headers
    sig_header = captured_headers["X-OpenWhistle-Signature"]
    assert sig_header.startswith("sha256=")
    expected_sig = hmac.new(
        secret.encode(), captured_body, hashlib.sha256
    ).hexdigest()
    assert sig_header == f"sha256={expected_sig}"


@pytest.mark.asyncio
async def test_send_webhook_no_signature_without_secret() -> None:
    cfg = _make_settings(
        notify_webhook_url="https://hooks.example.com/notify",
        notify_webhook_secret="",
    )
    captured_headers: dict[str, str] = {}
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()

    async def fake_post(url: str, *, content: bytes, headers: dict[str, str]) -> MagicMock:
        captured_headers.update(headers)
        return mock_response

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(side_effect=fake_post)

    with patch("httpx.AsyncClient", return_value=mock_client):
        from app.services.notifications import _send_webhook
        await _send_webhook("OW-2026-00001", cfg)

    assert "X-OpenWhistle-Signature" not in captured_headers


@pytest.mark.asyncio
async def test_send_webhook_swallows_http_exception() -> None:
    """HTTP failure must not propagate."""
    cfg = _make_settings(notify_webhook_url="https://hooks.example.com/notify")
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(side_effect=Exception("Connection refused"))

    with patch("httpx.AsyncClient", return_value=mock_client):
        from app.services.notifications import _send_webhook
        # Should not raise
        await _send_webhook("OW-2026-00001", cfg)


# ─── integration: submit endpoint triggers notification ───────────────────────


@pytest.mark.asyncio
@pytest.mark.integration
async def test_submit_triggers_notification(client: object) -> None:
    """POST /submit must schedule a notification background task.

    Requires a live test database — run with the full test suite (uv run pytest).
    Skipped automatically when the DB is not reachable.
    """
    import re

    from httpx import AsyncClient

    ac: AsyncClient = client  # type: ignore[assignment]

    # Get CSRF token first
    get_resp = await ac.get("/submit")
    m = re.search(r'name="csrf_token" value="([^"]+)"', get_resp.text)
    csrf = m.group(1) if m else ""

    with patch(
        "app.services.notifications.notify_new_report", new_callable=AsyncMock
    ) as mock_notify:
        resp = await ac.post(
            "/submit",
            data={
                "csrf_token": csrf,
                "category": "financial_fraud",
                "description": "Integration test — notification trigger verification.",
            },
        )

    assert resp.status_code == 200
    # BackgroundTasks run synchronously in ASGI test transport
    mock_notify.assert_awaited_once()
    called_case = mock_notify.call_args.args[0]
    assert called_case.startswith("OW-")
