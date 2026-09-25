"""Tests for v1.6.0 Task 14 (B4): webhooks carry counts only.

Webhooks (Slack, Teams, generic — third parties) must never carry a case
number or a deadline date; only aggregate counts. Email to the org's own
admins is unchanged and keeps case numbers.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.report import create_report


@pytest.mark.parametrize("kind", ["generic", "slack", "teams"])
def test_webhook_payloads_carry_no_case_number(kind: str) -> None:
    import json

    from app.services.notifications import _build_reminder_payload, _build_webhook_payload

    digest = json.dumps(_build_webhook_payload(2, 1, kind, "OW", "https://x/admin/dashboard"))
    reminder = json.dumps(
        _build_reminder_payload(1, 0, kind, "OW", "https://x/admin/dashboard", 2, 30)
    )
    for payload in (digest, reminder):
        assert "OW-" not in payload
    assert "2 new reports" in digest and "1 new message" in digest
    assert "1 case" in reminder


@pytest.mark.asyncio
async def test_digest_webhook_body_has_no_case_number(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import AsyncMock, MagicMock

    import httpx

    from app.config import settings
    from app.services.notifications import _send_webhook

    post = AsyncMock(return_value=MagicMock(status_code=200, raise_for_status=lambda: None))
    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    monkeypatch.setattr(settings, "notify_webhook_url", "https://hooks.example/x")
    await _send_webhook(["OW-2026-00001", "OW-2026-00002"], ["OW-2026-00003"], settings)
    body = post.await_args.kwargs["content"].decode()
    assert "OW-" not in body and "2" in body


@pytest.mark.asyncio
async def test_reminder_run_sends_one_webhook_with_counts(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime, timedelta
    from unittest.mock import AsyncMock

    from app.config import settings
    from app.redis_client import close_redis, get_redis
    from app.services import notifications, reminders

    for i in range(2):
        r, _ = await create_report(db_session, "corruption", f"Reminder count report {i} text.")
        r.submitted_at = datetime.now(UTC) - timedelta(days=6)
    await db_session.commit()
    monkeypatch.setattr(settings, "reminder_enabled", True)
    monkeypatch.setattr(settings, "notify_webhook_enabled", True)
    monkeypatch.setattr(settings, "notify_webhook_url", "https://hooks.example/x")
    sent = AsyncMock()
    monkeypatch.setattr(notifications, "_send_reminder_webhook", sent)
    redis = await get_redis()
    for key in await redis.keys("reminder:*"):
        await redis.delete(key)

    try:
        await reminders.send_sla_reminders()
    finally:
        await close_redis()

    assert sent.await_count == 1
    ack_due, _feedback_due, _cfg = sent.await_args.args
    assert ack_due >= 2
