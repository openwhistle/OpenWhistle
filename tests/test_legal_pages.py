"""No tracked file holds the operator's real data (name, c/o address).

The imprint and privacy policy live in openwhistle/website, which runs the same
scan; the strings come from OW_PRIVATE_STRINGS, never from a repository.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _leaks(forbidden: list[str]) -> list[str]:
    files = subprocess.run(
        ["git", "ls-files", "-z"],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout.split(b"\0")
    leaks = []
    for name in filter(None, files):
        path = ROOT / name.decode()
        if path.is_file():
            data = path.read_bytes()
            # The index, never the string: the message must not leak what it found.
            leaks += [
                f"{name.decode()}: string {i}"
                for i, s in enumerate(forbidden, 1)
                if s.encode() in data
            ]
    return leaks


def test_the_real_data_scan_finds_the_fixture_person() -> None:
    # The scan reads every tracked file: this one names the fixture person.
    assert "tests/test_legal_pages.py: string 1" in _leaks(["Erika Mustermann"])


def test_no_file_in_the_repository_holds_the_real_data() -> None:
    """The strings come from the environment, never the repo: naming them here leaks them."""
    forbidden = [s.strip() for s in os.environ.get("OW_PRIVATE_STRINGS", "").splitlines()]
    forbidden = [s for s in forbidden if s]
    if not forbidden:
        pytest.skip("OW_PRIVATE_STRINGS is not set")
    assert not (leaks := _leaks(forbidden)), leaks
