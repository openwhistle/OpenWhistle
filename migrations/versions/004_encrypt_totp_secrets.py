"""TOTP secrets are stored encrypted.

Revision ID: a1c6e0f4b201
Revises: 7d4e2b9c1a05
Create Date: 2026-09-24

The column becomes Text (a Fernet token is longer than 32 characters) and every
plaintext secret is encrypted in place. Idempotent: a value that already
decrypts is left alone. Downgrade decrypts and narrows the column again.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "a1c6e0f4b201"
down_revision: str | None = "7d4e2b9c1a05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_token(value: str) -> bool:
    from app.services.crypto import decrypt

    try:
        decrypt(value)
    except Exception:  # noqa: BLE001 — anything that does not decrypt is plaintext
        return False
    return True


def _rows() -> list[tuple[object, str]]:
    return list(op.get_bind().execute(sa.text("SELECT id, totp_secret FROM admin_users")).tuples())


def _set(user_id: object, value: str) -> None:
    op.get_bind().execute(
        sa.text("UPDATE admin_users SET totp_secret = :v WHERE id = :i"), {"v": value, "i": user_id}
    )


def upgrade() -> None:
    op.alter_column("admin_users", "totp_secret", type_=sa.Text(), existing_nullable=False)
    if context.is_offline_mode():
        return
    from app.services.crypto import encrypt

    for user_id, secret in _rows():
        if not _is_token(secret):
            _set(user_id, encrypt(secret))


def downgrade() -> None:
    if not context.is_offline_mode():
        from app.services.crypto import decrypt

        for user_id, secret in _rows():
            if _is_token(secret):
                _set(user_id, decrypt(secret))
    op.alter_column(
        "admin_users", "totp_secret", type_=sa.String(32), existing_nullable=False
    )
