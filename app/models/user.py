"""Admin user model with mandatory MFA."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base

if TYPE_CHECKING:
    from app.models.report import Report


class AdminRole(enum.StrEnum):
    admin = "admin"
    case_manager = "case_manager"


class AdminUser(Base):
    __tablename__ = "admin_users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(72), nullable=False)

    # TOTP (mandatory)
    totp_secret: Mapped[str] = mapped_column(String(32), nullable=False)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Role-based access control
    role: Mapped[AdminRole] = mapped_column(
        Enum(AdminRole, name="adminrole"), nullable=False, default=AdminRole.admin
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # OIDC (optional — when set, password login is disabled for this user)
    oidc_sub: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    oidc_issuer: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    assigned_reports: Mapped[list[Report]] = relationship(
        "Report",
        back_populates="assigned_to",
        foreign_keys="Report.assigned_to_id",
        lazy="noload",
    )
