"""Admin notification service — email and webhook channels.

Notifications are fire-and-forget: failures are logged but never propagated
to callers, so a misconfigured SMTP server cannot block report submission.

Privacy: notifications contain only the case number and a timestamp.
Report content (description, category) is never transmitted.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime
from email.mime.multipart import MIMEMultipart
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
        case_number, deadline_label, days_left, cfg.notify_webhook_type,
        cfg.app_name, dashboard_url,
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


async def notify_new_report(case_number: str) -> None:
    """Send all enabled notifications for a newly submitted report.

    Runs both channels concurrently. Designed to be called as a
    FastAPI BackgroundTask so it never delays the HTTP response.
    """
    import asyncio

    from app.config import settings

    tasks = []
    if settings.notify_email_enabled and settings.notify_email_to.strip():
        tasks.append(_send_email(case_number, settings))
    if settings.notify_webhook_enabled and settings.notify_webhook_url.strip():
        tasks.append(_send_webhook(case_number, settings))

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def _send_email(case_number: str, settings: object) -> None:
    """Send an SMTP notification email."""
    import aiosmtplib

    from app.config import Settings
    cfg: Settings = settings  # type: ignore[assignment]

    recipients = [r.strip() for r in cfg.notify_email_to.split(",") if r.strip()]
    if not recipients:
        return

    dashboard_url = f"{cfg.app_public_url.rstrip('/')}/admin/dashboard"
    subject = f"New report received — {cfg.app_name}"

    text_body = (
        f"A new whistleblower report has been submitted to {cfg.app_name}.\n\n"
        f"Case number : {case_number}\n"
        f"Received at : {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}\n\n"
        f"Review it in the admin dashboard:\n{dashboard_url}\n\n"
        "-- \n"
        "No report content is included in this notification to protect\n"
        "the submitter's privacy and anonymity."
    )

    td_label = 'padding:0.4rem 0.75rem;border:1px solid #ddd;background:#f5f5f5;font-weight:bold'
    td_value = 'padding:0.4rem 0.75rem;border:1px solid #ddd'
    td_mono = f'{td_value};font-family:monospace'
    btn = (
        'display:inline-block;padding:0.6rem 1.2rem;'
        'background:#0f4c81;color:#fff;text-decoration:none;border-radius:4px'
    )
    received = datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')
    html_body = (
        '<html><body style="font-family:sans-serif;max-width:600px;margin:auto;">'
        '<h2 style="color:#0f4c81;">New Report Received</h2>'
        '<p>A new whistleblower report has been submitted to'
        f' <strong>{cfg.app_name}</strong>.</p>'
        '<table style="border-collapse:collapse;width:100%;margin:1rem 0;">'
        f'<tr><td style="{td_label}">Case Number</td>'
        f'<td style="{td_mono}">{case_number}</td></tr>'
        f'<tr><td style="{td_label}">Received at</td>'
        f'<td style="{td_value}">{received}</td></tr>'
        '</table>'
        f'<p><a href="{dashboard_url}" style="{btn}">Open Admin Dashboard →</a></p>'
        '<hr style="border:none;border-top:1px solid #eee;margin:1.5rem 0;">'
        '<p style="font-size:0.8rem;color:#888;">No report content is included'
        ' in this notification to protect the submitter\'s privacy.</p>'
        '</body></html>'
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = cfg.notify_email_from
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

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
        log.info(
            "Notification email sent for %s to %d recipient(s)",
            case_number,
            len(recipients),
        )
    except Exception:
        log.exception("Failed to send notification email for %s", case_number)


def _build_webhook_payload(
    case_number: str, webhook_type: str, app_name: str, dashboard_url: str
) -> dict[str, Any]:
    """Build webhook payload in the format expected by the target service."""
    ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    if webhook_type == "slack":
        return {
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": f"🔔 New report — {app_name}"},
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Case number:*\n`{case_number}`"},
                        {"type": "mrkdwn", "text": f"*Received at:*\n{ts}"},
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
                                "text": f"New report received — {app_name}",
                            },
                            {
                                "type": "FactSet",
                                "facts": [
                                    {"title": "Case number", "value": case_number},
                                    {"title": "Received at", "value": ts},
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
        "event": "new_report",
        "case_number": case_number,
        "timestamp": datetime.now(UTC).isoformat(),
    }


async def _send_webhook(case_number: str, settings: object) -> None:
    """POST a JSON notification to the configured webhook URL."""
    import httpx

    from app.config import Settings
    cfg: Settings = settings  # type: ignore[assignment]

    dashboard_url = f"{cfg.app_public_url.rstrip('/')}/admin/dashboard"
    payload = _build_webhook_payload(
        case_number, cfg.notify_webhook_type, cfg.app_name, dashboard_url
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
            "Webhook notification sent for %s (type=%s, HTTP %s)",
            case_number, cfg.notify_webhook_type, resp.status_code,
        )
    except Exception:
        log.exception("Failed to send webhook notification for %s", case_number)
