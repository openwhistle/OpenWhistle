"""Setup status — tracks whether initial admin wizard has been completed."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SetupStatus(Base):
    __tablename__ = "setup_status"

    # Single row, always id=1
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
