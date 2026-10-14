"""A brand colour's theme tokens meet WCAG AA in both themes (spec: Colour)."""

from __future__ import annotations

import random

import pytest

from app.services import brand_colour as bc


def test_the_default_keeps_design_md_values() -> None:
    assert bc.tokens("#0c7253") == {
        "accent": "#0c7253",
        "on": "#ffffff",
        "accent-weak": "#e5f3ee",
        "accent-strong": "#0b6249",
        "accent-dark": "#23c088",
        "on-dark": "#06120d",
        "accent-weak-dark": "#0d211a",
        "accent-strong-dark": "#1fa878",
    }


def test_contrast_matches_wcag() -> None:
    assert round(bc.contrast("#000000", "#ffffff"), 2) == 21.0
    assert round(bc.contrast("#777777", "#ffffff"), 2) == 4.48


@pytest.mark.parametrize("value", ["0c7253", "#0c725", "#0c72533", "#gggggg", "", "red"])
def test_parse_refuses_anything_but_rrggbb(value: str) -> None:
    with pytest.raises(ValueError):
        bc.parse(value)


def test_parse_normalises_case_and_space() -> None:
    assert bc.parse(" #0C7253 ") == "#0c7253"


def _meets(primary: str) -> None:
    t = bc.tokens(primary)
    assert bc.contrast(t["accent"], bc.LIGHT_CANVAS) >= bc.TEXT_MINIMUM, (primary, t)
    assert bc.contrast(t["on"], t["accent"]) >= bc.TEXT_MINIMUM, (primary, t)
    assert bc.contrast(t["accent-dark"], bc.DARK_CANVAS) >= bc.TEXT_MINIMUM, (primary, t)
    assert bc.contrast(t["on-dark"], t["accent-dark"]) >= bc.TEXT_MINIMUM, (primary, t)


def test_two_hundred_colours_meet_aa_in_both_themes() -> None:
    rng = random.Random(20261014)  # noqa: S311 - a reproducible sample, not security
    for _ in range(200):
        _meets(f"#{rng.randrange(0x1000000):06x}")


@pytest.mark.parametrize("primary", ["#ffffff", "#000000", "#ffff00", "#0000ff", "#777777"])
def test_extremes_still_meet_aa(primary: str) -> None:
    _meets(primary)
