"""Re-encrypt everything under the current ENCRYPTION_KEY.

Run after moving the old key into ENCRYPTION_KEY_PREVIOUS, setting the new
ENCRYPTION_KEY and recreating the container (docker compose up -d):

    docker compose exec app python scripts/rotate_encryption_key.py

Only the per-report key wrappers and the directly encrypted fields change;
report content, messages, notes and attachments stay under their report key.

All or nothing: every value is re-encrypted in memory first. If any value
decrypts under none of the configured keys, the ids of those rows are printed
and nothing is written. Safe to run twice. Afterwards ENCRYPTION_KEY_PREVIOUS
can be emptied.
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_FIELDS = {
    "reports": ("confidential_name", "confidential_contact", "secure_email"),
    "admin_users": ("totp_secret",),
}


def _detail_rotator(key: str) -> Callable[[str], str]:
    def _rotate_detail(detail: str) -> str:
        from app.services.crypto import rotate

        data = json.loads(detail)
        data[key] = rotate(data[key])
        return json.dumps(data)

    return _rotate_detail


async def main() -> int:
    from cryptography.fernet import InvalidToken
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.config import settings
    from app.services.audit import AuditAction
    from app.services.crypto import rotate
    from app.services.encryption import (
        UNREADABLE_DATA_MESSAGE,
        configured_keys_read_existing_data,
        encryption_keys,
        rotate_dek,
    )

    previous = encryption_keys()[1:]
    if not settings.encryption_key or not previous:
        print(
            "Nothing to rotate from: ENCRYPTION_KEY and ENCRYPTION_KEY_PREVIOUS must both "
            "be set. Was the container recreated with the new variables?"
        )
        return 1
    print(f"Loaded {len(previous)} previous key(s).")
    if not await configured_keys_read_existing_data():
        # The full pass below names every unreadable row and writes nothing.
        print(UNREADABLE_DATA_MESSAGE)

    # (table, column, WHERE clause, transform)
    sources: list[tuple[str, str, str, Callable[[str], str]]] = [
        ("reports", "encrypted_dek", "encrypted_dek IS NOT NULL", rotate_dek),
    ]
    for table, columns in _FIELDS.items():
        sources += [(table, c, f"{c} IS NOT NULL", rotate) for c in columns]
    # Only these actions carry an encrypted detail value; other rows (e.g. the
    # retention job's report.auto_deleted) have a plaintext "reason" key.
    for action, key in (
        (AuditAction.IDENTITY_REVEALED, "reason"),
        (AuditAction.CONTENT_SEARCHED, "term"),
    ):
        sources.append((
            "audit_log", "detail",
            f"action = '{action}' AND detail LIKE '%\"{key}\"%'",
            _detail_rotator(key),
        ))

    engine = create_async_engine(settings.database_url, hide_parameters=True)
    writes: list[tuple[str, str, object, str, str]] = []
    failed: list[str] = []
    try:
        async with engine.connect() as conn:
            for table, column, where, transform in sources:
                rows = await conn.execute(
                    text(f"SELECT id, {column} FROM {table} WHERE {where}")  # noqa: S608
                )
                for row_id, value in rows.tuples():
                    try:
                        writes.append((table, column, row_id, value, transform(value)))
                    except InvalidToken:
                        failed.append(f"{table}.{column} id={row_id}")
        if failed:
            for entry in failed:
                print(entry)
            print(
                f"{len(failed)} value(s) decrypt under none of the configured keys; nothing "
                "was written. Add the key these were written under to "
                "ENCRYPTION_KEY_PREVIOUS and re-run."
            )
            return 1

        skipped = 0
        async with engine.begin() as conn:
            for table, column, row_id, old, new in writes:
                # Guard against a lost update: a value rewritten meanwhile (e.g. a
                # TOTP re-enrolment) is already under the current key; keep it.
                result = await conn.execute(
                    text(
                        f"UPDATE {table} SET {column} = :v "  # noqa: S608
                        f"WHERE id = :i AND {column} = :old"
                    ),
                    {"v": new, "i": row_id, "old": old},
                )
                skipped += 1 - result.rowcount
    finally:
        await engine.dispose()
    print(
        f"Re-encrypted {len(writes) - skipped} values under the current ENCRYPTION_KEY"
        f" ({skipped} changed meanwhile, left as written)."
    )
    if skipped:
        print("Re-run before emptying ENCRYPTION_KEY_PREVIOUS.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
