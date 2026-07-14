"""PIN and case number generation for whistleblower access.

Two-factor design:
  - case_number: short human-readable reference (public, non-secret)
  - pin: UUID4 string (secret, cryptographically random)

Both are required together to access a report. Neither alone is sufficient.
"""

import secrets
import uuid
from datetime import UTC, datetime


def generate_case_number() -> str:
    """Generate a case number like OW-2026-48210.

    The 5-digit component is **random** (not sequential): a sequential number
    would leak aggregate report volume — in a multi-tenant deployment a new
    tenant's first report would reveal how many reports exist elsewhere on the
    instance. The case number is a public, non-secret reference (the PIN is the
    secret). It is globally unique; a rare random collision is resolved by the
    caller's retry on the unique-constraint violation (see ``create_report``).
    """
    year = datetime.now(UTC).year
    return f"OW-{year}-{secrets.randbelow(100000):05d}"


def generate_pin() -> str:
    """Generate a cryptographically random UUID4 PIN."""
    return str(uuid.uuid4())
