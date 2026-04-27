"""Envelope encryption for report fields.

Architecture (at-rest encryption):
  MEK  — Master Encryption Key. Derived via HKDF-SHA256 from the SECRET_KEY
          environment variable. Never stored anywhere — re-derived on every call.
  DEK  — Data Encryption Key. 32 random bytes generated per report, then
          wrapped (encrypted) with the MEK-derived Fernet key.
          Stored in reports.encrypted_dek as a Fernet token string.
  Data — Report.description and ReportMessage.content are encrypted with a
          Fernet key derived from the per-report DEK.

Why envelope encryption?
  Compromising the database alone (without SECRET_KEY) yields only ciphertext.
  DEK rotation is possible per-report without re-keying everything.
"""

from __future__ import annotations

import base64
import os

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_MEK_SALT = b"openwhistle-mek-v1"
_MEK_INFO = b"report-encryption"


def derive_mek(secret_key: str) -> bytes:
    """Derive the 32-byte Master Encryption Key from SECRET_KEY via HKDF-SHA256."""
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_MEK_SALT,
        info=_MEK_INFO,
    )
    return hkdf.derive(secret_key.encode("utf-8"))


def make_mek_fernet(secret_key: str) -> Fernet:
    """Return a Fernet instance keyed with the MEK derived from secret_key."""
    raw = derive_mek(secret_key)
    return Fernet(base64.urlsafe_b64encode(raw))


def generate_dek() -> bytes:
    """Generate a cryptographically-random 32-byte Data Encryption Key."""
    return os.urandom(32)


def encrypt_dek(dek_raw: bytes, secret_key: str) -> str:
    """Encrypt a raw DEK with the MEK Fernet. Returns the Fernet token as a string."""
    mek_fernet = make_mek_fernet(secret_key)
    return mek_fernet.encrypt(dek_raw).decode("utf-8")


def decrypt_dek(encrypted_dek: str, secret_key: str) -> bytes:
    """Decrypt an MEK-wrapped DEK token. Returns the raw 32-byte DEK."""
    mek_fernet = make_mek_fernet(secret_key)
    return mek_fernet.decrypt(encrypted_dek.encode("utf-8"))


def make_report_fernet(encrypted_dek: str, secret_key: str) -> Fernet:
    """Build a Fernet instance from the stored encrypted DEK for a specific report."""
    dek_raw = decrypt_dek(encrypted_dek, secret_key)
    return Fernet(base64.urlsafe_b64encode(dek_raw))


def encrypt_field(fernet: Fernet, plaintext: str) -> str:
    """Encrypt a UTF-8 string field. Returns a Fernet token string."""
    return fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_field(fernet: Fernet, ciphertext: str) -> str:
    """Decrypt a Fernet-encrypted field. Returns the UTF-8 plaintext."""
    return fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")


def decrypt_field_safe(fernet: Fernet, ciphertext: str | None) -> str | None:
    """Decrypt a field, returning None on missing value or decryption failure.

    Used for backward-compatibility with pre-encryption data: if the stored
    value is not a valid Fernet token (e.g. plaintext from before migration),
    returns the raw value unchanged rather than raising.
    """
    if ciphertext is None:
        return None
    try:
        return fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except (InvalidToken, Exception):  # noqa: BLE001
        return ciphertext  # pre-encryption plaintext — return as-is
