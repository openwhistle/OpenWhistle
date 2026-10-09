"""scripts/build_site.py: the rules the site build promises (see its docstring)."""

from __future__ import annotations

import datetime
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
    assert not (out / ".nojekyll").exists()  # Pages-only; nginx needs none


def test_underscore_paths_never_reach_the_output(src: Path, tmp_path: Path) -> None:
    out = _build(src, tmp_path)
    leaked = [p for p in out.rglob("*") if any(x.startswith("_") for x in p.relative_to(out).parts)]
    assert not leaked
    assert "secret" not in "".join(p.read_text(errors="ignore") for p in out.rglob("*.html"))


def test_markdown_renders_tables_and_keeps_raw_html_and_utf8(src: Path, tmp_path: Path) -> None:
    html = (_build(src, tmp_path) / "en" / "docs" / "index.html").read_text(encoding="utf-8")
    assert "<h1>Änderungsprotokoll</h1>" in html
    # A table scrolls inside its own box: a wide one must not widen a phone page.
    assert '<div class="table-scroll"><table class="env-table">' in html
    # Markdown carries no classes: the page and its tables take the docs type from these two.
    assert '<main id="main-content" class="docs-content">' in html
    assert "</table></div>" in html
    assert '<div class="note">raw HTML stays</div>' in html


def test_a_body_is_never_evaluated_as_jinja(src: Path, tmp_path: Path) -> None:
    html = (_build(src, tmp_path) / "en" / "index.html").read_text(encoding="utf-8")
    assert "{{ .Values.image.tag }} {% raw %}" in html


def test_a_page_without_front_matter_fails(src: Path, tmp_path: Path) -> None:
    (src / "en" / "bare.html").write_text("<p>no front matter</p>", encoding="utf-8")
    with pytest.raises(B.BuildError, match=r"en/bare\.html: a page must open with '---'"):
        _build(src, tmp_path)


def test_unclosed_front_matter_is_a_build_error(src: Path, tmp_path: Path) -> None:
    (src / "en" / "open.html").write_text("---\ntitle: t\n<p>x</p>\n", encoding="utf-8")
    with pytest.raises(B.BuildError, match=r"en/open\.html: the front matter is never closed"):
        _build(src, tmp_path)


def test_an_unknown_generator_fails(src: Path, tmp_path: Path) -> None:
    (src / "en" / "docs" / "gen.md").write_text(
        "---\ntitle: t\ndescription: d\ntranslation_key: gen\ngenerated: nope\n---\n",
        encoding="utf-8",
    )
    with pytest.raises(B.BuildError, match="unknown generator 'nope'"):
        _build(src, tmp_path)


def test_an_undefined_template_name_fails(src: Path, tmp_path: Path) -> None:
    """StrictUndefined: a typo in a template is a build error, not an empty string."""
    import jinja2

    base = src / "_layouts" / "base.html"
    base.write_text(base.read_text().replace("{{ t.skip_link }}", "{{ t.skip_lnik }}"))
    with pytest.raises(jinja2.UndefinedError, match="skip_lnik"):
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
    # The German twin names the same x-default: the default language, not itself.
    page.url, page.lang = "/de/x/", "de"
    assert B.hreflang(page, site)[-1] == ("x-default", "https://example.test/en/x/")


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
        '<main id="main-content"><section id="compliance"></section><h1>Accueil</h1></main>\n',
        encoding="utf-8",
    )
    pages = _pages(src, tmp_path)
    site_after = B.load_data(src)["site"]
    assert pages["/fr/"].alternates == {"en": "/en/", "de": "/de/", "fr": "/fr/"}
    assert '<html lang="fr"' in (tmp_path / "out" / "fr" / "index.html").read_text(encoding="utf-8")
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
    assert '<a href="/en/docs/" hreflang="en">Dokumentation</a>' in html


def test_the_current_section_is_marked(src: Path, tmp_path: Path) -> None:
    html = (_build(src, tmp_path) / "en" / "docs" / "index.html").read_text(encoding="utf-8")
    assert 'href="/en/docs/" class="active" aria-current="page"' in html


def test_the_language_switch_goes_to_the_translation(src: Path, tmp_path: Path) -> None:
    html = (_build(src, tmp_path) / "en" / "index.html").read_text(encoding="utf-8")
    assert '<a href="/de/" hreflang="de" lang="de">Deutsch</a>' in html


def test_a_home_entry_is_current_only_on_the_home(src: Path, tmp_path: Path) -> None:
    """Every URL starts with /en/: the home entry must not light up on every page,
    and a #fragment entry (compliance) marks nothing, not even on the home."""
    (src / "_data" / "nav.yml").write_text(
        "primary:\n  - {label: nav.home, page: home}\n"
        "  - {label: nav.compliance, page: home, fragment: compliance}\n"
        "  - {label: nav.docs, page: docs}\nfooter: []\n"
    )
    out = _build(src, tmp_path)
    docs = (out / "en" / "docs" / "index.html").read_text(encoding="utf-8")
    assert docs.count('aria-current="page"') == 1
    home = (out / "en" / "index.html").read_text(encoding="utf-8")
    assert home.count('aria-current="page"') == 1
    assert 'href="/en/" class="active"' in home


def test_a_fragment_entry_marks_nothing(src: Path, tmp_path: Path) -> None:
    home = (_build(src, tmp_path) / "en" / "index.html").read_text(encoding="utf-8")
    assert 'aria-current="page"' not in home


def test_the_language_switch_of_a_translated_page_goes_to_its_twin(
    src: Path, tmp_path: Path
) -> None:
    (src / "de" / "docs").mkdir()
    (src / "de" / "docs" / "index.md").write_text(
        "---\ntitle: Doku\ndescription: d\ntranslation_key: docs\n---\n# Doku\n", encoding="utf-8"
    )
    html = (_build(src, tmp_path) / "en" / "docs" / "index.html").read_text(encoding="utf-8")
    assert '<a href="/de/docs/" hreflang="de" lang="de">Deutsch</a>' in html


def test_a_nav_entry_naming_no_page_fails(src: Path, tmp_path: Path) -> None:
    (src / "_data" / "nav.yml").write_text("primary: [{label: nav.docs, page: nope}]\nfooter: []\n")
    with pytest.raises(B.BuildError, match="nav.yml: primary names 'nope'"):
        _build(src, tmp_path)


def test_a_legal_entry_naming_no_page_fails(src: Path, tmp_path: Path) -> None:
    (src / "_data" / "nav.yml").write_text(
        "primary: []\nfooter: []\nlegal: [{label: nav.docs, page: nope}]\n"
    )
    with pytest.raises(B.BuildError, match="nav.yml: legal names 'nope'"):
        _build(src, tmp_path)


def test_a_legal_entry_is_a_footer_link(src: Path, tmp_path: Path) -> None:
    (src / "_data" / "nav.yml").write_text(
        "primary: [{label: nav.docs, page: docs}]\nfooter: []\n"
        "legal: [{label: nav.docs, page: docs}]\n"
    )
    html = (_build(src, tmp_path) / "en" / "index.html").read_text(encoding="utf-8")
    assert '<a href="/en/docs/">Documentation</a>' in html.split('class="site-footer"', 1)[1]


def test_a_language_home_needs_no_nav_entry(src: Path, tmp_path: Path) -> None:
    """The logo on every page links the home; the nav need not name it."""
    (src / "_data" / "nav.yml").write_text("primary: [{label: nav.docs, page: docs}]\nfooter: []\n")
    assert (_build(src, tmp_path) / "de" / "index.html").is_file()


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
        'translation_key: esc\n---\n<main id="main-content">x</main>\n'
    )
    (src / "en" / "docs" / "esc.md").write_text(esc_text, encoding="utf-8")
    path = tmp_path / "out" / "en" / "docs" / "esc" / "index.html"
    _build(src, tmp_path)
    html = path.read_text(encoding="utf-8")
    assert "<title>A &amp; B &#34;q&#34; &lt;x&gt;</title>" in html
    assert '<meta name="description" content="d ❤️ →">' in html


def _add_link(src: Path, href: str) -> None:
    page = src / "en" / "index.html"
    content = page.read_text().replace("</main>", f'<a href="{href}">x</a></main>')
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


@pytest.mark.parametrize(
    "tag", ['<img src="/img/missing.png" alt="">', '<img srcset="/img/missing.png 2x" alt="">']
)
def test_a_missing_image_fails(src: Path, tmp_path: Path, tag: str) -> None:
    page = src / "en" / "index.html"
    page.write_text(page.read_text().replace("</main>", f"{tag}</main>"), encoding="utf-8")
    with pytest.raises(B.BuildError, match="nothing at /img/missing.png"):
        _build(src, tmp_path)


def test_a_named_anchor_is_a_fragment_target(src: Path, tmp_path: Path) -> None:
    page = src / "en" / "index.html"
    page.write_text(
        page.read_text().replace("</main>", '<a name="legacy"></a><a href="#legacy">x</a></main>'),
        encoding="utf-8",
    )
    _build(src, tmp_path)


@pytest.mark.parametrize("out", ["src", "parent"])
def test_out_may_not_be_the_sources_or_above_them(src: Path, tmp_path: Path, out: str) -> None:
    target = src if out == "src" else src.parent
    with pytest.raises(B.BuildError, match="would overwrite the sources"):
        B.build(src, target)
    assert (src / "en" / "index.html").is_file()


def test_the_root_is_the_language_choice_not_a_page(src: Path, tmp_path: Path) -> None:
    out = _build(src, tmp_path)
    # The fixture builds without a root index.html (nginx serves the language choice)
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
        page.read_text() + '\n<span id="café">test</span>\n',
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


def test_a_broken_link_on_the_own_host_in_capitals_fails(src: Path, tmp_path: Path) -> None:
    _add_link(src, "https://EXAMPLE.TEST/en/gone/")
    with pytest.raises(B.BuildError, match="nothing at /en/gone/"):
        _build(src, tmp_path)


def test_out_inside_src_is_refused(src: Path, tmp_path: Path) -> None:
    out = src / "_site"
    with pytest.raises(B.BuildError, match="would overwrite the sources"):
        B.build(src, out)


NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9", "x": "http://www.w3.org/1999/xhtml"}


def test_the_sitemap_lists_indexable_pages_with_alternates(src: Path, tmp_path: Path) -> None:
    root = ET.parse(_build(src, tmp_path) / "sitemap.xml").getroot()  # noqa: S314 - our own generated file
    locs = {u.find("s:loc", NS).text: u for u in root.findall("s:url", NS)}
    assert set(locs) == {
        "https://example.test/en/",
        "https://example.test/de/",
        "https://example.test/en/docs/",
    }
    alts = {a.get("hreflang") for a in locs["https://example.test/de/"].findall("x:link", NS)}
    assert alts == {"en", "de", "x-default"}


def test_lastmod_is_the_last_commit_of_the_source() -> None:
    if B._git("status", "--porcelain", "--", "LICENSE"):
        pytest.skip("LICENSE has uncommitted changes")
    stamp = int(B._git("log", "-1", "--format=%ct", "--", "LICENSE"))
    day = datetime.datetime.fromtimestamp(stamp, datetime.UTC).date().isoformat()
    assert B.lastmod(ROOT / "LICENSE") == day


def test_lastmod_is_a_utc_date_not_the_local_one(monkeypatch: pytest.MonkeyPatch) -> None:
    # 2026-10-03 01:30 +0200 is still 2026-10-02 in UTC, where CI runs
    zone = datetime.timezone(datetime.timedelta(hours=2))
    local = datetime.datetime(2026, 10, 3, 1, 30, tzinfo=zone)
    monkeypatch.setattr(B, "_git", lambda *a: str(int(local.timestamp())) if "log" in a else "")
    assert B.lastmod(ROOT / "LICENSE") == "2026-10-02"


def test_the_changelog_page_is_dated_by_changelog_md(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(B, "lastmod", lambda path: path.name)
    site = {"base_url": "https://e.test", "languages": {"en": {}}, "default_language": "en"}
    generated = {"generated": "changelog"}
    changelog = B.Page(Path("en/changelog.html"), "/en/changelog/", "en", generated, "")
    roadmap = B.Page(Path("en/roadmap.html"), "/en/roadmap/", "en", {}, "")
    B.write_sitemap(tmp_path, tmp_path, [changelog, roadmap], site)
    sitemap = (tmp_path / "sitemap.xml").read_text(encoding="utf-8")
    assert "/en/changelog/</loc>\n    <lastmod>CHANGELOG.md</lastmod>" in sitemap
    assert "/en/roadmap/</loc>\n    <lastmod>roadmap.html</lastmod>" in sitemap


def test_a_redirect_from_a_page_fails(src: Path, tmp_path: Path) -> None:
    (src / "_data" / "redirects.yml").write_text("/en/docs/: /en/\n")
    with pytest.raises(B.BuildError, match="/en/docs/ is a page itself"):
        _build(src, tmp_path)


def test_a_redirect_to_no_page_fails(src: Path, tmp_path: Path) -> None:
    (src / "_data" / "redirects.yml").write_text("/old.html: /en/gone/\n")
    with pytest.raises(B.BuildError, match="/old.html -> /en/gone/, which is no page"):
        _build(src, tmp_path)


def test_a_link_to_an_old_url_fails(src: Path, tmp_path: Path) -> None:
    (src / "_data" / "redirects.yml").write_text("/docs.html: /en/docs/\n")
    home = src / "en" / "index.html"
    home.write_text(home.read_text().replace('href="/en/docs/"', 'href="/docs.html"'))
    with pytest.raises(B.BuildError, match="nothing at /docs.html"):
        _build(src, tmp_path)


def test_no_built_page_carries_an_inline_style() -> None:
    from tests.built_site import built

    offenders = [
        str(p.relative_to(built())) for p in built().rglob("*.html") if ' style="' in p.read_text()
    ]
    assert not offenders, (
        f"inline style= breaks the P4 CSP (style-src without 'unsafe-inline'): {offenders}"
    )


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A stand-in repository, so a guard that fails deletes nothing real."""
    root = tmp_path / "outer" / "repo"
    for name in ("app", ".git", "scripts"):
        (root / name).mkdir(parents=True)
        (root / name / "keep.txt").write_text("keep", encoding="utf-8")
    monkeypatch.setattr(B, "ROOT", root)
    return root


@pytest.mark.parametrize("name", ["app", ".git", "scripts"])
def test_out_inside_the_repository_is_refused_except_site(src: Path, repo: Path, name: str) -> None:
    with pytest.raises(B.BuildError, match="inside the repository"):
        B.build(src, repo / name)
    assert (repo / name / "keep.txt").is_file()


def test_out_above_the_repository_is_refused(src: Path, repo: Path) -> None:
    with pytest.raises(B.BuildError, match="inside the repository"):
        B.build(src, repo.parent)
    assert (repo / "app" / "keep.txt").is_file()


def test_the_repository_build_directory_is_allowed(src: Path, repo: Path) -> None:
    B._refuse_dangerous_out(src, repo / "_site")
    B._refuse_dangerous_out(src, repo / "_site" / "nested")


def test_out_outside_the_repository_must_be_empty_or_a_previous_build(
    src: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    out.mkdir()
    B._refuse_dangerous_out(src, out)  # empty
    (out / "precious.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(B.BuildError, match="not a previous build"):
        B.build(src, out)
    assert (out / "precious.txt").read_text(encoding="utf-8") == "keep"
    (out / "sitemap.xml").write_text("<urlset/>", encoding="utf-8")
    B.build(src, out)  # a previous build is replaced
    assert not (out / "precious.txt").exists()


def test_a_broken_data_file_names_itself(src: Path, tmp_path: Path) -> None:
    (src / "_data" / "nav.yml").write_text("primary: [unclosed\n", encoding="utf-8")
    with pytest.raises(B.BuildError, match=r"nav\.yml.*not valid YAML"):
        _build(src, tmp_path)


def test_a_generated_page_with_a_body_fails(src: Path, tmp_path: Path) -> None:
    page = src / "en" / "changelog.html"
    page.write_text(
        "---\ntitle: C\ndescription: d\ntranslation_key: cl\ngenerated: changelog\n---\n"
        "<p>lost</p>\n",
        encoding="utf-8",
    )
    with pytest.raises(B.BuildError, match="generated page has a body"):
        _build(src, tmp_path)


# ── P3: docs layout, settings tables, legacy files ─────────────────────────


def _docs_fixture(src: Path) -> None:
    """Two docs pages, a docs sidebar and one settings group on top of the fixture.

    The fixture already carries the real docs.html (test_the_fixture_uses_the_real_templates).
    """
    (src / "en" / "docs" / "index.md").unlink()
    for slug, body in {
        "": '<h1 id="overview">Docs</h1>\n<h2 id="start">Start</h2>',
        "ldap/": '<h1>LDAP</h1>\n<h2 id="setup">Set it up</h2>\n<div data-config="ldap"></div>',
    }.items():
        page = src / "en" / "docs" / slug / "index.html"
        page.parent.mkdir(parents=True, exist_ok=True)
        key = f"docs-{slug.strip('/')}" if slug else "docs"
        page.write_text(
            f"---\ntitle: T {key}\ndescription: D\ntranslation_key: {key}\n"
            f"layout: docs\n---\n{body}\n",
            encoding="utf-8",
        )
    nav = (src / "_data" / "nav.yml").read_text(encoding="utf-8")
    nav += (
        "docs:\n"
        "  - {group: Get started, pages: [{label: Overview, page: docs}]}\n"
        "  - {group: How-to, pages: [{label: LDAP / AD, page: docs-ldap}]}\n"
    )
    (src / "_data" / "nav.yml").write_text(nav, encoding="utf-8")
    (src / "_data" / "config.yml").write_text(
        "intro: <p>Everything is an environment variable.</p>\n"
        "groups:\n"
        "  - id: ldap\n    title: LDAP\n    page: /en/docs/ldap/\n    guide: LDAP login\n"
        "    settings:\n"
        "      - {name: LDAP_URL, need: required, description: 'The <code>ldaps://</code> URL.',"
        " default: '—'}\n"
        "      - {name: LDAP_TLS, need: optional, description: Verify the certificate.,"
        " default: '<code>true</code>'}\n",
        encoding="utf-8",
    )
    (src / "_data" / "docs_anchors.yml").write_text("ldap: /en/docs/ldap/\n", encoding="utf-8")


def test_a_settings_marker_becomes_the_groups_table(src: Path, tmp_path: Path) -> None:
    _docs_fixture(src)
    html = (_build(src, tmp_path) / "en" / "docs" / "ldap" / "index.html").read_text(
        encoding="utf-8"
    )
    assert 'data-config="ldap"' not in html
    # Two columns: the badge under the name, the default under the description.
    assert (
        '<td><code class="env-key">LDAP_URL</code> '
        '<span class="env-required env-req-yes">Required</span></td>'
    ) in html
    assert '<span class="env-required env-req-no">Optional</span>' in html
    assert ' <span class="env-note">Default: <code>true</code></span></td>' in html
    assert "Default: —" not in html
    assert '<th scope="col">Description</th>\n</tr>' in html
    # Pagefind reads cells that touch as one word: every cell and row ends on its own line.
    assert not re.search(r"</t[dhr]><", html)


def test_a_marker_naming_no_group_fails(src: Path, tmp_path: Path) -> None:
    _docs_fixture(src)
    page = src / "en" / "docs" / "ldap" / "index.html"
    page.write_text(page.read_text().replace('data-config="ldap"', 'data-config="ldpa"'))
    with pytest.raises(B.BuildError, match="no group 'ldpa' in _data/config.yml"):
        _build(src, tmp_path)


def test_the_docs_layout_builds_sidebar_toc_pager_and_edit_link(src: Path, tmp_path: Path) -> None:
    _docs_fixture(src)
    html = (_build(src, tmp_path) / "en" / "docs" / "ldap" / "index.html").read_text(
        encoding="utf-8"
    )
    assert '<a href="/en/docs/ldap/" aria-current="page">LDAP / AD</a>' in html
    assert re.search(r'<details class="sidebar-group" open>\s*<summary>How-to</summary>', html)
    assert '<a href="#setup">Set it up</a>' in html  # on this page
    assert 'rel="prev" href="/en/docs/"' in html and 'rel="next"' not in html
    assert "/edit/main/docs/en/docs/ldap/index.html" in html
    crumbs = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html)
    assert any(
        '"BreadcrumbList"' in b and '"https://example.test/en/docs/ldap/"' in b for b in crumbs
    )


def test_only_the_docs_start_page_carries_the_anchor_map(src: Path, tmp_path: Path) -> None:
    _docs_fixture(src)
    out = _build(src, tmp_path)
    start = (out / "en" / "docs" / "index.html").read_text(encoding="utf-8")
    ldap = (out / "en" / "docs" / "ldap" / "index.html").read_text(encoding="utf-8")
    assert '{"ldap": "/en/docs/ldap/"}' in start
    assert "location.replace" in start and "location.replace" not in ldap


def test_a_docs_page_missing_from_the_docs_nav_fails(src: Path, tmp_path: Path) -> None:
    _docs_fixture(src)
    nav = src / "_data" / "nav.yml"
    nav.write_text(
        nav.read_text().replace(
            "  - {group: How-to, pages: [{label: LDAP / AD, page: docs-ldap}]}\n", ""
        )
    )
    with pytest.raises(B.BuildError, match="the docs sidebar in _data/nav.yml does not list it"):
        _build(src, tmp_path)


def test_a_docs_nav_entry_without_a_page_fails(src: Path, tmp_path: Path) -> None:
    _docs_fixture(src)
    nav = src / "_data" / "nav.yml"
    nav.write_text(
        nav.read_text().replace(
            "page: docs-ldap}", "page: docs-ldap}, {label: Gone, page: docs-gone}"
        )
    )
    with pytest.raises(B.BuildError, match="docs names 'docs-gone', which no page has"):
        _build(src, tmp_path)


def test_an_unknown_layout_fails(src: Path, tmp_path: Path) -> None:
    page = src / "en" / "index.html"
    page.write_text(page.read_text().replace("---\n", "---\nlayout: wide\n", 1))
    with pytest.raises(B.BuildError, match="unknown layout 'wide'"):
        _build(src, tmp_path)


def test_markdown_headings_get_ids() -> None:
    assert B.add_heading_ids("<h2>1. Purpose and Scope</h2>") == (
        '<h2 id="1-purpose-and-scope">1. Purpose and Scope</h2>'
    )
    assert B.add_heading_ids('<h3 id="x">Kept</h3>') == '<h3 id="x">Kept</h3>'


def test_a_page_in_one_language_is_linked_from_every_language(src: Path, tmp_path: Path) -> None:
    """The imprint exists only in German; the English footer still links it."""
    imprint = src / "impressum" / "index.html"
    imprint.parent.mkdir()
    imprint.write_text(
        "---\ntitle: Impressum\ndescription: D\ntranslation_key: imprint\nlang: de\n---\n"
        '<main id="main-content"></main>\n'
    )
    nav = src / "_data" / "nav.yml"
    nav.write_text(
        nav.read_text().replace("footer: []", "footer:\n  - {label: nav.docs, page: imprint}")
    )
    html = (_build(src, tmp_path) / "en" / "index.html").read_text(encoding="utf-8")
    assert 'href="/impressum/"' in html


def test_a_docs_page_outside_the_default_language_fails(src: Path, tmp_path: Path) -> None:
    _docs_fixture(src)
    page = src / "de" / "docs" / "index.html"
    page.parent.mkdir(parents=True)
    page.write_text(
        "---\ntitle: T\ndescription: D\ntranslation_key: docs-de\nlayout: docs\n---\n<h1>x</h1>\n"
    )
    with pytest.raises(B.BuildError, match=r"de/docs/index.html: docs pages are English only"):
        _build(src, tmp_path)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("need: optional", "need: maybe", r"group 'ldap', setting 'LDAP_TLS': need 'maybe'"),
        ("name: LDAP_URL, ", "", r"group 'ldap', setting #1: lacks 'name'"),
        ("description: Verify the certificate., ", "", r"setting 'LDAP_TLS': lacks 'description'"),
        ("intro: <p>Everything is an environment variable.</p>\n", "", r"lacks 'intro'"),
        ("    settings:\n", "    settingz:\n", r"group 'ldap': lacks 'settings'"),
    ],
)
def test_a_broken_config_yml_fails_naming_the_setting(
    src: Path, tmp_path: Path, old: str, new: str, message: str
) -> None:
    _docs_fixture(src)
    config = src / "_data" / "config.yml"
    text = config.read_text()
    assert old in text
    config.write_text(text.replace(old, new))
    with pytest.raises(B.BuildError, match=r"_data/config.yml.*" + message):
        _build(src, tmp_path)


def test_heading_ids_are_unescaped_and_never_empty_or_twice() -> None:
    assert B.add_heading_ids("<h2>Q &amp; A</h2>") == '<h2 id="q-a">Q &amp; A</h2>'
    assert B.add_heading_ids("<h2>***</h2>") == '<h2 id="section">***</h2>'
    twice = B.add_heading_ids("<h2>Setup</h2><h3>Setup</h3><h3>Setup</h3>")
    assert (
        twice == '<h2 id="setup">Setup</h2><h3 id="setup-2">Setup</h3><h3 id="setup-3">Setup</h3>'
    )
    kept = B.add_heading_ids('<h2 id="setup">Mine</h2><h3>Setup</h3>')
    assert kept == '<h2 id="setup">Mine</h2><h3 id="setup-2">Setup</h3>'


def test_a_generated_pages_edit_link_names_its_source(src: Path, tmp_path: Path) -> None:
    _docs_fixture(src)
    page = src / "en" / "docs" / "configuration" / "index.html"
    page.parent.mkdir()
    page.write_text(
        "---\ntitle: T\ndescription: D\ntranslation_key: docs-configuration\n"
        "layout: docs\ngenerated: configuration\n---\n"
    )
    nav = src / "_data" / "nav.yml"
    nav.write_text(
        nav.read_text().replace(
            "page: docs-ldap}", "page: docs-ldap}, {label: Config, page: docs-configuration}"
        )
    )
    html = (_build(src, tmp_path) / "en" / "docs" / "configuration" / "index.html").read_text()
    assert "/edit/main/docs/_data/config.yml" in html


def test_the_build_indexes_only_docs_pages() -> None:
    """Pagefind indexes the <main> that carries data-pagefind-body: the docs, nothing else."""
    import json

    from tests.built_site import built, page, pages

    bundle = built() / "pagefind"
    assert (bundle / "pagefind.js").is_file()
    assert "data-pagefind-body" not in page("/en/")
    assert "data-pagefind-body" in page("/en/docs/ldap/")
    docs = sum("data-pagefind-body" in p.read_text(encoding="utf-8") for p in pages())
    entry = json.loads((bundle / "pagefind-entry.json").read_text(encoding="utf-8"))
    assert [lang["page_count"] for lang in entry["languages"].values()] == [docs]
    # search.js is the only UI: Pagefind's own bundles would ship unused.
    assert not sorted(p.name for p in bundle.glob("*ui*")), "Pagefind's UI bundles shipped"


def test_an_og_title_without_a_sora_glyph_is_refused(src: Path, tmp_path: Path) -> None:
    page = src / "en" / "index.html"
    page.write_text(
        page.read_text(encoding="utf-8").replace("title: Fixture home", "title: Fixture 中"),
        encoding="utf-8",
    )
    with pytest.raises(B.BuildError, match="'Fixture 中' uses '中', not in Sora latin"):
        _build(src, tmp_path)


def test_the_build_has_no_stub_writer_and_no_legacy_copies() -> None:
    """P5: nginx answers every old URL with a 301; Pages stubs and frozen copies are gone."""
    source = (ROOT / "scripts" / "build_site.py").read_text(encoding="utf-8")
    assert not re.search(r"write_stubs|STUB|redirect.stubs", source)
    assert not hasattr(B, "write_stubs")
    assert not (ROOT / "docs" / "_legacy").exists()


def test_no_workflow_deploys_to_github_pages() -> None:
    """P5: the site is the container image; Pages machinery must not come back."""
    workflows = ROOT / ".github" / "workflows"
    assert not (workflows / "pages.yml").exists()
    assert not (ROOT / "docs" / "CNAME").exists()  # nginx would serve it at /CNAME
    for path in workflows.glob("*.yml"):
        assert not re.search(r"deploy-pages|upload-pages-artifact", path.read_text()), path.name
