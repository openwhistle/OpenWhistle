"""DB-driven report categories — replaces the old Python enum."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ReportCategory(Base):
    __tablename__ = "report_categories"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    label_en: Mapped[str] = mapped_column(String(128), nullable=False)
    label_de: Mapped[str] = mapped_column(String(128), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
