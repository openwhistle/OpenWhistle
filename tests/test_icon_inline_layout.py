"""Structural guard: icons placed next to text must not render on their own line.

`_icons.html`'s `icon()` macro puts an inline SVG with `class="icon"` next to
plain text in several templates (an SLA value, an assignee name, an
attachment filename, ...). site.css resets `svg { display: block }` for
predictable sizing elsewhere (cards, avatars, ...); without `.icon`
overriding that back to an inline display, `vertical-align` on `.icon` is a
no-op (it only applies to inline-level boxes) and the icon renders on its
own line above the text (as it did on the admin/report.html "7-day
acknowledgement" SLA value). A flex/inline-flex
ancestor (.btn, .badge, .stepper-dot, ...) blockifies flex-item children
regardless of their own `display`, so those are unaffected either way; this
guard only has to hold for `.icon` itself.
"""

from __future__ import annotations

import re
from pathlib import Path

_CSS = Path(__file__).resolve().parent.parent / "app" / "static" / "css" / "site.css"


def _rule_body(css: str, selector: str) -> str:
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert match, f"no {selector!r} rule found in site.css"
    return match.group(1)


def test_icon_class_overrides_svg_reset_to_inline() -> None:
    css = _CSS.read_text(encoding="utf-8")
    body = _rule_body(css, ".icon")
    assert re.search(r"display\s*:\s*inline", body), (
        f".icon must set an inline display so vertical-align applies: {body!r}"
    )
