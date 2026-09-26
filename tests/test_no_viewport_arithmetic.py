"""calc(100vh - N px) guesses the height of the chrome around a page. Four
pages guessed 112 or 144 px against a real 151 px plus the 36 px demo banner,
and every one of them scrolled with the footer below the fold. A page that
fills the space between nav and footer takes the .page-fill class instead."""

import re
from pathlib import Path

APP = Path(__file__).parents[1] / "app"
_GUESS = re.compile(r"calc\(\s*100d?s?vh\s*-")


def test_no_stylesheet_or_template_subtracts_from_the_viewport_height() -> None:
    files = [APP / "static" / "css" / "site.css", *sorted((APP / "templates").rglob("*.html"))]
    offenders = [
        f"{f.relative_to(APP)}:{n}"
        for f in files
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1)
        if _GUESS.search(line)
    ]
    assert not offenders, offenders
