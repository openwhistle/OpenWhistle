"""scripts/build_site.py: the rules the site build promises (see its docstring)."""

from __future__ import annotations

import importlib.util
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "site"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_site", ROOT / "scripts" / "build_site.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # @dataclass looks its module up here
    spec.loader.exec_module(module)
    return module


B = _load()


@pytest.fixture
def src(tmp_path: Path) -> Path:
    """A writable copy of the fixture, so a test can break one file."""
    copy = tmp_path / "src"
    shutil.copytree(FIXTURE, copy)
    return copy


def _build(src: Path, tmp_path: Path, **kw: bool) -> Path:
    out = tmp_path / "out"
    B.build(src, out, **kw)
    return out


@pytest.mark.parametrize(
    ("rel", "url"),
    [
        ("en/index.html", "/en/"),
        ("en/docs/index.md", "/en/docs/"),
        ("de/blog/was-ist-neu.html", "/de/blog/was-ist-neu/"),
        ("404.html", "/404.html"),
    ],
)
def test_url_for(rel: str, url: str) -> None:
    assert B.url_for(Path(rel)) == url


def test_pages_land_at_their_url_and_statics_are_copied(src: Path, tmp_path: Path) -> None:
    out = _build(src, tmp_path)
    assert (out / "en" / "index.html").is_file()
    assert (out / "en" / "docs" / "index.html").is_file()
    assert (out / "de" / "index.html").is_file()
    assert (out / "404.html").is_file()
    assert (out / "img" / "pixel.png").read_bytes() == (src / "img" / "pixel.png").read_bytes()
    assert (out / ".nojekyll").is_file()


def test_underscore_paths_never_reach_the_output(src: Path, tmp_path: Path) -> None:
    out = _build(src, tmp_path)
    leaked = [p for p in out.rglob("*") if any(x.startswith("_") for x in p.relative_to(out).parts)]
    assert not leaked
    assert "secret" not in "".join(p.read_text(errors="ignore") for p in out.rglob("*.html"))


def test_markdown_renders_tables_and_keeps_raw_html_and_utf8(src: Path, tmp_path: Path) -> None:
    html = (_build(src, tmp_path) / "en" / "docs" / "index.html").read_text(encoding="utf-8")
    assert "<h1>Änderungsprotokoll</h1>" in html
    assert "<table>" in html
    assert '<div class="note">raw HTML stays</div>' in html


def test_a_body_is_never_evaluated_as_jinja(src: Path, tmp_path: Path) -> None:
    html = (_build(src, tmp_path) / "en" / "index.html").read_text(encoding="utf-8")
    assert "{{ .Values.image.tag }} {% raw %}" in html


def test_a_page_without_front_matter_fails(src: Path, tmp_path: Path) -> None:
    (src / "en" / "bare.html").write_text("<p>no front matter</p>", encoding="utf-8")
    with pytest.raises(B.BuildError, match=r"en/bare\.html.*front matter"):
        _build(src, tmp_path)


def test_an_unknown_front_matter_key_fails(src: Path, tmp_path: Path) -> None:
    page = src / "en" / "index.html"
    page.write_text(page.read_text().replace("title:", "titel: typo\ntitle:", 1), encoding="utf-8")
    with pytest.raises(B.BuildError, match="titel"):
        _build(src, tmp_path)


def test_a_missing_required_key_fails(src: Path, tmp_path: Path) -> None:
    page = src / "en" / "index.html"
    text = page.read_text().replace("description: The English home of the fixture site.\n", "")
    page.write_text(text, encoding="utf-8")
    with pytest.raises(B.BuildError, match="description"):
        _build(src, tmp_path)


def test_two_sources_for_one_url_fail(src: Path, tmp_path: Path) -> None:
    (src / "en" / "docs.md").write_text(
        "---\ntitle: t\ndescription: d\ntranslation_key: dup\n---\nx\n", encoding="utf-8"
    )
    with pytest.raises(B.BuildError, match="/en/docs/"):
        _build(src, tmp_path)


def test_a_page_outside_a_language_directory_needs_lang(src: Path, tmp_path: Path) -> None:
    page = src / "404.html"
    page.write_text(page.read_text().replace("lang: en\n", ""), encoding="utf-8")
    with pytest.raises(B.BuildError, match="404.html.*language"):
        _build(src, tmp_path)


def test_main_reports_a_build_error_as_exit_1(
    src: Path, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    (src / "en" / "bare.html").write_text("<p>x</p>", encoding="utf-8")
    assert B.main(["--src", str(src), "--out", str(tmp_path / "out")]) == 1
    assert "build failed" in capsys.readouterr().err


def _write(src: Path, text: str) -> None:
    (src / "en" / "index.html").write_bytes(text.encode("utf-8"))


def test_empty_front_matter_names_the_missing_keys(src: Path, tmp_path: Path) -> None:
    _write(src, "---\n---\n<p>x</p>")
    with pytest.raises(B.BuildError, match="lacks"):
        _build(src, tmp_path)


def test_front_matter_closed_on_the_last_line_has_an_empty_body() -> None:
    meta, body = B.split_front_matter(Path("x.html"), "---\ntitle: t\n---")
    assert meta == {"title": "t"}
    assert body == ""


def test_a_rule_line_in_the_body_stays_in_the_body() -> None:
    _, body = B.split_front_matter(Path("x.md"), "---\ntitle: t\n---\na\n---\nb\n")
    assert body == "a\n---\nb\n"


def test_invalid_yaml_front_matter_is_a_build_error(src: Path, tmp_path: Path) -> None:
    _write(src, "---\ntitle: [unclosed\n---\nx\n")
    with pytest.raises(B.BuildError, match=r"en/index\.html.*not valid YAML"):
        _build(src, tmp_path)


def test_non_mapping_front_matter_is_a_build_error(src: Path, tmp_path: Path) -> None:
    _write(src, "---\n- a\n- b\n---\nx\n")
    with pytest.raises(B.BuildError, match=r"en/index\.html.*must be a mapping"):
        _build(src, tmp_path)


def test_crlf_pages_build(src: Path, tmp_path: Path) -> None:
    page = src / "en" / "index.html"
    page.write_bytes(page.read_text(encoding="utf-8").replace("\n", "\r\n").encode("utf-8"))
    assert (_build(src, tmp_path) / "en" / "index.html").is_file()


def test_out_that_is_a_file_fails(src: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.write_text("x", encoding="utf-8")
    with pytest.raises(B.BuildError, match="is a file"):
        B.build(src, out)


def _pages(src: Path, tmp_path: Path) -> dict[str, object]:
    return {p.url: p for p in B.build(src, tmp_path / "out")}


def test_translations_point_at_each_other(src: Path, tmp_path: Path) -> None:
    pages = _pages(src, tmp_path)
    assert pages["/en/"].alternates == {"en": "/en/", "de": "/de/"}
    assert pages["/de/"].alternates == pages["/en/"].alternates


def test_the_home_x_default_is_the_root_for_language_roots(src: Path, tmp_path: Path) -> None:
    site = B.load_data(src)["site"]
    pages = _pages(src, tmp_path)
    # Home page: x-default is the root, which is language-agnostic
    assert B.hreflang(pages["/de/"], site) == [
        ("de", "https://example.test/de/"),
        ("en", "https://example.test/en/"),
        ("x-default", "https://example.test/"),
    ]


def test_non_root_translated_page_x_default_is_default_language(src: Path, tmp_path: Path) -> None:
    site = B.load_data(src)["site"]
    # Construct a non-root page with translations in both languages
    page = B.Page(
        source=Path("en/x.html"),
        url="/en/x/",
        lang="en",
        meta={},
        content="",
        alternates={"en": "/en/x/", "de": "/de/x/"},
    )
    assert B.hreflang(page, site) == [
        ("de", "https://example.test/de/x/"),
        ("en", "https://example.test/en/x/"),
        ("x-default", "https://example.test/en/x/"),
    ]


def test_a_group_without_default_language_gets_no_x_default(src: Path, tmp_path: Path) -> None:
    site = B.load_data(src)["site"]
    # Page with only non-default languages
    page = B.Page(
        source=Path("de/x.html"),
        url="/de/x/",
        lang="de",
        meta={},
        content="",
        alternates={"de": "/de/x/", "fr": "/fr/x/"},
    )
    assert B.hreflang(page, site) == [
        ("de", "https://example.test/de/x/"),
        ("fr", "https://example.test/fr/x/"),
    ]


def test_no_translation_no_hreflang(src: Path, tmp_path: Path) -> None:
    site = B.load_data(src)["site"]
    pages = _pages(src, tmp_path)
    assert B.hreflang(pages["/en/docs/"], site) == []  # no translation, no hreflang


def test_a_missing_translation_string_fails(src: Path, tmp_path: Path) -> None:
    (src / "_data" / "i18n" / "de.yml").write_text("{}\n", encoding="utf-8")
    with pytest.raises(B.BuildError, match=r"de\.yml: missing \[.*'skip_link'"):
        _build(src, tmp_path)


def test_one_language_twice_in_a_translation_group_fails(src: Path, tmp_path: Path) -> None:
    extra = src / "en" / "home-copy.html"
    extra.write_text((src / "en" / "index.html").read_text(), encoding="utf-8")
    with pytest.raises(B.BuildError, match="translation_key 'home' twice in en"):
        _build(src, tmp_path)


def test_a_third_language_needs_data_only(src: Path, tmp_path: Path) -> None:
    """D7: a language is config + translations, never a template change."""
    site_file = src / "_data" / "site.yml"
    site_text = site_file.read_text() + "  fr: {name: Français, locale: fr_FR}\n"
    site_file.write_text(site_text, encoding="utf-8")
    shutil.copy(src / "_data" / "i18n" / "en.yml", src / "_data" / "i18n" / "fr.yml")
    (src / "fr").mkdir()
    (src / "fr" / "index.html").write_text(
        "---\ntitle: Accueil\ndescription: La page d'accueil.\ntranslation_key: home\n---\n"
        '<main id="main-content"><section id="features"></section><h1>Accueil</h1></main>\n',
        encoding="utf-8",
    )
    pages = _pages(src, tmp_path)
    site_after = B.load_data(src)["site"]
    assert pages["/fr/"].alternates == {"en": "/en/", "de": "/de/", "fr": "/fr/"}
    assert 'lang="fr"' in (tmp_path / "out" / "fr" / "index.html").read_text(encoding="utf-8")
    assert B.hreflang(pages["/fr/"], site_after) == [
        ("de", "https://example.test/de/"),
        ("en", "https://example.test/en/"),
        ("fr", "https://example.test/fr/"),
        ("x-default", "https://example.test/"),
    ]


def test_the_fixture_uses_the_real_templates() -> None:
    for sub in ("_layouts", "_includes", "_data/i18n"):
        real = sorted((ROOT / "docs" / sub).rglob("*"))
        for path in real:
            if path.is_file():
                rel = path.relative_to(ROOT / "docs")
                assert (FIXTURE / rel).read_bytes() == path.read_bytes(), f"fixture {rel} drifted"


def test_a_german_reader_is_sent_to_the_english_docs(src: Path, tmp_path: Path) -> None:
    html = (_build(src, tmp_path) / "de" / "index.html").read_text(encoding="utf-8")
    assert '<a href="/en/docs/">Dokumentation</a>' in html


def test_the_current_section_is_marked(src: Path, tmp_path: Path) -> None:
    html = (_build(src, tmp_path) / "en" / "docs" / "index.html").read_text(encoding="utf-8")
    assert 'href="/en/docs/" class="active" aria-current="page"' in html


def test_the_language_switch_goes_to_the_translation(src: Path, tmp_path: Path) -> None:
    html = (_build(src, tmp_path) / "en" / "index.html").read_text(encoding="utf-8")
    assert '<a href="/de/" hreflang="de" lang="de">Deutsch</a>' in html


def test_a_nav_entry_naming_no_page_fails(src: Path, tmp_path: Path) -> None:
    (src / "_data" / "nav.yml").write_text(
        "primary: [{label: nav.docs, page: nope}]\nfooter: []\n"
    )
    with pytest.raises(B.BuildError, match="nav.yml: primary names 'nope'"):
        _build(src, tmp_path)


def test_a_page_no_nav_entry_leads_to_fails(src: Path, tmp_path: Path) -> None:
    (src / "en" / "orphan.md").write_text(
        "---\ntitle: o\ndescription: d\ntranslation_key: orphan\n---\nx\n"
    )
    with pytest.raises(B.BuildError, match="no entry of _data/nav.yml leads to /en/orphan/"):
        _build(src, tmp_path)


def test_the_footer_shows_the_app_version(src: Path, tmp_path: Path) -> None:
    config = (ROOT / "app/config.py").read_text()
    version = re.search(r'app_version: str = "([^"]+)"', config).group(1)
    html = (_build(src, tmp_path) / "en" / "index.html").read_text(encoding="utf-8")
    assert f"Version {version}</span>" in html


def test_title_and_description_are_html_escaped_and_utf8_stays_literal(
    src: Path, tmp_path: Path
) -> None:
    esc_text = (
        "---\ntitle: 'A & B \"q\" <x>'\ndescription: 'd ❤️ →'\n"
        "translation_key: esc\n---\n<main id=\"main-content\">x</main>\n"
    )
    (src / "en" / "docs" / "esc.md").write_text(esc_text, encoding="utf-8")
    path = tmp_path / "out" / "en" / "docs" / "esc" / "index.html"
    _build(src, tmp_path)
    html = path.read_text(encoding="utf-8")
    assert "<title>A &amp; B &#34;q&#34; &lt;x&gt;</title>" in html
    assert '<meta name="description" content="d ❤️ →">' in html


def _add_link(src: Path, href: str) -> None:
    page = src / "en" / "index.html"
    content = page.read_text().replace(
        "</main>", f'<a href="{href}">x</a></main>'
    )
    page.write_text(content, encoding="utf-8")


@pytest.mark.parametrize(
    "href",
    [
        "/en/missing/",
        "../nowhere.html",
        "/img/missing.png",
        "https://example.test/en/gone/",
    ],
)
def test_a_link_to_nothing_fails(src: Path, tmp_path: Path, href: str) -> None:
    _add_link(src, href)
    with pytest.raises(B.BuildError, match="broken internal links"):
        _build(src, tmp_path)


def test_a_link_to_a_missing_fragment_fails(src: Path, tmp_path: Path) -> None:
    _add_link(src, "/de/#nope")
    with pytest.raises(B.BuildError, match="no id 'nope'"):
        _build(src, tmp_path)


@pytest.mark.parametrize(
    "href",
    [
        "#main-content",
        "/de/#main-content",
        "mailto:info@openwhistle.net",
        "https://github.com/openwhistle/OpenWhistle",
        "//cdn.example.org/x.js",
    ],
)
def test_valid_and_external_links_pass(src: Path, tmp_path: Path, href: str) -> None:
    _add_link(src, href)
    _build(src, tmp_path)


@pytest.mark.parametrize("out", ["src", "parent"])
def test_out_may_not_be_the_sources_or_above_them(src: Path, tmp_path: Path, out: str) -> None:
    target = src if out == "src" else src.parent
    with pytest.raises(B.BuildError, match="would overwrite the sources"):
        B.build(src, target)
    assert (src / "en" / "index.html").is_file()


def test_the_root_is_the_language_choice_not_a_page(src: Path, tmp_path: Path) -> None:
    out = _build(src, tmp_path)
    # The fixture builds without a root index.html (served by stub/nginx language choice)
    assert not (out / "index.html").exists()
    # But hreflang x-default links to the root pass validation
    html = (out / "en" / "index.html").read_text(encoding="utf-8")
    assert '<link rel="alternate" hreflang="x-default" href="https://example.test/">' in html


def test_a_link_to_root_fragment_passes(src: Path, tmp_path: Path) -> None:
    _add_link(src, "/#something")
    _build(src, tmp_path)  # Passes: fragment on root is ignored


def test_percent_encoded_path_traversal_fails(src: Path, tmp_path: Path) -> None:
    # urljoin leaves %2e%2e alone, so only the guard stops out/en/../../etc/passwd,
    # which is a real file next to out/ (a raw ../ is normalised by urljoin and cannot escape).
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc" / "passwd").write_text("root", encoding="utf-8")
    _add_link(src, "%2e%2e/%2e%2e/etc/passwd")
    with pytest.raises(B.BuildError, match="traversal outside output"):
        _build(src, tmp_path)


def test_percent_encoded_path_to_existing_file_passes(src: Path, tmp_path: Path) -> None:
    _add_link(src, "/img/%70ixel.png")  # %70 = 'p'
    _build(src, tmp_path)


def test_fragment_with_percent_encoding_matches_id(src: Path, tmp_path: Path) -> None:
    _add_link(src, "/en/docs/#caf%C3%A9")  # café in percent-encoded
    page = src / "en" / "docs" / "index.md"
    # Add café ID to the docs page
    page.write_text(
        page.read_text().replace("</main>", '<span id="café">test</span></main>'),
        encoding="utf-8",
    )
    _build(src, tmp_path)


def test_same_page_missing_fragment_fails(src: Path, tmp_path: Path) -> None:
    _add_link(src, "#nope")
    with pytest.raises(B.BuildError, match="no id 'nope'"):
        _build(src, tmp_path)


def test_link_with_query_string_passes(src: Path, tmp_path: Path) -> None:
    _add_link(src, "/en/docs/?x=1")
    _build(src, tmp_path)


def test_unknown_scheme_is_skipped(src: Path, tmp_path: Path) -> None:
    _add_link(src, "javascript:alert('xss')")
    _build(src, tmp_path)  # javascript: is skipped, no error


def test_ftp_scheme_is_skipped(src: Path, tmp_path: Path) -> None:
    _add_link(src, "ftp://example.com/file.txt")
    _build(src, tmp_path)  # ftp: is skipped


def test_netloc_case_insensitive(src: Path, tmp_path: Path) -> None:
    _add_link(src, "https://EXAMPLE.TEST/en/")
    _build(src, tmp_path)  # Same host, case-insensitive match


def test_out_inside_src_is_refused(src: Path, tmp_path: Path) -> None:
    out = src / "_site"
    with pytest.raises(B.BuildError, match="would overwrite the sources"):
        B.build(src, out)


NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9", "x": "http://www.w3.org/1999/xhtml"}


def test_the_sitemap_lists_indexable_pages_with_alternates(src: Path, tmp_path: Path) -> None:
    root = ET.parse(_build(src, tmp_path) / "sitemap.xml").getroot()  # noqa: S314 - our own generated file
    locs = {u.find("s:loc", NS).text: u for u in root.findall("s:url", NS)}
    assert set(locs) == {"https://example.test/en/", "https://example.test/de/", "https://example.test/en/docs/"}
    alts = {a.get("hreflang") for a in locs["https://example.test/de/"].findall("x:link", NS)}
    assert alts == {"en", "de", "x-default"}


def test_a_redirect_to_no_page_fails(src: Path, tmp_path: Path) -> None:
    (src / "_data" / "redirects.yml").write_text("/old.html: /en/gone/\n")
    with pytest.raises(B.BuildError, match="/old.html -> /en/gone/, which is no page"):
        _build(src, tmp_path)


def test_a_stub_keeps_the_fragment_and_is_not_indexed(src: Path, tmp_path: Path) -> None:
    redirects = "/docs.html: /en/docs/\n/blog/: /de/\n/x.md: /en/\n"
    (src / "_data" / "redirects.yml").write_text(redirects)
    out = _build(src, tmp_path, redirect_stubs=True)
    stub = (out / "docs.html").read_text(encoding="utf-8")
    assert 'location.replace("/en/docs/"+location.hash)' in stub
    assert '<meta name="robots" content="noindex">' in stub
    assert (out / "blog" / "index.html").is_file()
    assert not (out / "x.md").exists()  # only nginx can redirect a non-HTML URL
    assert "/en/" in (out / "index.html").read_text(encoding="utf-8")  # "/" on Pages


def test_no_stubs_without_the_flag(src: Path, tmp_path: Path) -> None:
    (src / "_data" / "redirects.yml").write_text("/docs.html: /en/docs/\n")
    out = _build(src, tmp_path)
    assert not (out / "docs.html").exists() and not (out / "index.html").exists()


def test_a_stub_never_overwrites_a_page(src: Path, tmp_path: Path) -> None:
    (src / "_data" / "redirects.yml").write_text("/de/index.html: /en/\n")
    with pytest.raises(B.BuildError, match="would overwrite de/index.html"):
        _build(src, tmp_path, redirect_stubs=True)


def test_a_link_to_an_old_url_fails_although_a_stub_would_serve_it(
    src: Path, tmp_path: Path
) -> None:
    (src / "_data" / "redirects.yml").write_text("/docs.html: /en/docs/\n")
    home = src / "en" / "index.html"
    home.write_text(home.read_text().replace('href="/en/docs/"', 'href="/docs.html"'))
    with pytest.raises(B.BuildError, match="nothing at /docs.html"):
        _build(src, tmp_path, redirect_stubs=True)


def test_two_urls_of_one_file_share_one_stub(tmp_path: Path) -> None:
    site = {"default_language": "en", "base_url": "https://e.test"}
    B.write_stubs(tmp_path, {"/blog/": "/de/blog/", "/blog/index.html": "/de/blog/"}, site)
    assert '"/de/blog/"' in (tmp_path / "blog" / "index.html").read_text()
    with pytest.raises(B.BuildError, match="would overwrite blog/index.html"):
        B.write_stubs(tmp_path / "2", {"/blog/": "/de/blog/", "/blog/index.html": "/en/"}, site)


def test_a_stub_target_cannot_close_the_script(tmp_path: Path) -> None:
    site = {"default_language": "en", "base_url": "https://e.test"}
    B.write_stubs(tmp_path, {"/a.html": "/x</script>/"}, site)
    lines = (tmp_path / "a.html").read_text().splitlines()
    script = next(ln for ln in lines if ln.startswith("<script>"))
    assert "</script>" not in script.removesuffix("</script>")

