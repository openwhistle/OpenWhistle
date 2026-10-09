"""Search-engine guards for the published site (built from docs/, served as openwhistle.net).

Every page is found by glob, so a page added by anyone is held to the same
head: one title of at most 60 characters, a unique description of 120-160,
a canonical URL that is the address the server serves the file at and the
sitemap lists, Open Graph tags with an image that exists, and JSON-LD that
parses. The sitemap is the one in the built site.
The docs-tech link ban lives in tests/test_docs_boundary.py.
"""

import datetime
import json
import re
import struct
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

import pytest

from tests.built_site import builder, built, pages

DOCS = built()
SITE = "https://openwhistle.net/"
PAGES = pages()
IDS = [str(p.relative_to(DOCS)) for p in PAGES]
LANDING = (DOCS / "en" / "index.html", DOCS / "de" / "index.html")
# The landing pair's exact en/de/x-default set is held by
# test_docs_site.py::test_landing_pages_link_each_other_via_hreflang.


class _Head(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.lang: str | None = None
        self.titles: list[str] = []
        self.meta: dict[str, list[str]] = {}
        self.links: list[dict[str, str]] = []
        self.jsonld: list[str] = []
        self.head_scripts: list[str] = []
        self._in: str | None = None
        self._in_head = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: v or "" for k, v in attrs}
        if tag == "html":
            self.lang = a.get("lang")
        elif tag == "head":
            self._in_head = True
        elif tag == "title":
            self._in, self._buf = "title", ""
        elif tag == "meta" and ("name" in a or "property" in a):
            key = a.get("name") or a["property"]
            self.meta.setdefault(key, []).append(a.get("content", ""))
        elif tag == "link":
            self.links.append(a | {"_head": "1" if self._in_head else ""})
        elif tag == "script":
            if a.get("type") == "application/ld+json":
                self._in, self._buf = "ld", ""
            elif self._in_head and a.get("src"):
                self.head_scripts.append(a["src"])

    def handle_endtag(self, tag: str) -> None:
        if tag == "head":
            self._in_head = False
        elif tag == "title" and self._in == "title":
            self.titles.append(self._buf.strip())
            self._in = None
        elif tag == "script" and self._in == "ld":
            self.jsonld.append(self._buf)
            self._in = None

    def handle_data(self, data: str) -> None:
        if self._in:
            self._buf += data

    def rel(self, rel: str) -> list[dict[str, str]]:
        return [link for link in self.links if link.get("rel") == rel]

    def alternates(self) -> dict[str, str]:
        alternate = self.rel("alternate")
        return {link["hreflang"]: link["href"] for link in alternate if "hreflang" in link}


def _head(page: Path) -> _Head:
    h = _Head()
    h.feed(page.read_text())
    return h


def _noindex(h: _Head) -> bool:
    return any("noindex" in c for c in h.meta.get("robots", []))


def _one(h: _Head, key: str) -> str:
    values = h.meta.get(key, [])
    assert len(values) == 1, (key, values)
    return values[0]


def _file_for(url: str) -> Path:
    """The file the server serves at `url`: a trailing slash is the folder's index.html."""
    assert url.startswith(SITE), url
    path = url.removeprefix(SITE)
    if path == "" or path.endswith(("/", ".html")):
        return builder().output_file(DOCS, "/" + path)
    return DOCS / path


def _png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()[:24]
    assert data[:8] == b"\x89PNG\r\n\x1a\n", path
    return struct.unpack(">II", data[16:24])


def _walk(obj: object):  # type: ignore[no-untyped-def]
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def _jsonld(page: Path) -> list[dict]:
    return [json.loads(b) for b in _head(page).jsonld]


def _indexable() -> list[Path]:
    return [p for p in PAGES if not _noindex(_head(p))]


def test_the_page_glob_finds_the_site() -> None:
    assert len(PAGES) >= 11, IDS


@pytest.mark.parametrize("page", PAGES, ids=IDS)
def test_head_basics(page: Path) -> None:
    h = _head(page)
    assert h.lang in ("en", "de"), h.lang
    assert len(h.titles) == 1, h.titles
    assert 10 <= len(h.titles[0]) <= 60, (len(h.titles[0]), h.titles[0])
    desc = _one(h, "description")
    assert 120 <= len(desc) <= 160, (len(desc), desc)
    for key in ("og:title", "og:description", "og:image", "twitter:card"):
        assert _one(h, key), key
    image = _one(h, "og:image")
    assert image.startswith(SITE), image
    width, height = _png_size(_file_for(image))
    assert width >= 1200 and height >= 600, (image, width, height)
    assert (_one(h, "og:image:width"), _one(h, "og:image:height")) == (str(width), str(height))


def test_titles_and_descriptions_are_unique() -> None:
    heads = {p: _head(p) for p in PAGES}
    titles = [h.titles[0] for h in heads.values()]
    descs = [_one(h, "description") for h in heads.values()]
    assert len(set(titles)) == len(titles), titles
    assert len(set(descs)) == len(descs), descs


@pytest.mark.parametrize("page", PAGES, ids=IDS)
def test_canonical_is_the_address_the_file_is_served_at(page: Path) -> None:
    h = _head(page)
    canonical = h.rel("canonical")
    if _noindex(h):
        assert not canonical, "a noindex page must not declare a canonical"
        return
    assert len(canonical) == 1, canonical
    url = canonical[0]["href"]
    assert url.startswith(SITE), url
    assert _file_for(url) == page, (url, page)
    assert _one(h, "og:url") == url


def _sitemap() -> dict[str, dict[str, str]]:
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9", "x": "http://www.w3.org/1999/xhtml"}
    root = ET.parse(DOCS / "sitemap.xml").getroot()  # noqa: S314 — our own built file
    out = {}
    today = datetime.datetime.now(datetime.UTC).date()
    for url in root.findall("s:url", ns):
        loc = url.findtext("s:loc", namespaces=ns)
        lastmod = url.findtext("s:lastmod", namespaces=ns)
        assert loc and lastmod, (loc, lastmod)
        assert datetime.date.fromisoformat(lastmod) <= today, (loc, lastmod)
        assert loc not in out, f"{loc} listed twice"
        out[loc] = {a.get("hreflang"): a.get("href") for a in url.findall("x:link", ns)}
    return out


def test_sitemap_lists_exactly_the_indexable_pages_with_their_alternates() -> None:
    sitemap = _sitemap()
    pages = {_head(p).rel("canonical")[0]["href"]: _head(p).alternates() for p in _indexable()}
    assert set(sitemap) == set(pages), {
        "missing": sorted(set(pages) - set(sitemap)),
        "extra": sorted(set(sitemap) - set(pages)),
    }
    for loc, alternates in pages.items():
        assert sitemap[loc] == alternates, (loc, sitemap[loc], alternates)


def test_robots_txt_points_at_the_sitemap() -> None:
    robots = (DOCS / "robots.txt").read_text()
    assert f"Sitemap: {SITE}sitemap.xml" in robots.splitlines()


@pytest.mark.parametrize("page", PAGES, ids=IDS)
def test_hreflang_is_reciprocal(page: Path) -> None:
    h = _head(page)
    alternates = h.alternates()
    if not alternates:
        return
    own = h.rel("canonical")[0]["href"]
    assert alternates.get(h.lang or "") == own, "a page's own language must point at itself"
    assert "x-default" in alternates, alternates
    for lang, url in alternates.items():
        if url == SITE:
            # "/" is the language choice (a redirect, not a page), and only the
            # two language homes name it as their x-default.
            assert lang == "x-default" and own in (f"{SITE}en/", f"{SITE}de/"), (lang, own)
            continue
        other = _head(_file_for(url))
        if lang != "x-default":
            assert other.lang == lang, (url, other.lang)
        assert other.alternates() == alternates, (url, other.alternates())


@pytest.mark.parametrize("page", PAGES, ids=IDS)
def test_jsonld_parses_and_invents_no_ratings(page: Path) -> None:
    for block in _jsonld(page):
        for node in _walk(block):
            assert not {"aggregateRating", "review"} & set(node), node.get("@type")


def test_software_version_is_the_app_version() -> None:
    from app.config import settings

    for page in LANDING:
        apps = [b for b in _jsonld(page) if b.get("@type") == "SoftwareApplication"]
        assert len(apps) == 1, page
        assert apps[0]["softwareVersion"] == settings.app_version, page
        assert apps[0]["offers"]["price"] == "0", page


@pytest.mark.parametrize(
    "page",
    # A post is <lang>/blog/<slug>/index.html; <lang>/blog/index.html is the index.
    [p for p in PAGES if p.parent.parent.name == "blog"],
    ids=lambda p: p.parent.name,
)
def test_blog_posts_carry_dated_blogposting(page: Path) -> None:
    h = _head(page)
    posts = [b for b in _jsonld(page) if b.get("@type") == "BlogPosting"]
    assert len(posts) == 1
    post = posts[0]
    published = datetime.date.fromisoformat(post["datePublished"])
    modified = datetime.date.fromisoformat(post["dateModified"])
    assert published <= modified <= datetime.date.today(), (published, modified)
    assert post["inLanguage"] == h.lang
    assert post["author"]["name"]
    assert _one(h, "article:published_time") == post["datePublished"]
    assert _one(h, "article:modified_time") == post["dateModified"]


@pytest.mark.parametrize("page", PAGES, ids=IDS)
def test_head_loads_nothing_from_another_host(page: Path) -> None:
    h = _head(page)
    external = [s for s in h.head_scripts if re.match(r"https?://", s)]
    external += [
        link["href"]
        for link in h.links
        if link["_head"]
        and link.get("rel") in ("stylesheet", "preload")
        and re.match(r"https?://", link["href"])
    ]
    assert not external, external
    for link in h.rel("preload"):
        href = link["href"]
        target = DOCS / href.lstrip("/") if href.startswith("/") else page.parent / href
        assert target.resolve().is_file(), link["href"]


def test_404_page_exists_and_is_not_indexed() -> None:
    page = DOCS / "404.html"
    assert page.is_file()
    assert _noindex(_head(page))


INDEXES = [p for p in PAGES if p.name == "index.html"]


@pytest.mark.parametrize("page", INDEXES, ids=lambda p: str(p.relative_to(DOCS)))
def test_every_page_has_its_own_og_image(page: Path) -> None:
    h = _head(page)
    image = _one(h, "og:image")
    assert image == SITE + page.relative_to(DOCS).parent.as_posix() + "/og.png", image
    assert _one(h, "twitter:image") == image
    assert _png_size(_file_for(image)) == (1200, 630)
    for block in _jsonld(page):  # structured data names the same card
        for node in _walk(block):
            assert node.get("image", image) == image, node.get("@type")
    # The alt describes this page's image: its title over the OpenWhistle mark.
    alt = h.titles[0].removesuffix(" | OpenWhistle") + ": OpenWhistle"
    assert (_one(h, "og:image:alt"), _one(h, "twitter:image:alt")) == (alt, alt)


def test_og_images_differ_per_page() -> None:
    images = {_one(_head(p), "og:image") for p in INDEXES}
    assert len(images) == len(INDEXES)


@pytest.mark.parametrize("page", PAGES, ids=IDS)
def test_head_sends_no_referrer_and_types_its_image(page: Path) -> None:
    # An outbound click must not name the page, whatever header the server sends.
    h = _head(page)
    assert _one(h, "referrer") == "no-referrer"
    assert _one(h, "og:image:type") == "image/png"


@pytest.mark.parametrize("lang", ["en", "de"])
def test_the_blog_feed_lists_every_post(lang: str) -> None:
    ns = {"a": "http://www.w3.org/2005/Atom"}
    feed = ET.parse(DOCS / lang / "blog" / "feed.xml").getroot()  # noqa: S314 — our own built file
    posts = sorted(
        SITE + p.relative_to(DOCS).parent.as_posix() + "/"
        for p in PAGES
        if p.parent.parent.name == "blog" and p.parts[-4] == lang
    )
    entries = sorted(e.findtext("a:id", namespaces=ns) or "" for e in feed.findall("a:entry", ns))
    assert entries == posts
    self_link = feed.find("a:link[@rel='self']", ns)
    assert self_link is not None and self_link.get("href") == f"{SITE}{lang}/blog/feed.xml"
    for entry in feed.findall("a:entry", ns):
        for tag in ("title", "updated", "published", "summary"):
            assert entry.findtext(f"a:{tag}", namespaces=ns), tag


@pytest.mark.parametrize(
    "page",
    [p for p in PAGES if p.relative_to(DOCS).parts[1:2] == ("blog",)],
    ids=lambda p: str(p.relative_to(DOCS)),
)
def test_blog_pages_announce_their_feed(page: Path) -> None:
    lang = page.relative_to(DOCS).parts[0]
    feeds = [link for link in _head(page).rel("alternate") if link.get("type")]
    assert [(f["type"], f["href"]) for f in feeds] == [
        ("application/atom+xml", f"/{lang}/blog/feed.xml")
    ]


def test_both_homes_carry_software_and_organization() -> None:
    for page in LANDING:
        types = {b.get("@type") for b in _jsonld(page)}
        assert {"SoftwareApplication", "Organization"} <= types, (page, types)


@pytest.mark.parametrize(
    "page", [p for p in PAGES if "/docs/" in p.as_posix()], ids=lambda p: str(p.relative_to(DOCS))
)
def test_docs_pages_carry_a_breadcrumb(page: Path) -> None:
    crumbs = [b for b in _jsonld(page) if b.get("@type") == "BreadcrumbList"]
    assert len(crumbs) == 1
    items = crumbs[0]["itemListElement"]
    assert [i["position"] for i in items] == list(range(1, len(items) + 1))
    assert items[-1]["item"] == _head(page).rel("canonical")[0]["href"]
