"""Diagrams are pre-rendered by ``node scripts/render_diagrams.mjs`` and committed —
these tests are the CI-side half of that contract, and need no node at all.

Four checks, each catching a different way a committed SVG can drift from the
source it is supposed to be a picture of:

* every ``.mmd`` has both a ``-light.svg`` and a ``-dark.svg`` (staleness);
* each SVG's ``data-source-digest`` matches its source's own hash (staleness,
  precisely — the digest also folds in the mermaid-cli version, so a renderer
  upgrade without a re-render is caught too);
* the colours in each SVG are a subset of the docs site's own palette, so a
  ``docs.css`` redesign that forgets these diagrams fails here instead of
  shipping stale colours (this file's version of easywall's
  ``TestTheDiagramPaletteIsTheDocumentationPalette``);
* no SVG makes a network reference or carries a ``<script>``, so embedding one
  inline can never fetch anything or run anything.
"""

import hashlib
import re
from pathlib import Path

import pytest

from tests.built_site import css_of, page

ROOT = Path(__file__).parents[1]
DIAGRAMS_DIR = ROOT / "docs" / "_diagrams"
RENDERED_DIR = ROOT / "docs" / "img" / "diagrams"
RENDER_SCRIPT = ROOT / "scripts" / "render_diagrams.mjs"

THEMES = ("light", "dark")

_MMD_NAMES = sorted(p.stem for p in DIAGRAMS_DIR.glob("*.mmd"))


def _svg_path(name: str, theme: str) -> Path:
    return RENDERED_DIR / f"{name}-{theme}.svg"


def test_a_diagram_source_exists() -> None:
    """A guard against the guards below passing vacuously on an empty directory."""
    assert _MMD_NAMES, f"no .mmd files in {DIAGRAMS_DIR.relative_to(ROOT)}"


@pytest.mark.parametrize("name", _MMD_NAMES)
@pytest.mark.parametrize("theme", THEMES)
def test_every_diagram_is_rendered_for_both_themes(name: str, theme: str) -> None:
    svg = _svg_path(name, theme)
    assert svg.is_file(), (
        f"{svg.relative_to(ROOT)} is missing — run: node scripts/render_diagrams.mjs"
    )


def _mermaid_cli_version() -> str:
    js = RENDER_SCRIPT.read_text()
    m = re.search(r"MERMAID_CLI_VERSION = '([^']+)'", js)
    assert m, "render_diagrams.mjs has no MERMAID_CLI_VERSION"
    return m.group(1)


def _expected_digest(source: str) -> str:
    payload = f"{_mermaid_cli_version()}\n{source.strip()}"
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


@pytest.mark.parametrize("name", _MMD_NAMES)
@pytest.mark.parametrize("theme", THEMES)
def test_no_diagram_is_stale(name: str, theme: str) -> None:
    """The digest covers the .mmd source and the mermaid-cli version — not the
    theme's colours (see test_palette_matches_docs_site for that), and not the
    SVG's own layout, which mermaid does not reproduce byte-for-byte between two
    runs of the same input (see the comment on STAMP in render_diagrams.mjs's
    easywall counterpart) — only what determines that layout."""
    source = (DIAGRAMS_DIR / f"{name}.mmd").read_text()
    svg = _svg_path(name, theme).read_text()
    m = re.search(r'data-source-digest="([a-f0-9]+)"', svg)
    assert m, f"{name}-{theme}.svg has no data-source-digest"
    assert m.group(1) == _expected_digest(source), (
        f"{name}-{theme}.svg is stale — run: node scripts/render_diagrams.mjs"
    )


# ── palette ──────────────────────────────────────────────────────────────────


def _css_tokens(css: str, opener: str) -> dict[str, str]:
    """Reads the `--name: value;` pairs of one block of the docs stylesheet."""
    start = css.index(opener)
    open_brace = css.index("{", start)
    end = css.index("\n    }", start)  # docs.css indents rule bodies at 6 spaces
    body = css[open_brace:end]
    return dict(re.findall(r"(--[a-z0-9-]+)\s*:\s*([^;]+);", body))


def _js_theme(js: str, name: str) -> dict[str, str]:
    """Reads one theme object out of scripts/render_diagrams.mjs."""
    start = js.index(f"{name}: {{")
    end = js.index("\n  },", start)
    body = js[start:end]
    return dict(re.findall(r"(\w+):\s*'([^']*)'", body))


def _harmless_boilerplate_colors(js: str) -> set[str]:
    m = re.search(r"HARMLESS_MERMAID_BOILERPLATE_COLORS = \[([^\]]*)\]", js)
    assert m, "render_diagrams.mjs has no HARMLESS_MERMAID_BOILERPLATE_COLORS"
    return set(re.findall(r"'([^']*)'", m.group(1)))


# Which CSS custom property (docs/assets/css/docs.css) each mermaid themeVariable takes, in
# both themes. Kept here as a comparison rather than making the render script read
# docs.css, for the same reason as easywall's version of this test: this one
# fails immediately and names the token that moved; a script that reads the
# stylesheet needs a rebuild to reveal a mismatch, and rendering is not
# byte-reproducible, so a rebuild is not a free way to answer a question about
# colour.
_TOKENS = {
    "primaryColor": "--bg-raised",
    "primaryTextColor": "--text-primary",
    "primaryBorderColor": "--border-strong",
    "secondaryColor": "--bg-surface",
    "tertiaryColor": "--bg-base",
    "noteBkgColor": "--bg-overlay",
    "noteTextColor": "--text-muted",
    "noteBorderColor": "--border-subtle",
    "lineColor": "--text-secondary",
}


@pytest.mark.parametrize("theme,opener", [("light", ":root"), ("dark", '[data-theme="dark"]')])
def test_palette_matches_docs_site(theme: str, opener: str) -> None:
    css = css_of(page("/en/docs/"))
    js = RENDER_SCRIPT.read_text()

    want = _css_tokens(css, opener)
    got = _js_theme(js, theme)
    assert got, f"render_diagrams.mjs has no {theme} theme (or the file changed shape)"

    for mermaid_var, token in _TOKENS.items():
        assert token in want, f"docs.css defines no {token}, which {theme} {mermaid_var} takes"
        assert mermaid_var in got, (
            f"render_diagrams.mjs {theme} theme has no {mermaid_var}"
        )
        assert got[mermaid_var].lower() == want[token].lower(), (
            f"{theme} {mermaid_var} is {got[mermaid_var]}, "
            f"but docs.css {token} is {want[token]} — "
            "the committed diagrams would be drawn in a colour the documentation site no longer "
            "uses, and the staleness check cannot see it: the digest covers the .mmd source, the "
            "mermaid-cli version and the font, not the palette"
        )


_HEX_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b")
_BASE64_RE = re.compile(r"base64,[A-Za-z0-9+/=]+")


@pytest.mark.parametrize("name", _MMD_NAMES)
@pytest.mark.parametrize("theme,opener", [("light", ":root"), ("dark", '[data-theme="dark"]')])
def test_svg_colors_are_a_subset_of_the_docs_palette(name: str, theme: str, opener: str) -> None:
    css = css_of(page("/en/docs/"))
    js = RENDER_SCRIPT.read_text()
    palette = set(_css_tokens(css, opener).values())
    allowed = {c.lower() for c in palette} | {
        c.lower() for c in _harmless_boilerplate_colors(js)
    }

    svg = _svg_path(name, theme).read_text()
    # The embedded font is a base64 blob; base64's alphabet has no "#", so this
    # strip only guards against a coincidence, not a real risk.
    svg_without_font = _BASE64_RE.sub("", svg)
    used = {c.lower() for c in _HEX_RE.findall(svg_without_font)}

    stray = used - allowed
    assert not stray, (
        f"{name}-{theme}.svg uses colour(s) not in the docs palette: {sorted(stray)} — "
        "either docs.css's tokens moved and scripts/render_diagrams.mjs needs updating, "
        "or a new mermaid-cli version emits new boilerplate that belongs in "
        "HARMLESS_MERMAID_BOILERPLATE_COLORS"
    )


# ── no external references, no scripts ───────────────────────────────────────

# The SVG/XLink namespace declarations are not network requests; anything else
# starting http(s):// would be.
_ALLOWED_HTTP_REFS = {
    "http://www.w3.org/2000/svg",
    "http://www.w3.org/1999/xlink",
    "http://www.w3.org/1999/xhtml",
}
_HTTP_REF_RE = re.compile(r'https?://[^"\'\s)]*')


@pytest.mark.parametrize("name", _MMD_NAMES)
@pytest.mark.parametrize("theme", THEMES)
def test_svg_has_no_external_reference(name: str, theme: str) -> None:
    svg = _svg_path(name, theme).read_text()
    refs = set(_HTTP_REF_RE.findall(svg)) - _ALLOWED_HTTP_REFS
    assert not refs, f"{name}-{theme}.svg references external URL(s): {sorted(refs)}"


@pytest.mark.parametrize("name", _MMD_NAMES)
@pytest.mark.parametrize("theme", THEMES)
def test_svg_has_no_script(name: str, theme: str) -> None:
    svg = _svg_path(name, theme).read_text()
    assert "<script" not in svg.lower(), f"{name}-{theme}.svg contains a <script> element"
