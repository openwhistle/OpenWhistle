"""Imprint and privacy policy state exactly this setup (spec § Legal pages, W4)."""

from __future__ import annotations

import datetime
import os
import re
import subprocess

import pytest
import yaml

from tests.built_site import ROOT, built, page

# Where the address was: the operator mounts it, so neither the repo nor the image holds it (R16).
INCLUDE = '<!--# include virtual="/_private/address.html" -->'
ADDRESS = "{address}"
# The redesign spec's § Legal pages text, line for line; compared word for word.
IMPRINT = """
Impressum
Inhalte gemäß § 5 DDG
{address}
Kontaktdaten:
E-Mail: info@openwhistle.net
Redaktionell verantwortlich (§ 18 Abs. 2 MStV):
{address}
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
    html = html.replace(INCLUDE, ADDRESS)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).replace("&amp;", "&").strip()


def test_the_imprint_is_the_provider_text_word_for_word() -> None:
    assert _main("/impressum/") == " ".join(IMPRINT.split())


def test_each_privacy_policy_includes_the_address_once_in_its_controller_section() -> None:
    for url, section in (("/de/datenschutz/", "verantwortlich"), ("/en/privacy/", "controller")):
        html = page(url)
        controller = html.split(f'id="{section}"', 1)[1].split("</section>", 1)[0]
        assert html.count(INCLUDE) == 1 and INCLUDE in controller, url
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", controller.replace(INCLUDE, ADDRESS)))
        assert re.search(rf"{re.escape(ADDRESS)} E-[Mm]ail: info@openwhistle\.net", text), url


def _leaks(forbidden: list[str]) -> list[str]:
    files = subprocess.run(
        ["git", "ls-files", "-z"],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout.split(b"\0")
    leaks = []
    for name in filter(None, files):
        path = ROOT / name.decode()
        if path.is_file():
            data = path.read_bytes()
            # The index, never the string: the message must not leak what it found.
            leaks += [
                f"{name.decode()}: string {i}"
                for i, s in enumerate(forbidden, 1)
                if s.encode() in data
            ]
    return leaks


def test_the_real_data_scan_finds_the_fixture_person() -> None:
    assert "tests/website/fixtures/private/address.html: string 1" in _leaks(["Erika Mustermann"])


def test_no_file_in_the_repository_holds_the_real_data() -> None:
    """The strings come from the environment, never the repo: naming them here leaks them."""
    forbidden = [s.strip() for s in os.environ.get("OW_PRIVATE_STRINGS", "").splitlines()]
    forbidden = [s for s in forbidden if s]
    if not forbidden:
        pytest.skip("OW_PRIVATE_STRINGS is not set")
    assert not (leaks := _leaks(forbidden)), leaks


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
        ):
            assert fact in text, (url, fact)
        assert not BOILERPLATE.search(text), (url, BOILERPLATE.search(text))


def _demo_cookies() -> set[str]:
    # Every cookie name the app sets, read from its source: a new cookie must reach the policy.
    names = set()
    for path in (ROOT / "app").rglob("*.py"):
        code = path.read_text(encoding="utf-8")
        names.update(re.findall(r'set_cookie\(\s*(?:key=)?"([^"]+)"', code))
        names.update(re.findall(r'^_CSRF_COOKIE = "([^"]+)"', code, re.M))
    return names


def test_the_demo_section_names_its_cookies_their_basis_and_processor() -> None:
    # The demo footer links this policy, so it is the demo's notice too (spec P3-7).
    cookies = _demo_cookies()
    assert {"ow_csrf", "ow_session", "ow-lang"} <= cookies, cookies
    for url, facts in (
        ("/de/datenschutz/", ("§ 25 Abs. 2 Nr. 2 TDDDG", "Art. 28 DSGVO", "ow-theme")),
        ("/en/privacy/", ("§ 25(2) no. 2 TDDDG", "Art. 28 GDPR", "ow-theme")),
    ):
        demo = page(url).split('id="demo"', 1)[1].split("</section>", 1)[0]
        demo = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", demo))
        for fact in (*sorted(cookies), *facts):
            assert fact in demo, (url, fact)


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
    # RFC 9116 § 2.5.5: less than a year; the monthly rebuild renews it long before it lapses.
    day = datetime.timedelta(days=1)
    assert now + 31 * day < expires <= now + 336 * day, expires


def test_the_image_renews_security_txt_monthly() -> None:
    # The scheduled run rebuilds and publishes the image, so the deployed file stays young.
    workflow = yaml.safe_load((ROOT / ".github/workflows/website-image.yml").read_text())
    # `on:` parses as True in YAML 1.1.
    assert {"cron": "41 4 2 * *"} in workflow[True]["schedule"]
