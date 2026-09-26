"""Structural guard: the login page's stacked cards must not sit flush.

login.html renders three cards in a column when local review + demo mode are
both on: the local-review-login `.panel`, the `.demo-credentials` box, then
the real login `.panel`. Spacing between two `.panel`s comes from the
adjacent-sibling rule `.panel + .panel` in site.css — but `.demo-credentials`
is a different class, so that rule never matched, and the "Enter the local
review" card sat flush against the demo credentials card below it. This guard fails if the matching
`.panel + .demo-credentials` spacing rule regresses.
"""

from __future__ import annotations

import re
from pathlib import Path

_CSS = Path(__file__).resolve().parent.parent / "app" / "static" / "css" / "site.css"


def test_panel_before_demo_credentials_has_spacing() -> None:
    css = _CSS.read_text(encoding="utf-8")
    # `.panel + .demo-credentials` may be grouped with other selectors in a
    # comma list, but it is always the selector directly preceding `{`.
    match = re.search(r"\.panel \+ \.demo-credentials\s*\{([^}]*)\}", css)
    assert match, (
        ".panel + .demo-credentials must have a margin-top rule — otherwise the "
        "local-review-login panel sits flush against the demo credentials box"
    )
    assert re.search(r"margin-top\s*:\s*\S", match.group(1)), match.group(1)
