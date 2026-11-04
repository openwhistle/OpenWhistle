"""The update check reads one feed, openwhistle.net/security.json (docs-tech/security-feed.md),
and tells the admins who can update the instance when the running version is affected by a
published security advisory. On by default since 2.5.0."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, settings
from app.models.user import AdminRole
from app.services import version_check as vc
from tests.test_v210_bug_bounty import _totp_user
from tests.test_version_check import _mock_httpx

# ── The range matcher ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("version", "vulnerable_range", "expected"),
    [
        ("2.4.1", "<= 2.4.1", True),
        ("2.4.2", "<= 2.4.1", False),
        ("2.4.1", "< 2.4.2", True),
        ("2.4.2", "< 2.4.2", False),
        ("1.4.0", ">= 1.4.0", True),
        ("1.3.9", ">= 1.4.0", False),
        ("1.4.1", "> 1.4.0", True),
        ("1.4.0", "> 1.4.0", False),
        ("2.0.0", "= 2.0.0", True),
        ("2.0.1", "= 2.0.0", False),
        ("2.0.0", "2.0.0", True),  # a bare version is an exact one
        ("2.0.0", ">= 1.4.0, < 2.4.2", True),
        ("1.3.0", ">= 1.4.0, < 2.4.2", False),
        ("2.4.2", ">= 1.4.0, < 2.4.2", False),
        ("2.0.0", "  >=1.4.0 ,<2.4.2  ", True),  # whitespace anywhere
        ("v2.0.0", ">= v1.4.0, < v2.4.2", True),  # v prefix on either side
        ("2.4", "= 2.4.0", True),  # 2.4 is 2.4.0
        ("2.4.0", "< 2.4", False),
        ("2.4.1-rc1", "<= 2.4.1", True),  # a pre-release of the release
        ("2.0.0", "", False),
        ("2.0.0", "   ", False),
        ("2.0.0", "garbage", False),
        ("2.0.0", "== 2.0.0", False),
        ("2.0.0", ">= 1.0.0, garbage", False),
        ("2.0.0", ">= 1.0.0,", False),
        ("2.0.0", "~> 2.0", False),
        ("2.0.0", "< 3.0.0-beta", False),
    ],
)
def test_version_in_range(version: str, vulnerable_range: str, expected: bool) -> None:
    assert vc.version_in_range(version, vulnerable_range) is expected


# ── fetch_feed: what validates is cached, the rest is dropped ──────────────

_ADVISORY: dict[str, Any] = {
    "id": "GHSA-aaaa-bbbb-cccc",
    "cve_ids": ["CVE-2026-0001"],
    "summary": "Status page leaks the case number",
    "severity": "high",
    "affected": ">= 1.4.0, < 2.4.2",
    "fixed": "2.4.2",
    "url": "https://github.com/openwhistle/OpenWhistle/security/advisories/GHSA-aaaa-bbbb-cccc",
}
_LATEST = {
    "version": "2.4.2",
    "url": "https://github.com/openwhistle/OpenWhistle/releases/tag/v2.4.2",
    "published_at": "2026-11-01T10:00:00Z",
}


def _feed(*advisories: Any, latest: Any = _LATEST, schema: Any = 1) -> dict[str, Any]:
    return {"schema": schema, "latest": latest, "advisories": list(advisories)}


def _redis(*gets: object) -> AsyncMock:
    redis = AsyncMock()
    redis.get = AsyncMock(side_effect=list(gets))
    redis.set = AsyncMock()
    return redis


def _cached(redis: AsyncMock, key: str) -> Any:
    """What the fetch wrote to Redis under `key`, decoded."""
    for call in redis.set.await_args_list:
        if call.args[0] == key:
            return json.loads(call.args[1])
    raise AssertionError(f"{key} was not written")


async def _fetch(body: Any, redis: AsyncMock | None = None) -> tuple[Any, AsyncMock, Any]:
    redis = redis or _redis(None)  # no prior etag
    client = _mock_httpx(200, etag='W/"feed"')
    client.get.return_value.json = MagicMock(return_value=body)
    with patch("httpx.AsyncClient", return_value=client):
        result = await vc.fetch_feed(redis)
    return result, redis, client


@pytest.mark.asyncio
async def test_the_feed_is_the_only_url_and_carries_nothing_about_the_instance() -> None:
    _, _, client = await _fetch(_feed())
    assert client.get.await_args.args == ("https://openwhistle.net/security.json",)
    headers = client.get.await_args.kwargs["headers"]
    assert headers == {"Accept": "application/json", "User-Agent": "OpenWhistle"}


@pytest.mark.asyncio
async def test_a_valid_feed_caches_the_release_the_advisories_and_the_etag() -> None:
    result, redis, _ = await _fetch(_feed(_ADVISORY))
    assert result["tag_name"] == "2.4.2"
    assert result["html_url"] == _LATEST["url"]
    assert _cached(redis, vc._CACHE_KEY)["tag_name"] == "2.4.2"
    assert _cached(redis, vc._ADVISORIES_KEY) == [_ADVISORY]
    redis.set.assert_any_await(vc._ETAG_KEY, 'W/"feed"', ex=vc._CACHE_TTL)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", None),
        ("id", "GHSA <script>"),
        ("id", "x" * 65),
        ("summary", ""),
        ("summary", 7),
        ("affected", "garbage"),
        ("affected", ">= 1.0.0, nonsense"),
        ("affected", None),
        ("affected", "< 2.0.0, " * 30),  # over 200 characters
        ("fixed", "soon"),
        ("fixed", 2),
    ],
)
@pytest.mark.asyncio
async def test_an_advisory_with_a_garbled_required_field_is_dropped(field: str, value: Any) -> None:
    _, redis, _ = await _fetch(_feed({**_ADVISORY, field: value}, _ADVISORY))
    assert _cached(redis, vc._ADVISORIES_KEY) == [_ADVISORY]


@pytest.mark.asyncio
async def test_optional_fields_that_do_not_validate_are_blanked() -> None:
    odd = {
        **_ADVISORY,
        "url": "javascript:alert(1)",
        "severity": "apocalyptic",
        "cve_ids": ["CVE-2026-0001", "not a cve", 3] + [f"CVE-2026-{n:04d}" for n in range(20)],
        "summary": "s" * 1000,
    }
    del odd["fixed"]
    _, redis, _ = await _fetch(_feed(odd, "not a dict"))
    [adv] = _cached(redis, vc._ADVISORIES_KEY)
    assert (adv["url"], adv["severity"], adv["fixed"]) == ("", "", "")
    assert adv["cve_ids"][0] == "CVE-2026-0001"
    assert len(adv["cve_ids"]) == vc._MAX_CVES
    assert len(adv["summary"]) == vc._MAX_SUMMARY


@pytest.mark.asyncio
async def test_a_plain_http_link_is_not_kept() -> None:
    _, redis, _ = await _fetch(_feed({**_ADVISORY, "url": "http://example.org/x"}))
    assert _cached(redis, vc._ADVISORIES_KEY)[0]["url"] == ""


@pytest.mark.asyncio
async def test_the_list_is_capped() -> None:
    many = [{**_ADVISORY, "id": f"GHSA-{n:04d}-bbbb-cccc"} for n in range(vc._MAX_ADVISORIES + 50)]
    _, redis, _ = await _fetch(_feed(*many))
    assert len(_cached(redis, vc._ADVISORIES_KEY)) == vc._MAX_ADVISORIES


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {**_feed(_ADVISORY), "schema": 2},
        {"latest": _LATEST, "advisories": [_ADVISORY]},  # no schema
        [_ADVISORY],
        None,
    ],
)
async def test_a_feed_that_is_not_schema_1_changes_nothing(body: Any) -> None:
    cached = {"tag_name": "2.4.0", "html_url": "", "checked_at": "t"}
    result, redis, _ = await _fetch(body, _redis(None, json.dumps(cached)))
    assert result == cached
    redis.set.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_body_that_is_not_json_changes_nothing() -> None:
    redis = _redis(None, None)
    client = _mock_httpx(200)
    client.get.return_value.json = MagicMock(side_effect=ValueError("not json"))
    with patch("httpx.AsyncClient", return_value=client):
        assert await vc.fetch_feed(redis) is None
    redis.set.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "latest",
    [None, {"version": "latest"}, {"version": 2}, {"url": "https://x"}, "2.4.2"],
)
async def test_a_garbled_latest_release_keeps_the_cached_one(latest: Any) -> None:
    cached = {"tag_name": "2.4.0", "html_url": "", "checked_at": "t"}
    redis = _redis(None, json.dumps(cached))
    result, redis, _ = await _fetch(_feed(_ADVISORY, latest=latest), redis)
    assert result == cached
    assert _cached(redis, vc._ADVISORIES_KEY) == [_ADVISORY]  # the advisories still count
    assert vc._CACHE_KEY not in [c.args[0] for c in redis.set.await_args_list]


@pytest.mark.asyncio
async def test_a_release_link_that_is_not_https_is_dropped() -> None:
    result, _, _ = await _fetch(_feed(latest={**_LATEST, "url": "javascript:x"}))
    assert result["html_url"] == ""


@pytest.mark.asyncio
async def test_a_feed_without_an_advisories_list_keeps_the_cached_ones() -> None:
    _, redis, _ = await _fetch({"schema": 1, "latest": _LATEST, "advisories": "none"})
    assert vc._ADVISORIES_KEY not in [c.args[0] for c in redis.set.await_args_list]


@pytest.mark.asyncio
async def test_an_empty_advisories_list_clears_the_cached_ones() -> None:
    _, redis, _ = await _fetch(_feed())
    assert _cached(redis, vc._ADVISORIES_KEY) == []


def test_the_check_is_on_by_default() -> None:
    assert Settings.model_fields["update_check_enabled"].default is True


# ── get_update_status: matched at read time ────────────────────────────────

_CACHED = [
    {**_ADVISORY, "id": "GHSA-old", "severity": "low", "affected": "< 2.0.0", "fixed": "2.0.0"},
    {**_ADVISORY, "id": "GHSA-new", "severity": "critical"},
    {**_ADVISORY, "id": "GHSA-nofix", "severity": "", "affected": "<= 2.4.1", "fixed": ""},
]


def _status_redis() -> AsyncMock:
    redis = AsyncMock()
    redis.get = AsyncMock(
        side_effect=lambda key: json.dumps(_CACHED) if key == vc._ADVISORIES_KEY else None
    )
    return redis


@pytest.mark.asyncio
async def test_status_lists_only_the_advisories_of_the_running_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "update_check_enabled", True)

    status = await vc.get_update_status(_status_redis(), "1.9.0")
    assert [a["id"] for a in status["advisories"]] == ["GHSA-old", "GHSA-new", "GHSA-nofix"]
    assert status["fixed_in"] == "2.4.2"

    # After the upgrade the same cache names nothing: no refetch needed.
    status = await vc.get_update_status(_status_redis(), "2.4.2")
    assert status["advisories"] == []
    assert status["fixed_in"] == ""

    status = await vc.get_update_status(_status_redis(), "2.4.1")
    assert [a["id"] for a in status["advisories"]] == ["GHSA-new", "GHSA-nofix"]


@pytest.mark.asyncio
async def test_status_names_no_advisory_while_the_check_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "update_check_enabled", False)
    status = await vc.get_update_status(_status_redis(), "1.9.0")
    assert status["advisories"] == []


def test_fixed_in_compares_versions_not_text() -> None:
    assert vc._fixed_in([{"fixed": "2.10.0"}, {"fixed": "2.9.0"}, {"fixed": ""}]) == "2.10.0"


# ── The pages ──────────────────────────────────────────────────────────────

BANNER = 'id="security-advisory-banner"'
BLOCK = 'id="security-advisories"'


@pytest_asyncio.fixture(loop_scope="function")
async def advisories(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    from app.redis_client import get_redis

    monkeypatch.setattr(settings, "update_check_enabled", True)
    monkeypatch.setattr(settings, "app_version", "2.4.1")
    redis = await get_redis()
    await redis.set(vc._ADVISORIES_KEY, json.dumps(_CACHED[1:]))
    yield
    await redis.delete(vc._ADVISORIES_KEY)


async def _get(acting_as, user, path: str) -> str:  # type: ignore[no-untyped-def]
    client, act = acting_as
    act(user)
    resp = await client.get(path)
    assert resp.status_code == 200
    return resp.text


@pytest.mark.asyncio
async def test_the_system_page_lists_the_advisories_of_an_affected_version(
    acting_as, db_session: AsyncSession, advisories: None
) -> None:
    admin = await _totp_user(db_session, AdminRole.admin)
    page = await _get(acting_as, admin, "/admin/system")
    assert f'<div class="alert alert-error" {BLOCK} role="alert">' in page
    assert "Version v2.4.1 has known security vulnerabilities" in page
    assert "Update to 2.4.2 or later." in page
    assert "Status page leaks the case number" in page
    assert "Critical severity" in page
    assert (
        f'<a href="{_ADVISORY["url"]}" rel="noopener noreferrer" target="_blank">GHSA-new</a>'
        ", CVE-2026-0001."
    ) in page
    assert "Fixed in 2.4.2." in page
    assert "No fixed release yet." in page  # GHSA-nofix
    # While the check runs, the page says what it sends, to whom, and how to stop it.
    assert "<code>openwhistle.net/security.json</code>" in page
    assert "The site sees the server's IP address and logs nothing" in page
    assert "<code>UPDATE_CHECK_ENABLED=false</code> turns it off" in page


@pytest.mark.asyncio
async def test_the_system_page_of_a_fixed_version_names_no_advisory(
    acting_as, db_session: AsyncSession, advisories: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "app_version", "2.4.2")
    admin = await _totp_user(db_session, AdminRole.admin)
    page = await _get(acting_as, admin, "/admin/system")
    assert BLOCK not in page


@pytest.mark.asyncio
async def test_the_disabled_notice_says_what_switching_on_discloses(
    acting_as, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "update_check_enabled", False)
    admin = await _totp_user(db_session, AdminRole.admin)
    page = await _get(acting_as, admin, "/admin/system")
    assert "The update check is off (<code>UPDATE_CHECK_ENABLED=false</code>)" in page
    assert "<code>openwhistle.net/security.json</code>" in page
    assert "The site sees the server's IP address and logs nothing" in page


@pytest.mark.asyncio
async def test_the_dashboard_warns_who_can_update_an_affected_version(
    acting_as, db_session: AsyncSession, advisories: None
) -> None:
    admin = await _totp_user(db_session, AdminRole.admin)
    page = await _get(acting_as, admin, "/admin/dashboard")
    assert BANNER in page
    assert "Your version v2.4.1 is affected by 2 published security advisories." in page
    assert "Update to 2.4.2 or later." in page
    assert 'href="/admin/system#security-advisories"' in page


@pytest.mark.asyncio
async def test_the_dashboard_banner_speaks_of_one_advisory(
    acting_as, db_session: AsyncSession, advisories: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "app_version", "1.3.0")  # only GHSA-nofix
    admin = await _totp_user(db_session, AdminRole.admin)
    page = await _get(acting_as, admin, "/admin/dashboard")
    assert "Your version v1.3.0 is affected by a published security advisory." in page
    assert "Update to" not in page  # no fix yet


@pytest.mark.asyncio
async def test_the_dashboard_of_a_fixed_version_has_no_banner(
    acting_as, db_session: AsyncSession, advisories: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "app_version", "2.4.2")
    admin = await _totp_user(db_session, AdminRole.admin)
    assert BANNER not in await _get(acting_as, admin, "/admin/dashboard")


@pytest.mark.asyncio
async def test_a_case_manager_sees_no_advisory_banner(
    acting_as, db_session: AsyncSession, advisories: None
) -> None:
    manager = await _totp_user(db_session, AdminRole.case_manager)
    assert BANNER not in await _get(acting_as, manager, "/admin/dashboard")


@pytest.mark.asyncio
async def test_an_organisations_admin_sees_no_advisory_banner_under_multi_tenancy(
    acting_as, db_session: AsyncSession, advisories: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "multi_tenancy_enabled", True)
    admin = await _totp_user(db_session, AdminRole.admin)
    assert BANNER not in await _get(acting_as, admin, "/admin/dashboard")
