"""A disabled pagination button at 38 % opacity fell below axe's 4.5:1 text
contrast. The e2e axe run only meets it once the dashboard has a second page,
which a fresh CI database never has, so the rule is pinned here."""

import re
from pathlib import Path

_PATH = Path(__file__).parents[1] / "app" / "static" / "css" / "site.css"
CSS = re.sub(r"/\*.*?\*/", "", _PATH.read_text(), flags=re.S)


def test_disabled_pagination_is_muted_not_transparent() -> None:
    rule = re.search(r"\.pagination-disabled \{([^}]*)\}", CSS)
    assert rule, "no .pagination-disabled rule"
    assert "opacity" not in rule.group(1)
    assert "color: var(--muted)" in rule.group(1)
