"""The P3 pages: what each must say, so a rewrite cannot drop it."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

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


def test_the_nav_is_compliance_security_docs_blog_and_one_demo_button() -> None:
    nav = page("/en/").split('class="nav-links"', 1)[1].split("</ul>", 1)[0]
    labels = [label.strip() for label in re.findall(r">([^<]+)</a></li>", nav)]
    assert labels == ["Compliance", "Security", "Documentation", "Blog", "Deutsch", "Try the demo"]
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


def test_security_pages_name_codeql_and_link_its_alerts() -> None:
    for url in ("/en/security/", "/de/sicherheit/"):
        html = page(url)
        assert "CodeQL" in _text(url), url
        assert "github.com/openwhistle/OpenWhistle/security/code-scanning" in html, url


COMPLIANCE = {
    "/en/compliance/": "/de/compliance/",
    "/en/compliance/eu-directive/": "/de/compliance/eu-richtlinie/",
    "/en/compliance/hinschg/": "/de/compliance/hinschg/",
}


def test_compliance_pages_exist_in_both_languages_and_disclaim_advice() -> None:
    for en, de in COMPLIANCE.items():
        assert "not legal advice" in _text(en), en
        assert "keine Rechtsberatung" in _text(de), de


def test_each_law_page_has_one_requirement_table_with_proof_links() -> None:
    for url in (
        "/en/compliance/eu-directive/",
        "/en/compliance/hinschg/",
        "/de/compliance/eu-richtlinie/",
        "/de/compliance/hinschg/",
    ):
        html = page(url)
        assert html.count('class="env-table"') >= 1, url
        table = html.split('class="env-table"', 1)[1].split("</table>", 1)[0]
        rows = re.findall(r"<tr>(.*?)</tr>", table, re.S)[1:]
        assert len(rows) >= 7, (url, len(rows))
        for row in rows:
            assert 'href="/en/docs/' in row or "not covered" in row or "nicht abgedeckt" in row, (
                url,
                row,
            )


def test_the_old_hinschg_reference_leads_to_the_hinschg_page() -> None:
    redirects = yaml.safe_load((Path(__file__).parents[1] / "docs/_data/redirects.yml").read_text())
    assert redirects["/hinschg_reference.md"] == "/en/compliance/hinschg/"
    assert redirects["/en/docs/hinschg-reference/"] == "/en/compliance/hinschg/"
