"""Security middleware: IP detection warning, security headers, no IP logging."""

import secrets

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.onion import is_onion_request

# Headers that indicate an upstream proxy is forwarding IP information.
_IP_REVEAL_HEADERS = frozenset(
    [
        "x-forwarded-for",
        "x-real-ip",
        "forwarded",
        "x-client-ip",
        "x-cluster-client-ip",
        "true-client-ip",
        "cf-connecting-ip",  # Cloudflare
    ]
)

_REDIS_IP_WARNING_KEY = "openwhistle:ip_headers_detected"

# Static headers that never vary per request. The Content-Security-Policy is
# built per request in _build_csp() because it carries a per-response nonce.
# Strict-Transport-Security is added separately (see send_with_security) —
# RFC 6797 forbids sending it over a connection that was never TLS, which the
# plain-HTTP onion listener never is.
_STATIC_SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "0",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
}
_HSTS = "max-age=31536000; includeSubDomains; preload"


def _build_csp(nonce: str) -> str:
    """Strict Content-Security-Policy with no 'unsafe-inline'.

    Inline <script>/<style> blocks are allowed only when they carry the
    matching per-response nonce; inline event-handler attributes and inline
    style="" attributes are forbidden by the policy (they carry no nonce), so
    all interactivity/styling must live in nonce'd blocks, external files, or
    be applied via the CSSOM.
    """
    return (
        "default-src 'self'; "
        f"script-src 'self' 'nonce-{nonce}'; "
        f"style-src 'self' 'nonce-{nonce}'; "
        "font-src 'self'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "object-src 'none'; "
        "frame-ancestors 'none';"
    )


class SecurityMiddleware:
    """Pure ASGI middleware: security headers + upstream IP-leakage detection.

    Implemented as a raw ASGI callable (not BaseHTTPMiddleware) to avoid anyio
    task-group issues when tests run with different event loops per test function.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Per-response CSP nonce, exposed to templates via request.state so that
        # inline <script>/<style> blocks can carry nonce="{{ request.state.csp_nonce }}".
        nonce = secrets.token_urlsafe(16)
        state = scope.get("state")
        if state is None:
            state = {}
            scope["state"] = state
        state["csp_nonce"] = nonce

        # scope["headers"] is list[tuple[bytes, bytes]] in the ASGI spec
        raw_headers: list[tuple[bytes, bytes]] = list(scope.get("headers", []))
        # nginx-asserted, never the client-supplied Host — see app/onion.py.
        # Every onion-aware decision below — Onion-Location, HSTS, and (via
        # app.onion.cookie_secure, reused from request.state) every Set-Cookie
        # — answers the same question from the same value instead of drifting.
        is_onion = is_onion_request(raw_headers)
        state["is_onion"] = is_onion
        ip_headers_present = any(
            name.decode("latin-1").lower() in _IP_REVEAL_HEADERS
            for name, _ in raw_headers
        )

        if ip_headers_present:
            try:
                from app.redis_client import get_redis

                redis = await get_redis()
                await redis.set(_REDIS_IP_WARNING_KEY, "1")
            except Exception:  # noqa: BLE001, S110
                pass
            # Noted above; now gone, so no handler, error report or log line
            # further down can ever see a whistleblower's address.
            scope["headers"] = [
                (name, value) for name, value in raw_headers
                if name.decode("latin-1").lower() not in _IP_REVEAL_HEADERS
            ]
        # The peer address is the proxy's at best, the whistleblower's at worst.
        scope["client"] = None

        async def send_with_security(message: Message) -> None:
            if message["type"] == "http.response.start":
                mutable = MutableHeaders(scope=message)
                for name, value in _STATIC_SECURITY_HEADERS.items():
                    mutable[name] = value
                mutable["Content-Security-Policy"] = _build_csp(nonce)
                # RFC 6797 §8.1: an HSTS host MUST NOT send this header over a
                # connection that was not secure — the onion listener never is.
                if not is_onion:
                    mutable["Strict-Transport-Security"] = _HSTS
                from app.config import settings  # noqa: PLC0415

                # Onion-Location is a page-navigation hint (Tor Browser acts on
                # it only for a top-level document load): scope to HTML so a
                # JSON endpoint like /health never carries it — this also
                # covers every /static/ asset (css/js/images/fonts), none of
                # which are ever served as text/html, without a second check.
                content_type = mutable.get("content-type", "")
                if (
                    settings.onion_location
                    and not is_onion
                    and content_type.lower().startswith("text/html")
                ):
                    mutable["Onion-Location"] = (
                        settings.onion_location.rstrip("/") + str(scope.get("path", "/"))
                    )
                # A PIN, a report or an attachment must not be left in the browser
                # cache of a shared office computer for the next user to find.
                if not str(scope.get("path", "")).startswith("/static/"):
                    mutable["Cache-Control"] = "no-store"
                # Remove server identification headers
                for h in ("server", "x-powered-by"):
                    if h in mutable:
                        del mutable[h]
            await send(message)

        await self.app(scope, receive, send_with_security)


async def check_ip_warning() -> bool:
    """Returns True if IP-leaking headers have been detected since last reset."""
    try:
        from app.redis_client import get_redis

        redis = await get_redis()
        return bool(await redis.exists(_REDIS_IP_WARNING_KEY) == 1)
    except Exception:
        return False


async def clear_ip_warning() -> None:
    """Clears the IP warning flag (admin action after fixing proxy config)."""
    try:
        from app.redis_client import get_redis

        redis = await get_redis()
        await redis.delete(_REDIS_IP_WARNING_KEY)
    except Exception:  # noqa: BLE001, S110
        pass
