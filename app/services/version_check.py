"""Update check — one static feed with the latest release and the security advisories.

Privacy: on by default, off with ``UPDATE_CHECK_ENABLED=false``. Once a day the
server fetches ``https://openwhistle.net/security.json``, a static file whose
host logs nothing. The request carries **no instance or report data** — a
plain GET with a User-Agent of ``OpenWhistle``, no version; the site sees the
server's IP address. The feed is cached in Redis by a daily background job, so
admin page rendering never makes an outbound call. Which advisories affect the
running version is decided when a page is rendered, so an upgrade clears the
notice without a refetch.

The feed is untrusted input: anything that does not match schema 1 is dropped
(docs-tech/security-feed.md).
"""

from __future__ import annotations

import json
import logging
import operator
import re
from typing import Any

from redis.asyncio import Redis

log = logging.getLogger(__name__)

SECURITY_FEED_URL = "https://openwhistle.net/security.json"
_CACHE_KEY = "openwhistle:update_check"
_ADVISORIES_KEY = "openwhistle:update_check_advisories"
_ETAG_KEY = "openwhistle:update_check_etag"
_LOCK_KEY = "openwhistle:job_lock:update_check"
_CACHE_TTL = 7 * 24 * 3600  # 7-day fallback; the daily job keeps it fresh
_SEVERITIES = frozenset({"low", "medium", "high", "critical"})
_MAX_ADVISORIES = 100
_MAX_SUMMARY = 300
_MAX_CVES = 10
_MAX_RANGE = 200


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


_VERSION = re.compile(r"[vV]?\d{1,6}(?:\.\d{1,6}){0,3}")
_OPS = {"<=": operator.le, "<": operator.lt, ">=": operator.ge, ">": operator.gt, "=": operator.eq}
_ADVISORY_ID = re.compile(r"[A-Za-z0-9-]{1,64}")
_CVE_ID = re.compile(r"CVE-\d{4}-\d{4,7}")


def _constraints(vulnerable_range: str) -> list[tuple[str, str]] | None:
    """Each comma-separated constraint as (operator, version); None when any does not parse.

    No regex around the whitespace: the range comes from the feed, and ``\\s*`` beside an
    optional operator backtracks polynomially (CodeQL py/polynomial-redos)."""
    if len(vulnerable_range) > _MAX_RANGE:
        return None
    parsed = []
    for raw in vulnerable_range.split(","):
        rest = raw.strip()
        op = next((o for o in ("<=", ">=", "<", ">", "=") if rest.startswith(o)), "=")
        if rest.startswith(op):
            rest = rest[len(op) :].lstrip()
        if not _VERSION.fullmatch(rest):
            return None
        parsed.append((op, rest))
    return parsed


def version_in_range(version: str, vulnerable_range: str) -> bool:
    """True when ``version`` meets every constraint of an advisory range.

    The range is GitHub's syntax: comma-separated constraints such as ``<= 2.4.1``
    or ``>= 1.4.0, < 2.4.2``. Anything that does not parse matches nothing: a
    garbled range must not raise a false alarm.
    """
    constraints = _constraints(vulnerable_range)
    if constraints is None:
        return False
    current = parse_version(version)
    for op, raw_bound in constraints:
        bound = parse_version(raw_bound)
        width = max(len(current), len(bound))  # 2.4 == 2.4.0
        cur = current + (0,) * (width - len(current))
        bound += (0,) * (width - len(bound))
        if not _OPS[op](cur, bound):
            return False
    return True


def _https(url: Any) -> str:
    """The URL when it is an https link, else empty: only those are rendered as links."""
    return url if isinstance(url, str) and url.startswith("https://") and len(url) <= 500 else ""


def _text(value: Any, limit: int) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _latest(raw: Any) -> dict[str, str] | None:
    """The feed's ``latest`` entry, or None when it is missing or garbled."""
    if not isinstance(raw, dict):
        return None
    version = raw.get("version")
    if not isinstance(version, str) or not _VERSION.fullmatch(version):
        return None
    return {
        "tag_name": version,
        "html_url": _https(raw.get("url")),
        "published_at": _text(raw.get("published_at"), 40),
    }


def _advisory(raw: Any) -> dict[str, Any] | None:
    """One feed advisory with only the fields shown, or None when a required one is garbled."""
    if not isinstance(raw, dict):
        return None
    adv_id, affected, fixed = raw.get("id"), raw.get("affected"), raw.get("fixed", "")
    summary = _text(raw.get("summary"), _MAX_SUMMARY)
    if (
        not isinstance(adv_id, str)
        or not _ADVISORY_ID.fullmatch(adv_id)
        or not summary
        or not isinstance(affected, str)
        or _constraints(affected) is None
        or not isinstance(fixed, str)
        or (fixed and not _VERSION.fullmatch(fixed))
    ):
        return None
    cves = raw.get("cve_ids")
    severity = raw.get("severity")
    return {
        "id": adv_id,
        "cve_ids": [c for c in cves if isinstance(c, str) and _CVE_ID.fullmatch(c)][:_MAX_CVES]
        if isinstance(cves, list)
        else [],
        "summary": summary,
        "severity": severity if severity in _SEVERITIES else "",
        "affected": affected,
        "fixed": fixed,
        "url": _https(raw.get("url")),
    }


async def _read_json(redis: Redis, key: str) -> Any:
    raw = await redis.get(key)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError, TypeError:
        return None


async def _read_cache(redis: Redis) -> dict[str, Any] | None:
    parsed = await _read_json(redis, _CACHE_KEY)
    return parsed if isinstance(parsed, dict) else None


async def _read_advisories(redis: Redis) -> list[dict[str, Any]]:
    parsed = await _read_json(redis, _ADVISORIES_KEY)
    return parsed if isinstance(parsed, list) else []


async def fetch_feed(redis: Redis) -> dict[str, Any] | None:
    """Fetch the security feed (ETag-conditional) and cache what validates.

    Best-effort: on timeout / any error / a feed that is not schema 1, the cached
    release and advisories are kept, and the cached release is returned.
    """
    from datetime import UTC, datetime

    import httpx

    headers = {
        "Accept": "application/json",
        # A User-Agent, not a version: which release runs here is the one fact the
        # installation count asks consent for.
        "User-Agent": "OpenWhistle",
    }
    etag = await redis.get(_ETAG_KEY)
    if etag:
        headers["If-None-Match"] = etag.decode() if isinstance(etag, bytes) else etag

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(SECURITY_FEED_URL, headers=headers)
    except Exception:
        log.exception("Update check: feed request failed; keeping cached result")
        return await _read_cache(redis)

    now_iso = datetime.now(UTC).isoformat()

    if resp.status_code == 304:
        cached = await _read_cache(redis)
        if cached is not None:
            cached["checked_at"] = now_iso
            await redis.set(_CACHE_KEY, json.dumps(cached), ex=_CACHE_TTL)
        return cached

    if resp.status_code != 200:
        log.warning("Update check: feed returned HTTP %s", resp.status_code)
        return await _read_cache(redis)

    try:
        data = resp.json()
    except ValueError:
        data = None
    if not isinstance(data, dict) or data.get("schema") != 1:
        log.warning("Update check: feed is not schema 1; keeping cached result")
        return await _read_cache(redis)

    advisories = data.get("advisories")
    if isinstance(advisories, list):
        kept = [a for a in map(_advisory, advisories[:_MAX_ADVISORIES]) if a is not None]
        await redis.set(_ADVISORIES_KEY, json.dumps(kept), ex=_CACHE_TTL)
    latest = _latest(data.get("latest"))
    if latest is None:
        log.warning("Update check: feed names no valid latest release")
        return await _read_cache(redis)
    payload: dict[str, Any] = {**latest, "checked_at": now_iso}
    await redis.set(_CACHE_KEY, json.dumps(payload), ex=_CACHE_TTL)
    new_etag = resp.headers.get("ETag")
    if new_etag:
        await redis.set(_ETAG_KEY, new_etag, ex=_CACHE_TTL)
    return payload


def affecting(advisories: list[dict[str, Any]], version: str) -> list[dict[str, Any]]:
    """The cached advisories whose range contains ``version``."""
    return [a for a in advisories if version_in_range(version, str(a.get("affected", "")))]


def _fixed_in(advisories: list[dict[str, Any]]) -> str:
    """The highest fixing release among ``advisories``; empty while none has a fix."""
    fixes = [str(a["fixed"]) for a in advisories if a.get("fixed")]
    return max(fixes, key=parse_version, default="")


async def get_update_status(redis: Redis, current_version: str) -> dict[str, Any]:
    """Read-only status for the admin pages — built from cache, no network call."""
    from app.config import settings

    cached = await _read_cache(redis)
    status: dict[str, Any] = {
        "enabled": settings.update_check_enabled,
        "current": current_version,
        "latest": None,
        "status": "unknown",
        "html_url": "",
        "checked_at": None,
        "advisories": [],
        "fixed_in": "",
    }
    if settings.update_check_enabled:
        # Matched now, not when fetched: after an upgrade the notice is gone at once.
        status["advisories"] = affecting(await _read_advisories(redis), current_version)
        status["fixed_in"] = _fixed_in(status["advisories"])
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
    """Daily background job: refresh the cached feed.

    Uses a dedicated Redis connection and a best-effort distributed lock so that
    scaled/stateless replicas do not all fetch it (mirrors the retention job).
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
        await fetch_feed(redis)
    finally:
        if acquired:
            try:
                await redis.delete(_LOCK_KEY)
            except Exception:  # noqa: BLE001, S110
                pass
        await redis.aclose()
