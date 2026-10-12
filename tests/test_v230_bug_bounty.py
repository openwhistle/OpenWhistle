"""Defects found by the bug bounty after v2.2.1, each reproduced before it was fixed."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

# ── The lockout must not say when the reporter signed in ───────────────────


@pytest.mark.asyncio
async def test_a_correct_pin_leaves_the_lockout_as_it_was(
    client: object, db_session: AsyncSession
) -> None:
    """A correct PIN cleared the case's failure counter. Anyone who knows a case number
    (every admin does) could lock it with wrong PINs and probe again: the lock gone meant
    the reporter had signed in, to the minute of the probe. A correct PIN gets in
    whatever the counter says, so it no longer touches it."""
    from app.config import settings
    from app.redis_client import get_redis
    from app.services.report import authenticate_whistleblower, create_report

    redis = await get_redis()
    report, pin = await create_report(db_session, "financial_fraud", "Probed for its sign-in.")
    for _ in range(settings.max_access_attempts + 1):
        _, locked = await authenticate_whistleblower(db_session, redis, report.case_number, "x")
    assert locked > 0

    found, _ = await authenticate_whistleblower(db_session, redis, report.case_number, pin)
    assert found is not None  # the reporter still gets in

    _, locked_after = await authenticate_whistleblower(db_session, redis, report.case_number, "x")
    assert locked_after > 0


# ── nginx clears every header the app knows to carry an address ─────────────


def test_nginx_clears_every_header_the_app_strips() -> None:
    """2.2.1 taught the app seven more address headers (Fastly, Envoy, Azure, App Engine,
    ingress-nginx, Cloudflare IPv6); the bundled nginx kept clearing the first seven only,
    while its comment said no IP data could reach the app "under any circumstances"."""
    import re
    from pathlib import Path

    from app.middleware import _IP_REVEAL_HEADERS

    conf = (Path(__file__).parents[1] / "nginx/snippets/proxy-headers.conf").read_text()
    cleared = {h.lower() for h in re.findall(r'^proxy_set_header\s+(\S+)\s+"";', conf, re.M)}
    assert set(_IP_REVEAL_HEADERS) <= cleared, sorted(set(_IP_REVEAL_HEADERS) - cleared)
