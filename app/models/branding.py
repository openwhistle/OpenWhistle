"""Operator branding: one row per organisation, one default row (org_id NULL), images by hash."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, LargeBinary, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class BrandImage(Base):
    __tablename__ = "brand_images"

    # The PNG's own SHA-256: the public URL, so it names no organisation.
    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    png: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)


def _image_ref() -> Mapped[str | None]:
    return mapped_column(String(64), ForeignKey("brand_images.sha256"), nullable=True)


class Branding(Base):
    __tablename__ = "branding"
    __table_args__ = (
        Index(
            "uq_branding_default",
            text("(org_id IS NULL)"),
            unique=True,
            postgresql_where=text("org_id IS NULL"),
        ),
    )

    IMAGE_FIELDS = ("logo_light", "logo_dark", "favicon_32", "favicon_180")

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        unique=True,
        nullable=True,
    )
    name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    primary_color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    logo_light: Mapped[str | None] = _image_ref()
    logo_dark: Mapped[str | None] = _image_ref()
    favicon_32: Mapped[str | None] = _image_ref()
    favicon_180: Mapped[str | None] = _image_ref()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True
    )
