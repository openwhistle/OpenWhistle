"""TOTP-based MFA service (RFC 6238 / Google Authenticator compatible)."""

import base64
import io
import re

import pyotp
import qrcode
from redis.asyncio import Redis

from app.config import settings


def generate_totp_secret() -> str:
    """Generate a new TOTP secret (base32 encoded, 32 chars)."""
    return pyotp.random_base32()


def get_totp(secret: str) -> pyotp.TOTP:
    return pyotp.TOTP(secret)


# Six ASCII digits and nothing else. pyotp NFKC-normalises before comparing,
# so "１２３４５６" (fullwidth) used to match "123456" while the single-use key
# below held the raw string: one code opened a second session.
_TOTP_CODE = re.compile(r"[0-9]{6}")


def verify_totp(secret: str, code: str) -> bool:
    """Verify a TOTP code with a ±1 step window to handle clock drift."""
    if not _TOTP_CODE.fullmatch(code):
        return False
    totp = get_totp(secret)
    return totp.verify(code, valid_window=1)


async def consume_totp(redis: Redis, user_id: object, secret: str, code: str) -> bool:
    """Verify a code and mark it used: it authenticates one action in its ~90 s window.

    Prevents an intercepted or relayed code (AiTM, a glance over a shoulder)
    from being used a second time — for a second session, a password change,
    or a sign-in right after enrolment.
    """
    return verify_totp(secret, code) and bool(
        await redis.set(f"openwhistle:totp_used:{user_id}:{code}", "1", nx=True, ex=90)
    )


def verify_demo_totp(code: str, username: str) -> bool:
    """In demo mode only: accept the static code '000000' for the seeded demo
    accounts. Any other account keeps real TOTP, so a production database
    started with DEMO_MODE=true by mistake does not lose its second factor."""
    from app.services.demo_seed import DEMO_USERNAMES  # noqa: PLC0415

    return code == "000000" and username in DEMO_USERNAMES


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
