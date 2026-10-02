"""renovate.json must reach every pin it claims to manage.

A custom manager whose file pattern or regex matches nothing is
indistinguishable from one that works: Renovate reports it at debug level
only, and the pin silently falls behind (easywall lost seven Go pins that way).
"""

import hashlib
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


def test_axe_core_manager_reads_the_registry_and_the_version_constant() -> None:
    (manager,) = [m for m in CONFIG["customManagers"] if m.get("depNameTemplate") == "axe-core"]
    assert manager["datasourceTemplate"] == "npm"
    assert re.search(
        manager["matchStrings"][0].replace("(?<", "(?P<"),
        (ROOT / "tests/e2e/conftest.py").read_text(),
        re.M,
    )


def test_the_vendored_axe_is_the_pinned_version_and_hash() -> None:
    conftest = (ROOT / "tests/e2e/conftest.py").read_text()
    version = re.search(r'^AXE_VERSION = "([\d.]+)"', conftest, re.M).group(1)  # type: ignore[union-attr]
    digest = re.search(r'^AXE_SHA256 = "([0-9a-f]{64})"', conftest, re.M).group(1)  # type: ignore[union-attr]
    data = (ROOT / "tests/e2e/vendor/axe.min.js").read_bytes()
    assert data.startswith(f"/*! axe v{version}".encode()), (
        "run scripts/vendor_axe.py after a version bump"
    )
    assert hashlib.sha256(data).hexdigest() == digest


def test_every_digest_pinned_image_in_a_workflow_is_managed() -> None:
    """The CI nginx pins sat in `docker run` lines no matchString reached, so
    Renovate never moved them and nothing said so."""
    captured = {
        hit.group("currentDigest")
        for manager in CONFIG["customManagers"]
        for rx in (re.compile(m.replace("(?<", "(?P<")) for m in manager["matchStrings"])
        if "currentDigest" in rx.groupindex
        for f in _files(manager)
        for hit in rx.finditer(f.read_text())
    }
    pinned = {
        digest
        for wf in (ROOT / ".github/workflows").glob("*.yml")
        for line in wf.read_text().splitlines()
        if "uses:" not in line
        for digest in re.findall(r"\S+@(sha256:[0-9a-f]{64})", line)
    }
    assert pinned, "no pinned image found — the check reaches nothing"
    assert pinned <= captured, pinned - captured
