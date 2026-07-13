"""Update check — optional, opt-in check against the GitHub Releases API.

Privacy: the check is disabled by default (``UPDATE_CHECK_ENABLED``). When
enabled it performs a single GET to GitHub's public "latest release" endpoint;
it sends **no instance or report data** — only a standard HTTP request (the
server's own IP + a User-Agent). The result is cached in Redis and refreshed by
a daily background job, so admin page rendering never makes an outbound call.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from redis.asyncio import Redis

log = logging.getLogger(__name__)

GITHUB_LATEST_RELEASE_URL = (
    "https://api.github.com/repos/openwhistle/OpenWhistle/releases/latest"
)
_CACHE_KEY = "openwhistle:update_check"
_ETAG_KEY = "openwhistle:update_check_etag"
_LOCK_KEY = "openwhistle:job_lock:update_check"
_CACHE_TTL = 7 * 24 * 3600  # 7-day fallback; the daily job keeps it fresh


def parse_version(v: str) -> tuple[int, ...]:
    """Parse a semver-ish string (``v1.2.3``, ``1.2.3-rc1``) into an int tuple.

    Any pre-release / build suffix is dropped so ``1.2.3`` and ``1.2.3-rc1``
    compare as equal cores; non-numeric junk stops parsing.
    """
    core = v.strip().lstrip("vV").split("-")[0].split("+")[0]
    parts: list[int] = []
    for p in core.split("."):
        if not p.isdigit():
            break
        parts.append(int(p))
    return tuple(parts) or (0,)


def compare_versions(current: str, latest: str) -> str:
    """Return ``update_available`` | ``up_to_date`` | ``ahead``."""
    cur, lat = parse_version(current), parse_version(latest)
    if lat > cur:
        return "update_available"
    if lat < cur:
        return "ahead"
    return "up_to_date"


async def _read_cache(redis: Redis) -> dict[str, Any] | None:
    raw = await redis.get(_CACHE_KEY)
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


async def fetch_latest_release(redis: Redis) -> dict[str, Any] | None:
    """Fetch the latest GitHub release (ETag-conditional) and cache it.

    Best-effort: on timeout / rate-limit / any error the existing cached result
    is kept and returned rather than raising.
    """
    from datetime import UTC, datetime

    import httpx

    from app.config import settings

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"OpenWhistle/{settings.app_version}",
    }
    etag = await redis.get(_ETAG_KEY)
    if etag:
        # A 304 for an unchanged resource does not count against the rate limit.
        headers["If-None-Match"] = etag

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(GITHUB_LATEST_RELEASE_URL, headers=headers)
    except Exception:
        log.exception("Update check: GitHub request failed; keeping cached result")
        return await _read_cache(redis)

    now_iso = datetime.now(UTC).isoformat()

    if resp.status_code == 304:
        cached = await _read_cache(redis)
        if cached is not None:
            cached["checked_at"] = now_iso
            await redis.setex(_CACHE_KEY, _CACHE_TTL, json.dumps(cached))
        return cached

    if resp.status_code != 200:
        log.warning("Update check: GitHub returned HTTP %s", resp.status_code)
        return await _read_cache(redis)

    data = resp.json()
    payload: dict[str, Any] = {
        "tag_name": data.get("tag_name", ""),
        "html_url": data.get("html_url", ""),
        "published_at": data.get("published_at", ""),
        "checked_at": now_iso,
    }
    await redis.setex(_CACHE_KEY, _CACHE_TTL, json.dumps(payload))
    new_etag = resp.headers.get("ETag")
    if new_etag:
        await redis.setex(_ETAG_KEY, _CACHE_TTL, new_etag)
    return payload


async def get_update_status(redis: Redis, current_version: str) -> dict[str, Any]:
    """Read-only status for the admin page — built from cache, no network call."""
    from app.config import settings

    cached = await _read_cache(redis)
    status: dict[str, Any] = {
        "enabled": settings.update_check_enabled,
        "current": current_version,
        "latest": None,
        "status": "unknown",
        "html_url": "",
        "checked_at": None,
    }
    if cached and cached.get("tag_name"):
        latest = cached["tag_name"]
        status.update(
            latest=latest,
            status=compare_versions(current_version, latest),
            html_url=cached.get("html_url", ""),
            checked_at=cached.get("checked_at"),
        )
    return status


async def refresh_update_check() -> None:
    """Daily background job: refresh the cached latest-release info.

    Uses a dedicated Redis connection and a best-effort distributed lock so that
    scaled/stateless replicas do not all poll GitHub (mirrors the retention job).
    """
    from app.config import settings

    if not settings.update_check_enabled:
        return

    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    acquired = False
    try:
        try:
            acquired = bool(await redis.set(_LOCK_KEY, "1", nx=True, ex=300))
            if not acquired:
                return
        except Exception:  # noqa: BLE001
            log.warning("Update-check lock unavailable; proceeding without it")
        await fetch_latest_release(redis)
    finally:
        if acquired:
            try:
                await redis.delete(_LOCK_KEY)
            except Exception:  # noqa: BLE001, S110
                pass
        await redis.aclose()
