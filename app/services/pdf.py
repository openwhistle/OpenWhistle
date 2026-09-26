"""PDF export service using fpdf2 - pure Python, no system packages required."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from app.models.report import Report
from app.services.report import (
    decrypt_attachment_names,
    decrypt_note_contents,
    decrypt_report_fields,
    format_day,
    whistleblower_caused,
)

# Signal-style printed record (DESIGN.md, "Printed case record").
_INK = (10, 10, 11)
_MUTED = (106, 106, 110)
_ACCENT = (12, 114, 83)
_HAIRLINE = (216, 216, 214)

# DejaVu LGC Sans (Latin/Greek/Cyrillic) — see app/fonts/README for source,
# version and license. Helvetica (fpdf2's core font) is latin-1 only; a
# report written in Polish, Greek or Cyrillic needs a real Unicode font, not
# a "?" substitution.
_FONT_DIR = Path(__file__).resolve().parents[1] / "fonts"
_FONT = "DejaVu"


def _register_font(pdf: FPDF) -> None:
    pdf.add_font(_FONT, "", str(_FONT_DIR / "DejaVuLGCSans.ttf"))
    pdf.add_font(_FONT, "B", str(_FONT_DIR / "DejaVuLGCSans-Bold.ttf"))


def generate_report_pdf(
    report: Report, include_identity: bool = False, category_label: str | None = None
) -> bytes:
    description, msg_contents = decrypt_report_fields(report)
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    _register_font(pdf)
    pdf.add_page()

    # ── Header ────────────────────────────────────────────────────
    pdf.set_text_color(*_INK)
    pdf.set_font(_FONT, "B", 18)
    pdf.cell(
        0, 10, "OpenWhistle - Case Export",
        align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT,
    )
    pdf.set_font(_FONT, "", 10)
    generated = f"Generated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}"
    pdf.cell(0, 6, generated, align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_draw_color(*_ACCENT)
    pdf.set_line_width(0.6)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.set_line_width(0.2)
    pdf.ln(6)

    # ── Case metadata ─────────────────────────────────────────────
    pdf.set_font(_FONT, "B", 13)
    pdf.cell(0, 8, "Case Information", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_draw_color(*_HAIRLINE)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(3)

    pdf.set_font(_FONT, "", 10)
    _meta_row(pdf, "Case Number", report.case_number)
    # The exporting admin's language, org-scoped label (get_category_labels) —
    # falls back to the raw slug if the caller has none (e.g. a category
    # deleted outright since), same as the case page's category_label filter.
    _meta_row(pdf, "Category", category_label or report.category)
    _meta_row(pdf, "Status", report.status.value.replace("_", " ").title())
    _meta_row(pdf, "Submission Mode", report.submission_mode.value.title())
    if report.location:
        _meta_row(pdf, "Location", f"{report.location.name} ({report.location.code})")
    _meta_row(pdf, "Submitted", format_day(report.submitted_at))
    if report.acknowledged_at:
        _meta_row(pdf, "Acknowledged", _fmt_dt(report.acknowledged_at))
    if report.feedback_due_at:
        _meta_row(pdf, "Feedback Due", _fmt_dt(report.feedback_due_at))
    if report.closed_at:
        _meta_row(pdf, "Closed", _fmt_dt(report.closed_at))
    if report.assigned_to:
        _meta_row(pdf, "Assigned To", report.assigned_to.username)
    if report.confidential_name or report.confidential_contact:
        if include_identity:
            from app.services.crypto import decrypt_or_none
            if report.confidential_name:
                name = decrypt_or_none(report.confidential_name) or "[encrypted]"
                _meta_row(pdf, "Confidential Name", name)
            if report.confidential_contact:
                contact = decrypt_or_none(report.confidential_contact) or "[encrypted]"
                _meta_row(pdf, "Confidential Contact", contact)
        else:
            _meta_row(pdf, "Identity", "[on file — not included]")
    if report.secure_email:
        _meta_row(pdf, "Secure Email", "[on file — not printed]")
    pdf.ln(5)

    # ── SLA status ────────────────────────────────────────────────
    pdf.set_font(_FONT, "B", 13)
    pdf.cell(
        0, 8, "SLA Compliance (HinSchG §17)",
        new_x=XPos.LMARGIN, new_y=YPos.NEXT,
    )
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(3)
    pdf.set_font(_FONT, "", 10)

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
    pdf.set_font(_FONT, "B", 13)
    pdf.cell(0, 8, "Initial Report", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(3)
    pdf.set_font(_FONT, "", 10)
    pdf.multi_cell(0, 5, _safe(description))
    pdf.ln(5)

    # ── Communication thread ───────────────────────────────────────
    public_msgs = list(report.messages)
    if public_msgs:
        pdf.set_font(_FONT, "B", 13)
        pdf.cell(0, 8, "Communication Thread", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(3)
        pdf.set_font(_FONT, "", 10)
        for i, msg in enumerate(public_msgs):
            sender = "Reporting Office" if msg.sender.value == "admin" else "Whistleblower"
            when = format_day(msg.sent_at) if whistleblower_caused(msg, i) else _fmt_dt(msg.sent_at)
            pdf.set_font(_FONT, "B", 9)
            pdf.cell(
                0, 5, f"{sender}  ·  {when}",
                new_x=XPos.LMARGIN, new_y=YPos.NEXT,
            )
            pdf.set_font(_FONT, "", 10)
            msg_text = msg_contents[i] if i < len(msg_contents) else msg.content
            pdf.multi_cell(0, 5, _safe(msg_text))
            pdf.ln(2)
        pdf.ln(3)

    # ── Internal notes ─────────────────────────────────────────────
    if report.notes:
        pdf.set_font(_FONT, "B", 13)
        pdf.cell(
            0, 8,
            "Internal Notes (Admin only - not shared with whistleblower)",
            new_x=XPos.LMARGIN, new_y=YPos.NEXT,
        )
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(3)
        for note, note_text in zip(report.notes, decrypt_note_contents(report), strict=True):
            pdf.set_font(_FONT, "B", 9)
            pdf.cell(
                0, 5, f"{_safe(note.author_username)}  ·  {_fmt_dt(note.created_at)}",
                new_x=XPos.LMARGIN, new_y=YPos.NEXT,
            )
            pdf.set_font(_FONT, "", 10)
            pdf.multi_cell(0, 5, _safe(note_text))
            pdf.ln(2)
        pdf.ln(3)

    # ── Attachments list ───────────────────────────────────────────
    if report.attachments:
        pdf.set_font(_FONT, "B", 13)
        pdf.cell(0, 8, "Attachments", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(3)
        pdf.set_font(_FONT, "", 10)
        for att, att_name in zip(report.attachments, decrypt_attachment_names(report), strict=True):
            size_kb = att.size // 1024
            pdf.cell(
                0, 5,
                f"- {_safe(att_name)}  ({size_kb} KB, {att.content_type})",
                new_x=XPos.LMARGIN, new_y=YPos.NEXT,
            )
        pdf.ln(3)

    # ── Footer ────────────────────────────────────────────────────
    # Regular, not italic: only Regular and Bold are bundled (app/fonts/README).
    pdf.set_font(_FONT, "", 8)
    pdf.set_text_color(*_MUTED)
    footer_text = (
        "This document was generated by OpenWhistle"
        " - confidential, for authorised use only."
    )
    pdf.cell(0, 5, footer_text, align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    return bytes(pdf.output())


def _meta_row(pdf: FPDF, label: str, value: str) -> None:
    pdf.set_font(_FONT, "B", 10)
    pdf.set_text_color(*_MUTED)
    pdf.cell(55, 5, label + ":", new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.set_font(_FONT, "", 10)
    pdf.set_text_color(*_INK)
    pdf.cell(0, 5, _safe(value), new_x=XPos.LMARGIN, new_y=YPos.NEXT)


def _fmt_dt(dt: datetime | None) -> str:
    if not dt:
        return "-"
    return dt.strftime("%Y-%m-%d %H:%M UTC")


# DejaVu (loaded via HarfBuzz shaping) renders full Unicode text directly, so
# nothing needs transliterating or replacing to fit latin-1 any more. Only
# C0/DEL control characters are stripped — a whistleblower's editor can embed
# these by accident (or a hostile upload on purpose), and fpdf2 does not
# render them meaningfully either way. \t, \n and \r are kept: multi_cell
# relies on them for layout.
# ponytail: does not strip bidi-override/zero-width characters (a visual
# text-spoofing risk in the rendered page, not a content-integrity one — PDF
# text extraction such as pypdf reads logical order, unaffected by them).
# Add stripping for those if a printed record ever needs to defend against
# visually misleading text, not just missing text.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _safe(text: str) -> str:
    return _CONTROL_CHARS.sub("", text)
