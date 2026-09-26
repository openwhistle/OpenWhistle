"""Rendered check for the admin table-stack tables (fix round 1, item 5;
rewritten in fix round 2 per task-X10-rereview-1.md): the dashboard, users
and audit-log tables must not clip their last visible column outside the
enclosing panel at 1440/1920px in German — the exact defect a shared
`.table-stack th:last-child` selector used to cause on whichever of these
tables was not the one it was built for (task-X10-review, Important 2), and
the badge/column-width overflow item 8 originally found on the dashboard.

Round 1's version used the ASGI test client + a real `db_session` to render
the pages, which needs a host-reachable Postgres/Redis — the E2E CI job
(.github/workflows/e2e.yml, the only job that collects tests/e2e/) provisions
neither (docker-compose.e2e.yml's db/redis publish no host ports) and would
have errored on every push. This version follows the same pattern as every
other test in this file: a real HTTP request to the already-running `app` at
`base_url`, signed in with the demo admin credentials from this directory's
own conftest.py (test values for this project, published intentionally for
the demo instance) — no database access from the test process at all.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Browser

from tests.e2e.conftest import (
    DEMO_ADMIN_PASSWORD,
    DEMO_ADMIN_TOTP_SECRET,
    DEMO_ADMIN_USERNAME,
    _admin_login,
)

pytestmark = pytest.mark.e2e

# Demo report OW-DEMO-00003 (app/services/demo_seed.py) is seeded
# pending_feedback and unassigned — its German status badge ("Rückmeldung
# ausstehend", unbreakable — .badge is white-space: nowrap) alone is the
# item-8 repro: it widens the dashboard's 8-column table past its scroll
# viewport at both 1440 and 1920px (the admin-shell caps content width at
# 1440px regardless of screen size), and used to push the row's own "view"
# action off the visible edge.
_TABLE_PAGES = ("/admin/dashboard", "/admin/users", "/admin/audit-log")


def _last_column_overflow(page, width: int) -> dict[str, float]:  # type: ignore[no-untyped-def]
    """{cell_right, panel_right} for the bottom-right table cell at `width`px."""
    page.set_viewport_size({"width": width, "height": 1000})
    return page.evaluate(
        """
        () => {
            const cell = document.querySelector(
                '.table-stack tbody tr:last-child td:last-child'
            );
            const panel = cell ? cell.closest('.panel') : null;
            if (!cell || !panel) return {cell_right: -1, panel_right: -1};
            return {
                cell_right: cell.getBoundingClientRect().right,
                panel_right: panel.getBoundingClientRect().right,
            };
        }
        """
    )


def test_admin_tables_last_column_stays_inside_the_panel_in_german(
    browser: Browser, base_url: str
) -> None:
    ctx = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = ctx.new_page()
    _admin_login(page, base_url, DEMO_ADMIN_USERNAME, DEMO_ADMIN_PASSWORD, DEMO_ADMIN_TOTP_SECRET)
    # Every request after this carries the cookie for this context.
    ctx.add_cookies([{"name": "ow-lang", "value": "de", "url": base_url}])

    for path in _TABLE_PAGES:
        page.goto(f"{base_url}{path}")
        page.wait_for_load_state("networkidle")
        for width in (1440, 1920):
            info = _last_column_overflow(page, width)
            assert info["cell_right"] > 0, f"{path}@{width}: no table row found"
            assert info["cell_right"] <= info["panel_right"] + 1, (
                f"{path}@{width}px: last column right edge "
                f"({info['cell_right']}) exceeds its panel ({info['panel_right']})"
            )
    ctx.close()
