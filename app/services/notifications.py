"""Admin notification service — email and webhook channels.

Notifications are fire-and-forget: failures are logged but never propagated
to callers, so a misconfigured SMTP server cannot block report submission.

Privacy: notifications contain only counts and case numbers. Report content
(description, category) is never transmitted, and new-report notices are
batched so their timing does not reveal when a report was submitted.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime
from email.mime.text import MIMEText
from typing import Any

log = logging.getLogger(__name__)


async def notify_reply_to_whistleblower(secure_email: str, app_public_url: str) -> None:
    """Send a brief notification to the whistleblower's secure email.

    Content intentionally minimal — no report data, no case number in body.
    The secure_email is never written to logs.
    """
    import aiosmtplib  # noqa: PLC0415

    from app.config import settings  # noqa: PLC0415

    if not settings.notify_email_enabled:
        return

    status_url = f"{app_public_url.rstrip('/')}/status"
    subject = f"New reply on your report — {settings.app_name}"
    text_body = (
        f"You have a new reply on your report submitted to {settings.app_name}.\n\n"
        f"Log in at {status_url} using your case number and PIN to read it.\n\n"
        "This notification does not contain any report content to protect your privacy."
    )

    msg_obj = MIMEText(text_body, "plain", "utf-8")
    msg_obj["Subject"] = subject
    msg_obj["From"] = settings.notify_email_from
    msg_obj["To"] = secure_email

    smtp_kwargs: dict[str, Any] = {
        "hostname": settings.notify_smtp_host,
        "port": settings.notify_smtp_port,
        "use_tls": settings.notify_smtp_ssl,
        "start_tls": settings.notify_smtp_tls and not settings.notify_smtp_ssl,
    }
    if settings.notify_smtp_user:
        smtp_kwargs["username"] = settings.notify_smtp_user
    if settings.notify_smtp_password:
        smtp_kwargs["password"] = settings.notify_smtp_password

    try:
        await aiosmtplib.send(msg_obj, recipients=[secure_email], **smtp_kwargs)
        log.info("Whistleblower reply notification sent (recipient redacted)")
    except Exception:
        log.exception("Failed to send whistleblower reply notification (recipient redacted)")


async def _send_reminder_email(
    case_number: str, deadline_label: str, days_left: int, settings: object
) -> None:
    """Send an SLA reminder email to all configured admin recipients."""
    import aiosmtplib

    from app.config import Settings

    cfg: Settings = settings  # type: ignore[assignment]

    recipients = [r.strip() for r in cfg.notify_email_to.split(",") if r.strip()]
    if not recipients:
        return

    dashboard_url = f"{cfg.app_public_url.rstrip('/')}/admin/dashboard"
    subject = f"⚠ SLA reminder: {deadline_label} — {cfg.app_name}"
    text_body = (
        f"SLA reminder for {cfg.app_name}.\n\n"
        f"Case number : {case_number}\n"
        f"Deadline    : {deadline_label}\n"
        f"Days left   : {days_left}\n\n"
        f"Review the case: {dashboard_url}\n"
    )

    msg = MIMEText(text_body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = cfg.notify_email_from
    msg["To"] = ", ".join(recipients)

    smtp_kwargs: dict[str, Any] = {
        "hostname": cfg.notify_smtp_host,
        "port": cfg.notify_smtp_port,
        "use_tls": cfg.notify_smtp_ssl,
        "start_tls": cfg.notify_smtp_tls and not cfg.notify_smtp_ssl,
    }
    if cfg.notify_smtp_user:
        smtp_kwargs["username"] = cfg.notify_smtp_user
    if cfg.notify_smtp_password:
        smtp_kwargs["password"] = cfg.notify_smtp_password

    try:
        await aiosmtplib.send(msg, recipients=recipients, **smtp_kwargs)
        log.info("SLA reminder email sent for %s (%s)", case_number, deadline_label)
    except Exception:
        log.exception("Failed to send SLA reminder email for %s", case_number)


async def _send_reminder_webhook(
    case_number: str, deadline_label: str, days_left: int, settings: object
) -> None:
    """POST an SLA reminder to the configured webhook URL."""
    import httpx

    from app.config import Settings

    cfg: Settings = settings  # type: ignore[assignment]

    dashboard_url = f"{cfg.app_public_url.rstrip('/')}/admin/dashboard"
    payload = _build_reminder_payload(
        case_number,
        deadline_label,
        days_left,
        cfg.notify_webhook_type,
        cfg.app_name,
        dashboard_url,
    )
    body_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if cfg.notify_webhook_secret:
        sig = hmac.new(
            cfg.notify_webhook_secret.encode(),
            body_bytes,
            hashlib.sha256,
        ).hexdigest()
        headers["X-OpenWhistle-Signature"] = f"sha256={sig}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(cfg.notify_webhook_url, content=body_bytes, headers=headers)
            resp.raise_for_status()
        log.info("SLA reminder webhook sent for %s (%s)", case_number, deadline_label)
    except Exception:
        log.exception("Failed to send SLA reminder webhook for %s", case_number)


def _build_reminder_payload(
    case_number: str,
    deadline_label: str,
    days_left: int,
    webhook_type: str,
    app_name: str,
    dashboard_url: str,
) -> dict[str, Any]:
    ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    days_text = f"{days_left} day{'s' if days_left != 1 else ''} remaining"

    if webhook_type == "slack":
        return {
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": f"⚠ SLA reminder — {app_name}"},
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Case number:*\n`{case_number}`"},
                        {"type": "mrkdwn", "text": f"*Deadline:*\n{deadline_label}"},
                        {"type": "mrkdwn", "text": f"*Time left:*\n{days_text}"},
                        {"type": "mrkdwn", "text": f"*Checked at:*\n{ts}"},
                    ],
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Open dashboard →"},
                            "url": dashboard_url,
                            "style": "danger",
                        }
                    ],
                },
            ]
        }

    if webhook_type == "teams":
        return {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": {
                        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                        "type": "AdaptiveCard",
                        "version": "1.4",
                        "body": [
                            {
                                "type": "TextBlock",
                                "size": "Medium",
                                "weight": "Bolder",
                                "text": f"SLA reminder — {app_name}",
                                "color": "Warning",
                            },
                            {
                                "type": "FactSet",
                                "facts": [
                                    {"title": "Case number", "value": case_number},
                                    {"title": "Deadline", "value": deadline_label},
                                    {"title": "Time left", "value": days_text},
                                ],
                            },
                        ],
                        "actions": [
                            {
                                "type": "Action.OpenUrl",
                                "title": "Open dashboard",
                                "url": dashboard_url,
                            }
                        ],
                    },
                }
            ],
        }

    return {
        "event": "sla_reminder",
        "case_number": case_number,
        "deadline": deadline_label,
        "days_left": days_left,
        "timestamp": datetime.now(UTC).isoformat(),
    }


# ── New reports and whistleblower messages: batched digest ─────────────────
#
# A notification sent the moment a report arrives carries its submission time,
# and an employer can match that time to who was at their desk. Events are
# therefore queued in Redis and delivered as one digest every
# NOTIFICATION_BATCH_MINUTES, on wall-clock boundaries shared by all replicas.
# NOTIFICATION_BATCH_MINUTES=0 sends each event at once (operator's choice).

_QUEUE_KEYS = {
    "new_reports": "openwhistle:notify:new_reports",
    "new_messages": "openwhistle:notify:new_messages",
}
_background: set[asyncio.Task[None]] = set()


def _channels_enabled(cfg: Any) -> bool:
    email = cfg.notify_email_enabled and cfg.notify_email_to.strip()
    webhook = cfg.notify_webhook_enabled and cfg.notify_webhook_url.strip()
    return bool(email or webhook)


def batching_enabled() -> bool:
    from app.config import settings

    return settings.notification_batch_minutes > 0 and _channels_enabled(settings)


async def notify_new_report(case_number: str) -> None:
    """Queue (or, unbatched, send) the notice that a report arrived."""
    await _queue_or_send("new_reports", case_number)


async def notify_whistleblower_message(case_number: str) -> None:
    """Queue (or, unbatched, send) the notice that a whistleblower replied."""
    await _queue_or_send("new_messages", case_number)


async def _queue_or_send(kind: str, case_number: str) -> None:
    from app.config import settings

    if not _channels_enabled(settings):
        return
    if settings.notification_batch_minutes <= 0:
        # Never delay the whistleblower's response on SMTP or a webhook.
        task = asyncio.create_task(_deliver(**{kind: [case_number]}))
        _background.add(task)
        task.add_done_callback(_background.discard)
        return
    try:
        from app.redis_client import get_redis

        await (await get_redis()).sadd(_QUEUE_KEYS[kind], case_number)
    except Exception:
        log.exception("Failed to queue a notification")


async def deliver_notification_digest() -> None:
    """Scheduler job: send everything queued since the last run as one digest.

    The queue is read and cleared in one MULTI/EXEC, so when every replica
    runs this job at the same moment exactly one of them gets the events.
    """
    from redis.asyncio import Redis

    from app.config import settings

    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        async with redis.pipeline(transaction=True) as pipe:
            pipe.smembers(_QUEUE_KEYS["new_reports"])
            pipe.smembers(_QUEUE_KEYS["new_messages"])
            pipe.delete(*_QUEUE_KEYS.values())
            new_reports, new_messages, _ = await pipe.execute()
    except Exception:
        log.exception("Failed to read the notification queue")
        return
    finally:
        await redis.aclose()
    if new_reports or new_messages:
        await _deliver(sorted(new_reports), sorted(new_messages))


async def _deliver(
    new_reports: list[str] | None = None, new_messages: list[str] | None = None
) -> None:
    from app.config import settings

    reports, messages = new_reports or [], new_messages or []
    tasks = []
    if settings.notify_email_enabled and settings.notify_email_to.strip():
        tasks.append(_send_email(reports, messages, settings))
    if settings.notify_webhook_enabled and settings.notify_webhook_url.strip():
        tasks.append(_send_webhook(reports, messages, settings))
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


def _summary(cases: list[str]) -> str:
    return f"{len(cases)} ({', '.join(cases)})" if cases else "0"


async def _send_email(new_reports: list[str], new_messages: list[str], settings: object) -> None:
    """Send the digest by SMTP: counts and case numbers, nothing else."""
    import aiosmtplib

    from app.config import Settings

    cfg: Settings = settings  # type: ignore[assignment]

    recipients = [r.strip() for r in cfg.notify_email_to.split(",") if r.strip()]
    if not recipients:
        return

    dashboard_url = f"{cfg.app_public_url.rstrip('/')}/admin/dashboard"
    text_body = (
        f"New activity on {cfg.app_name}.\n\n"
        f"New reports                  : {_summary(new_reports)}\n"
        f"New whistleblower messages on: {_summary(new_messages)}\n\n"
        f"Review them in the admin dashboard:\n{dashboard_url}\n\n"
        "-- \n"
        "No report content is included in this notification, and notifications\n"
        "are batched, so their timing does not reveal when a report was sent."
    )
    msg = MIMEText(text_body, "plain", "utf-8")
    msg["Subject"] = f"New activity — {cfg.app_name}"
    msg["From"] = cfg.notify_email_from
    msg["To"] = ", ".join(recipients)

    smtp_kwargs: dict[str, Any] = {
        "hostname": cfg.notify_smtp_host,
        "port": cfg.notify_smtp_port,
        "use_tls": cfg.notify_smtp_ssl,
        "start_tls": cfg.notify_smtp_tls and not cfg.notify_smtp_ssl,
    }
    if cfg.notify_smtp_user:
        smtp_kwargs["username"] = cfg.notify_smtp_user
    if cfg.notify_smtp_password:
        smtp_kwargs["password"] = cfg.notify_smtp_password

    try:
        await aiosmtplib.send(msg, recipients=recipients, **smtp_kwargs)
        log.info("Notification email sent to %d recipient(s)", len(recipients))
    except Exception:
        log.exception("Failed to send notification email")


def _build_webhook_payload(
    new_reports: list[str],
    new_messages: list[str],
    webhook_type: str,
    app_name: str,
    dashboard_url: str,
) -> dict[str, Any]:
    """Build webhook payload in the format expected by the target service."""
    reports, messages = _summary(new_reports), _summary(new_messages)

    if webhook_type == "slack":
        return {
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": f"🔔 New activity — {app_name}"},
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*New reports:*\n{reports}"},
                        {"type": "mrkdwn", "text": f"*New messages on:*\n{messages}"},
                    ],
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Open dashboard →"},
                            "url": dashboard_url,
                            "style": "primary",
                        }
                    ],
                },
            ]
        }

    if webhook_type == "teams":
        return {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": {
                        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                        "type": "AdaptiveCard",
                        "version": "1.4",
                        "body": [
                            {
                                "type": "TextBlock",
                                "size": "Medium",
                                "weight": "Bolder",
                                "text": f"New activity — {app_name}",
                            },
                            {
                                "type": "FactSet",
                                "facts": [
                                    {"title": "New reports", "value": reports},
                                    {"title": "New messages on", "value": messages},
                                ],
                            },
                        ],
                        "actions": [
                            {
                                "type": "Action.OpenUrl",
                                "title": "Open dashboard",
                                "url": dashboard_url,
                            }
                        ],
                    },
                }
            ],
        }

    # generic (default)
    return {
        "event": "new_activity",
        "new_reports": new_reports,
        "new_messages": new_messages,
    }


async def _send_webhook(new_reports: list[str], new_messages: list[str], settings: object) -> None:
    """POST the digest as JSON to the configured webhook URL."""
    import httpx

    from app.config import Settings

    cfg: Settings = settings  # type: ignore[assignment]

    dashboard_url = f"{cfg.app_public_url.rstrip('/')}/admin/dashboard"
    payload = _build_webhook_payload(
        new_reports, new_messages, cfg.notify_webhook_type, cfg.app_name, dashboard_url
    )
    body_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if cfg.notify_webhook_secret:
        sig = hmac.new(
            cfg.notify_webhook_secret.encode(),
            body_bytes,
            hashlib.sha256,
        ).hexdigest()
        headers["X-OpenWhistle-Signature"] = f"sha256={sig}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(cfg.notify_webhook_url, content=body_bytes, headers=headers)
            resp.raise_for_status()
        log.info(
            "Webhook notification sent (type=%s, HTTP %s)",
            cfg.notify_webhook_type,
            resp.status_code,
        )
    except Exception:
        log.exception("Failed to send webhook notification")


def _build_security_alert_payload(subject: str, text: str, webhook_type: str) -> dict[str, Any]:
    if webhook_type == "slack":
        return {"text": f"*{subject}*\n{text}"}
    if webhook_type == "teams":
        return {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": {
                        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                        "type": "AdaptiveCard",
                        "version": "1.4",
                        "body": [
                            {
                                "type": "TextBlock",
                                "weight": "Bolder",
                                "color": "Attention",
                                "text": subject,
                            },
                            {"type": "TextBlock", "wrap": True, "text": text},
                        ],
                    },
                }
            ],
        }
    return {"event": "security_alert", "subject": subject, "message": text}


async def notify_security_alert(subject: str, text: str) -> None:
    """Send a security alert to the admin email recipients and the webhook, now.

    Same channels and fire-and-forget contract as the digest, but never queued:
    an attack in progress must not wait for NOTIFICATION_BATCH_MINUTES, and the
    alert carries no whistleblower activity whose timing could identify anyone.
    """
    import aiosmtplib
    import httpx

    from app.config import settings as cfg

    if not _channels_enabled(cfg):
        return

    if cfg.notify_email_enabled and cfg.notify_email_to.strip():
        recipients = [r.strip() for r in cfg.notify_email_to.split(",") if r.strip()]
        msg = MIMEText(text, "plain", "utf-8")
        msg["Subject"] = f"{subject} — {cfg.app_name}"
        msg["From"] = cfg.notify_email_from
        msg["To"] = ", ".join(recipients)
        smtp_kwargs: dict[str, Any] = {
            "hostname": cfg.notify_smtp_host,
            "port": cfg.notify_smtp_port,
            "use_tls": cfg.notify_smtp_ssl,
            "start_tls": cfg.notify_smtp_tls and not cfg.notify_smtp_ssl,
        }
        if cfg.notify_smtp_user:
            smtp_kwargs["username"] = cfg.notify_smtp_user
        if cfg.notify_smtp_password:
            smtp_kwargs["password"] = cfg.notify_smtp_password
        try:
            await aiosmtplib.send(msg, recipients=recipients, **smtp_kwargs)
            log.info("Security alert email sent: %s", subject)
        except Exception:
            log.exception("Failed to send security alert email")

    if cfg.notify_webhook_enabled and cfg.notify_webhook_url.strip():
        payload = _build_security_alert_payload(subject, text, cfg.notify_webhook_type)
        body_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if cfg.notify_webhook_secret:
            sig = hmac.new(cfg.notify_webhook_secret.encode(), body_bytes, hashlib.sha256)
            headers["X-OpenWhistle-Signature"] = f"sha256={sig.hexdigest()}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    cfg.notify_webhook_url, content=body_bytes, headers=headers
                )
                resp.raise_for_status()
            log.info("Security alert webhook sent: %s", subject)
        except Exception:
            log.exception("Failed to send security alert webhook")
