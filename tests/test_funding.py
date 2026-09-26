"""Payment links in a public repository carry a handle, and a handle can be a
personal identifier. The project's public identity is the GitHub account
`jp1337`; a payment handle built from anything else (a real name, for
instance) must not be tracked. .github/FUNDING.yml renders as a Sponsor button
on every page of the repository, which is exactly where such a leak sits
unnoticed."""

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
PUBLIC_HANDLE = "jp1337"
LINK = re.compile(
    r"(?i)\b(?:paypal\.me|paypal\.com/paypalme|ko-fi\.com|buymeacoffee\.com|liberapay\.com|patreon\.com)"
    r"/([A-Za-z0-9_.-]+)"
)


def _tracked_files() -> list[Path]:
    try:
        out = subprocess.run(  # noqa: S603 — fixed argv, no user input
            ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True,  # noqa: S607
        ).stdout.decode()
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout")
    # The changelog records history, including a funding platform once added.
    return [ROOT / n for n in out.split("\0") if n and n != "CHANGELOG.md"]


def test_no_personal_payment_links_are_tracked() -> None:
    offenders = []
    for path in _tracked_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for m in LINK.finditer(text):
            if m.group(1).lower() != PUBLIC_HANDLE:
                offenders.append(f"{path.relative_to(ROOT)}: {m.group(0)}")
    assert not offenders, offenders


def test_funding_file_offers_github_sponsors_and_ko_fi() -> None:
    funding = (ROOT / ".github/FUNDING.yml").read_text()
    assert re.search(r"(?m)^github:\s*jp1337\s*$", funding)
    assert re.search(r"(?m)^ko_fi:\s*jp1337\s*$", funding)
    assert not re.search(r"(?m)^custom:", funding)
