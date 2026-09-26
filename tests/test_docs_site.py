"""The roadmap lives on the website, not in a ROADMAP.md a stranger has to
clone the repo to read. These guards keep it that way: the file stays gone,
every page's nav points at it, no version already shipped is shown as
planned, and the page never reaches out to a font CDN."""

import html as html_lib
import json
import re
from pathlib import Path

ROOT = Path(__file__).parents[1]

# Every page whose top nav must carry a "Roadmap" link, and the relative
# path from that page to docs/roadmap.html.
NAV_PAGES = {
    "docs/index.html": "roadmap.html",
    "docs/de/index.html": "../roadmap.html",
    "docs/docs.html": "roadmap.html",
    "docs/roadmap.html": "roadmap.html",
    # Every blog page, discovered — a new article cannot miss the link unnoticed.
    **{
        f"docs/blog/{p.name}": "../roadmap.html"
        for p in sorted((ROOT / "docs" / "blog").glob("*.html"))
    },
}


def _app_version() -> tuple[int, ...]:
    # Same source tests/test_v100.py::test_every_published_version_string_matches
    # reads from, rather than a second regex over app/config.py's source text.
    from app.config import settings

    return tuple(int(p) for p in settings.app_version.split("."))


def test_roadmap_md_does_not_exist() -> None:
    assert not (ROOT / "ROADMAP.md").exists(), (
        "ROADMAP.md must be gone — the roadmap lives at docs/roadmap.html now"
    )


def test_roadmap_page_exists() -> None:
    assert (ROOT / "docs/roadmap.html").is_file()


def test_every_nav_page_links_to_roadmap() -> None:
    missing = []
    for page, href in NAV_PAGES.items():
        html = (ROOT / page).read_text()
        nav_match = re.search(r'<ul class="nav-links"[^>]*>.*?</ul>', html, re.DOTALL)
        assert nav_match, f"{page}: no <ul class=\"nav-links\"> found"
        if f'href="{href}"' not in nav_match.group(0):
            missing.append(page)
    assert not missing, f"pages whose nav does not link to roadmap.html: {missing}"


def test_roadmap_has_no_released_version_as_planned_heading() -> None:
    html = (ROOT / "docs/roadmap.html").read_text()
    current = _app_version()
    headings = re.findall(r"<h2[^>]*>\s*v(\d+\.\d+\.\d+)\b", html)
    assert headings, "docs/roadmap.html has no version headings to check"
    released = [
        v for v in headings if tuple(int(p) for p in v.split(".")) <= current
    ]
    assert not released, (
        f"roadmap.html shows already-released version(s) as planned: {released} "
        f"(current app_version is {'.'.join(map(str, current))})"
    )


def test_roadmap_uses_only_self_hosted_fonts() -> None:
    html = (ROOT / "docs/roadmap.html").read_text()
    assert "fonts.googleapis.com" not in html
    assert "fonts.gstatic.com" not in html
    assert re.search(r"@font-face\s*\{[^}]*url\(['\"]?fonts/", html), (
        "docs/roadmap.html must declare its fonts from docs/fonts/, like docs/docs.html does"
    )


def test_roadmap_points_to_changelog_for_everything_released() -> None:
    html = (ROOT / "docs/roadmap.html").read_text()
    assert "CHANGELOG.md" in html


def _root_tokens_block(html: str) -> str:
    """The first top-level `:root { ... }` block (the light-mode design
    tokens), whitespace-normalised so formatting differences don't matter."""
    m = re.search(r":root\s*\{([^}]*)\}", html, re.DOTALL)
    assert m, ":root token block not found"
    return re.sub(r"\s+", " ", m.group(1)).strip()


def test_de_landing_page_shares_design_tokens_with_english() -> None:
    """Regression guard (Task X11): docs/index.html was rebuilt onto the
    "Signal" design (Sora + JetBrains Mono, ink/green tokens) while
    docs/de/index.html kept an older serif/navy design, so the two pages
    drifted apart. Pin the :root tokens and font-family variables identical
    so a future edit to one page can't silently un-sync the other."""
    en = (ROOT / "docs/index.html").read_text()
    de = (ROOT / "docs/de/index.html").read_text()
    assert _root_tokens_block(en) == _root_tokens_block(de)
    for var in ("--font-display", "--font-body", "--font-mono"):
        pattern = re.escape(var) + r":\s*([^;]+);"
        en_m, de_m = re.search(pattern, en), re.search(pattern, de)
        assert en_m and de_m, var
        assert en_m.group(1).strip() == de_m.group(1).strip(), (
            var, en_m.group(1), de_m.group(1)
        )


def _clean_text(s: str) -> str:
    """Strip tags, unescape entities (so a visible `&nbsp;` matches a JSON-LD
    plain space), collapse whitespace."""
    return re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", "", s))).strip()


def _word_set(s: str) -> set[str]:
    return set(re.findall(r"[a-zA-ZäöüÄÖÜß]+", s.lower()))


def _word_overlap(a: str, b: str) -> float:
    wa, wb = _word_set(a), _word_set(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / max(len(wa), len(wb))


def _faqpage_jsonld(html: str) -> list[tuple[str, str]]:
    for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL):
        data = json.loads(block)
        if data.get("@type") == "FAQPage":
            return [
                (_clean_text(e["name"]), _clean_text(e["acceptedAnswer"]["text"]))
                for e in data["mainEntity"]
            ]
    raise AssertionError("no FAQPage JSON-LD script found")


def _visible_faq(html: str) -> list[tuple[str, str]]:
    items = re.findall(
        r'<details class="faq-item">\s*<summary>(.*?)</summary>\s*'
        r'<div class="faq-answer">(.*?)</div>\s*</details>',
        html,
        re.DOTALL,
    )
    assert items, "no visible FAQ items found"
    return [(_clean_text(q), _clean_text(a)) for q, a in items]


def test_faqpage_jsonld_matches_visible_faq_one_to_one() -> None:
    """Regression guard (Task X11 fix round 1): docs/de/index.html's FAQPage
    JSON-LD used to carry a question ("Was ist ein Hinweisgebersystem nach
    HinSchG?") that doesn't appear anywhere in the visible FAQ list, and was
    missing several visible questions outright (5 JSON-LD entries vs. 8
    visible). Search engines index the JSON-LD, so a mismatch there is
    effectively lying to search results. Pin same count, same order, and a
    substantial word overlap per question/answer pair (not byte-for-byte:
    docs/index.html's own JSON-LD already paraphrases its visible answers
    slightly, e.g. "Does OpenWhistle comply" vs. "Does it comply" -- this
    guard would otherwise be RED on the English page too)."""
    for page in ("docs/index.html", "docs/de/index.html"):
        html = (ROOT / page).read_text()
        jsonld_pairs = _faqpage_jsonld(html)
        visible_pairs = _visible_faq(html)
        assert len(jsonld_pairs) == len(visible_pairs), (
            page, len(jsonld_pairs), len(visible_pairs)
        )
        for i, ((jq, ja), (vq, va)) in enumerate(
            zip(jsonld_pairs, visible_pairs, strict=True)
        ):
            assert _word_overlap(jq, vq) >= 0.6, (page, i, "question", jq, vq)
            assert _word_overlap(ja, va) >= 0.6, (page, i, "answer", ja, va)


def test_landing_pages_link_each_other_via_hreflang() -> None:
    """Regression guard (Task X11 fix round 1): neither page declared
    hreflang alternates for the other before this. Every one of the two
    pages must declare itself, the other language, and an x-default,
    pointing at absolute URLs."""
    en = (ROOT / "docs/index.html").read_text()
    de = (ROOT / "docs/de/index.html").read_text()

    for html, own in ((en, "en"), (de, "de")):
        for lang, href in (
            ("en", "https://openwhistle.net/"),
            ("de", "https://openwhistle.net/de/"),
            ("x-default", "https://openwhistle.net/"),
        ):
            tag = f'<link rel="alternate" hreflang="{lang}" href="{href}">'
            assert tag in html, (own, lang, tag)
