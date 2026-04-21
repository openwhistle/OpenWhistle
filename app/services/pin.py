"""PIN and case number generation for whistleblower access.

Two-factor design:
  - case_number: short human-readable reference (public, non-secret)
  - pin: UUID4 string (secret, cryptographically random)

Both are required together to access a report. Neither alone is sufficient.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.report import Report


async def generate_case_number(db: AsyncSession) -> str:
    """Generate a sequential case number like OW-2026-00042."""
    year = datetime.now(UTC).year
    result = await db.execute(
        select(func.count()).select_from(Report)
    )
    count: int = result.scalar_one()
    sequence = count + 1
    return f"OW-{year}-{sequence:05d}"


def generate_pin() -> str:
    """Generate a cryptographically random UUID4 PIN."""
    return str(uuid.uuid4())
