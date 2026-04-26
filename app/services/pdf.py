"""PDF export service using fpdf2 - pure Python, no system packages required."""

from __future__ import annotations

from datetime import UTC, datetime

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from app.models.report import Report


def generate_report_pdf(report: Report) -> bytes:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # ── Header ────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(
        0, 10, "OpenWhistle - Case Export",
        align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT,
    )
    pdf.set_font("Helvetica", "", 10)
    generated = f"Generated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}"
    pdf.cell(0, 6, generated, align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(6)

    # ── Case metadata ─────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 8, "Case Information", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_draw_color(180, 180, 180)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(3)

    pdf.set_font("Helvetica", "", 10)
    _meta_row(pdf, "Case Number", report.case_number)
    _meta_row(pdf, "Category", report.category)
    _meta_row(pdf, "Status", report.status.value.replace("_", " ").title())
    _meta_row(pdf, "Submission Mode", report.submission_mode.value.title())
    if report.location:
        _meta_row(pdf, "Location", f"{report.location.name} ({report.location.code})")
    _meta_row(pdf, "Submitted", _fmt_dt(report.submitted_at))
    if report.acknowledged_at:
        _meta_row(pdf, "Acknowledged", _fmt_dt(report.acknowledged_at))
    if report.feedback_due_at:
        _meta_row(pdf, "Feedback Due", _fmt_dt(report.feedback_due_at))
    if report.closed_at:
        _meta_row(pdf, "Closed", _fmt_dt(report.closed_at))
    if report.assigned_to:
        _meta_row(pdf, "Assigned To", report.assigned_to.username)
    if report.confidential_name or report.confidential_contact:
        from app.services.crypto import decrypt_or_none
        if report.confidential_name:
            name = decrypt_or_none(report.confidential_name) or "[encrypted]"
            _meta_row(pdf, "Confidential Name", name)
        if report.confidential_contact:
            contact = decrypt_or_none(report.confidential_contact) or "[encrypted]"
            _meta_row(pdf, "Confidential Contact", contact)
    if report.secure_email:
        _meta_row(pdf, "Secure Email", "[on file — not printed]")
    pdf.ln(5)

    # ── SLA status ────────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(
        0, 8, "SLA Compliance (HinSchG §17)",
        new_x=XPos.LMARGIN, new_y=YPos.NEXT,
    )
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(3)
    pdf.set_font("Helvetica", "", 10)

    submitted = report.submitted_at
    now = datetime.now(UTC)
    if submitted.tzinfo is None:
        submitted = submitted.replace(tzinfo=UTC)

    days_since = (now - submitted).days
    if report.acknowledged_at:
        ack_tz = report.acknowledged_at.tzinfo or UTC
        ack_normalized = report.acknowledged_at.replace(tzinfo=ack_tz)
        ack_days = (ack_normalized - submitted).days
        ack_status = "OK Compliant" if ack_days <= 7 else "OK Acknowledged (late)"
    else:
        ack_status = f"Pending - Day {days_since}/7"
    _meta_row(pdf, "7-Day Acknowledgement", ack_status)

    if report.feedback_due_at:
        fdt = report.feedback_due_at
        if fdt.tzinfo is None:
            fdt = fdt.replace(tzinfo=UTC)
        days_left = (fdt - now).days
        if report.closed_at:
            feedback_status = "OK Delivered"
        else:
            feedback_status = f"{max(0, days_left)} days remaining"
        _meta_row(pdf, "3-Month Feedback Deadline", feedback_status)
    pdf.ln(5)

    # ── Description ───────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 8, "Initial Report", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(3)
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 5, _safe(report.description))
    pdf.ln(5)

    # ── Communication thread ───────────────────────────────────────
    public_msgs = list(report.messages)
    if public_msgs:
        pdf.set_font("Helvetica", "B", 13)
        pdf.cell(0, 8, "Communication Thread", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(3)
        pdf.set_font("Helvetica", "", 10)
        for msg in public_msgs:
            sender = "Reporting Office" if msg.sender.value == "admin" else "Whistleblower"
            pdf.set_font("Helvetica", "B", 9)
            pdf.cell(
                0, 5, f"{sender}  ·  {_fmt_dt(msg.sent_at)}",
                new_x=XPos.LMARGIN, new_y=YPos.NEXT,
            )
            pdf.set_font("Helvetica", "", 10)
            pdf.multi_cell(0, 5, _safe(msg.content))
            pdf.ln(2)
        pdf.ln(3)

    # ── Internal notes ─────────────────────────────────────────────
    if report.notes:
        pdf.set_font("Helvetica", "B", 13)
        pdf.cell(
            0, 8,
            "Internal Notes (Admin only - not shared with whistleblower)",
            new_x=XPos.LMARGIN, new_y=YPos.NEXT,
        )
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(3)
        for note in report.notes:
            pdf.set_font("Helvetica", "B", 9)
            pdf.cell(
                0, 5, f"{note.author_username}  ·  {_fmt_dt(note.created_at)}",
                new_x=XPos.LMARGIN, new_y=YPos.NEXT,
            )
            pdf.set_font("Helvetica", "", 10)
            pdf.multi_cell(0, 5, _safe(note.content))
            pdf.ln(2)
        pdf.ln(3)

    # ── Attachments list ───────────────────────────────────────────
    if report.attachments:
        pdf.set_font("Helvetica", "B", 13)
        pdf.cell(0, 8, "Attachments", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(3)
        pdf.set_font("Helvetica", "", 10)
        for att in report.attachments:
            size_kb = att.size // 1024
            pdf.cell(
                0, 5,
                f"- {_safe(att.filename)}  ({size_kb} KB, {att.content_type})",
                new_x=XPos.LMARGIN, new_y=YPos.NEXT,
            )
        pdf.ln(3)

    # ── Footer ────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(120, 120, 120)
    footer_text = (
        "This document was generated by OpenWhistle"
        " - confidential, for authorised use only."
    )
    pdf.cell(0, 5, footer_text, align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    return bytes(pdf.output())


def _meta_row(pdf: FPDF, label: str, value: str) -> None:
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(55, 5, label + ":", new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 5, _safe(value), new_x=XPos.LMARGIN, new_y=YPos.NEXT)


def _fmt_dt(dt: datetime | None) -> str:
    if not dt:
        return "-"
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def _safe(text: str) -> str:
    return text.encode("latin-1", errors="replace").decode("latin-1")
