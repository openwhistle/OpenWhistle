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
    for theme, canvas in (("", bc.LIGHT_CANVAS), ("-dark", bc.DARK_CANVAS)):
        accent, on = t[f"accent{theme}"], t[f"on{theme}"]
        pairs = {
            "link on the canvas": (accent, canvas),
            "text on the button": (on, accent),
            # .badge-action, .filter-pill-active, the active admin nav entry
            "accent on its tint": (accent, t[f"accent-weak{theme}"]),
            "text on the hovered button": (on, t[f"accent-strong{theme}"]),
        }
        for what, (fg, bg) in pairs.items():
            assert bc.contrast(fg, bg) >= bc.TEXT_MINIMUM, (primary, theme, what, t)


def test_two_hundred_colours_meet_aa_in_both_themes() -> None:
    rng = random.Random(20261014)  # noqa: S311 - a reproducible sample, not security
    for _ in range(200):
        _meets(f"#{rng.randrange(0x1000000):06x}")


@pytest.mark.parametrize(
    "primary", ["#ffffff", "#000000", "#ffff00", "#0000ff", "#777777", "#ffd000", "#0c7253"]
)
def test_extremes_still_meet_aa(primary: str) -> None:
    _meets(primary)


def test_text_on_a_mid_grey_fill_is_pure_black() -> None:
    # The ink (#0a0a0b) would reach only 4.42:1 on #777777; pure black reaches 4.69:1.
    assert bc._on("#777777") == bc.BLACK


def test_a_custom_colour_emits_every_token_the_default_does() -> None:
    assert bc.tokens("#aa3300").keys() == bc.DESIGN_TOKENS.keys()


def test_a_mix_rounds_half_up_like_the_preview() -> None:
    # Math.round in branding.js rounds 0.5 up; round() in Python would give 0x7e here.
    assert bc._mix("#fd0000", "#000000", 0.5) == "#7f0000"
