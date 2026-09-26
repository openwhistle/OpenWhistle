"""Every setting added since the previous release is in the changelog.

Four shipped features of v1.6.0 had no changelog entry until the release audit;
a new setting is the cheapest sign of a user-visible change to check for.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.config import Settings, settings

ROOT = Path(__file__).parents[1]
PREVIOUS = ROOT / "tests/data/previous_release_settings.txt"


def _current_section() -> str:
    """[Unreleased] plus the section of the current version."""
    text = (ROOT / "CHANGELOG.md").read_text()
    sections = re.split(r"^## ", text, flags=re.M)
    wanted = ("[Unreleased]", f"[{settings.app_version}]")
    return "\n".join(s for s in sections if s.startswith(wanted))


def test_every_new_setting_is_in_the_changelog() -> None:
    previous = {
        line.strip() for line in PREVIOUS.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }
    section = _current_section()
    missing = [
        name.upper() for name in Settings.model_fields
        if name not in previous and name.upper() not in section
    ]
    assert not missing, f"new settings without a CHANGELOG entry: {missing}"
