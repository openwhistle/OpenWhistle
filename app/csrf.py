"""CSRF protection using the Double-Submit Cookie pattern."""

import secrets

from fastapi import Cookie, Form, Header, HTTPException, status
from starlette.datastructures import MutableHeaders
from starlette.requests import cookie_parser
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import settings
from app.onion import is_onion_request

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

        # Starlette's parser, the one Cookie() below reads through: with two
        # ow_csrf cookies this used to take the first and the check the last,
        # so every form on the page was refused.
        token = cookie_parser(cookie_header.decode("latin-1")).get(_CSRF_COOKIE)
        if not token:
            token = secrets.token_urlsafe(_TOKEN_BYTES)

        if "state" not in scope:
            scope["state"] = {}
        scope["state"]["csrf_token"] = token
        # Same question the Onion-Location header answers (app/onion.py): a
        # Secure cookie set over the onion listener's plain-HTTP connection
        # can be silently refused by the browser, which would break every
        # CSRF-protected POST — exactly the submissions this feature exists
        # to protect. Computed independently of SecurityMiddleware's own
        # is_onion (rather than reading request.state) since this middleware
        # can run before it and must not depend on that ordering. Trusts only
        # the nginx-asserted X-OW-Onion header, never the client-supplied
        # Host — see app/onion.py.
        is_onion = is_onion_request(raw_headers)

        async def send_with_csrf(message: Message) -> None:
            if message["type"] == "http.response.start":
                mutable = MutableHeaders(scope=message)
                secure = "; Secure" if (settings.secure_cookies and not is_onion) else ""
                mutable.append(
                    "set-cookie",
                    f"{_CSRF_COOKIE}={token}; Path=/; SameSite=Lax; HttpOnly{secure}",
                )
            await send(message)

        await self.app(scope, receive, send_with_csrf)


def _same_token(submitted: str | None, cookie: str | None) -> bool:
    # Bytes: compare_digest raises TypeError on non-ASCII str, which made a
    # forged token a 500 instead of a 403.
    if not submitted or not cookie:
        return False
    return secrets.compare_digest(submitted.encode(), cookie.encode())


async def validate_csrf(
    csrf_token: str = Form(...),
    ow_csrf: str | None = Cookie(None),
) -> None:
    """Dependency: validates CSRF double-submit token on state-changing form submissions."""
    if not _same_token(csrf_token, ow_csrf):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF validation failed.",
        )


async def validate_csrf_header(
    x_csrf_token: str | None = Header(None),
    ow_csrf: str | None = Cookie(None),
) -> None:
    """CSRF validation for fetch/AJAX endpoints (no form body).

    The token arrives in the ``X-CSRF-Token`` header — JavaScript reads it from
    the ``<meta name="csrf-token">`` tag since the double-submit cookie is
    HttpOnly. Same double-submit comparison against the ``ow_csrf`` cookie.
    """
    if not _same_token(x_csrf_token, ow_csrf):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF validation failed.",
        )
