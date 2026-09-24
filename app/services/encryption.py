"""Envelope encryption for report fields.

Architecture (at-rest encryption):
  MEK  — Master Encryption Key. Derived via HKDF-SHA256 from ENCRYPTION_KEY
          (falling back to SECRET_KEY when unset). Never stored anywhere —
          re-derived on every call. Keys in ENCRYPTION_KEY_PREVIOUS stay
          accepted for decryption (MultiFernet), so the MEK can be rotated:
          scripts/rotate_encryption_key.py re-wraps every DEK under the current one.
  DEK  — Data Encryption Key. 32 random bytes generated per report, then
          wrapped (encrypted) with the MEK-derived Fernet key.
          Stored in reports.encrypted_dek as a Fernet token string.
  Data — Report.description and ReportMessage.content are encrypted with a
          Fernet key derived from the per-report DEK.

Why envelope encryption?
  Compromising the database alone (without ENCRYPTION_KEY) yields only ciphertext.
  Rotating the MEK re-wraps the DEKs only; report data is never re-encrypted.
"""

from __future__ import annotations

import base64
import logging
import os

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

log = logging.getLogger(__name__)

_MEK_SALT = b"openwhistle-mek-v1"
_MEK_INFO = b"report-encryption"

# Fernet tokens always start with this prefix after base64url encoding
_FERNET_PREFIX = "gAAAA"


def derive_mek(secret_key: str) -> bytes:
    """Derive the 32-byte Master Encryption Key from a root key via HKDF-SHA256."""
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_MEK_SALT,
        info=_MEK_INFO,
    )
    return hkdf.derive(secret_key.encode("utf-8"))


def encryption_keys() -> list[str]:
    """Current key first, then every key still accepted for decryption."""
    from app.config import settings  # noqa: PLC0415

    current = settings.encryption_key or settings.secret_key
    previous = [k.strip() for k in settings.encryption_key_previous.split(",") if k.strip()]
    return [current, *previous]


def make_mek_fernet() -> MultiFernet:
    """Encrypts with the current MEK, decrypts with any configured one."""
    return MultiFernet(
        [Fernet(base64.urlsafe_b64encode(derive_mek(k))) for k in encryption_keys()]
    )


def generate_dek() -> bytes:
    """Generate a cryptographically-random 32-byte Data Encryption Key."""
    return os.urandom(32)


def encrypt_dek(dek_raw: bytes) -> str:
    """Wrap a raw DEK with the current MEK. Returns the Fernet token as a string."""
    return make_mek_fernet().encrypt(dek_raw).decode("utf-8")


def decrypt_dek(encrypted_dek: str) -> bytes:
    """Unwrap an MEK-wrapped DEK token. Returns the raw 32-byte DEK."""
    return make_mek_fernet().decrypt(encrypted_dek.encode("utf-8"))


def rotate_dek(encrypted_dek: str) -> str:
    """Re-wrap a DEK under the current MEK. The data it protects is untouched."""
    return make_mek_fernet().rotate(encrypted_dek.encode("utf-8")).decode("utf-8")


def make_report_fernet(encrypted_dek: str) -> Fernet:
    """Build a Fernet instance from the stored encrypted DEK for a specific report."""
    return Fernet(base64.urlsafe_b64encode(decrypt_dek(encrypted_dek)))


def encrypt_field(fernet: Fernet, plaintext: str) -> str:
    """Encrypt a UTF-8 string field. Returns a Fernet token string."""
    return fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_field(fernet: Fernet, ciphertext: str) -> str:
    """Decrypt a Fernet-encrypted field. Returns the UTF-8 plaintext."""
    return fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")


def decrypt_field_safe(fernet: Fernet, ciphertext: str | None) -> str | None:
    """Decrypt a field, returning None on missing value or decryption failure.

    Two failure modes are handled differently:
    - Pre-encryption plaintext (value does not look like a Fernet token):
      returned as-is for backward compatibility with rows written before migration 013.
    - Fernet token that fails to decrypt (wrong key, e.g. ENCRYPTION_KEY was rotated):
      logs a warning and returns an error sentinel so the UI shows an actionable
      message rather than raw ciphertext.
    """
    if ciphertext is None:
        return None
    try:
        return fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        if ciphertext.startswith(_FERNET_PREFIX):
            # This looks like a real Fernet token — decryption key mismatch
            log.warning(
                "Fernet decryption failed for an encrypted field. "
                "ENCRYPTION_KEY/SECRET_KEY may have been rotated without re-encrypting stored DEKs."
            )
            return "[DECRYPTION FAILED — check ENCRYPTION_KEY/SECRET_KEY]"
        # Does not look like a Fernet token — treat as pre-encryption plaintext
        return ciphertext
    except Exception:  # noqa: BLE001
        return ciphertext
