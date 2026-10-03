"""A mutation-audit entry whose `old` text no longer occurs in its file guards
nothing: the audit can only report it as stale at release time. Every entry of
the installed release's specs (`app_version`) and of every release in
development after it must match its file exactly once, so a refactor
that moves a guard fails here, in the change that moved it."""

import json
import re
from pathlib import Path

import pytest

from app.config import settings

ROOT = Path(__file__).parents[1]
_VERSION = re.compile(r"v(\d+)\.(\d+)\.(\d+)(?:-[\w-]+)?\.json")


def _version(name: str) -> tuple[int, ...]:
    found = _VERSION.fullmatch(name)
    assert found, f"mutation spec name is not vX.Y.Z[-topic].json: {name}"
    return tuple(int(part) for part in found.groups())


def _current() -> tuple[int, ...]:
    return tuple(int(part) for part in settings.app_version.split("."))


# The installed release and every release in development after it: once a
# release is tagged its specs are history, but until then they must hold.
ALL_SPECS = sorted((ROOT / "docs-tech" / "mutations").glob("*.json"))
SPECS = [p for p in ALL_SPECS if _version(p.name) >= _current()]


def test_every_spec_name_carries_a_version() -> None:
    for spec in ALL_SPECS:
        _version(spec.name)


def test_the_current_release_has_mutation_specs() -> None:
    assert any(_version(p.name) == _current() for p in SPECS), (settings.app_version, SPECS)


def test_a_release_in_development_is_covered() -> None:
    # Pins the >= comparison: a v2.1.0 spec counts while app_version is 2.0.0.
    assert _version("v2.1.0-x.json") > _version("v2.0.0-x.json") > _version("v1.10.0.json")


@pytest.mark.parametrize("spec", SPECS, ids=lambda p: p.name)
def test_every_mutation_matches_its_file_exactly_once(spec: Path) -> None:
    stale = []
    for m in json.loads(spec.read_text())["mutations"]:
        target = ROOT / (m.get("file") or m["path"])
        if "create" in m:  # the audit adds this file, so it must not exist yet
            count = 0 if target.exists() else 1
        else:
            count = target.read_text().count(m["old"]) if target.exists() else 0
        if count != 1:
            stale.append(f"{m.get('id') or m.get('name')}: {target.relative_to(ROOT)} x{count}")
    assert not stale, stale


def test_a_spec_cannot_name_a_file_outside_the_repo() -> None:
    from scripts.mutation_audit import inside_root

    assert inside_root("app/config.py")
    for bad in ("/etc/passwd", "../outside.txt", "app/../../outside.txt"):
        assert not inside_root(bad), bad


@pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda p: p.name)
def test_every_spec_file_is_inside_the_repo(spec: Path) -> None:
    from scripts.mutation_audit import inside_root

    for m in json.loads(spec.read_text())["mutations"]:
        name = m.get("file") or m["path"]
        assert inside_root(name), f"{m.get('id') or m.get('name')}: {name}"
