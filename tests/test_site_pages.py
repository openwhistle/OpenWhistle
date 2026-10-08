"""The P3 pages: what each must say, so a rewrite cannot drop it."""

from __future__ import annotations

import re
from pathlib import Path

from tests.built_site import page, pages

SPONSOR = "https://github.com/sponsors/jp1337"


def _text(url: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page(url)))


def test_every_page_footer_links_sponsor_contribute_and_github() -> None:
    for path in pages():
        if path.name == "404.html":
            continue
        footer = path.read_text().split('class="site-footer"', 1)[1]
        assert SPONSOR in footer, path
        assert re.search(r'href="/(en/contribute|de/mitmachen)/"', footer), path


def test_the_nav_is_security_docs_blog_and_one_demo_button() -> None:
    nav = page("/en/").split('class="nav-links"', 1)[1].split("</ul>", 1)[0]
    labels = re.findall(r">([^<]+)</a></li>", nav)
    assert labels[-1].strip() == "Try the demo"
    assert nav.count("nav-cta") == 1 and "github.com" not in nav


def test_security_pages_say_research_is_welcome_and_unpaid() -> None:
    en, de = _text("/en/security/"), _text("/de/sicherheit/")
    assert "security/advisories/new" in page("/en/security/")
    assert "unpaid" in en and "unbezahlt" in de
    assert "one maintainer" in en.lower() and "external audit" in en.lower()


def test_security_md_says_reports_are_unpaid() -> None:
    text = (Path(__file__).parents[1] / "SECURITY.md").read_text()
    # The heading says "unpaid" too: the sentence itself must stay.
    assert "There is no payment" in text and "security/advisories/new" in text
