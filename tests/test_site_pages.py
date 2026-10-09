"""SECURITY.md keeps the sentence the website's security pages repeat."""

from __future__ import annotations

from pathlib import Path


def test_security_md_says_reports_are_unpaid() -> None:
    text = (Path(__file__).parents[1] / "SECURITY.md").read_text()
    # The heading says "unpaid" too: the sentence itself must stay.
    assert "There is no payment" in text and "security/advisories/new" in text
