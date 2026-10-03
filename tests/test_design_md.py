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


def test_the_k3_sizes_are_named() -> None:
    brand = TEXT.split("### Brand mark (K3)")[1].split("###")[0]
    for size in ("22px", "18px", "24px"):
        assert size in brand, size


def test_no_retired_token_name_survives() -> None:
    assert not re.search(r"--(bg-|text-|border-subtle|nav-bg|footer-bg|code-)[\w-]*", TEXT), (
        "a retired custom-property name is back in DESIGN.md"
    )


def test_the_nav_footer_buttons_and_edges_read_as_built() -> None:
    """Five statements the P2b review found contradicting the CSS (final review, Minor 1)."""
    assert "translucent" not in TEXT  # both navs are an opaque canvas
    assert "Footer sits on `{colors.inverse}`" in TEXT  # site and app footer
    assert 'flat:   "none (1px {colors.hairline} ring' in TEXT  # borders as shadows
    assert "**Secondary** — `{colors.canvas}` fill, a 1px `{colors.hairline}` ring" in TEXT
    accent = re.search(r"^  accent: .*$", TEXT, re.M)
    assert accent and "brand mark" not in accent.group(0)  # K3 is never in the accent
    assert "per-page select" in TEXT  # the one button-like control that keeps a border
