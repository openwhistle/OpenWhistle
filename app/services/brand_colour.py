"""A brand colour and the theme tokens derived from it, by WCAG 2.x contrast.

base.html emits the tokens as --brand-<name> custom properties; site.css reads
them for links, focus rings, outlines and the primary button in both themes.
"""

from __future__ import annotations

import re

DEFAULT = "#0c7253"
LIGHT_CANVAS = "#ffffff"
DARK_CANVAS = "#0a0a0b"
WHITE = "#ffffff"
BLACK = "#000000"
# WCAG 2.2 SC 1.4.3 for text; it also covers SC 1.4.11's 3:1 for focus and outlines.
TEXT_MINIMUM = 4.5

_HEX = re.compile(r"#[0-9a-f]{6}")

# DESIGN.md's emerald, exactly as specified there; any other colour is computed.
DESIGN_TOKENS = {
    "accent": "#0c7253",
    "on": "#ffffff",
    "accent-weak": "#e5f3ee",
    "accent-strong": "#0b6249",
    "accent-dark": "#23c088",
    "on-dark": "#06120d",
    "accent-weak-dark": "#0d211a",
    "accent-strong-dark": "#1fa878",
}


def parse(value: str) -> str:
    colour = value.strip().lower()
    if not _HEX.fullmatch(colour):
        raise ValueError("a colour is written #rrggbb")
    return colour


def _channels(colour: str) -> tuple[int, int, int]:
    return int(colour[1:3], 16), int(colour[3:5], 16), int(colour[5:7], 16)


def luminance(colour: str) -> float:
    def linear(channel: int) -> float:
        s = channel / 255
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = (linear(c) for c in _channels(colour))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _mix(colour: str, toward: str, share: float) -> str:
    pairs = zip(_channels(colour), _channels(toward), strict=True)
    return "#" + "".join(f"{round(c + (t - c) * share):02x}" for c, t in pairs)


def _on(fill: str) -> str:
    # Pure black, not the ink: with #0a0a0b the worst mid-grey reached only 4.44:1.
    return WHITE if contrast(fill, WHITE) >= contrast(fill, BLACK) else BLACK


def _readable(colour: str, canvas: str, toward: str) -> str:
    for step in range(51):
        candidate = _mix(colour, toward, step / 50)
        if contrast(candidate, canvas) >= TEXT_MINIMUM:
            return candidate
    return toward


def tokens(primary: str) -> dict[str, str]:
    colour = parse(primary)
    if colour == DEFAULT:
        return dict(DESIGN_TOKENS)
    light = _readable(colour, LIGHT_CANVAS, BLACK)
    dark = _readable(colour, DARK_CANVAS, WHITE)
    return {"accent": light, "on": _on(light), "accent-dark": dark, "on-dark": _on(dark)}
