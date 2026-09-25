"""Whether a request reached OpenWhistle over the Tor onion listener.

The onion service (`nginx/nginx.conf`'s `listen 8080;` block) is plain HTTP
from nginx's perspective — Tor already encrypts end to end — and is reachable
only from the host's own Tor daemon. A visitor already there must not be
offered the same `Onion-Location` again, must not receive an HSTS header for a
connection that was never TLS, and a `Secure`-flagged cookie sent over that
plain-HTTP connection may be silently refused by the browser, breaking every
CSRF-protected POST. All three answer the same question — does this request's
Host header already end in ``.onion``? — so it is answered here once instead
of drifting across `middleware.py`, `csrf.py` and every route that sets a
cookie.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.config import settings

if TYPE_CHECKING:
    from fastapi import Request


def is_onion_host(host: str) -> bool:
    """True when ``host`` (a request's Host header) is itself an onion address."""
    return host.lower().endswith(".onion")


def raw_host_header(headers: list[tuple[bytes, bytes]]) -> str:
    """Extract the Host header from raw ASGI scope headers."""
    for name, value in headers:
        if name.decode("latin-1").lower() == "host":
            return value.decode("latin-1")
    return ""


def cookie_secure(request: Request) -> bool:
    """Whether a Set-Cookie for this request should carry ``Secure``.

    ``SECURE_COOKIES`` still governs every ordinary host; the onion Host is
    the one case where True must not be honoured, since the connection was
    never TLS and a browser can refuse to store the cookie, silently breaking
    the whistleblower-facing form it was meant to protect. Reads the single
    decision ``SecurityMiddleware`` already made for this request
    (``request.state.is_onion``, the same value the Onion-Location and HSTS
    skips use) rather than re-deriving it, so the answer cannot drift; falls
    back to deriving it directly if that middleware was somehow not run.
    """
    is_onion = getattr(request.state, "is_onion", None)
    if is_onion is None:
        is_onion = is_onion_host(request.headers.get("host", ""))
    return settings.secure_cookies and not is_onion
