"""The app links the split documentation pages, never an anchor of the old one-pager.

The website's anchor script is a safety net for bookmarks; the app's templates and
locales (escaped quotes in JSON) link the page that holds the content.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_no_app_file_links_a_one_pager_anchor() -> None:
    stale = re.compile(r'href=\\?"(?:https://openwhistle\.net)?/en/docs/#')
    files = [*(ROOT / "app").rglob("*.html"), *(ROOT / "app/locales").glob("*.json")]
    assert files
    hits = [p.as_posix() for p in files if stale.search(p.read_text(encoding="utf-8"))]
    assert not hits, hits
