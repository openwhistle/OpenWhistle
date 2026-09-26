"""Rendered check for the admin table-stack tables (fix round 1, item 5):
the dashboard, users and audit-log tables must not clip their last visible
column outside the enclosing panel at 1440/1920px in German — the exact
defect a shared `.table-stack th:last-child` selector used to cause on
whichever of these tables was not the one it was built for (task-X10-review,
Important 2).

No live server or review stack needed: renders each page through the normal
ASGI test client (the app's own `client`/`db_session` fixtures), serves that
HTML plus `app/static/` from a local `ThreadingHTTPServer`, and measures it
with Playwright's async API (compatible with the already-running pytest-
asyncio event loop; the sync API is not).
"""

from __future__ import annotations

import contextlib
import http.server
import threading
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pyotp
import pytest
from httpx import AsyncClient
from playwright.async_api import async_playwright
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.report import ReportStatus
from app.models.user import AdminRole, AdminUser
from app.services.auth import hash_password
from app.services.report import create_report
from tests.test_v160_design import _login

pytestmark = pytest.mark.e2e

_STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "app" / "static"


class _PageServer(http.server.BaseHTTPRequestHandler):
    pages: dict[str, str] = {}

    def log_message(self, *args: object) -> None:
        pass

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path.startswith("/static/"):
            fs_path = _STATIC_DIR / path.removeprefix("/static/")
            if not fs_path.is_file():
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            if fs_path.suffix == ".css":
                self.send_header("Content-Type", "text/css")
            elif fs_path.suffix == ".js":
                self.send_header("Content-Type", "application/javascript")
            elif fs_path.suffix == ".woff2":
                self.send_header("Content-Type", "font/woff2")
            self.end_headers()
            self.wfile.write(fs_path.read_bytes())
            return
        body = self.pages.get(path.lstrip("/"))
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))


@contextlib.contextmanager
def _serve(pages: dict[str, str]) -> Iterator[str]:
    handler = type("Handler", (_PageServer,), {"pages": pages})
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()


async def _last_column_overflow(url: str, page_name: str, width: int) -> dict[str, float]:
    """{table_right, panel_right} for the bottom-right table cell at `width`px."""
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        ctx = await browser.new_context(viewport={"width": width, "height": 1000})
        page = await ctx.new_page()
        await page.goto(f"{url}/{page_name}")
        await page.wait_for_load_state("networkidle")
        result: dict[str, float] = await page.evaluate(
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
        await browser.close()
        return result


@pytest.mark.asyncio
async def test_admin_tables_last_column_stays_inside_the_panel_in_german(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin = await _login(client, db_session, AdminRole.admin)

    # Dashboard: the reproduced defect — a pending_feedback report's German
    # status badge ("Rückmeldung ausstehend", unbreakable) alone widens the
    # 8-column table past its scroll viewport at both 1440 and 1920px (the
    # admin-shell caps content width at 1440px regardless of screen size).
    assignee = AdminUser(
        id=uuid.uuid4(), username="case_manager_hamburg",
        password_hash=hash_password("Fixture-Password-160"),
        totp_secret=pyotp.random_base32(), totp_enabled=True, role=AdminRole.case_manager,
    )
    db_session.add(assignee)
    await db_session.commit()
    report, _ = await create_report(db_session, "discrimination", "x" * 30)
    report.assigned_to_id = assignee.id
    report.status = ReportStatus.pending_feedback
    report.acknowledged_at = datetime.now(UTC)
    report.feedback_due_at = datetime.now(UTC) + timedelta(days=45)
    await db_session.commit()

    client.cookies.set("ow-lang", "de")
    dashboard_html = (await client.get("/admin/dashboard")).text
    users_html = (await client.get("/admin/users")).text

    from app.services import audit as audit_service
    await audit_service.log(db_session, admin, "auth.login")
    await db_session.commit()
    audit_html = (await client.get("/admin/audit-log")).text

    pages = {
        "dashboard.html": dashboard_html,
        "users.html": users_html,
        "audit-log.html": audit_html,
    }
    with _serve(pages) as url:
        for page_name in pages:
            for width in (1440, 1920):
                info = await _last_column_overflow(url, page_name, width)
                assert info["cell_right"] > 0, f"{page_name}@{width}: no table row found"
                assert info["cell_right"] <= info["panel_right"] + 1, (
                    f"{page_name}@{width}px: last column right edge "
                    f"({info['cell_right']}) exceeds its panel "
                    f"({info['panel_right']})"
                )
