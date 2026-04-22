"""CSRF protection using the Double-Submit Cookie pattern."""

import secrets

from fastapi import Cookie, Form, HTTPException, status
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_CSRF_COOKIE = "ow_csrf"
_TOKEN_BYTES = 32


class CSRFMiddleware:
    """Pure ASGI middleware: sets CSRF cookie and injects token into request.state."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        raw_headers: list[tuple[bytes, bytes]] = scope.get("headers", [])
        cookie_header = b""
        for name, value in raw_headers:
            if name.lower() == b"cookie":
                cookie_header = value
                break

        token = _parse_cookie(cookie_header.decode("latin-1"), _CSRF_COOKIE)
        if not token:
            token = secrets.token_urlsafe(_TOKEN_BYTES)

        if "state" not in scope:
            scope["state"] = {}
        scope["state"]["csrf_token"] = token

        async def send_with_csrf(message: Message) -> None:
            if message["type"] == "http.response.start":
                mutable = MutableHeaders(scope=message)
                mutable.append(
                    "set-cookie",
                    f"{_CSRF_COOKIE}={token}; Path=/; SameSite=Lax; HttpOnly",
                )
            await send(message)

        await self.app(scope, receive, send_with_csrf)


def _parse_cookie(header: str, name: str) -> str | None:
    for part in header.split(";"):
        stripped = part.strip()
        if stripped.startswith(f"{name}="):
            return stripped[len(f"{name}="):]
    return None


async def validate_csrf(
    csrf_token: str = Form(...),
    ow_csrf: str | None = Cookie(None),
) -> None:
    """Dependency: validates CSRF double-submit token on state-changing form submissions."""
    if not ow_csrf or not secrets.compare_digest(csrf_token, ow_csrf):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF validation failed.",
        )
