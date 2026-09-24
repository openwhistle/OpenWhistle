"""renovate.json must reach every pin it claims to manage.

A custom manager whose file pattern or regex matches nothing is
indistinguishable from one that works: Renovate reports it at debug level
only, and the pin silently falls behind (easywall lost seven Go pins that way).
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
CONFIG = json.loads((ROOT / "renovate.json").read_text())
_SKIP = {".git", ".venv", "node_modules", "__pycache__", ".claude", ".serena"}
TRACKED = [
    p.relative_to(ROOT).as_posix()
    for p in ROOT.rglob("*")
    if p.is_file() and not _SKIP & set(p.relative_to(ROOT).parts)
]


def _files(manager: dict) -> list[Path]:
    patterns = [re.compile(p.strip("/")) for p in manager["managerFilePatterns"]]
    return [ROOT / f for f in TRACKED if any(p.search(f) for p in patterns)]


def _captures(manager: dict) -> list[str]:
    regexes = [re.compile(m.replace("(?<", "(?P<")) for m in manager["matchStrings"]]
    return [
        hit.group("currentValue")
        for f in _files(manager)
        for rx in regexes
        for hit in rx.finditer(f.read_text())
    ]


def test_every_custom_manager_reaches_a_pin() -> None:
    for manager in CONFIG["customManagers"]:
        assert _files(manager), f"no tracked file matches {manager['managerFilePatterns']}"
        assert _captures(manager), f"no pin matched by {manager['matchStrings']}"


def test_every_match_string_matches_somewhere() -> None:
    for manager in CONFIG["customManagers"]:
        text = "\n".join(f.read_text() for f in _files(manager))
        for pattern in manager["matchStrings"]:
            assert re.search(pattern.replace("(?<", "(?P<"), text), f"dead pattern: {pattern}"


def test_python_runtime_rule_does_not_override_digest_automerge() -> None:
    """The Python runtime packageRule is later in the array than the general digest
    rule, so if it matched digest updates it would silently win and base-image
    digest refreshes would never auto-merge (a later matching rule overrides an
    earlier one for the same field in Renovate)."""
    rules = [r for r in CONFIG["packageRules"] if r.get("groupName") == "Python runtime"]
    assert rules, "no 'Python runtime' packageRule found"
    for rule in rules:
        assert "matchUpdateTypes" in rule, "rule must scope its update types"
        assert "digest" not in rule["matchUpdateTypes"]


def test_no_managed_file_is_ignored() -> None:
    """config:recommended ignores tests/ by default (:ignoreModulesAndTests),
    which silently hid the axe-core pin in tests/e2e/conftest.py. ignorePaths
    must be explicit, and must not cover any file a custom manager reads."""
    from fnmatch import fnmatch

    assert "ignorePaths" in CONFIG, "set ignorePaths explicitly; the preset hides tests/"
    for manager in CONFIG["customManagers"]:
        for f in _files(manager):
            rel = f.relative_to(ROOT).as_posix()
            hit = [g for g in CONFIG["ignorePaths"] if fnmatch(rel, g) or fnmatch("/" + rel, g)]
            assert not hit, f"{rel} is managed but ignored by {hit}"
