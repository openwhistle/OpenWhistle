"""Browsers compile an input's ``pattern`` with the ``v`` flag, where a bare ``-``
at the end of a character class is a syntax error: Chrome then logs the error
and skips the check. ``[A-Za-z0-9_-]+`` on the new-user form did exactly that."""

import re
from pathlib import Path

TEMPLATES = Path(__file__).parents[1] / "app" / "templates"
_PATTERN = re.compile(r'\spattern="([^"]*)"')
# A hyphen right before "]" (or right after "[") that is not escaped.
_BARE_HYPHEN = re.compile(r"(?<!\\)-\]|\[-")


def test_every_pattern_attribute_is_valid_with_the_v_flag() -> None:
    bad = [
        f"{path.relative_to(TEMPLATES)}: {pattern}"
        for path in TEMPLATES.rglob("*.html")
        for pattern in _PATTERN.findall(path.read_text(encoding="utf-8"))
        if _BARE_HYPHEN.search(pattern)
    ]
    assert not bad, bad
