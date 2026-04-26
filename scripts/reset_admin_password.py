#!/usr/bin/env python3
"""Management script: reset an admin user's password.

Usage
-----
    # Interactive (prompts for new password):
    python scripts/reset_admin_password.py --username admin

    # Non-interactive (CI / automation):
    python scripts/reset_admin_password.py --username admin --password "NewPass123!"

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

    engine = create_async_engine(settings.database_url, echo=False)
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

    engine = create_async_engine(settings.database_url, echo=False)
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


def _prompt_password() -> str:
    """Prompt for a new password twice, validate strength, return confirmed value."""
    while True:
        pw1 = getpass.getpass("  New password: ")
        # Each print() argument is a string literal — no variable derived from pw1
        # ever appears in a print() call, severing any CodeQL taint flow.
        if len(pw1) < 12:
            print("  ✗ Password must be at least 12 characters.")
            continue
        if not any(c.isupper() for c in pw1):
            print("  ✗ Password must contain at least one uppercase letter.")
            continue
        if not any(c.islower() for c in pw1):
            print("  ✗ Password must contain at least one lowercase letter.")
            continue
        if not any(c.isdigit() for c in pw1):
            print("  ✗ Password must contain at least one digit.")
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

    username: str = args.username

    if args.password:
        # Each print() argument is a string literal — no variable derived from
        # args.password appears in any print() call, severing the CodeQL taint flow.
        if len(args.password) < 12:
            print("\n  Error: Password must be at least 12 characters.\n", file=sys.stderr)
            sys.exit(1)
        if not any(c.isupper() for c in args.password):
            print("\n  Error: Password must contain at least one uppercase letter.\n",
                  file=sys.stderr)
            sys.exit(1)
        if not any(c.islower() for c in args.password):
            print("\n  Error: Password must contain at least one lowercase letter.\n",
                  file=sys.stderr)
            sys.exit(1)
        if not any(c.isdigit() for c in args.password):
            print("\n  Error: Password must contain at least one digit.\n", file=sys.stderr)
            sys.exit(1)
        new_password = args.password
    else:
        print(f"\nResetting password for admin user: {username}")
        print("Password requirements: ≥12 chars, upper + lower + digit\n")
        new_password = _prompt_password()

    print("\n  Connecting to database…")
    success = asyncio.run(_reset_password(username, new_password))

    if success:
        print(f"  ✓ Password for '{username}' updated successfully.")
        print("  The TOTP secret is unchanged — your authenticator app still works.\n")
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
