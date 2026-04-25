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


async def _send_webhook(case_number: str, settings: object) -> None:
    """POST a JSON notification to the configured webhook URL."""
    import httpx

    from app.config import Settings
    cfg: Settings = settings  # type: ignore[assignment]

    payload = {
        "event": "new_report",
        "case_number": case_number,
        "timestamp": datetime.now(UTC).isoformat(),
    }
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
        log.info("Webhook notification sent for %s (HTTP %s)", case_number, resp.status_code)
    except Exception:
        log.exception("Failed to send webhook notification for %s", case_number)
