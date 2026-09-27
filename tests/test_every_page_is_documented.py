"""Every page of the interface is documented in docs/docs.html.

The list of pages comes from the FastAPI app, not from a list somebody has to
extend: every GET route is either a page — and then docs.html must name it —
or it is in ``NOT_A_PAGE`` by exact path, with the reason. A new route cannot
slip through by happening to look like an exclusion, and an exclusion whose
route is gone fails too.

The matching rule: docs.html (entities decoded) must contain the route path
bounded on both sides by a character that cannot be part of a path, so
``/admin/reports/{report_id}`` is not satisfied by
``/admin/reports/{id}/export.pdf``. Each ``{param}`` in the route matches any
placeholder the docs use for it: ``{id}``, ``{report_id}``, ``<slug>``. A
full URL (``https://host/admin/oidc/callback``) does not count: it is a
configuration example, not a description of the page.
"""

import html
import re
from pathlib import Path

from tests.test_local_review import _walk_routes

ROOT = Path(__file__).parents[1]

NOT_A_PAGE = {
    "/": "redirects to /setup or /submit",
    "/admin": "redirects to /admin/login",
    "/admin/": "redirects to /admin/login",
    "/health": "JSON for an orchestrator, not a page",
    "/admin/local-review-login": "maintainer-only review login, docs-tech/local-review.md",
    "/admin/session/ttl": "JSON polled by the session timer of an admin page",
    "/admin/oidc/authorize": "redirects to the identity provider",
    "/admin/oidc/callback": "the identity provider's redirect target, not a page one opens",
    "/status/attachments/{attachment_id}": "a file download from the status page",
    "/admin/reports/{report_id}/export.pdf": "a file download from the case page",
    "/admin/reports/{report_id}/attachments/{attachment_id}": "a file download from the case page",
    "/admin/audit-log/export.csv": "a file download from the audit log page",
}

_PARAM = r"(?:\{[^}\s]+\}|<[^>\s]+>)"
_EDGE_BEFORE = r"(?<![\w/.-])"
# A full stop may end the sentence after a path, but not start a suffix (.pdf).
_EDGE_AFTER = r"(?![\w/{}-]|\.\w)"


def _get_routes() -> set[str]:
    from app.main import app

    return {r.path for r in _walk_routes(app) if r.methods and "GET" in r.methods}


def _pattern(path: str) -> re.Pattern[str]:
    parts = re.split(r"\{[^}]+\}", path)
    return re.compile(_EDGE_BEFORE + _PARAM.join(map(re.escape, parts)) + _EDGE_AFTER)


def _is_documented(path: str, docs: str) -> bool:
    return _pattern(path).search(docs) is not None


def test_every_page_is_documented() -> None:
    docs = html.unescape((ROOT / "docs/docs.html").read_text(encoding="utf-8"))
    missing = sorted(
        path for path in _get_routes() if path not in NOT_A_PAGE and not _is_documented(path, docs)
    )
    assert not missing, "page(s) not named in docs/docs.html:\n  " + "\n  ".join(missing)


def test_every_exclusion_is_a_real_route() -> None:
    stale = sorted(set(NOT_A_PAGE) - _get_routes())
    assert not stale, f"NOT_A_PAGE lists route(s) the app no longer has: {stale}"


def test_the_matching_rule_is_pinned() -> None:
    docs = "<code>/admin</code> and /admin/reports/{id}/export.pdf and /submit/<slug>."
    assert _is_documented("/admin", docs)
    assert _is_documented("/submit/{org_slug}", docs)
    assert _is_documented("/admin/reports/{report_id}/export.pdf", docs)
    assert not _is_documented("/admin/reports/{report_id}", docs)
    assert not _is_documented("/admin/login", docs)
    assert not _is_documented("/submit", "/admin/submit")
    assert not _is_documented("/admin/oidc/callback", "https://example.com/admin/oidc/callback")
