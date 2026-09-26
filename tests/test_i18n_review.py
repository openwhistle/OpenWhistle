"""docs-tech/i18n-review.md names the keys a translation reviewer reads first.
A key renamed or removed from en.json would silently drop out of that review."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_every_key_on_the_review_page_exists() -> None:
    page = (ROOT / "docs-tech/i18n-review.md").read_text(encoding="utf-8")
    keys = re.findall(r"^\| `([^`]+)` \|", page, re.MULTILINE)
    assert len(keys) >= 25, f"review page lists only {len(keys)} keys — the table format changed?"
    en = json.loads((ROOT / "app/locales/en.json").read_text(encoding="utf-8"))
    missing = [k for k in keys if k not in en]
    assert not missing, f"i18n-review.md names key(s) missing from en.json: {missing}"
