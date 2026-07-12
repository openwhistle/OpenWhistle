"""Security middleware: IP detection warning, security headers, no IP logging."""

import secrets

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

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
_STATIC_SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "0",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains; preload",
}


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

        async def send_with_security(message: Message) -> None:
            if message["type"] == "http.response.start":
                mutable = MutableHeaders(scope=message)
                for name, value in _STATIC_SECURITY_HEADERS.items():
                    mutable[name] = value
                mutable["Content-Security-Policy"] = _build_csp(nonce)
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
