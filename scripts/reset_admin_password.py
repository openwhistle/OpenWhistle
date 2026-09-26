#!/usr/bin/env python3
"""Management script: reset an admin user's password or authenticator.

Usage
-----
    # Interactive (prompts for new password):
    python scripts/reset_admin_password.py --username admin

    # Lost authenticator: new TOTP secret, printed once, every session ended:
    python scripts/reset_admin_password.py --reset-totp admin

    # Non-interactive (CI / automation):
    python scripts/reset_admin_password.py --username admin --password "a-long-passphrase"

    # List all admin users:
    python scripts/reset_admin_password.py --list

Docker
------
    docker exec -it openwhistle python scripts/reset_admin_password.py --username admin
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys

# Allow running from the project root without installing the package
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Ensure SECRET_KEY is set (required by pydantic-settings even for this script)
os.environ.setdefault("SECRET_KEY", "reset-script-placeholder-not-used-for-crypto")


async def _list_users() -> None:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import settings
    from app.models.user import AdminUser

    engine = create_async_engine(settings.database_url, echo=False, hide_parameters=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        result = await session.execute(select(AdminUser).order_by(AdminUser.created_at))
        users = result.scalars().all()

    await engine.dispose()

    if not users:
        print("No admin users found.")
        return

    print(f"\n{'Username':<30} {'Created':<22} {'Last login':<22} {'OIDC'}")
    print("-" * 90)
    for u in users:
        last_login = u.last_login_at.strftime("%Y-%m-%d %H:%M UTC") if u.last_login_at else "never"
        created = u.created_at.strftime("%Y-%m-%d %H:%M UTC")
        oidc = f"yes ({u.oidc_issuer})" if u.oidc_sub else "no"
        print(f"{u.username:<30} {created:<22} {last_login:<22} {oidc}")
    print()


async def _reset_password(username: str, new_password: str) -> bool:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import settings
    from app.models.user import AdminUser
    from app.services.auth import hash_password

    engine = create_async_engine(settings.database_url, echo=False, hide_parameters=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        result = await session.execute(
            select(AdminUser).where(AdminUser.username == username)
        )
        user = result.scalar_one_or_none()

        if user is None:
            print(f"\n  Error: No admin user '{username}' found.", file=sys.stderr)
            print("  Run with --list to see all admin users.\n", file=sys.stderr)
            await engine.dispose()
            return False

        if user.oidc_sub and not user.password_hash:
            print(
                f"\n  Warning: '{username}' is an OIDC-only account.",
                file=sys.stderr,
            )
            print(
                "  Setting a password will also enable local login for this account.\n",
                file=sys.stderr,
            )

        user.password_hash = hash_password(new_password)
        await session.commit()

    await engine.dispose()
    return True


async def _reset_totp(username: str) -> tuple[str, str] | None:
    """Give ``username`` a new TOTP secret; return (secret, otpauth URI).

    Enrolled at once (the operator hands the secret over), so the next login
    asks for a code from it. Every session and pending login of the account
    ends, and the audit log records it. Works for any role, the last
    superadmin included: this is the way back in when no one else can help.
    """
    from redis.asyncio import from_url
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import settings
    from app.models.user import AdminUser
    from app.services import audit
    from app.services.auth import revoke_user_sessions
    from app.services.mfa import get_provisioning_uri
    from app.services.users import require_new_authenticator

    engine = create_async_engine(settings.database_url, echo=False, hide_parameters=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        result = await session.execute(select(AdminUser).where(AdminUser.username == username))
        user = result.scalar_one_or_none()
        if user is None:
            print(f"\n  Error: No admin user '{username}' found.", file=sys.stderr)
            print("  Run with --list to see all admin users.\n", file=sys.stderr)
            await engine.dispose()
            return None

        secret = require_new_authenticator(user)
        user.totp_enabled = True
        await audit.log_system(
            session, audit.AuditAction.ADMIN_TOTP_RESET,
            detail={"username": user.username, "via": "command line"}, org_id=user.org_id,
        )
        await session.commit()
        user_id = str(user.id)

    await engine.dispose()

    redis = await from_url(settings.redis_url, decode_responses=True)
    try:
        await revoke_user_sessions(redis, user_id)
    finally:
        await redis.aclose()
    return secret, get_provisioning_uri(secret, username)


# Printed instead of the validator's message: no value derived from the
# password ever reaches print() (keeps CodeQL's taint tracking quiet).
_POLICY = "Password must be at least 12 characters and at most 72 bytes."


def _password_allowed(password: str) -> bool:
    """The same policy as the setup wizard and admin-created users."""
    from app.services.auth import validate_password

    try:
        validate_password(password)
    except ValueError:
        return False
    return True


def _prompt_password() -> str:
    """Prompt for a new password twice, validate strength, return confirmed value."""
    while True:
        pw1 = getpass.getpass("  New password: ")
        # Each print() argument is a string literal — no variable derived from pw1
        # ever appears in a print() call, severing any CodeQL taint flow.
        if not _password_allowed(pw1):
            print(f"  ✗ {_POLICY}")
            continue
        pw2 = getpass.getpass("  Confirm password: ")
        if pw1 != pw2:
            print("  ✗ Passwords do not match. Try again.\n")
            continue
        return pw1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reset an OpenWhistle admin user's password.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--username", "-u", metavar="USERNAME", help="Admin username to update")
    group.add_argument("--list", "-l", action="store_true", help="List all admin users")
    group.add_argument(
        "--reset-totp", metavar="USERNAME",
        help="Give USERNAME a new authenticator secret (lost authenticator app)",
    )
    parser.add_argument(
        "--password",
        "-p",
        metavar="PASSWORD",
        help="New password (omit to be prompted interactively)",
    )
    args = parser.parse_args()

    if args.list:
        asyncio.run(_list_users())
        return

    if args.reset_totp:
        print("\n  Connecting to database…")
        reset = asyncio.run(_reset_totp(args.reset_totp))
        if reset is None:
            sys.exit(1)
        secret, uri = reset
        print(f"  ✓ New authenticator secret for '{args.reset_totp}', shown this once:\n")
        print(f"    Secret: {secret}")
        print(f"    URI:    {uri}\n")
        print("  Enter the secret in the authenticator app, or turn the URI into a QR code.")
        print("  The old app no longer works; every session of this account has ended.\n")
        sys.exit(0)

    username: str = args.username

    if args.password:
        # Each print() argument is a string literal — no variable derived from
        # args.password appears in any print() call, severing the CodeQL taint flow.
        if not _password_allowed(args.password):
            print(f"\n  Error: {_POLICY}\n", file=sys.stderr)
            sys.exit(1)
        new_password = args.password
    else:
        print(f"\nResetting password for admin user: {username}")
        print(f"{_POLICY}\n")
        new_password = _prompt_password()

    print("\n  Connecting to database…")
    success = asyncio.run(_reset_password(username, new_password))

    if success:
        print(f"  ✓ Password for '{username}' updated successfully.")
        print("  The TOTP secret is unchanged — your authenticator app still works.")
        print("  Lost the authenticator? Run with --reset-totp USERNAME.\n")
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
