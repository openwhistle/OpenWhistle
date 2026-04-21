"""Security middleware: IP detection warning, security headers, no IP logging."""

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

# Headers that indicate an upstream proxy is forwarding IP information.
# Their presence means IP data is flowing into our stack — we must warn the admin.
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


class SecurityMiddleware(BaseHTTPMiddleware):
    """Applies security headers and detects upstream IP leakage."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Detect IP-leaking headers from upstream proxies.
        # We do NOT read the values — we only note their presence.
        ip_headers_present = any(
            h in _IP_REVEAL_HEADERS for h in (k.lower() for k in request.headers.keys())
        )

        if ip_headers_present:
            try:
                from app.redis_client import get_redis

                redis = await get_redis()
                await redis.set(_REDIS_IP_WARNING_KEY, "1")
            except Exception:  # noqa: BLE001, S110
                pass  # Non-fatal — warning storage is best-effort

        response = await call_next(request)

        # Security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "0"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=()"
        )
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "font-src 'self'; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "frame-ancestors 'none';"
        )
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains; preload"
        )
        # Explicitly remove any server identification
        if "server" in response.headers:
            del response.headers["server"]
        if "x-powered-by" in response.headers:
            del response.headers["x-powered-by"]

        return response  # type: ignore[return-value]


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
