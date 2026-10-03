"""The roadmap lives on the website, not in a ROADMAP.md a stranger has to
clone the repo to read. These guards keep it that way: the file stays gone,
every page's nav points at it, no version already shipped is shown as
planned, and the page never reaches out to a font CDN."""

import html as html_lib
import json
import re
from pathlib import Path

from tests.built_site import builder, built, css_of, page, pages

ROOT = Path(__file__).parents[1]


def _url(path: Path) -> str:
    """The URL a built file is served at: a folder's index.html at the folder."""
    return "/" + path.relative_to(built()).as_posix().removesuffix("index.html")


# Every blog page, discovered from the build: both indexes and every article,
# so a new article cannot miss a guard unnoticed.
BLOG_PAGES = [
    "/en/blog/",
    "/de/blog/",
    *(_url(p) for p in sorted((built() / "en/blog").glob("*/index.html"))),
    *(_url(p) for p in sorted((built() / "de/blog").glob("*/index.html"))),
]

# Every page whose top nav must carry a "Roadmap" link. The roadmap is English
# only, so the German pages link the English one.
NAV_PAGES = ["/en/", "/de/", "/en/docs/", "/en/roadmap/", *BLOG_PAGES]
ROADMAP = "/en/roadmap/"


def _app_version() -> tuple[int, ...]:
    # Same source tests/test_v100.py::test_every_published_version_string_matches
    # reads from, rather than a second regex over app/config.py's source text.
    from app.config import settings

    return tuple(int(p) for p in settings.app_version.split("."))


def test_roadmap_md_does_not_exist() -> None:
    assert not (ROOT / "ROADMAP.md").exists(), (
        "ROADMAP.md must be gone — the roadmap lives at /en/roadmap/ now"
    )


def test_roadmap_page_exists() -> None:
    assert (ROOT / "docs/en/roadmap/index.html").is_file()
    assert builder().output_file(built(), ROADMAP).is_file()


def test_every_nav_page_links_to_roadmap() -> None:
    assert len(BLOG_PAGES) > 2, "no blog article found in the build"
    missing = []
    for url in NAV_PAGES:
        html = page(url)
        nav_match = re.search(r'<ul class="nav-links"[^>]*>.*?</ul>', html, re.DOTALL)
        assert nav_match, f"{url}: no <ul class=\"nav-links\"> found"
        if f'href="{ROADMAP}"' not in nav_match.group(0):
            missing.append(url)
    assert not missing, f"pages whose nav does not link to {ROADMAP}: {missing}"


def test_roadmap_has_no_released_version_as_planned_heading() -> None:
    html = page(ROADMAP)
    current = _app_version()
    headings = re.findall(r"<h2[^>]*>\s*v(\d+\.\d+\.\d+)\b", html)
    assert headings, f"{ROADMAP} has no version headings to check"
    released = [
        v for v in headings if tuple(int(p) for p in v.split(".")) <= current
    ]
    assert not released, (
        f"roadmap.html shows already-released version(s) as planned: {released} "
        f"(current app_version is {'.'.join(map(str, current))})"
    )


def test_roadmap_uses_only_self_hosted_fonts() -> None:
    html = page(ROADMAP)
    text = html + css_of(html)
    assert "fonts.googleapis.com" not in text
    assert "fonts.gstatic.com" not in text
    assert re.search(r"@font-face\s*\{[^}]*url\(['\"]?/fonts/", css_of(html)), (
        f"{ROADMAP} must declare its fonts from /fonts/, like /en/docs/ does"
    )


def test_roadmap_points_to_changelog_for_everything_released() -> None:
    html = page(ROADMAP)
    assert "CHANGELOG.md" in html


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
    """Regression guard: docs/de/index.html's FAQPage
    JSON-LD used to carry a question ("Was ist ein Hinweisgebersystem nach
    HinSchG?") that doesn't appear anywhere in the visible FAQ list, and was
    missing several visible questions outright (5 JSON-LD entries vs. 8
    visible). Search engines index the JSON-LD, so a mismatch there is
    effectively lying to search results. Pin same count, same order, and a
    substantial word overlap per question/answer pair (not byte-for-byte:
    docs/en/index.html's own JSON-LD already paraphrases its visible answers
    slightly, e.g. "Does OpenWhistle comply" vs. "Does it comply" -- this
    guard would otherwise be RED on the English page too)."""
    for url in ("/en/", "/de/"):
        html = page(url)
        jsonld_pairs = _faqpage_jsonld(html)
        visible_pairs = _visible_faq(html)
        assert len(jsonld_pairs) == len(visible_pairs), (
            url, len(jsonld_pairs), len(visible_pairs)
        )
        for i, ((jq, ja), (vq, va)) in enumerate(
            zip(jsonld_pairs, visible_pairs, strict=True)
        ):
            assert _word_overlap(jq, vq) >= 0.6, (url, i, "question", jq, vq)
            assert _word_overlap(ja, va) >= 0.6, (url, i, "answer", ja, va)


def _resolve_nav_target(page: Path, href: str) -> str:
    """Resolve a nav ``href`` (on the built file ``page``) to a canonical,
    page-independent target string: the target's path relative to the built
    site.

    An absolute URL (GitHub, the demo) is returned unchanged -- every page
    that links to it uses the identical string, so no resolution is needed.
    A root-relative href resolves against the site root, a relative one
    against ``page``'s own directory; a target that resolves to a directory
    is treated as that directory's ``index.html`` (a trailing-slash link and
    an explicit ``index.html`` link are the same page). The fragment (if any)
    is preserved, since Features and How-it-works are otherwise
    indistinguishable from home.
    """
    if href.startswith(("http://", "https://")):
        return href
    path_part, _, frag = href.partition("#")
    site = built().resolve()
    if path_part.startswith("/"):
        resolved = (site / path_part.lstrip("/")).resolve()
    elif path_part in ("", "./"):
        resolved = page.resolve()
    else:
        resolved = (page.parent / path_part).resolve()
    if resolved.is_dir():
        resolved = resolved / "index.html"
    rel = resolved.relative_to(site).as_posix()
    return rel + (f"#{frag}" if frag else "")


# A link with ``hreflang`` is the language switch: on a blog article it names
# the article's twin, on the other pages the other language's home -- one
# bucket, whatever its target.
_LANGUAGE_SWITCH = "<language switch>"


def _link_targets(page: Path, links_html: str) -> set[str]:
    """Resolved targets of a link list."""
    targets = set()
    for attrs in re.findall(r"<a\s+([^>]*)>", links_html):
        href = re.search(r'href="([^"]+)"', attrs)
        if not href:
            continue
        targets.add(
            _LANGUAGE_SWITCH if "hreflang=" in attrs else _resolve_nav_target(page, href.group(1))
        )
    return targets


def _nav_targets(page: Path) -> set[str]:
    html = page.read_text()
    m = re.search(r'<ul class="nav-links"[^>]*>(.*?)</ul>', html, re.DOTALL)
    assert m, f"{page}: no <ul class=\"nav-links\"> found"
    return _link_targets(page, m.group(1))


def _lang(page: Path) -> str:
    m = re.search(r'<html lang="([a-z]+)"', page.read_text())
    assert m, f"{page}: no <html lang>"
    return m.group(1)


def test_every_docs_page_nav_has_the_same_item_set() -> None:
    """Regression guard: docs.html and roadmap.html's nav lacked
    a Blog link and a language-switch link that every other page carried,
    and the blog scaffold's nav lacked Features/How-it-works and GitHub
    entirely. Every built page's top nav must resolve to the exact same set
    of targets as its own language's home, by href target rather than by
    label text (labels are legitimately localised on German-language pages,
    see `test_current_nav_item_is_marked`)."""
    built_pages = pages()
    assert built_pages
    home = {lang: _nav_targets(built() / lang / "index.html") for lang in ("en", "de")}
    assert all(home.values()), "a home page's nav resolved to no targets at all"
    mismatches = {}
    for path in built_pages:
        targets = _nav_targets(path)
        canonical = home[_lang(path)]
        if targets != canonical:
            mismatches[_url(path)] = {
                "missing": sorted(canonical - targets),
                "extra": sorted(targets - canonical),
            }
    assert not mismatches, mismatches


def _fold_language(targets: set[str]) -> set[str]:
    """/de/... onto /en/...: the German twin of a page counts as that page.
    English-only pages are linked at /en/ from both homes already."""
    return {"en/" + t.removeprefix("de/") if t.startswith("de/") else t for t in targets}


def test_the_german_home_links_what_the_english_home_links() -> None:
    """Per-language comparison alone would let the two languages drift apart;
    the German home's nav and footer, language folded, must equal the English."""
    en, de = built() / "en/index.html", built() / "de/index.html"
    assert _fold_language(_nav_targets(de)) == _nav_targets(en)
    assert _fold_language(_footer_targets(de)) == _footer_targets(en)


# Pages whose nav marks one specific item as the current page (by the
# resolved target from `_resolve_nav_target`); /en/ and /de/ are home pages
# with no single discrete nav item to mark (Features/How-it-works are anchors
# into the same page, not a separate "home" entry) and so carry none.
_CURRENT_NAV_TARGET = {
    "/en/docs/": "en/docs/index.html",
    "/en/roadmap/": "en/roadmap/index.html",
    "/en/changelog/": "en/changelog/index.html",
    **{url: f"{url.split('/')[1]}/blog/index.html" for url in BLOG_PAGES},
}


def test_current_nav_item_is_marked() -> None:
    """Every page in `_CURRENT_NAV_TARGET` marks its own nav item
    `aria-current="page"`, on the anchor whose resolved target is that
    page's own target -- and no other nav item on that page is marked."""
    for page_str, own_target in _CURRENT_NAV_TARGET.items():
        path = builder().output_file(built(), page_str)
        html = path.read_text()
        m = re.search(r'<ul class="nav-links"[^>]*>(.*?)</ul>', html, re.DOTALL)
        assert m, page_str
        anchors = re.findall(r'<a\s+([^>]*href="[^"]+"[^>]*)>', m.group(1))
        marked = [a for a in anchors if 'aria-current="page"' in a]
        assert len(marked) == 1, (page_str, marked)
        href_m = re.search(r'href="([^"]+)"', marked[0])
        assert href_m
        assert _resolve_nav_target(path, href_m.group(1)) == own_target, (
            page_str, href_m.group(1)
        )


def _footer_targets(page: Path) -> set[str]:
    html = page.read_text()
    m = re.search(r'<ul class="footer-links"[^>]*>(.*?)</ul>', html, re.DOTALL)
    assert m, f"{page}: no <ul class=\"footer-links\"> found"
    return _link_targets(page, m.group(1))


# Every page's footer link-list must resolve to the same target set as its
# landing page, in the page's own language: <lang>/blog/index.html for the
# blog section (the home's footer links *out* to the blog section as a "Blog"
# entry, which a page already inside that section has no reason to link back
# to itself), and <lang>/index.html for every other page -- no page is exempt.
def _footer_landing_page(page: Path) -> Path:
    lang = _lang(page)
    if "blog" in page.relative_to(built()).parts:
        return built() / lang / "blog" / "index.html"
    return built() / lang / "index.html"


def test_every_page_footer_has_the_same_link_set_as_its_landing_page() -> None:
    """Regression guard: the four blog articles kept their old, smaller
    footer link-list (6 targets, missing Issues and License) after
    docs/de/blog/index.html was rebuilt with the full one (7 targets), and
    docs.html/roadmap.html carried an entirely different, much smaller
    footer (no `.footer-links` list at all). Every built page must resolve
    to the exact same footer link-target set as its landing page (see
    `_footer_landing_page`); no page is exempt."""
    built_pages = pages()
    assert built_pages
    mismatches = {}
    for path in built_pages:
        landing = _footer_landing_page(path)
        targets = _footer_targets(path)
        canonical = _footer_targets(landing)
        if targets != canonical:
            mismatches[_url(path)] = {
                "missing": sorted(canonical - targets),
                "extra": sorted(targets - canonical),
            }
    assert not mismatches, mismatches


def test_landing_pages_link_each_other_via_hreflang() -> None:
    """Regression guard: neither page declared
    hreflang alternates for the other before this. Every one of the two
    pages must declare itself, the other language, and an x-default,
    pointing at absolute URLs."""
    en = page("/en/")
    de = page("/de/")

    for html, own in ((en, "en"), (de, "de")):
        for lang, href in (
            ("en", "https://openwhistle.net/en/"),
            ("de", "https://openwhistle.net/de/"),
            ("x-default", "https://openwhistle.net/"),
        ):
            tag = f'<link rel="alternate" hreflang="{lang}" href="{href}">'
            assert tag in html, (own, lang, tag)


def test_every_blog_page_exists_in_english_and_german() -> None:
    """The blog was German only. Every page has its twin in the other
    language, named by hreflang (tests/test_seo.py holds the pair reciprocal)."""
    missing = []
    assert len(BLOG_PAGES) > 2, "no blog article found in the build"
    for url in BLOG_PAGES:
        html = page(url)
        lang = re.search(r'<html lang="([a-z]+)"', html)
        assert lang, url
        other = "de" if lang.group(1) == "en" else "en"
        if f'hreflang="{other}"' not in html.split("</head>")[0]:
            missing.append(url)
    assert not missing, missing
