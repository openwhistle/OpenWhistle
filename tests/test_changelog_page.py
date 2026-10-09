"""/en/changelog/ is rendered from CHANGELOG.md at build time by
scripts/render_changelog.py (scripts/build_site.py calls it). These guards
keep the built page the render of its source, keep CHANGELOG.md's version headings and link
definitions in agreement with each other (deliberately re-checked here with
independent regexes, not by importing the renderer's own — a heading neither
one parses would otherwise be invisible to both, see easywall's
check-changelog-versions.mjs), keep the page free of links to anywhere but
GitHub and the site's own domain, and pin the renderer's own escaping and
list-nesting behaviour against a small fixture."""

import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest

from tests.built_site import built

ROOT = Path(__file__).parents[1]
CHANGELOG = ROOT / "CHANGELOG.md"


def _page() -> Path:
    return built() / "en/changelog/index.html"


def _load_renderer() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "render_changelog", ROOT / "scripts" / "render_changelog.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RENDER_CHANGELOG = _load_renderer()


def test_the_built_page_is_the_changelog() -> None:
    versions, link_defs = RENDER_CHANGELOG.parse(CHANGELOG.read_text())
    content = RENDER_CHANGELOG.render_content(versions, link_defs)
    assert content in _page().read_text(encoding="utf-8")


def test_the_older_page_holds_the_rest_and_no_release_is_on_both() -> None:
    versions, link_defs = RENDER_CHANGELOG.parse(CHANGELOG.read_text())
    older = RENDER_CHANGELOG.render_content(versions, link_defs, older=True)
    assert older in (built() / "en/changelog/older/index.html").read_text(encoding="utf-8")
    ids = lambda page: set(re.findall(r'<section class="docs-section" id="([^"]+)"', page))  # noqa: E731
    current = ids(RENDER_CHANGELOG.render_content(versions, link_defs))
    assert current and ids(older) and not current & ids(older)
    assert "v1-0-0" in ids(older) and "unreleased" in current
    # Unreleased plus the newest NEWEST releases: a count, so a release never breaks the budget.
    assert len(current - {"unreleased"}) <= 5 == RENDER_CHANGELOG.NEWEST


def test_render_content_holds_no_site_chrome() -> None:
    content = RENDER_CHANGELOG.render_content(*RENDER_CHANGELOG.parse(_FIXTURE))
    assert "<footer" not in content and "site-nav" not in content and "<head" not in content


# Deliberately independent of RENDER_CHANGELOG.HEADING_RE / LINK_DEF_RE: a
# heading or link definition that the renderer's own regex fails to parse
# would otherwise pass unnoticed on both sides of that one comparison.
_HEADING_RE = re.compile(r"^## \[([^\]]+)\]", re.MULTILINE)
_LINK_DEF_RE = re.compile(r"^\[([^\]]+)\]:\s*(\S+)", re.MULTILINE)


def test_every_version_heading_has_a_link_definition_and_vice_versa() -> None:
    changelog = CHANGELOG.read_text()
    headings = _HEADING_RE.findall(changelog)
    link_defs = dict(_LINK_DEF_RE.findall(changelog))

    assert headings, "CHANGELOG.md has no `## [x.y.z]` version headings"
    seen = set()
    for name in headings:
        assert name not in seen, f"version {name} has two headings"
        seen.add(name)
        assert name in link_defs, (
            f"CHANGELOG.md: [{name}] has a heading and no link definition "
            f"(`[{name}]: https://...`) at the foot of the file"
        )

    extra = set(link_defs) - seen
    assert not extra, f"link definition(s) with no matching heading: {sorted(extra)}"

    semver_headings = [n for n in headings if re.fullmatch(r"\d+\.\d+\.\d+", n)]
    assert semver_headings, "CHANGELOG.md has no `## [x.y.z]` semantic-version headings"
    for name in semver_headings:
        url = link_defs[name]
        assert url.startswith("https://github.com/openwhistle/OpenWhistle/"), (name, url)


_HREF_URL_RE = re.compile(r'(?:href|src)="(https?://[^"]+)"')
_ALLOWED_DOMAINS = ("github.com", "openwhistle.net")


def test_page_links_only_to_github_and_its_own_domain() -> None:
    html = _page().read_text(encoding="utf-8")
    offenders = []
    for url in _HREF_URL_RE.findall(html):
        host = re.sub(r"^https?://", "", url).split("/")[0]
        if not any(host == d or host.endswith("." + d) for d in _ALLOWED_DOMAINS):
            offenders.append(url)
    assert not offenders, f"/en/changelog/ links outside github.com/openwhistle.net: {offenders}"


# ── Renderer self-test on a small fixture ──────────────────────────────────

_FIXTURE = """## [9.9.9] — 2026-01-01

A paragraph with a [link](https://example.com/x?a=1&b=2) and `inline code`.

### Added

- A bullet with <script>alert(1)</script> that must come out escaped.
- A bullet with a nested list:
  - first nested item
  - second nested item with `code`
- **Bold** and *italic* together.

[9.9.9]: https://github.com/openwhistle/OpenWhistle/releases/tag/v9.9.9
"""


def test_renderer_escapes_and_nests_correctly_on_a_fixture() -> None:
    versions, link_defs = RENDER_CHANGELOG.parse(_FIXTURE)
    assert [v.name for v in versions] == ["9.9.9"]
    html = RENDER_CHANGELOG.render_content(versions, link_defs)

    # The literal <script> tag from the source must never appear unescaped.
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    # ...and it must not have been double-escaped either.
    assert "&amp;lt;" not in html

    # A link's URL keeps its query string, its ampersand HTML-escaped.
    assert '<a href="https://example.com/x?a=1&amp;b=2">link</a>' in html

    # Inline code, bold and italic all render as tags, not literal markup.
    assert "<code>inline code</code>" in html
    assert "<strong>Bold</strong>" in html
    assert "<em>italic</em>" in html

    # The nested bullet list is a real <ul> inside the parent <li>, and the
    # parent bullet's own <ul>...</ul> wrapper is not re-escaped.
    assert (
        "<li>A bullet with a nested list:<ul>"
        "<li>first nested item</li>"
        "<li>second nested item with <code>code</code></li>"
        "</ul></li>" in html
    )

    # The heading gets a stable id built from the version number.
    assert 'id="v9-9-9"' in html


def test_the_older_page_refuses_to_render_empty() -> None:
    few = "\n".join(
        f"## [1.0.{i}] — 2026-01-01\n\n- x\n\n[1.0.{i}]: https://example.test\n" for i in range(5)
    )
    versions, link_defs = RENDER_CHANGELOG.parse(few)
    assert RENDER_CHANGELOG.render_content(versions, link_defs)
    with pytest.raises(ValueError, match="would be empty"):
        RENDER_CHANGELOG.render_content(versions, link_defs, older=True)
