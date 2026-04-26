"""Fernet symmetric encryption for confidential report fields.

Key derivation: SHA-256 of SECRET_KEY → 32 bytes → url-safe base64 → Fernet key.
This means the same SECRET_KEY always produces the same encryption key; rotating
SECRET_KEY will make previously encrypted data unreadable (intended behaviour —
treat SECRET_KEY as the root secret).
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet


def _make_fernet() -> Fernet:
    from app.config import settings

    raw = hashlib.sha256(settings.secret_key.encode()).digest()
    key = base64.urlsafe_b64encode(raw)
    return Fernet(key)


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
        return None
