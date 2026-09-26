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


def _resolve_nav_target(page: Path, href: str) -> str:
    """Resolve a nav ``href`` to a canonical, page-independent target string.

    An absolute URL (GitHub, the demo) is returned unchanged -- every page
    that links to it uses the identical string, so no resolution is needed.
    A relative href is resolved against ``page``'s own directory; a target
    that resolves to a directory is treated as that directory's
    ``index.html`` (a trailing-slash link and an explicit ``index.html``
    link are the same page). Finally, ``docs/de/index.html`` is folded onto
    ``docs/index.html`` -- the two are each page's own language mirror of
    "home", so e.g. Features/How-it-works anchors on the German page and
    the English-tree pages point at the same conceptual target, and the
    language-switch link (which always targets the *other* language's home)
    resolves to the same bucket from either direction. The fragment (if any)
    is preserved, since Features and How-it-works are otherwise
    indistinguishable from the language switch.
    """
    if href.startswith(("http://", "https://")):
        return href
    path_part, _, frag = href.partition("#")
    resolved = page if path_part in ("", "./") else (page.parent / path_part).resolve()
    if resolved.is_dir():
        resolved = resolved / "index.html"
    rel = str(resolved.relative_to(ROOT))
    if rel == "docs/de/index.html":
        rel = "docs/index.html"
    return rel + (f"#{frag}" if frag else "")


def _nav_targets(page: Path) -> set[str]:
    html = page.read_text()
    m = re.search(r'<ul class="nav-links"[^>]*>(.*?)</ul>', html, re.DOTALL)
    assert m, f"{page}: no <ul class=\"nav-links\"> found"
    return {
        _resolve_nav_target(page, href)
        for href in re.findall(r'<a\s+href="([^"]+)"', m.group(1))
    }


def test_every_docs_page_nav_has_the_same_item_set() -> None:
    """Regression guard (Task X12): docs.html and roadmap.html's nav lacked
    a Blog link and a language-switch link that every other docs/ page
    carried, and the blog scaffold's nav lacked Features/How-it-works and
    GitHub entirely. Every docs/**/*.html page's top nav must resolve to the
    exact same set of targets (see `_resolve_nav_target` for what "same"
    means across the English/German split), by href target rather than by
    label text (labels are legitimately localised on German-language pages,
    see `test_current_nav_item_is_marked`)."""
    pages = sorted((ROOT / "docs").rglob("*.html"))
    assert pages
    canonical_page = ROOT / "docs/index.html"
    canonical = _nav_targets(canonical_page)
    assert canonical, "docs/index.html nav resolved to no targets at all"
    mismatches = {}
    for page in pages:
        targets = _nav_targets(page)
        if targets != canonical:
            mismatches[str(page.relative_to(ROOT))] = {
                "missing": sorted(canonical - targets),
                "extra": sorted(targets - canonical),
            }
    assert not mismatches, mismatches


# Pages whose nav marks one specific item as the current page (by the
# resolved target from `_resolve_nav_target`); docs/index.html and
# docs/de/index.html are home pages with no single discrete nav item to
# mark (Features/How-it-works are anchors into the same page, not a
# separate "home" entry) and so carry none.
_CURRENT_NAV_TARGET = {
    "docs/docs.html": "docs/docs.html",
    "docs/roadmap.html": "docs/roadmap.html",
    **{
        f"docs/blog/{p.name}": "docs/blog/index.html"
        for p in sorted((ROOT / "docs" / "blog").glob("*.html"))
    },
}


def test_current_nav_item_is_marked() -> None:
    """Every page in `_CURRENT_NAV_TARGET` marks its own nav item
    `aria-current="page"`, on the anchor whose resolved target is that
    page's own target -- and no other nav item on that page is marked."""
    for page_str, own_target in _CURRENT_NAV_TARGET.items():
        page = ROOT / page_str
        html = page.read_text()
        m = re.search(r'<ul class="nav-links"[^>]*>(.*?)</ul>', html, re.DOTALL)
        assert m, page_str
        anchors = re.findall(r'<a\s+([^>]*href="[^"]+"[^>]*)>', m.group(1))
        marked = [a for a in anchors if 'aria-current="page"' in a]
        assert len(marked) == 1, (page_str, marked)
        href_m = re.search(r'href="([^"]+)"', marked[0])
        assert href_m
        assert _resolve_nav_target(page, href_m.group(1)) == own_target, (
            page_str, href_m.group(1)
        )


def _footer_targets(page: Path) -> set[str]:
    html = page.read_text()
    m = re.search(r'<ul class="footer-links"[^>]*>(.*?)</ul>', html, re.DOTALL)
    assert m, f"{page}: no <ul class=\"footer-links\"> found"
    return {
        _resolve_nav_target(page, href)
        for href in re.findall(r'<a\s+href="([^"]+)"', m.group(1))
    }


# Every page's footer link-list must resolve to the same target set as its
# landing page: docs/blog/index.html for the blog section (not
# docs/de/index.html -- that page's footer links *out* to the blog section as
# a "Blog" entry, which a page already inside that section has no reason to
# link back to itself, so the two can never share an identical set regardless
# of maintenance), docs/de/index.html for itself, and docs/index.html for
# every other page -- no page is exempt (Task X12 fix round 2: docs.html and
# roadmap.html used to carry a structurally different, much smaller footer
# with no `.footer-links` list at all; they now carry the same footer as
# docs/index.html, so they're covered like every other page).
def _footer_landing_page(page: Path) -> Path:
    if page.parent.name == "blog":
        return ROOT / "docs/blog/index.html"
    if page == ROOT / "docs/de/index.html":
        return page
    return ROOT / "docs/index.html"


def test_every_page_footer_has_the_same_link_set_as_its_landing_page() -> None:
    """Regression guard (Task X12 fix rounds 1-2): the four blog articles
    kept their old, smaller footer link-list (6 targets, missing Issues and
    License) after docs/blog/index.html was rebuilt with the full one (7
    targets) -- round 1. docs.html/roadmap.html carried an entirely
    different, much smaller footer (no `.footer-links` list at all) -- round
    2. Every docs/**/*.html page must resolve to the exact same footer
    link-target set as its landing page (see `_footer_landing_page`); no
    page is exempt."""
    pages = sorted((ROOT / "docs").rglob("*.html"))
    assert pages
    mismatches = {}
    for page in pages:
        landing = _footer_landing_page(page)
        targets = _footer_targets(page)
        canonical = _footer_targets(landing)
        if targets != canonical:
            mismatches[str(page.relative_to(ROOT))] = {
                "missing": sorted(canonical - targets),
                "extra": sorted(targets - canonical),
            }
    assert not mismatches, mismatches


def _root_tokens_dict(html: str) -> dict[str, str]:
    m = re.search(r":root\s*\{([^}]*)\}", html, re.DOTALL)
    assert m, ":root token block not found"
    return dict(re.findall(r"(--[\w-]+):\s*([^;]+);", m.group(1)))


def test_blog_pages_share_design_tokens_with_english_landing() -> None:
    """Extends `test_de_landing_page_shares_design_tokens_with_english`
    (Task X11) to the blog (Task X12): the blog scaffold used to run its own
    Spectral/Source Serif 4 + navy design, disconnected from the rest of the
    site. Unlike the strict de/index.html <-> index.html guard, this is not
    byte-identical -- the blog (like docs.html before it) legitimately
    extends the shared token set with its own `--warning`/`--warning-fog`
    (needed for `.callout-warn`/`.val-warn`, see
    test_docs_warn_callouts_do_not_converge_on_the_accent) that
    docs/index.html itself has no use for. What must hold is that every
    token blog *does* share by name with docs/index.html has the identical
    value -- no silent drift on the tokens that are supposed to be shared."""
    en_tokens = _root_tokens_dict((ROOT / "docs/index.html").read_text())
    for page in sorted((ROOT / "docs/blog").glob("*.html")):
        blog_tokens = _root_tokens_dict(page.read_text())
        shared = set(en_tokens) & set(blog_tokens)
        assert shared, page.name
        mismatches = {
            k: (en_tokens[k], blog_tokens[k])
            for k in shared
            if en_tokens[k].strip() != blog_tokens[k].strip()
        }
        assert not mismatches, (page.name, mismatches)
        for var in ("--font-display", "--font-body", "--font-mono"):
            assert var in blog_tokens, (page.name, var)


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
