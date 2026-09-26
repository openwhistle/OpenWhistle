"""Fernet symmetric encryption for confidential report fields.

Key derivation: SHA-256 of ENCRYPTION_KEY (falling back to SECRET_KEY when unset)
→ 32 bytes → url-safe base64 → Fernet key. Keys listed in ENCRYPTION_KEY_PREVIOUS
remain accepted for decryption; rotate() re-encrypts a token under the current key
(see scripts/rotate_encryption_key.py).
"""

from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, MultiFernet

log = logging.getLogger(__name__)


def _make_fernet() -> MultiFernet:
    from app.services.encryption import encryption_keys  # noqa: PLC0415

    return MultiFernet([
        Fernet(base64.urlsafe_b64encode(hashlib.sha256(k.encode()).digest()))
        for k in encryption_keys()
    ])


def encrypt(plaintext: str) -> str:
    """Encrypt a UTF-8 string. Returns a base64url token (str)."""
    f = _make_fernet()
    return f.encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    """Decrypt a Fernet token produced by encrypt(). Raises on bad token."""
    f = _make_fernet()
    return f.decrypt(token.encode()).decode()


def decrypt_or_none(token: str | None) -> str | None:
    if not token:
        return None
    try:
        return decrypt(token)
    except Exception:
        # A non-empty token that fails to decrypt is NOT the same as an absent
        # field: it means corruption, a rotated encryption key, or tampering. Log it
        # so an operator can investigate rather than silently showing "blank".
        log.warning(
            "Failed to decrypt a confidential field; showing it as empty. "
            "This indicates data corruption or a rotated ENCRYPTION_KEY."
        )
        return None


def rotate(token: str) -> str:
    """Re-encrypt a token under the current key."""
    return _make_fernet().rotate(token.encode()).decode()
