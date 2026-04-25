"""Whistleblower report models — no IP address fields anywhere."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from app.models.attachment import Attachment

from app.database import Base


class ReportCategory(enum.StrEnum):
    financial_fraud = "financial_fraud"
    workplace_safety = "workplace_safety"
    environmental = "environmental"
    corruption = "corruption"
    data_protection = "data_protection"
    discrimination = "discrimination"
    other = "other"


class ReportStatus(enum.StrEnum):
    received = "received"
    acknowledged = "acknowledged"
    in_progress = "in_progress"
    closed = "closed"


class ReportSender(enum.StrEnum):
    whistleblower = "whistleblower"
    admin = "admin"


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Human-readable case reference (e.g. OW-2026-00042) — shown to whistleblower
    case_number: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    # bcrypt hash of the secret UUID4 PIN
    pin_hash: Mapped[str] = mapped_column(String(72), nullable=False)

    category: Mapped[ReportCategory] = mapped_column(
        Enum(ReportCategory, name="reportcategory"), nullable=False
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[ReportStatus] = mapped_column(
        Enum(ReportStatus, name="reportstatus"),
        nullable=False,
        default=ReportStatus.received,
    )

    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Set when admin confirms receipt (HinSchG §17 Abs. 1 — within 7 days)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set automatically when acknowledged (3 months SLA per HinSchG §17 Abs. 2)
    feedback_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    messages: Mapped[list[ReportMessage]] = relationship(
        "ReportMessage", back_populates="report", cascade="all, delete-orphan"
    )
    attachments: Mapped[list["Attachment"]] = relationship(
        "Attachment", back_populates="report", cascade="all, delete-orphan"
    )


class ReportMessage(Base):
    """A message in the bidirectional communication thread.

    Required by HinSchG §17 Abs. 3 — same channel for follow-up communication.
    No IP address stored anywhere.
    """

    __tablename__ = "report_messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reports.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sender: Mapped[ReportSender] = mapped_column(
        Enum(ReportSender, name="reportsender"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    report: Mapped[Report] = relationship("Report", back_populates="messages")
