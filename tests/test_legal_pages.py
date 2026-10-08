"""Imprint and privacy policy state exactly this setup (spec § Legal pages, W4)."""

from __future__ import annotations

import datetime
import re

import yaml

from tests.built_site import ROOT, built, page

# The redesign spec's § Legal pages text, line for line; compared word for word.
IMPRINT = """
Impressum
Inhalte gemäß § 5 DDG
Jochen Pylypiw
c/o IP-Management #12226
Ludwig-Erhard-Straße 18
20459 Hamburg
Kontaktdaten:
E-Mail: info@openwhistle.net
Redaktionell verantwortlich (§ 18 Abs. 2 MStV):
Jochen Pylypiw
c/o IP-Management #12226
Ludwig-Erhard-Straße 18
20459 Hamburg
Quelle: Impressum-Privatschutz
"""

PLACEHOLDER = re.compile(r"Platzhalter|Placeholder|TODO|TBD|Lorem|\[[^\]]*\]|XXX", re.I)
# Generator text for a site this is not: cookies to consent to, trackers, forms, social media.
BOILERPLATE = re.compile(
    r"Google|Matomo|Facebook|Instagram|LinkedIn|Newsletter|Kontaktformular|contact form|Consent|"
    r"Einwilligung|Cookie-Banner|Zahlungsdienstleister|payment service provider",
    re.I,
)


def _main(url: str) -> str:
    # From the end of the <main id="main-content" ...> tag, whatever attributes follow the id.
    html = page(url).split('id="main-content"', 1)[1].split(">", 1)[1].split("</main>", 1)[0]
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).replace("&amp;", "&").strip()


def test_the_imprint_is_the_provider_text_word_for_word() -> None:
    assert _main("/impressum/") == " ".join(IMPRINT.split())


def test_no_placeholder_in_imprint_or_privacy_policy() -> None:
    for url in ("/impressum/", "/de/datenschutz/", "/en/privacy/"):
        assert not PLACEHOLDER.search(_main(url)), (url, PLACEHOLDER.search(_main(url)))


def test_the_privacy_policy_names_this_setup_and_nothing_else() -> None:
    for url in ("/de/datenschutz/", "/en/privacy/"):
        text = _main(url)
        for fact in (
            "GitHub Pages",
            "GitHub B.V.",
            "Hetzner Online GmbH",
            "ow-theme",
            "info@openwhistle.net",
            "demo.openwhistle.net",
            "IP-Management",
        ):
            assert fact in text, (url, fact)
        assert not BOILERPLATE.search(text), (url, BOILERPLATE.search(text))


# Per language: the retention periods in context, the transfer basis and every legal basis.
FACTS = {
    "/de/datenschutz/": (
        "30 Tage auf dem Server und 365 Tage",
        "30 Tage auf dem Server und 90 Tage",
        "EU-U.S. Data Privacy Framework",
        "§ 25 Abs. 2 Nr. 2 TDDDG",
        "Art. 28 DSGVO",
        "Art. 77 DSGVO",
    ),
    "/en/privacy/": (
        "30 days on the server and 365 days",
        "30 days on the server and 90 days",
        "EU-U.S. Data Privacy Framework",
        "§ 25(2) no. 2 TDDDG",
        "Art. 28 GDPR",
        "Art. 77 GDPR",
    ),
}


def test_both_languages_state_the_same_periods_and_legal_bases() -> None:
    for url, facts in FACTS.items():
        text = _main(url)
        for fact in facts:
            assert fact in text, (url, fact)


def test_every_footer_links_imprint_and_privacy_in_its_language() -> None:
    en, de = page("/en/"), page("/de/")
    # The imprint is German only: an English page says so with hreflang and lang.
    assert (
        '<a href="/impressum/" hreflang="de">Legal notice (<span lang="de">Impressum</span>)</a>'
        in en
    )
    assert '<a href="/impressum/">Impressum</a>' in de
    assert 'href="/en/privacy/"' in en and 'href="/de/datenschutz/"' in de


def test_security_txt_is_valid_and_not_expired() -> None:
    text = (built() / ".well-known" / "security.txt").read_text()
    fields = dict(
        line.split(": ", 1) for line in text.splitlines() if line and not line.startswith("#")
    )
    assert fields["Contact"] == "https://github.com/openwhistle/OpenWhistle/security/advisories/new"
    assert fields["Canonical"] == "https://openwhistle.net/.well-known/security.txt"
    assert fields["Policy"] == "https://openwhistle.net/en/security/"
    assert fields["Preferred-Languages"] == "en, de"
    expires = datetime.datetime.fromisoformat(fields["Expires"].replace("Z", "+00:00"))
    now = datetime.datetime.now(datetime.UTC)
    assert now < expires <= now + datetime.timedelta(days=366), expires


def test_the_pages_deploy_ships_well_known_and_renews_it_monthly() -> None:
    # upload-pages-artifact drops every dot-directory unless told otherwise.
    workflow = yaml.safe_load((ROOT / ".github/workflows/pages.yml").read_text())
    upload = next(
        step
        for step in workflow["jobs"]["deploy"]["steps"]
        if step.get("uses", "").startswith("actions/upload-pages-artifact@")
    )
    assert str(upload["with"].get("include-hidden-files")).lower() == "true"
    # `on:` parses as True in YAML 1.1.
    assert {"cron": "17 4 1 * *"} in workflow[True]["schedule"]
