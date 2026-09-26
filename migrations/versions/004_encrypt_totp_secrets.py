"""TOTP secrets are stored encrypted.

Revision ID: a1c6e0f4b201
Revises: 7d4e2b9c1a05
Create Date: 2026-09-24

The column becomes Text (a Fernet token is longer than 32 characters) and every
plaintext secret is encrypted in place. Idempotent: a value that already
decrypts is left alone. Downgrade decrypts and narrows the column again.
Downgrade refuses if a secret does not decrypt with the current key.
Online only: offline SQL (``--sql``) cannot encrypt the existing rows.
"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from cryptography.fernet import InvalidToken

revision: str = "a1c6e0f4b201"
down_revision: str | None = "7d4e2b9c1a05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = logging.getLogger("alembic.runtime.migration")


def _is_token(value: str) -> bool:
    from app.services.crypto import decrypt

    try:
        decrypt(value)
    except InvalidToken:
        return False
    return True


def _rows() -> list[tuple[object, str]]:
    return list(op.get_bind().execute(sa.text("SELECT id, totp_secret FROM admin_users")).tuples())


def _set(user_id: object, value: str) -> None:
    op.get_bind().execute(
        sa.text("UPDATE admin_users SET totp_secret = :v WHERE id = :i"), {"v": value, "i": user_id}
    )


def _refuse_offline() -> None:
    if context.is_offline_mode():
        # Only the ALTER would be emitted: the secrets would stay plaintext
        # (or ciphertext, going down), and every login would then fail.
        msg = "Migration 004 must run online: offline SQL cannot re-encrypt the TOTP secrets"
        raise RuntimeError(msg)


def upgrade() -> None:
    _refuse_offline()
    op.alter_column("admin_users", "totp_secret", type_=sa.Text(), existing_nullable=False)
    from app.services.crypto import encrypt

    for user_id, secret in _rows():
        if not _is_token(secret):
            _set(user_id, encrypt(secret))


def downgrade() -> None:
    _refuse_offline()
    from app.services.crypto import decrypt

    rows = _rows()
    # A value longer than the target VARCHAR(32) that does not decrypt is not
    # a legacy plaintext secret — it cannot be narrowed safely (wrong/rotated
    # ENCRYPTION_KEY/SECRET_KEY, corruption). Refuse before touching the column.
    stuck = [
        user_id for user_id, secret in rows if len(secret) > 32 and not _is_token(secret)
    ]
    if stuck:
        for user_id in stuck:
            log.warning(
                "Migration 004 downgrade: totp_secret for admin_users.id=%s does not "
                "decrypt with the current ENCRYPTION_KEY/SECRET_KEY",
                user_id,
            )
        msg = (
            f"{len(stuck)} totp_secret value(s) do not decrypt with the current "
            "ENCRYPTION_KEY/SECRET_KEY; refusing to downgrade"
        )
        raise RuntimeError(msg)

    for user_id, secret in rows:
        if _is_token(secret):
            _set(user_id, decrypt(secret))
    op.alter_column(
        "admin_users", "totp_secret", type_=sa.String(32), existing_nullable=False
    )
