"""DESIGN.md describes what was built, not what was once planned."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT = (ROOT / "DESIGN.md").read_text(encoding="utf-8")


def test_the_seal_mark_that_was_never_built_is_gone() -> None:
    for phrase in ("wax seal", "seal mark", "Brand / seal"):
        assert phrase not in TEXT, phrase


def test_brand_names_the_k3_mark() -> None:
    assert "### Brand mark (K3)" in TEXT
    assert "scripts/render_icons.py" in TEXT


def test_diagrams_have_their_own_section() -> None:
    assert "## Diagrams" in TEXT
    for rule in ("style C", "beside", "roles", "docs-tech/diagrams.md"):
        assert rule in TEXT, rule


def test_color_scheme_is_documented() -> None:
    assert "color-scheme: only light" in TEXT


def test_every_colour_key_is_named_in_the_prose() -> None:
    front = TEXT.split("---", 2)[1]
    keys = re.findall(r"^  ([a-z][\w-]*):\s*[{\"]", front.split("typography:")[0], re.M)
    body = TEXT.split("---", 2)[2]
    missing = [k for k in keys if f"colors.{k}}}" not in body and k != "primary"]
    assert not missing, missing
