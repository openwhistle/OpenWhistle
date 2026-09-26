"""Every locale file carries exactly the keys of en.json, with the same placeholders.

Discovers locales by file, so a new language is checked without editing this test.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

LOCALES = Path(__file__).parents[1] / "app" / "locales"
EN: dict[str, str] = json.loads((LOCALES / "en.json").read_text(encoding="utf-8"))
_PLACEHOLDER = re.compile(r"\{(\w+)\}")
OTHERS = sorted(p for p in LOCALES.glob("*.json") if p.stem != "en")


def _load(path: Path) -> dict[str, str]:
    data: dict[str, str] = json.loads(path.read_text(encoding="utf-8"))
    return data


@pytest.mark.parametrize("path", OTHERS, ids=lambda p: p.stem)
def test_locale_has_exactly_the_keys_of_en(path: Path) -> None:
    data = _load(path)
    assert sorted(set(EN) - set(data)) == [], "missing"
    assert sorted(set(data) - set(EN)) == [], "not in en.json"


@pytest.mark.parametrize("path", OTHERS, ids=lambda p: p.stem)
def test_locale_keeps_every_placeholder(path: Path) -> None:
    data = _load(path)
    wrong = [
        k for k, v in EN.items()
        if k in data and set(_PLACEHOLDER.findall(v)) != set(_PLACEHOLDER.findall(data[k]))
    ]
    assert wrong == []


def test_there_are_other_locales() -> None:
    assert len(OTHERS) >= 3


_INFORMAL_DE = re.compile(
    r"\b(du|dich|dir|dein\w*|kannst|musst|hast|bist|wirst|setze|gib|klicke)\b", re.IGNORECASE
)


def test_german_addresses_the_reader_formally() -> None:
    informal = {k: v for k, v in _load(LOCALES / "de.json").items() if _INFORMAL_DE.search(v)}
    assert not informal, informal
