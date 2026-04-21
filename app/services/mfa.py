"""TOTP-based MFA service (RFC 6238 / Google Authenticator compatible)."""

import base64
import io

import pyotp
import qrcode

from app.config import settings


def generate_totp_secret() -> str:
    """Generate a new TOTP secret (base32 encoded, 32 chars)."""
    return pyotp.random_base32()


def get_totp(secret: str) -> pyotp.TOTP:
    return pyotp.TOTP(secret)


def verify_totp(secret: str, code: str) -> bool:
    """Verify a TOTP code with a ±1 step window to handle clock drift."""
    totp = get_totp(secret)
    return totp.verify(code, valid_window=1)


def verify_demo_totp(code: str) -> bool:
    """In demo mode only: accept the static code '000000'."""
    return code == "000000"


def get_provisioning_uri(secret: str, username: str) -> str:
    totp = get_totp(secret)
    return totp.provisioning_uri(
        name=username,
        issuer_name=settings.app_name,
    )


def generate_qr_code_base64(secret: str, username: str) -> str:
    """Return a base64-encoded PNG of the TOTP QR code for inline display."""
    uri = get_provisioning_uri(secret, username)
    img = qrcode.make(uri)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()
