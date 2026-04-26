"""Whistleblower report models — no IP address fields anywhere."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base

if TYPE_CHECKING:
    from app.models.attachment import Attachment
    from app.models.user import AdminUser


class ReportStatus(enum.StrEnum):
    received = "received"
    in_review = "in_review"
    pending_feedback = "pending_feedback"
    closed = "closed"


# Valid status transitions: {from_status: set_of_allowed_to_statuses}
STATUS_TRANSITIONS: dict[str, set[str]] = {
    "received":         {"in_review", "closed"},
    "in_review":        {"pending_feedback", "closed", "received"},
    "pending_feedback": {"closed", "in_review"},
    "closed":           {"in_review"},
}


class ReportSender(enum.StrEnum):
    whistleblower = "whistleblower"
    admin = "admin"


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    case_number: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    pin_hash: Mapped[str] = mapped_column(String(72), nullable=False)

    # Stored as plain string — denormalized at submit time for history immutability
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[ReportStatus] = mapped_column(
        Enum(ReportStatus, name="reportstatus"),
        nullable=False,
        default=ReportStatus.received,
    )

    # Case assignment
    assigned_to_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("admin_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    assigned_to: Mapped[AdminUser | None] = relationship(
        "AdminUser",
        back_populates="assigned_reports",
        foreign_keys=[assigned_to_id],
        lazy="joined",
    )

    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    feedback_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    messages: Mapped[list[ReportMessage]] = relationship(
        "ReportMessage", back_populates="report", cascade="all, delete-orphan",
        order_by="ReportMessage.sent_at",
    )
    attachments: Mapped[list[Attachment]] = relationship(
        "Attachment", back_populates="report", cascade="all, delete-orphan"
    )
    notes: Mapped[list[AdminNote]] = relationship(
        "AdminNote", back_populates="report", cascade="all, delete-orphan",
        order_by="AdminNote.created_at",
    )
    links_as_a: Mapped[list[CaseLink]] = relationship(
        "CaseLink",
        foreign_keys="CaseLink.report_id_a",
        back_populates="report_a",
        cascade="all, delete-orphan",
    )
    links_as_b: Mapped[list[CaseLink]] = relationship(
        "CaseLink",
        foreign_keys="CaseLink.report_id_b",
        back_populates="report_b",
        cascade="all, delete-orphan",
    )
    deletion_request: Mapped[DeletionRequest | None] = relationship(
        "DeletionRequest",
        back_populates="report",
        cascade="all, delete-orphan",
        uselist=False,
    )


class ReportMessage(Base):
    """A message in the bidirectional communication thread."""

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


class AdminNote(Base):
    """Internal note visible only to admins — never shown to the whistleblower."""

    __tablename__ = "admin_notes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reports.id", ondelete="CASCADE"), nullable=False, index=True
    )
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True
    )
    author_username: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    report: Mapped[Report] = relationship("Report", back_populates="notes")


class CaseLink(Base):
    """Bidirectional link between two reports (de-duplication / same whistleblower)."""

    __tablename__ = "case_links"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Smaller UUID always in report_id_a for normalization
    report_id_a: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reports.id", ondelete="CASCADE"), nullable=False
    )
    report_id_b: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reports.id", ondelete="CASCADE"), nullable=False
    )
    linked_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True
    )
    linked_by_username: Mapped[str] = mapped_column(String(64), nullable=False)
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    report_a: Mapped[Report] = relationship(
        "Report", foreign_keys=[report_id_a], back_populates="links_as_a"
    )
    report_b: Mapped[Report] = relationship(
        "Report", foreign_keys=[report_id_b], back_populates="links_as_b"
    )


class DeletionRequest(Base):
    """4-eyes deletion workflow: request by one admin, confirm by another."""

    __tablename__ = "deletion_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("reports.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    requested_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True
    )
    requested_by_username: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    confirmed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True
    )
    confirmed_by_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    report: Mapped[Report] = relationship("Report", back_populates="deletion_request")
