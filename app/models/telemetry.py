"""Installation-count state: consent, the random identifier, the last success."""

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, String, false
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TelemetryState(Base):
    __tablename__ = "telemetry_state"
    __table_args__ = (CheckConstraint("id = 1", name="telemetry_state_single_row"),)

    # Single row, always id=1. No row means never asked, which is off.
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    # 16 random bytes as hex, made on first use; never derived from the host.
    installation_id: Mapped[str] = mapped_column(String(32), nullable=False)
    # Only ever set after a report the far end accepted.
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
