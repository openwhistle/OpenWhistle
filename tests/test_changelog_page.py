"""docs/changelog.html is generated from CHANGELOG.md by
scripts/render_changelog.py and committed, like docs/roadmap.html: the site
is static HTML with no build step in CI. These guards keep the committed
page in sync with its source, keep CHANGELOG.md's version headings and link
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

ROOT = Path(__file__).parents[1]
CHANGELOG = ROOT / "CHANGELOG.md"
PAGE = ROOT / "docs" / "changelog.html"


def _load_renderer() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "render_changelog", ROOT / "scripts" / "render_changelog.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RENDER_CHANGELOG = _load_renderer()


def test_committed_page_matches_a_fresh_render() -> None:
    versions, link_defs = RENDER_CHANGELOG.parse(CHANGELOG.read_text())
    want = RENDER_CHANGELOG.render(versions, link_defs)
    have = PAGE.read_text()
    assert have == want, (
        "docs/changelog.html does not match CHANGELOG.md. "
        "Run `uv run python scripts/render_changelog.py` and commit the result."
    )


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
        assert url.startswith("https://github.com/openwhistle/OpenWhistle/"), (
            name, url
        )


_HREF_URL_RE = re.compile(r'(?:href|src)="(https?://[^"]+)"')
_ALLOWED_DOMAINS = ("github.com", "openwhistle.net")


def test_page_links_only_to_github_and_its_own_domain() -> None:
    html = PAGE.read_text()
    offenders = []
    for url in _HREF_URL_RE.findall(html):
        host = re.sub(r"^https?://", "", url).split("/")[0]
        if not any(host == d or host.endswith("." + d) for d in _ALLOWED_DOMAINS):
            offenders.append(url)
    assert not offenders, f"docs/changelog.html links outside github.com/openwhistle.net: " \
        f"{offenders}"


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
    html = RENDER_CHANGELOG.render(versions, link_defs)

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
