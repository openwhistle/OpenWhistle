"""A mutation-audit entry whose `old` text no longer occurs in its file guards
nothing: the audit can only report it as stale at release time. Every entry of
the current release's specs must match its file exactly once, so a refactor
that moves a guard fails here, in the change that moved it."""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SPECS = sorted((ROOT / "docs-tech" / "mutations").glob("v2.0.0-*.json"))


def test_the_current_release_has_mutation_specs() -> None:
    assert len(SPECS) >= 5, SPECS


@pytest.mark.parametrize("spec", SPECS, ids=lambda p: p.name)
def test_every_mutation_matches_its_file_exactly_once(spec: Path) -> None:
    stale = []
    for m in json.loads(spec.read_text())["mutations"]:
        target = ROOT / (m.get("file") or m["path"])
        count = target.read_text().count(m["old"]) if target.exists() else 0
        if count != 1:
            stale.append(f"{m.get('id') or m.get('name')}: {target.relative_to(ROOT)} x{count}")
    assert not stale, stale
