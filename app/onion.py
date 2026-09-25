"""Whether a request reached OpenWhistle over the Tor onion listener.

The onion service (`nginx/nginx.conf`'s `listen 8080;` block) is plain HTTP
from nginx's perspective — Tor already encrypts end to end — and is reachable
only from the host's own Tor daemon. A visitor already there must not be
offered the same `Onion-Location` again, must not receive an HSTS header for a
connection that was never TLS, and a `Secure`-flagged cookie sent over that
plain-HTTP connection may be silently refused by the browser, breaking every
CSRF-protected POST. All three answer the same question — so it is answered
here once instead of drifting across `middleware.py`, `csrf.py` and every
route that sets a cookie.

Trust: **never the client-supplied Host header.** A client on the real TLS
listener can send any Host it likes (`Host: <56 chars>.onion`), and nginx's
`server_name _;` catch-all forwards it unchanged — trusting Host would let
that client get non-Secure cookies and no HSTS on a connection that genuinely
is TLS. Instead, nginx itself asserts which listener served the request via
the `X-OW-Onion` header: `nginx/snippets/proxy-headers.conf` clears it
(`proxy_set_header X-OW-Onion "";`) for both server blocks, and the onion
(8080) block sets it back to `"1"` afterwards — the same override-after-`
include` pattern already used to strip the IP-forwarding headers, so neither
block can forget it (see `nginx/nginx.conf`). This means the app port itself
must be reachable only through the shipped nginx, exactly as already required
for IP-header stripping — a deployment that talks to the app directly must
set or clear this header itself (see docs "Offering an onion address").
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.config import settings

if TYPE_CHECKING:
    from fastapi import Request

# nginx-only header (see module docstring): "1" on the onion listener,
# cleared (never forwarded from a client) everywhere else.
_ONION_HEADER = "x-ow-onion"


def is_onion_request(headers: list[tuple[bytes, bytes]]) -> bool:
    """True when nginx marked this request as arriving via the onion listener."""
    return raw_header(_ONION_HEADER, headers) == "1"


def raw_header(name: str, headers: list[tuple[bytes, bytes]]) -> str:
    """Extract a header's value from raw ASGI scope headers, or "" if absent."""
    lname = name.lower()
    for hname, hvalue in headers:
        if hname.decode("latin-1").lower() == lname:
            return hvalue.decode("latin-1")
    return ""


def cookie_secure(request: Request) -> bool:
    """Whether a Set-Cookie for this request should carry ``Secure``.

    ``SECURE_COOKIES`` still governs every ordinary request; the onion
    listener is the one case where True must not be honoured, since the
    connection was never TLS and a browser can refuse to store the cookie,
    silently breaking the whistleblower-facing form it was meant to protect.
    Reads the single decision ``SecurityMiddleware`` already made for this
    request (``request.state.is_onion``) strictly — no fallback — so that a
    wiring bug (``SecurityMiddleware`` not registered) raises immediately
    instead of silently falling back to a guess.
    """
    return settings.secure_cookies and not request.state.is_onion
