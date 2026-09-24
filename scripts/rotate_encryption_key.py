"""Re-encrypt everything under the current ENCRYPTION_KEY.

Run after moving the old key into ENCRYPTION_KEY_PREVIOUS and restarting:

    docker compose exec app python scripts/rotate_encryption_key.py

Only the per-report key wrappers and the directly encrypted fields change;
report content, messages, notes and attachments stay under their report key.
Safe to run twice. Afterwards ENCRYPTION_KEY_PREVIOUS can be emptied.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_FIELDS = {
    "reports": ("confidential_name", "confidential_contact", "secure_email"),
    "admin_users": ("totp_secret",),
}


async def main() -> int:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.config import settings
    from app.services.crypto import rotate
    from app.services.encryption import rotate_dek

    engine = create_async_engine(settings.database_url)
    changed = 0
    async with engine.begin() as conn:
        reports = await conn.execute(text("SELECT id, encrypted_dek FROM reports"))
        for row_id, dek in reports.tuples():
            await conn.execute(
                text("UPDATE reports SET encrypted_dek = :v WHERE id = :i"),
                {"v": rotate_dek(dek), "i": row_id},
            )
            changed += 1
        for table, columns in _FIELDS.items():
            for column in columns:
                rows = await conn.execute(
                    text(f"SELECT id, {column} FROM {table} WHERE {column} IS NOT NULL")  # noqa: S608
                )
                for row_id, value in rows.tuples():
                    await conn.execute(
                        text(f"UPDATE {table} SET {column} = :v WHERE id = :i"),  # noqa: S608
                        {"v": rotate(value), "i": row_id},
                    )
                    changed += 1
        # Only identity reveals carry an encrypted reason; other rows (e.g. the
        # retention job's report.auto_deleted) have a plaintext "reason" key.
        audit = await conn.execute(
            text(
                "SELECT id, detail FROM audit_log "
                "WHERE action = 'report.identity_revealed' AND detail LIKE '%\"reason\"%'"
            )
        )
        for row_id, detail in audit.tuples():
            data = json.loads(detail)
            data["reason"] = rotate(data["reason"])
            await conn.execute(
                text("UPDATE audit_log SET detail = :v WHERE id = :i"),
                {"v": json.dumps(data), "i": row_id},
            )
            changed += 1
    await engine.dispose()
    print(f"Re-encrypted {changed} values under the current ENCRYPTION_KEY.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
