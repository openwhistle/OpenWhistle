"""Security middleware: IP detection warning, security headers, no IP logging."""

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

_SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "0",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "font-src 'self'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none';"
    ),
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains; preload",
}


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
                for name, value in _SECURITY_HEADERS.items():
                    mutable[name] = value
                mutable.update(_SECURITY_HEADERS)
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
