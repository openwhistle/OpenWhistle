# Website P2a: draw.io diagrams Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every diagram in the repository is a draw.io SVG in style C, light and dark, checked by geometry tests,
and Mermaid exists nowhere.

**Architecture:** Sources are draw.io XML whose cells name a role (`ow:step`), never a colour.
`scripts/render_diagrams.py` expands roles into style C per theme (colours from the DESIGN.md front matter),
exports with the digest-pinned draw.io CLI in podman or docker, embeds a Sora subset and stamps each SVG.
`scripts/diagram_geometry.py` measures the exported SVG with Sora's metrics, both right after a render and in
pytest. CI never runs draw.io.

**Tech Stack:** Python 3.14, fonttools (woff2 via brotli), PyYAML, draw.io desktop headless in a container,
pytest.

**Spec:** `docs-tech/specs/2026-10-02-website-p2-design.md` (section P2a). Background:
`docs-tech/specs/2026-10-01-website-redesign-design.md` § Diagrams.

## Global Constraints

- Code, comments and docs in English; German only as diagram labels and page content of `/de/` pages.
- Sync only with `uv sync --inexact --extra dev --extra s3 --extra e2e --group site`. Never pass `--extra ldap`,
  never sync without `--inexact` (python-ldap cannot be rebuilt on this host).
- Full suite: `export DATABASE_URL="postgresql+asyncpg://openwhistle:openwhistle@127.0.0.1:55432/openwhistle_test"
  REDIS_URL="redis://127.0.0.1:56379/1" SECRET_KEY="ci-test-secret-key-not-for-production" DEMO_MODE=true` then
  `uv run pytest -q -p no:cacheprovider` (coverage gate 90 %). Focused: `uv run pytest <file> -q --no-cov`.
- Lint before every commit: `uv run ruff check <py files>`, `npx --yes markdownlint-cli2 <md files>`,
  `uv lock --check` when `pyproject.toml` changed.
- Containers: `podman` (docker has no socket access on this host). The renderer accepts either.
- Draw.io image, one line, tag and digest:
  `docker.io/rlespinasse/drawio-desktop-headless:v1.73.0@sha256:f33bc2f204738209a063ce38edf8003959c3be09cc18ecc9087a295aa5c585ef`.
- Every export: `--theme light --embed-svg-fonts false`; `auto` writes `light-dark()`, which follows the OS.
- Sources: `html=0` (set by the renderer), line breaks by hand (`&#xa;`), never `whiteSpace=wrap`.
- Style C (maintainer's choice): filled cards, ink arrows, Start/Submit in `accent`, result in `ink`; dark nodes on
  `surface-2`.
- Labels never on a line: an edge label carries `<mxPoint as="offset" …/>`; the geometry test decides.
- Sora has no glyph for `→` or `✓`: write "to", "redirects to", or rephrase.
- Commit messages: conventional style; never mention "Claude Code"; end with exactly:

  ```text
  Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_013NwHs21bPEE5cpr4rDSeZz
  ```

- XML is parsed with the stdlib `xml.etree.ElementTree`: the only inputs are the repository's own sources and
  the SVGs the pinned image wrote from them, and Python's expat neither resolves external entities nor expands
  billion-laughs payloads. A security linter's `defusedxml` hint does not apply; say so in the report if it
  appears.
- Every finding is fixed in the task that found it, or reported as a concern. Nothing is carried forward.

## Review Focus

1. **A label Sora cannot draw** (`→`, `✓`, an emoji): the browser falls back to another font, and the measured
   geometry is wrong. Expect a refusal at render time and a red test. Pinned in Task 1 (`expand`) and Task 2
   (`problems`).
2. **A label touching an arrowhead or a node instead of the line**: just as unreadable as one on the line. Pinned
   in Task 2 (`test_a_label_on_an_arrowhead_is_found`, `test_a_label_over_a_node_is_found`).
3. **A colour written into a source**: it would hold in one theme and be wrong in the other. Expect a refusal.
   Pinned in Task 1 (`test_a_colour_in_a_source_is_refused`).
4. **A host with docker and no podman, or neither**: the script must still render, or name what is missing.
   Pinned in Task 3 (`test_engine_*`).
5. **A diagram renamed or deleted, the old SVG left behind; an English diagram on a German page, or the
   reverse**: expect a red test that names the file. Pinned in Task 4 (`test_every_svg_has_a_source`,
   `test_pages_show_diagrams_in_their_own_language`).

## File structure

| File | Responsibility |
| --- | --- |
| `scripts/render_diagrams.py` | Roles → style C per theme, export in a container, post-process (DOCTYPE, px, Sora, stamp) |
| `scripts/diagram_geometry.py` | Parse an exported SVG into cells; report text that does not fit, touches a line, overlaps |
| `tests/diagram_tools.py` | Load both scripts as modules for tests |
| `tests/test_render_diagrams.py` | Renderer unit tests (no container) |
| `tests/test_diagram_geometry.py` | Geometry unit tests on hand-made SVG |
| `tests/test_diagrams.py` | Rewritten: every committed diagram is current, legible, self-contained, in the right language; no Mermaid |
| `docs/_diagrams/*.drawio` | Site sources (`<name>.de.drawio` for German pages) |
| `docs-tech/_diagrams/*.drawio` | Maintainer-doc sources |
| `docs/img/diagrams/`, `docs-tech/img/diagrams/` | Rendered SVGs, committed |
| `docs-tech/diagrams.md` | How to add and render a diagram (replaces `docs/_diagrams/README.md`) |
| Removed | `docs/_diagrams/*.mmd`, `docs/_diagrams/README.md`, `scripts/render_diagrams.mjs` |

---

### Task 1: Renderer core: roles, palette, stamp

**Files:**

- Create: `scripts/render_diagrams.py`
- Create: `tests/diagram_tools.py`
- Create: `tests/test_render_diagrams.py`
- Modify: `pyproject.toml` (group `site`), `uv.lock`

**Interfaces:**

- Produces (used by Tasks 3, 4, 6):
  - `palette(design: Path = DESIGN) -> dict[str, dict[str, str]]`: theme → token → lower-case hex,
    aliases included.
  - `expand_style(style: str, colors: dict[str, str]) -> str`
  - `expand(source: str, theme: str, colors: dict | None = None) -> str`
  - `roles_by_id(source: str) -> dict[str, str]`
  - `stamp(source: str, theme: str) -> str`: 16 hex characters.
  - `sources(names: Sequence[str] = ()) -> list[tuple[Path, Path]]`: (source file, output dir).
  - `svg_path(source: Path, out_dir: Path, theme: str) -> Path`
  - Constants and classes: `class DiagramError(Exception)`, `ROLES`, `COMMON`, `ALIASES`, `THEMES`, `DIRS`,
    `IMAGE`, `FONTS`.
  - `tests/diagram_tools.py`: `renderer() -> ModuleType`, `geometry() -> ModuleType`.

- [ ] **Step 1: Declare the font dependency**

fonttools and brotli are in `uv.lock` only as transitive dependencies; the renderer and the tests import them
directly. In `pyproject.toml`, `[dependency-groups] site`, add one line (alphabetical):

```toml
site = [
    "fonttools[woff]>=4.66.0",
    "jinja2>=3.1.6",
    "markdown-it-py>=4.2.0",
    "pagefind[extended]>=1.5.2",
    "pyyaml>=6.0.3",
]
```

Run: `uv lock && uv sync --inexact --extra dev --extra s3 --extra e2e --group site && uv lock --check`
Expected: lock updated, check passes.

- [ ] **Step 2: Write the test loader**

`tests/diagram_tools.py`:

```python
"""The two diagram scripts as importable modules, for tests (scripts/ is not a package)."""

from __future__ import annotations

import importlib.util
import sys
from functools import cache
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # @dataclass looks its module up here
    spec.loader.exec_module(module)
    return module


@cache
def geometry() -> ModuleType:
    return _load("diagram_geometry")


@cache
def renderer() -> ModuleType:
    geometry()  # render_diagrams imports it by name
    return _load("render_diagrams")
```

- [ ] **Step 3: Write the failing tests**

`tests/test_render_diagrams.py`:

```python
"""scripts/render_diagrams.py turns role names into style C, one theme at a time."""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from tests.diagram_tools import renderer

SOURCE = """<mxfile><diagram name="t"><mxGraphModel><root>
<mxCell id="0"/><mxCell id="1" parent="0"/>
<mxCell id="a" value="Start" style="ow:start" vertex="1" parent="1">
  <mxGeometry x="0" y="0" width="120" height="40" as="geometry"/></mxCell>
<mxCell id="b" value="Case number&#xa;shown once" style="ow:result" vertex="1" parent="1">
  <mxGeometry x="0" y="80" width="120" height="52" as="geometry"/></mxCell>
<mxCell id="e" value="" style="ow:edge;exitX=0.5;exitY=1" edge="1" parent="1" source="a" target="b">
  <mxGeometry relative="1" as="geometry"/></mxCell>
</root></mxGraphModel></diagram></mxfile>"""


def _styles(xml: str) -> dict[str, str]:
    return {
        c.get("id"): c.get("style") for c in ET.fromstring(xml).iter("mxCell") if c.get("style")
    }


def test_palette_reads_both_themes_from_design_md() -> None:
    p = renderer().palette()
    assert p["light"]["canvas"] == "#ffffff"
    assert p["dark"]["canvas"] == "#08080a"
    assert p["light"]["node"] == p["light"]["surface"]
    assert p["dark"]["node"] == p["dark"]["surface-2"]


def test_one_light_value_keeps_its_role_in_dark() -> None:
    """#ffffff is canvas, surface-2 and accent-ink in light; each has its own dark value."""
    r = renderer()
    light, dark = r.palette()["light"], r.palette()["dark"]
    assert light["canvas"] == light["surface-2"] == light["accent-ink"] == "#ffffff"
    assert "fontColor=#08080a" in r.expand_style("ow:result", dark)  # canvas
    assert "fontColor=#06120d" in r.expand_style("ow:start", dark)  # accent-ink
    assert "fillColor=#1b1b1e" in r.expand_style("ow:step", dark)  # node = surface-2


def test_a_role_starts_with_the_common_settings_and_keeps_overrides() -> None:
    r = renderer()
    style = r.expand_style("ow:edge;exitX=1;exitY=0.5", r.palette()["light"])
    assert style.startswith(r.COMMON)
    assert "html=0" in style and "whiteSpace=nowrap" in style
    assert style.endswith("exitX=1;exitY=0.5")


@pytest.mark.parametrize("role", sorted(renderer().ROLES))
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_every_role_resolves_every_token(role: str, theme: str) -> None:
    r = renderer()
    assert "{" not in r.expand_style(role, r.palette()[theme])


def test_an_unknown_role_is_refused() -> None:
    r = renderer()
    with pytest.raises(r.DiagramError, match="unknown role"):
        r.expand_style("ow:box", r.palette()["light"])


@pytest.mark.parametrize(
    "key", ["fillColor", "strokeColor", "fontColor", "labelBackgroundColor", "swimlaneFillColor"]
)
def test_a_colour_in_a_source_is_refused(key: str) -> None:
    r = renderer()
    with pytest.raises(r.DiagramError, match="colours come from the role"):
        r.expand_style(f"ow:step;{key}=#ff0000", r.palette()["light"])


def test_expand_gives_every_cell_its_theme() -> None:
    r = renderer()
    styles = _styles(r.expand(SOURCE, "dark"))
    assert set(styles) == {"a", "b", "e"}
    assert "fillColor=#23c088" in styles["a"]
    assert "fillColor=#fafafa" in styles["b"]
    assert "strokeColor=#fafafa" in styles["e"]


def test_a_cell_without_a_role_is_refused() -> None:
    r = renderer()
    with pytest.raises(r.DiagramError, match="has no role"):
        r.expand(SOURCE.replace(' style="ow:result"', ""), "light")


@pytest.mark.parametrize("label", ["a → b", "done ✓"])
def test_a_label_sora_cannot_draw_is_refused(label: str) -> None:
    r = renderer()
    with pytest.raises(r.DiagramError, match="no glyph"):
        r.expand(SOURCE.replace('value="Start"', f'value="{label}"'), "light")


def test_roles_by_id_maps_every_vertex_and_edge() -> None:
    assert renderer().roles_by_id(SOURCE) == {"a": "ow:start", "b": "ow:result", "e": "ow:edge"}


def test_the_stamp_covers_source_theme_roles_image_and_fonts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r = renderer()
    base = r.stamp(SOURCE, "light")
    assert len(base) == 16
    assert r.stamp(SOURCE, "dark") != base
    assert r.stamp(SOURCE + " ", "light") != base
    monkeypatch.setitem(r.ROLES, "ow:step", r.ROLES["ow:step"] + "shadow=1;")
    assert r.stamp(SOURCE, "light") != base
    monkeypatch.undo()
    monkeypatch.setattr(r, "IMAGE", r.IMAGE.replace("v1.", "v9."))
    assert r.stamp(SOURCE, "light") != base


def test_sources_and_output_names(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    r = renderer()
    src, out = tmp_path / "src", tmp_path / "out"
    src.mkdir()
    (src / "flow.drawio").write_text(SOURCE)
    (src / "flow.de.drawio").write_text(SOURCE)
    monkeypatch.setattr(r, "DIRS", {src: out})
    assert [s.name for s, _ in r.sources()] == ["flow.de.drawio", "flow.drawio"]
    assert [s.name for s, _ in r.sources(["flow.de"])] == ["flow.de.drawio"]
    assert r.svg_path(src / "flow.de.drawio", out, "dark") == out / "flow.de-dark.svg"
    with pytest.raises(SystemExit, match="no source named"):
        r.sources(["nope"])
```

- [ ] **Step 4: Run them to verify they fail**

Run: `uv run pytest tests/test_render_diagrams.py -q --no-cov`
Expected: FAIL. `scripts/diagram_geometry.py` and `scripts/render_diagrams.py` do not exist (`FileNotFoundError`
from `diagram_tools._load`).

- [ ] **Step 5: Write the renderer core**

`scripts/render_diagrams.py`:

```python
"""Render every draw.io diagram to a committed light and a dark SVG.

    uv run python scripts/render_diagrams.py              render every source
    uv run python scripts/render_diagrams.py NAME ...     render the named ones (stem, e.g. home-flow.de)

A source names roles (style="ow:step"), never colours; ROLES is the one place style C
lives, and DESIGN.md's front matter is the one place a colour lives. Rendering needs
podman or docker; every check of the result is a pytest test (tests/test_diagrams.py),
so CI needs neither. How to add a diagram: docs-tech/diagrams.md.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from xml.etree import ElementTree as ET

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import diagram_geometry as geometry  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DESIGN = ROOT / "DESIGN.md"

# One line, so Renovate's regex manager moves tag and digest together.
IMAGE = "docker.io/rlespinasse/drawio-desktop-headless:v1.73.0@sha256:f33bc2f204738209a063ce38edf8003959c3be09cc18ecc9087a295aa5c585ef"  # noqa: E501

DIRS = {
    ROOT / "docs" / "_diagrams": ROOT / "docs" / "img" / "diagrams",
    ROOT / "docs-tech" / "_diagrams": ROOT / "docs-tech" / "img" / "diagrams",
}
THEMES = ("light", "dark")
FONTS = geometry.FONTS

# A token a role may use besides DESIGN.md's colours: one name, a different colour per
# theme. Dark nodes sit on surface-2; surface (#131315) barely parts from the #08080a page.
ALIASES = {"node": {"light": "surface", "dark": "surface-2"}}

COMMON = "fontFamily=Sora;fontSize=13;html=0;whiteSpace=nowrap;"
_BOX = "rounded=1;arcSize=14;absoluteArcSize=1;"
_EDGE = (
    "edgeStyle=orthogonalEdgeStyle;rounded=1;endArrow=classic;endSize=6;"
    "strokeColor={ink};fontColor={ink};fontSize=11;labelBackgroundColor=none;"
)
_PILL = (
    "rounded=1;arcSize=50;fillColor={accent};strokeColor=none;fontColor={accent-ink};fontStyle=1;"
)

# Style C, chosen by the maintainer on 2026-10-02 from three rendered variants.
ROLES = {
    "ow:start": _PILL,
    "ow:end": _PILL,
    "ow:step": _BOX + "fillColor={node};strokeColor=none;fontColor={ink};",
    "ow:result": _BOX + "fillColor={ink};strokeColor=none;fontColor={canvas};fontStyle=1;",
    "ow:decision": (
        "rhombus;perimeter=rhombusPerimeter;fillColor={canvas};strokeColor={ink};fontColor={ink};fontSize=12;"
    ),
    "ow:store": "shape=cylinder3;boundedLbl=1;size=8;fillColor={node};strokeColor={ink};fontColor={ink};",
    "ow:note": _BOX
    + "fillColor=none;strokeColor={muted};dashed=1;dashPattern=4 3;fontColor={muted};fontSize=12;",
    "ow:group": _BOX
    + (
        "container=1;fillColor=none;strokeColor={hairline};verticalAlign=top;align=left;"
        "spacingLeft=12;spacingTop=6;fontColor={muted};fontSize=11;fontStyle=1;"
    ),
    "ow:lane": "swimlane;startSize=32;"
    + _BOX
    + ("fillColor=none;swimlaneFillColor=none;strokeColor={hairline};fontColor={ink};fontStyle=1;"),
    "ow:lifeline": "shape=umlLifeline;perimeter=lifelinePerimeter;size=40;fillColor={node};strokeColor={muted};"
    "fontColor={ink};",
    "ow:edge": _EDGE,
    "ow:edge-optional": _EDGE + "dashed=1;dashPattern=4 3;",
    "ow:message": "endArrow=classic;endSize=6;strokeColor={ink};fontColor={ink};fontSize=11;"
    "labelBackgroundColor=none;align=left;",
}

_TOKEN = re.compile(r"\{([a-z0-9-]+)\}")
_COLOR_KEY = re.compile(r"(?:^|;)([A-Za-z]*Color)=")


class DiagramError(Exception):
    """A source the renderer refuses: it would not be style C in both themes."""


def palette(design: Path = DESIGN) -> dict[str, dict[str, str]]:
    """Theme -> token -> colour, from DESIGN.md's front matter, aliases included."""
    front = design.read_text(encoding="utf-8").split("---\n", 2)[1]
    colors = yaml.safe_load(front)["colors"]
    out: dict[str, dict[str, str]] = {t: {} for t in THEMES}
    for name, value in colors.items():
        if isinstance(value, dict):  # `primary` is a single tooling value, not a token
            for theme in THEMES:
                out[theme][name] = value[theme].lower()
    for alias, per_theme in ALIASES.items():
        for theme in THEMES:
            out[theme][alias] = out[theme][per_theme[theme]]
    return out


def expand_style(style: str, colors: dict[str, str]) -> str:
    """'ow:step;exitX=1' -> COMMON + the role's draw.io style in these colours + the overrides."""
    role, _, rest = style.partition(";")
    if role not in ROLES:
        raise DiagramError(f"unknown role {role!r}; a style starts with one of {sorted(ROLES)}")
    if m := _COLOR_KEY.search(rest):
        raise DiagramError(f"{m.group(1)} in a source: colours come from the role, not the cell")

    def token(m: re.Match[str]) -> str:
        if m.group(1) not in colors:
            raise DiagramError(f"role {role} uses {m.group(1)!r}, which DESIGN.md does not define")
        return colors[m.group(1)]

    return COMMON + _TOKEN.sub(token, ROLES[role]) + rest


def _drawable(cell: ET.Element) -> bool:
    return cell.get("vertex") == "1" or cell.get("edge") == "1"


def expand(source: str, theme: str, colors: dict[str, dict[str, str]] | None = None) -> str:
    """The source with every role replaced by its style in one theme; refuses what Sora cannot draw."""
    theme_colors = (colors or palette())[theme]
    root = ET.fromstring(source)
    for cell in root.iter("mxCell"):
        if not _drawable(cell):
            continue
        if not cell.get("style"):
            raise DiagramError(f"cell {cell.get('id')!r} has no role")
        cell.set("style", expand_style(cell.get("style", ""), theme_colors))
        label = cell.get("value", "").replace("\n", "")
        if missing := geometry.missing_glyphs(label, 400) or geometry.missing_glyphs(label, 700):
            raise DiagramError(f"cell {cell.get('id')!r}: Sora has no glyph for {missing}")
    return ET.tostring(root, encoding="unicode")


def roles_by_id(source: str) -> dict[str, str]:
    return {
        cell.get("id", ""): cell.get("style", "").partition(";")[0]
        for cell in ET.fromstring(source).iter("mxCell")
        if _drawable(cell)
    }


def stamp(source: str, theme: str) -> str:
    """Hash of everything that decides the picture: a change to any of it makes the SVG stale."""
    fonts = {str(w): hashlib.sha256(p.read_bytes()).hexdigest() for w, p in FONTS.items()}
    payload = json.dumps(
        {
            "source": source,
            "theme": theme,
            "common": COMMON,
            "roles": ROLES,
            "aliases": ALIASES,
            "palette": palette()[theme],
            "image": IMAGE,
            "fonts": fonts,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def sources(names: Sequence[str] = ()) -> list[tuple[Path, Path]]:
    found = [(p, out) for src, out in DIRS.items() for p in sorted(src.glob("*.drawio"))]
    if names:
        found = [f for f in found if f[0].name.removesuffix(".drawio") in names]
        unknown = set(names) - {f[0].name.removesuffix(".drawio") for f in found}
        if unknown:
            raise SystemExit(f"no source named {sorted(unknown)}")
    return found


def svg_path(source: Path, out_dir: Path, theme: str) -> Path:
    return out_dir / f"{source.name.removesuffix('.drawio')}-{theme}.svg"
```

Task 1 needs `geometry.missing_glyphs` and `geometry.FONTS`. Put this minimal version into
`scripts/diagram_geometry.py` (Task 2 extends this file, it does not replace these two):

```python
"""What every rendered diagram must hold: text fits its shape, and no text touches a line."""

from __future__ import annotations

from functools import cache
from pathlib import Path

from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[1]
FONTS = {
    400: ROOT / "docs" / "fonts" / "sora-latin-400-normal.woff2",
    700: ROOT / "docs" / "fonts" / "sora-latin-700-normal.woff2",
}


@cache
def font(weight: int) -> TTFont:
    return TTFont(FONTS[weight])


def missing_glyphs(text: str, weight: int) -> list[str]:
    cmap = font(weight).getBestCmap()
    return sorted({ch for ch in text if ord(ch) not in cmap})
```

- [ ] **Step 6: Run the tests to verify they pass**

Run:

```bash
uv run pytest tests/test_render_diagrams.py -q --no-cov \
  && uv run ruff check scripts/render_diagrams.py scripts/diagram_geometry.py tests/diagram_tools.py tests/test_render_diagrams.py
```

Expected: all PASS, ruff clean.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock scripts/render_diagrams.py scripts/diagram_geometry.py tests/diagram_tools.py tests/test_render_diagrams.py
git commit -m "feat(site): diagram sources name roles; the renderer expands them into style C per theme"
```

---

### Task 2: Geometry checks

**Files:**

- Modify: `scripts/diagram_geometry.py`
- Create: `tests/test_diagram_geometry.py`

**Interfaces:**

- Consumes: `FONTS`, `font()`, `missing_glyphs()` from Task 1.
- Produces:
  - `problems(svg: str, roles: dict[str, str]) -> list[str]`: empty means legible. Each message starts with
    the cell id.
  - `texts(svg: str) -> list[Text]`: every text line with its box and weight (Task 3 reads the characters per
    weight).
  - `text_box(text, x, y, size, weight, anchor) -> Box`
  - Constants: `EDGES`, `LINES`, `CONTAINERS`, `CLEAR`, `PAD_X`, `PAD_Y`.

- [ ] **Step 1: Write the failing tests**

`tests/test_diagram_geometry.py`. The SVG mimics draw.io's export: every cell is a
`<g data-cell-id>` holding its own shape, path and text, with child cells nested.

```python
"""scripts/diagram_geometry.py finds every way a rendered label stops being readable."""

from __future__ import annotations

from tests.diagram_tools import geometry

HEAD = '<svg xmlns="http://www.w3.org/2000/svg" width="600" height="400" viewBox="0 0 600 400"><g>'
TAIL = "</g></svg>"


def _text(
    x: float, y: float, text: str, size: int = 13, bold: bool = False, anchor: str = "middle"
) -> str:
    weight = ' font-weight="bold"' if bold else ""
    return (
        f'<g><g fill="#0a0a0b" font-family="Sora"{weight} text-anchor="{anchor}" font-size="{size}px">'
        f'<text x="{x}" y="{y}">{text}</text></g></g>'
    )


def node(cid: str, x: float, y: float, w: float, h: float, label: str = "", inner: str = "") -> str:
    text = _text(x + w / 2, y + h / 2 + 4.5, label) if label else ""
    return (
        f'<g data-cell-id="{cid}"><g><rect x="{x}" y="{y}" width="{w}" height="{h}" '
        f'fill="#f6f6f5" stroke="none"/></g>{text}{inner}</g>'
    )


def decision(cid: str, cx: float, cy: float, w: float, h: float, label: str) -> str:
    d = f"M {cx} {cy - h / 2} L {cx + w / 2} {cy} L {cx} {cy + h / 2} L {cx - w / 2} {cy} Z"
    return (
        f'<g data-cell-id="{cid}"><g><path d="{d}" fill="#ffffff" stroke="#0a0a0b"/></g>'
        f"{_text(cx, cy + 4, label, 12)}</g>"
    )


def edge(
    cid: str, points: list[tuple[float, float]], label: str = "", at: tuple[float, float] = (0, 0)
) -> str:
    d = "M " + " L ".join(f"{x} {y}" for x, y in points)
    (x1, y1) = points[-1]
    head = f"M {x1} {y1} L {x1 - 4} {y1 - 7} L {x1 + 4} {y1 - 7} Z"
    text = _text(at[0], at[1], label, 11) if label else ""
    return (
        f'<g data-cell-id="{cid}"><g><path d="{d}" fill="none" stroke="#0a0a0b"/>'
        f'<path d="{head}" fill="#0a0a0b" stroke="#0a0a0b"/></g>{text}</g>'
    )


def svg(*cells: str) -> str:
    return HEAD + '<g data-cell-id="0"><g data-cell-id="1">' + "".join(cells) + "</g></g>" + TAIL


ROLES = {"a": "ow:step", "b": "ow:step", "d": "ow:decision", "e": "ow:edge", "g": "ow:group"}


def test_a_clean_diagram_has_no_problem() -> None:
    picture = svg(
        node("a", 0, 0, 200, 40, "Start a report"),
        edge("e", [(100, 40), (100, 120)], "no", at=(114, 84)),
        node("b", 0, 120, 200, 40, "Category"),
    )
    assert geometry().problems(picture, ROLES) == []


def test_a_label_on_its_own_line_is_found() -> None:
    picture = svg(edge("e", [(0, 100), (300, 100)], "yes", at=(150, 104)))
    assert any("touches a line of e" in p for p in geometry().problems(picture, ROLES))


def test_a_label_beside_its_line_is_fine() -> None:
    picture = svg(edge("e", [(0, 100), (300, 100)], "yes", at=(150, 88)))
    assert geometry().problems(picture, ROLES) == []


def test_a_line_through_a_decision_label_is_found() -> None:
    picture = svg(
        decision("d", 150, 100, 230, 80, "Locations"),
        edge("e", [(150, 100), (400, 100)]),
    )
    assert any(
        p.startswith("d: ") and "touches a line" in p for p in geometry().problems(picture, ROLES)
    )


def test_text_wider_than_its_box_is_found() -> None:
    picture = svg(node("a", 0, 0, 60, 40, "Choose own password"))
    assert any("does not fit" in p for p in geometry().problems(picture, ROLES))


def test_text_in_a_decision_corner_is_found() -> None:
    """The bounding box would hold it; the diamond does not."""
    picture = svg(decision("d", 150, 100, 160, 50, "Password set by someone"))
    assert any("does not fit" in p for p in geometry().problems(picture, ROLES))


def test_a_label_on_an_arrowhead_is_found() -> None:
    picture = svg(edge("e", [(100, 0), (100, 100)], "x", at=(108, 97)))
    assert any("arrowhead" in p for p in geometry().problems(picture, ROLES))


def test_a_label_over_a_node_is_found() -> None:
    picture = svg(
        node("a", 0, 0, 200, 40, "Start"),
        edge("e", [(250, 0), (250, 100)], "username", at=(205, 20)),
    )
    assert any("overlaps a" in p for p in geometry().problems(picture, ROLES))


def test_overlapping_nodes_are_found() -> None:
    picture = svg(node("a", 0, 0, 200, 40, "One"), node("b", 150, 20, 200, 40, "Two"))
    assert any("a and b overlap" in p for p in geometry().problems(picture, ROLES))


def test_a_container_may_hold_nodes() -> None:
    picture = svg(node("g", 0, 0, 400, 200, inner=node("a", 20, 40, 200, 40, "PostgreSQL")))
    assert geometry().problems(picture, ROLES) == []


def test_a_child_text_is_not_measured_against_its_container() -> None:
    """A child cell's text belongs to the child: nested <g data-cell-id> ends the parent."""
    picture = svg(node("g", 0, 0, 400, 200, inner=node("a", 20, 40, 60, 40, "Choose own password")))
    found = geometry().problems(picture, ROLES)
    assert any(p.startswith("a: ") and "does not fit" in p for p in found)
    assert not any(p.startswith("g: ") for p in found)


def test_a_glyph_sora_lacks_is_found() -> None:
    picture = svg(node("a", 0, 0, 200, 40, "80 → 443"))
    assert any("no glyph" in p for p in geometry().problems(picture, ROLES))


def test_bold_is_measured_wider() -> None:
    g = geometry()
    regular = g.text_box("Submit", 0, 0, 13, 400, "start")
    bold = g.text_box("Submit", 0, 0, 13, 700, "start")
    assert bold.x1 > regular.x1 > 30


def test_an_unknown_path_command_fails_loudly() -> None:
    picture = svg(
        '<g data-cell-id="e"><g><path d="m 0 0 l 10 10" fill="none" stroke="#000"/></g></g>'
    )
    try:
        geometry().problems(picture, ROLES)
    except ValueError as err:
        assert "path command" in str(err)
    else:
        raise AssertionError("a relative path command was silently ignored")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_diagram_geometry.py -q --no-cov`
Expected: FAIL. `problems` and `text_box` are not defined.

- [ ] **Step 3: Write the geometry module**

Replace `scripts/diagram_geometry.py` with this (Task 1's three definitions are kept unchanged at the top):

```python
"""What every rendered diagram must hold: text fits its shape, and no text touches a line.

problems() reads the SVG draw.io exported, where every cell is a <g data-cell-id="...">
holding its own shape, lines and text, with child cells nested inside. Pure functions:
tests/test_diagrams.py runs them on every committed SVG, scripts/render_diagrams.py right
after a render. Text is measured with Sora's own metrics, because the headless exporter
measures with whatever fallback font its container has.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from xml.etree import ElementTree as ET

from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[1]
FONTS = {
    400: ROOT / "docs" / "fonts" / "sora-latin-400-normal.woff2",
    700: ROOT / "docs" / "fonts" / "sora-latin-700-normal.woff2",
}
EDGES = {"ow:edge", "ow:edge-optional", "ow:message"}
LINES = EDGES | {"ow:lifeline"}  # their unfilled paths are lines text must clear
CONTAINERS = {"ow:group", "ow:lane", "ow:lifeline"}  # boxes that hold other cells
PAD_X = 6.0  # room between a text line and the side of its shape
PAD_Y = 2.0
CLEAR = 3.0  # gap between any text and any line, arrowhead or foreign node

_INHERITED = ("font-size", "font-weight", "text-anchor", "fill", "stroke")
_NUMBER = r"-?(?:\d+\.?\d*|\.\d+)(?:[eE]-?\d+)?"
_PATH_TOKEN = re.compile(rf"[MLQCZ]|{_NUMBER}")
_ARGS = {"M": 2, "L": 2, "Q": 4, "C": 6}

Point = tuple[float, float]
Segment = tuple[Point, Point]


@cache
def font(weight: int) -> TTFont:
    return TTFont(FONTS[weight])


def missing_glyphs(text: str, weight: int) -> list[str]:
    cmap = font(weight).getBestCmap()
    return sorted({ch for ch in text if ord(ch) not in cmap})


@dataclass(frozen=True)
class Box:
    x0: float
    y0: float
    x1: float
    y1: float

    def grow(self, dx: float, dy: float | None = None) -> Box:
        dy = dx if dy is None else dy
        return Box(self.x0 - dx, self.y0 - dy, self.x1 + dx, self.y1 + dy)

    def overlaps(self, o: Box) -> bool:
        return self.x0 < o.x1 and o.x0 < self.x1 and self.y0 < o.y1 and o.y0 < self.y1

    def within(self, o: Box) -> bool:
        return o.x0 <= self.x0 and self.x1 <= o.x1 and o.y0 <= self.y0 and self.y1 <= o.y1

    def corners(self) -> list[Point]:
        return [(self.x0, self.y0), (self.x1, self.y0), (self.x1, self.y1), (self.x0, self.y1)]


@dataclass(frozen=True)
class Text:
    text: str
    box: Box
    weight: int


@dataclass
class Cell:
    id: str
    rects: list[Box] = field(default_factory=list)
    filled: list[list[Point]] = field(default_factory=list)
    unfilled: list[list[Point]] = field(default_factory=list)
    texts: list[Text] = field(default_factory=list)


def _bounds(points: list[Point]) -> Box:
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return Box(min(xs), min(ys), max(xs), max(ys))


def _union(boxes: list[Box]) -> Box | None:
    if not boxes:
        return None
    return Box(
        min(b.x0 for b in boxes),
        min(b.y0 for b in boxes),
        max(b.x1 for b in boxes),
        max(b.y1 for b in boxes),
    )


def _num(value: str | None) -> float:
    m = re.match(_NUMBER, value or "0")
    return float(m.group(0)) if m else 0.0


def _subpaths(d: str) -> list[list[Point]]:
    """A draw.io path as point lists; a curve counts by its end point (corner radii are small)."""
    if leftover := _PATH_TOKEN.sub("", d).replace(",", "").strip():
        raise ValueError(f"path command not understood: {leftover!r} in {d!r}")
    tokens = _PATH_TOKEN.findall(d)
    out: list[list[Point]] = []
    cmd, i = "", 0
    while i < len(tokens):
        if tokens[i] in "MLQCZ":
            cmd, i = tokens[i], i + 1
            if cmd == "Z":
                if out and out[-1]:
                    out[-1].append(out[-1][0])
                continue
        if not cmd or cmd == "Z":
            raise ValueError(f"path command not understood: numbers without a command in {d!r}")
        args = [float(t) for t in tokens[i : i + _ARGS[cmd]]]
        i += _ARGS[cmd]
        point = (args[-2], args[-1])
        if cmd == "M":
            out.append([point])
            cmd = "L"  # numbers after a moveto are linetos
        else:
            out[-1].append(point)
    return out


def text_box(text: str, x: float, y: float, size: float, weight: int, anchor: str) -> Box:
    """The inked box of one line: advance widths across, glyph outlines up and down."""
    f = font(weight)
    cmap, hmtx, glyf = f.getBestCmap(), f["hmtx"], f["glyf"]
    scale = size / f["head"].unitsPerEm
    names = [cmap[ord(ch)] for ch in text if ord(ch) in cmap]
    width = sum(hmtx[n][0] for n in names) * scale
    tops = [getattr(glyf[n], "yMax", 0) for n in names] or [0]
    bottoms = [getattr(glyf[n], "yMin", 0) for n in names] or [0]
    x0 = {"middle": x - width / 2, "end": x - width}.get(anchor, x)
    return Box(x0, y - max(tops) * scale, x0 + width, y - min(bottoms) * scale)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _cells(svg: str) -> dict[str, Cell]:
    found: dict[str, Cell] = {}

    def walk(el: ET.Element, inherited: dict[str, str], cell: Cell | None) -> None:
        attrs = {**inherited, **{k: v for k in _INHERITED if (v := el.get(k)) is not None}}
        if (cid := el.get("data-cell-id")) is not None:
            cell = found.setdefault(cid, Cell(cid))
        tag = _local(el.tag)
        if cell is not None and tag == "rect":
            x, y = _num(el.get("x")), _num(el.get("y"))
            cell.rects.append(Box(x, y, x + _num(el.get("width")), y + _num(el.get("height"))))
        elif cell is not None and tag == "ellipse":
            cx, cy, rx, ry = (_num(el.get(k)) for k in ("cx", "cy", "rx", "ry"))
            cell.rects.append(Box(cx - rx, cy - ry, cx + rx, cy + ry))
        elif cell is not None and tag == "path":
            target = cell.unfilled if attrs.get("fill", "black") == "none" else cell.filled
            target.extend(p for p in _subpaths(el.get("d", "")) if len(p) > 1)
        elif cell is not None and tag == "text":
            weight = 700 if attrs.get("font-weight") in ("bold", "700") else 400
            line = "".join(el.itertext())
            box = text_box(
                line,
                _num(el.get("x")),
                _num(el.get("y")),
                _num(attrs.get("font-size", "12")),
                weight,
                attrs.get("text-anchor", "start"),
            )
            cell.texts.append(Text(line, box, weight))
            return
        for child in el:
            walk(child, attrs, cell)

    walk(ET.fromstring(svg), {}, None)
    return found


def texts(svg: str) -> list[Text]:
    return [t for cell in _cells(svg).values() for t in cell.texts]


def _hits(box: Box, seg: Segment) -> bool:
    """Liang-Barsky: does the segment cross the box?"""
    (x0, y0), (x1, y1) = seg
    dx, dy = x1 - x0, y1 - y0
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x0 - box.x0), (dx, box.x1 - x0), (-dy, y0 - box.y0), (dy, box.y1 - y0)):
        if p == 0:
            if q < 0:
                return False
            continue
        t = q / p
        if p < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 > t1:
            return False
    return True


def _inside(point: Point, polygon: list[Point]) -> bool:
    x, y = point
    inside = False
    for (xa, ya), (xb, yb) in zip(polygon, polygon[1:] + polygon[:1], strict=True):
        if (ya > y) != (yb > y) and x < (xb - xa) * (y - ya) / (yb - ya) + xa:
            inside = not inside
    return inside


def _segments(paths: list[list[Point]]) -> list[Segment]:
    return [(a, b) for pts in paths for a, b in zip(pts, pts[1:], strict=False)]


def _outline(cell: Cell) -> Box | None:
    return _union(cell.rects + [_bounds(p) for p in cell.filled + cell.unfilled])


def _fits(t: Text, cell: Cell, role: str) -> bool:
    if role == "ow:decision" and cell.filled:
        diamond = cell.filled[0]
        return all(_inside(c, diamond) for c in t.box.grow(PAD_X / 2, PAD_Y).corners())
    outline = _outline(cell)
    return outline is not None and t.box.grow(PAD_X, PAD_Y).within(outline)


def problems(svg: str, roles: dict[str, str]) -> list[str]:
    """Everything that makes a label unreadable; an empty list means the diagram is legible."""
    found = _cells(svg)
    lines = [
        (cid, s)
        for cid, c in found.items()
        if roles.get(cid) in LINES
        for s in _segments(c.unfilled)
    ]
    heads = [
        (cid, _bounds(p)) for cid, c in found.items() if roles.get(cid) in EDGES for p in c.filled
    ]
    solid = {
        cid: box
        for cid, c in found.items()
        if cid in roles
        and roles[cid] not in EDGES | CONTAINERS
        and (box := _outline(c)) is not None
    }
    out: list[str] = []
    for cid, cell in found.items():
        role = roles.get(cid, "")
        for t in cell.texts:
            if missing := missing_glyphs(t.text, t.weight):
                out.append(f"{cid}: Sora has no glyph for {missing} in {t.text!r}")
            if role and role not in EDGES and not _fits(t, cell, role):
                out.append(f"{cid}: text {t.text!r} does not fit its shape")
            near = t.box.grow(CLEAR)
            out += [
                f"{cid}: text {t.text!r} touches a line of {lid}"
                for lid, s in lines
                if _hits(near, s)
            ]
            if role in EDGES:
                out += [
                    f"{cid}: label {t.text!r} touches an arrowhead of {hid}"
                    for hid, b in heads
                    if near.overlaps(b)
                ]
                out += [
                    f"{cid}: label {t.text!r} overlaps {nid}"
                    for nid, b in solid.items()
                    if near.overlaps(b)
                ]
    ids = sorted(solid)
    out += [
        f"{a} and {b} overlap"
        for i, a in enumerate(ids)
        for b in ids[i + 1 :]
        if solid[a].overlaps(solid[b])
    ]
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:

```bash
uv run pytest tests/test_diagram_geometry.py tests/test_render_diagrams.py -q --no-cov \
  && uv run ruff check scripts/diagram_geometry.py tests/test_diagram_geometry.py
```

Expected: all PASS.

The test coordinates are measured against Sora: "x" at 11 px is 6.16 px wide, 5.87 px tall, so `at=(108, 97)`
is 1.9 px clear of the line and inside `CLEAR` of the arrowhead. If a geometry test disagrees, recompute the
coordinates; never relax `CLEAR`, `PAD_X` or `PAD_Y`.

- [ ] **Step 5: Commit**

```bash
git add scripts/diagram_geometry.py tests/test_diagram_geometry.py
git commit -m "feat(site): geometry checks find labels on lines, clipped text and overlaps in a rendered diagram"
```

---

### Task 3: Export, post-processing, Renovate

**Files:**

- Modify: `scripts/render_diagrams.py`
- Modify: `renovate.json` (`customManagers`)
- Modify: `tests/test_render_diagrams.py`

**Interfaces:**

- Consumes: Task 1 (`expand`, `stamp`, `sources`, `svg_path`, `roles_by_id`), Task 2 (`texts`, `problems`).
- Produces:
  - `engine() -> str`
  - `export(src_dir: Path, out_dir: Path) -> None`
  - `font_faces(svg: str) -> str`
  - `postprocess(svg: str, stamp_value: str) -> str`
  - `main(argv: Sequence[str] | None = None) -> int`: 0 = rendered and legible; 1 = written, but `problems()`
    found something (printed to stderr).
  - The stamp attribute is `data-ow-stamp="<16 hex>"` on the root `<svg>`.

- [ ] **Step 1: Write the failing tests**

Add `import base64`, `import io`, `import json`, `import re` and `from fontTools.ttLib import TTFont` to the
imports at the top of `tests/test_render_diagrams.py` (ruff E402 forbids them mid-file), then append:

```python
EXPORTED = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">\n'
    '<svg xmlns="http://www.w3.org/2000/svg" style="color-scheme: light;" version="1.1" '
    'width="498px" height="745px" viewBox="0 0 498 745"><defs/><g>'
    '<g data-cell-id="a"><g fill="#ffffff" font-family="Sora" font-weight="bold" text-anchor="middle" '
    'font-size="13px"><text x="60" y="25">Submit</text></g></g>'
    '<g data-cell-id="b"><g fill="#0a0a0b" font-family="Sora" text-anchor="middle" font-size="13px">'
    '<text x="60" y="105">Größe § 1</text></g></g></g></svg>'
)


def _faces(svg: str) -> dict[int, TTFont]:
    out = {}
    for weight, data in re.findall(
        r"font-weight:(\d+);src:url\(data:font/woff2;base64,([^)]+)\)", svg
    ):
        out[int(weight)] = TTFont(io.BytesIO(base64.b64decode(data)))
    return out


def test_postprocess_drops_the_doctype_and_the_px_units_and_stamps() -> None:
    out = renderer().postprocess(EXPORTED, "0123456789abcdef")
    assert "<!DOCTYPE" not in out and "svg11.dtd" not in out
    assert 'width="498"' in out and 'height="745"' in out
    assert 'data-ow-stamp="0123456789abcdef"' in out


def test_postprocess_embeds_sora_for_every_weight_it_uses() -> None:
    faces = _faces(renderer().postprocess(EXPORTED, "0" * 16))
    assert set(faces) == {400, 700}
    assert {ord(c) for c in "Submit"} <= set(faces[700].getBestCmap())
    assert {ord(c) for c in "Größe § 1"} <= set(faces[400].getBestCmap())


def test_the_embedded_font_is_a_subset() -> None:
    faces = _faces(renderer().postprocess(EXPORTED, "0" * 16))
    assert len(faces[700].getGlyphOrder()) < 20


def test_engine_prefers_podman(monkeypatch: pytest.MonkeyPatch) -> None:
    r = renderer()
    monkeypatch.setattr(r.shutil, "which", lambda name: f"/usr/bin/{name}")
    assert r.engine() == "podman"


def test_engine_falls_back_to_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    r = renderer()
    monkeypatch.setattr(
        r.shutil, "which", lambda name: "/usr/bin/docker" if name == "docker" else None
    )
    assert r.engine() == "docker"


def test_engine_names_what_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    r = renderer()
    monkeypatch.setattr(r.shutil, "which", lambda name: None)
    with pytest.raises(SystemExit, match="podman or docker"):
        r.engine()


def test_export_runs_the_pinned_image_offline_in_light(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    r = renderer()
    calls: list[list[str]] = []
    monkeypatch.setattr(r, "engine", lambda: "podman")
    monkeypatch.setattr(r.subprocess, "run", lambda args, check: calls.append(args))
    r.export(tmp_path / "in", tmp_path / "out")
    args = calls[0]
    assert args[:2] == ["podman", "run"] and "--network=none" in args and r.IMAGE in args
    assert args[args.index("--theme") + 1] == "light"
    assert args[args.index("--embed-svg-fonts") + 1] == "false"


def test_renovate_moves_the_image_tag_and_digest_together() -> None:
    config = json.loads((Path(__file__).parents[1] / "renovate.json").read_text())
    manager = next(
        m
        for m in config["customManagers"]
        if any("render_diagrams" in p for p in m["managerFilePatterns"])
    )
    script = (Path(__file__).parents[1] / "scripts" / "render_diagrams.py").read_text()
    pattern = manager["matchStrings"][0].replace("(?<", "(?P<")
    m = re.search(pattern, script)
    assert m, "Renovate's regex does not match the IMAGE line"
    assert renderer().IMAGE.endswith(f"{m['depName']}:{m['currentValue']}@{m['currentDigest']}")
    assert manager["datasourceTemplate"] == "docker"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_render_diagrams.py -q --no-cov`
Expected: FAIL. `postprocess`, `engine` and `export` are not defined, and renovate.json has no manager.

- [ ] **Step 3: Implement export and post-processing**

Add to the imports of `scripts/render_diagrams.py`:

```python
import base64
import io
import shutil
import subprocess
import tempfile

from fontTools import subset
from fontTools.ttLib import TTFont
```

Append to `scripts/render_diagrams.py`:

```python
def engine() -> str:
    for name in ("podman", "docker"):
        if shutil.which(name):
            return name
    raise SystemExit("render_diagrams.py needs podman or docker on PATH")


def export(src_dir: Path, out_dir: Path) -> None:
    """Every .drawio in src_dir to an SVG of the same stem in out_dir, offline, light, no font fetch."""
    subprocess.run(
        [
            engine(),
            "run",
            "--rm",
            "--network=none",
            "-v",
            f"{src_dir}:/in:ro,Z",
            "-v",
            f"{out_dir}:/out:Z",
            IMAGE,
            "-x",
            "-f",
            "svg",
            "--theme",
            "light",
            "--embed-svg-fonts",
            "false",
            "-b",
            "12",
            "-o",
            "/out/",
            "/in/",
        ],
        check=True,
    )


def font_faces(svg: str) -> str:
    """@font-face rules carrying exactly the Sora glyphs the picture draws, per weight."""
    chars: dict[int, set[str]] = {}
    for t in geometry.texts(svg):
        chars.setdefault(t.weight, set()).update(t.text)
    rules = []
    for weight in sorted(chars):
        font = TTFont(FONTS[weight], recalcTimestamp=False)
        subsetter = subset.Subsetter(subset.Options())
        subsetter.populate(text="".join(sorted(chars[weight])))
        subsetter.subset(font)
        font.flavor = "woff2"
        buf = io.BytesIO()
        font.save(buf)
        data = base64.b64encode(buf.getvalue()).decode()
        rules.append(
            f'@font-face{{font-family:"Sora";font-weight:{weight};'
            f'src:url(data:font/woff2;base64,{data}) format("woff2")}}'
        )
    return "".join(rules)


def postprocess(svg: str, stamp_value: str) -> str:
    """The exported SVG made self-contained: no DTD URL, unitless size, Sora inside, stamped."""
    svg = re.sub(r"<!DOCTYPE[^>]*>\s*", "", svg)
    root = re.search(r"<svg\b[^>]*>", svg)
    if not root:
        raise DiagramError("the export has no <svg> element")
    tag = re.sub(r'\b(width|height)="([\d.]+)px"', r'\1="\2"', root.group(0))
    tag = tag.replace("<svg ", f'<svg data-ow-stamp="{stamp_value}" ', 1)
    style = f"<defs><style>{font_faces(svg)}</style></defs>"
    return svg[: root.start()] + tag + style + svg[root.end() :]


def main(argv: Sequence[str] | None = None) -> int:
    todo = sources(sys.argv[1:] if argv is None else argv)
    colors = palette()
    failed = False
    # Docker writes the exports as root; leaving them in /tmp beats crashing on cleanup.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        src_dir, out_dir = Path(tmp, "in"), Path(tmp, "out")
        src_dir.mkdir()
        out_dir.mkdir()
        for source, _ in todo:
            text = source.read_text(encoding="utf-8")
            for theme in THEMES:
                name = svg_path(source, src_dir, theme).with_suffix(".drawio")
                name.write_text(expand(text, theme, colors), encoding="utf-8")
        export(src_dir, out_dir)
        for source, dest in todo:
            text = source.read_text(encoding="utf-8")
            for theme in THEMES:
                target = svg_path(source, dest, theme)
                exported = (out_dir / target.name).read_text(encoding="utf-8")
                svg = postprocess(exported, stamp(text, theme))
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(svg, encoding="utf-8")
                for problem in geometry.problems(svg, roles_by_id(text)):
                    failed = True
                    print(f"{target}: {problem}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Add the Renovate manager**

Append to `customManagers` in `renovate.json`:

```json
    {
      "customType": "regex",
      "description": "The draw.io CLI image scripts/render_diagrams.py exports with, tag and digest on one line. A bump changes every diagram stamp, so the PR stays red until scripts/render_diagrams.py re-renders. The regex manager's default versioning (semver-coerced) reads the v prefix.",
      "managerFilePatterns": [
        "/^scripts/render_diagrams\\.py$/"
      ],
      "matchStrings": [
        "IMAGE = \"docker\\.io/(?<depName>rlespinasse/drawio-desktop-headless):(?<currentValue>v\\d+\\.\\d+\\.\\d+)@(?<currentDigest>sha256:[0-9a-f]{64})\""
      ],
      "datasourceTemplate": "docker"
    }
```

Run: `python3 -m json.tool renovate.json > /dev/null`
Expected: no output (valid JSON). The Renovate test in Step 1 checks that the regex matches.

- [ ] **Step 5: Run the tests to verify they pass**

Run:

```bash
uv run pytest tests/test_render_diagrams.py tests/test_diagram_geometry.py -q --no-cov \
  && uv run ruff check scripts/ tests/test_render_diagrams.py
```

Expected: all PASS.

- [ ] **Step 6: Smoke-render a scratch source in the real container**

```bash
mkdir -p /tmp/ow-smoke && cat > /tmp/ow-smoke/smoke.drawio <<'EOF'
<mxfile><diagram name="smoke"><mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/>
<mxCell id="a" value="Start a report" style="ow:start" vertex="1" parent="1"><mxGeometry x="0" y="0" width="200" height="40" as="geometry"/></mxCell>
<mxCell id="b" value="Größe § 1&#xa;second line" style="ow:step" vertex="1" parent="1"><mxGeometry x="0" y="80" width="200" height="52" as="geometry"/></mxCell>
<mxCell id="e" value="next" style="ow:edge" edge="1" parent="1" source="a" target="b"><mxGeometry relative="1" as="geometry"><mxPoint as="offset" x="20" y="0"/></mxGeometry></mxCell>
</root></mxGraphModel></diagram></mxfile>
EOF
uv run python - <<'EOF'
import sys; sys.path.insert(0, "scripts")
from pathlib import Path
import render_diagrams as r
r.DIRS = {Path("/tmp/ow-smoke"): Path("/tmp/ow-smoke/out")}
print("exit", r.main([]))
EOF
ls /tmp/ow-smoke/out && grep -o "@font-face" /tmp/ow-smoke/out/smoke-dark.svg | wc -l
```

Expected: `exit 0`; `smoke-light.svg` and `smoke-dark.svg` exist; 2 `@font-face`; no `foreignObject`
(`grep -c foreignObject /tmp/ow-smoke/out/*.svg` prints 0 for both).
If the export hangs or fails because of `--network=none`, drop that flag from
`export()` and its test assertion, and record the reason in the report under "Decisions". Remove `/tmp/ow-smoke`
afterwards.

- [ ] **Step 7: Commit**

```bash
git add scripts/render_diagrams.py renovate.json tests/test_render_diagrams.py
git commit -m "feat(site): render diagrams offline in the pinned draw.io image, Sora subset embedded, stamped"
```

---

### Task 4: The site diagrams, redrawn; the Mermaid pipeline removed

**Files:**

- Create: `docs/_diagrams/{submission-flow,case-lifecycle,admin-login,architecture,architecture.de}.drawio`
- Create (rendered): `docs/img/diagrams/<name>-{light,dark}.svg` for those five (overwrites the four Mermaid
  renders of the same names)
- Delete: `docs/_diagrams/*.mmd`, `docs/_diagrams/README.md`, `scripts/render_diagrams.mjs`
- Create: `docs-tech/diagrams.md`
- Rewrite: `tests/test_diagrams.py`
- Modify: `docs/en/docs/index.html`, `docs/en/index.html`, `docs/en/blog/free-internal-reporting-channel.html`,
  `docs/de/blog/interne-meldestelle-kostenlos.html` (`width`/`height` of each diagram `<img>`; the German post
  points at `architecture.de-*`)
- Modify: `CONTRIBUTING.md` (§ Documentation, "Diagrams"), `docs/assets/css/figures.css` and
  `docs/assets/css/docs.css` (comments naming `docs/_diagrams/README.md` now name `docs-tech/diagrams.md`)

**Interfaces:**

- Consumes: `renderer()` (Tasks 1–3), `geometry().problems`.
- Produces: `tests/test_diagrams.py` helpers `ALL` (list of `(source, out_dir)`) and `_svg(source, out, theme)`,
  which Task 6 extends.

- [ ] **Step 1: Write the new committed-diagram tests**

Replace `tests/test_diagrams.py` completely:

```python
"""Every committed diagram is current, legible, self-contained and in its page's language.

Rendering needs a container (scripts/render_diagrams.py); these checks need nothing but
the committed files, so CI runs them on every push.
"""

from __future__ import annotations

import base64
import io
import re
from pathlib import Path

import pytest
from fontTools.ttLib import TTFont

from app.models.report import ReportStatus
from tests.built_site import built, pages
from tests.diagram_tools import geometry, renderer

ROOT = Path(__file__).parents[1]
THEMES = ("light", "dark")
ALL = renderer().sources()
IDS = [source.name for source, _ in ALL]


def _svg(source: Path, out: Path, theme: str) -> str:
    return renderer().svg_path(source, out, theme).read_text(encoding="utf-8")


def test_there_are_diagrams() -> None:
    names = {s.name for s, _ in ALL}
    assert {"submission-flow.drawio", "architecture.de.drawio"} <= names, names


@pytest.mark.parametrize(("source", "out"), ALL, ids=IDS)
@pytest.mark.parametrize("theme", THEMES)
def test_every_source_is_rendered_and_current(source: Path, out: Path, theme: str) -> None:
    path = renderer().svg_path(source, out, theme)
    assert path.is_file(), (
        f"{path.relative_to(ROOT)} is missing: uv run python scripts/render_diagrams.py"
    )
    m = re.search(r'data-ow-stamp="([0-9a-f]{16})"', path.read_text(encoding="utf-8"))
    assert m, f"{path.relative_to(ROOT)} has no stamp"
    assert m.group(1) == renderer().stamp(source.read_text(encoding="utf-8"), theme), (
        f"{path.relative_to(ROOT)} is stale: uv run python scripts/render_diagrams.py "
        f"{source.name.removesuffix('.drawio')}"
    )


def test_every_svg_has_a_source() -> None:
    expected = {renderer().svg_path(s, o, t) for s, o in ALL for t in THEMES}
    on_disk = {p for out in renderer().DIRS.values() if out.is_dir() for p in out.glob("*.svg")}
    orphans = sorted(p.relative_to(ROOT).as_posix() for p in on_disk - expected)
    assert not orphans, f"SVG(s) without a source, delete them: {orphans}"


@pytest.mark.parametrize(("source", "out"), ALL, ids=IDS)
@pytest.mark.parametrize("theme", THEMES)
def test_every_diagram_is_legible(source: Path, out: Path, theme: str) -> None:
    roles = renderer().roles_by_id(source.read_text(encoding="utf-8"))
    found = geometry().problems(_svg(source, out, theme), roles)
    assert not found, "\n  ".join([f"{source.name} ({theme}):", *found])


_HEX = re.compile(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b")
_RGB = re.compile(r"rgb\(\s*(\d+),\s*(\d+),\s*(\d+)\s*\)")
_BLOB = re.compile(r"base64,[A-Za-z0-9+/=]+")


def _colours(svg: str) -> set[str]:
    svg = _BLOB.sub("", svg)
    found = set()
    for h in _HEX.findall(svg):
        h = h.lower()
        found.add("#" + "".join(c * 2 for c in h[1:]) if len(h) == 4 else h)
    found |= {"#{:02x}{:02x}{:02x}".format(*map(int, m)) for m in _RGB.findall(svg)}
    return found


@pytest.mark.parametrize(("source", "out"), ALL, ids=IDS)
@pytest.mark.parametrize("theme", THEMES)
def test_colours_are_the_palette_of_their_theme(source: Path, out: Path, theme: str) -> None:
    allowed = set(renderer().palette()[theme].values())
    stray = _colours(_svg(source, out, theme)) - allowed
    assert not stray, (
        f"{source.name} ({theme}) uses {sorted(stray)}, which is not a {theme} DESIGN.md colour: "
        "a role leaves a draw.io default in place; set that key in ROLES"
    )


_NAMESPACES = {
    "http://www.w3.org/2000/svg",
    "http://www.w3.org/1999/xlink",
    "http://www.w3.org/1999/xhtml",
}


@pytest.mark.parametrize(("source", "out"), ALL, ids=IDS)
@pytest.mark.parametrize("theme", THEMES)
def test_every_svg_is_self_contained(source: Path, out: Path, theme: str) -> None:
    svg = _svg(source, out, theme)
    for marker in ("light-dark(", "<foreignObject", "<script", "<!DOCTYPE"):
        assert marker not in svg, f"{source.name} ({theme}) contains {marker}"
    assert not re.search(r"url\((?!data:)", svg), (
        f"{source.name} ({theme}) loads something by url()"
    )
    assert not re.search(r'href="(?!#|data:)', svg), f"{source.name} ({theme}) links out"
    refs = set(re.findall(r'https?://[^"\'\s)]*', svg)) - _NAMESPACES
    assert not refs, f"{source.name} ({theme}) references {sorted(refs)}"


@pytest.mark.parametrize(("source", "out"), ALL, ids=IDS)
def test_every_drawn_glyph_is_in_the_embedded_font(source: Path, out: Path) -> None:
    svg = _svg(source, out, "light")
    faces = {
        int(w): set(TTFont(io.BytesIO(base64.b64decode(d))).getBestCmap())
        for w, d in re.findall(r"font-weight:(\d+);src:url\(data:font/woff2;base64,([^)]+)\)", svg)
    }
    for t in geometry().texts(svg):
        missing = {c for c in t.text if ord(c) not in faces.get(t.weight, set())}
        assert not missing, (
            f"{source.name}: {t.text!r} draws {sorted(missing)} without an embedded glyph"
        )


def _diagram_srcs(html: str) -> set[str]:
    return set(re.findall(r'src="/img/diagrams/([^"]+?)-(?:light|dark)\.svg"', html))


def test_pages_show_diagrams_in_their_own_language() -> None:
    wrong = []
    for page in pages():
        html = page.read_text(encoding="utf-8")
        lang = re.search(r'<html[^>]*\blang="([a-z]{2})', html)
        for name in _diagram_srcs(html):
            german = name.endswith(".de")
            if lang and (lang.group(1) == "de") != german:
                wrong.append(f"{page.relative_to(built())} (lang={lang.group(1)}) shows {name}")
    assert not wrong, "\n  ".join(["diagram in the wrong language:", *wrong])


def test_the_case_lifecycle_names_exactly_the_report_statuses() -> None:
    source = (ROOT / "docs/_diagrams/case-lifecycle.drawio").read_text(encoding="utf-8")
    roles = renderer().roles_by_id(source)
    labels = dict(re.findall(r'<mxCell id="([^"]+)" value="([^"]*)"', source))
    steps = {labels[cid] for cid, role in roles.items() if role == "ow:step"}
    assert steps == {s.value for s in ReportStatus}
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_diagrams.py -q --no-cov`
Expected: FAIL in `test_there_are_diagrams` (there are no `.drawio` sources yet), and in
`test_every_svg_has_a_source` (the eight Mermaid SVGs have no source).

- [ ] **Step 3: Write `submission-flow.drawio` (the template for every source)**

Layout rules for every source:

- one `mxCell` per element, pretty-printed;
- ids are words (`has-locations`, `e-yes`);
- vertical steps 72 px apart;
- nodes 40 px high for one line, 52 for two, 68 for three;
- a decision's ports are explicit;
- every edge label has an offset.

`docs/_diagrams/submission-flow.drawio`:

```xml
<mxfile>
  <diagram name="submission-flow">
    <mxGraphModel>
      <root>
        <mxCell id="0"/>
        <mxCell id="1" parent="0"/>
        <mxCell id="start" value="Start a report" style="ow:start" vertex="1" parent="1">
          <mxGeometry x="0" y="0" width="230" height="40" as="geometry"/>
        </mxCell>
        <mxCell id="mode" value="1 · Mode&#xa;anonymous or confidential" style="ow:step" vertex="1" parent="1">
          <mxGeometry x="0" y="72" width="230" height="52" as="geometry"/>
        </mxCell>
        <mxCell id="has-locations" value="Locations&#xa;configured?" style="ow:decision" vertex="1" parent="1">
          <mxGeometry x="0" y="156" width="230" height="80" as="geometry"/>
        </mxCell>
        <mxCell id="location" value="2 · Location" style="ow:step" vertex="1" parent="1">
          <mxGeometry x="290" y="176" width="170" height="40" as="geometry"/>
        </mxCell>
        <mxCell id="category" value="3 · Category" style="ow:step" vertex="1" parent="1">
          <mxGeometry x="0" y="272" width="230" height="40" as="geometry"/>
        </mxCell>
        <mxCell id="details" value="4 · Details&#xa;description" style="ow:step" vertex="1" parent="1">
          <mxGeometry x="0" y="344" width="230" height="52" as="geometry"/>
        </mxCell>
        <mxCell id="files" value="5 · Files&#xa;attachments, optional" style="ow:step" vertex="1" parent="1">
          <mxGeometry x="0" y="428" width="230" height="52" as="geometry"/>
        </mxCell>
        <mxCell id="review" value="6 · Review" style="ow:step" vertex="1" parent="1">
          <mxGeometry x="0" y="512" width="230" height="40" as="geometry"/>
        </mxCell>
        <mxCell id="submit" value="Submit" style="ow:end" vertex="1" parent="1">
          <mxGeometry x="0" y="584" width="230" height="40" as="geometry"/>
        </mxCell>
        <mxCell id="receipt" value="Case number + PIN&#xa;issued once, shown once" style="ow:result" vertex="1" parent="1">
          <mxGeometry x="0" y="656" width="230" height="52" as="geometry"/>
        </mxCell>
        <mxCell id="e-start" style="ow:edge" edge="1" parent="1" source="start" target="mode">
          <mxGeometry relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="e-mode" style="ow:edge;entryX=0.5;entryY=0;entryDx=0;entryDy=0;" edge="1" parent="1" source="mode" target="has-locations">
          <mxGeometry relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="e-yes" value="yes" style="ow:edge;exitX=1;exitY=0.5;exitDx=0;exitDy=0;entryX=0;entryY=0.5;entryDx=0;entryDy=0;" edge="1" parent="1" source="has-locations" target="location">
          <mxGeometry relative="1" as="geometry">
            <mxPoint as="offset" x="0" y="-11"/>
          </mxGeometry>
        </mxCell>
        <mxCell id="e-no" value="no" style="ow:edge;exitX=0.5;exitY=1;exitDx=0;exitDy=0;" edge="1" parent="1" source="has-locations" target="category">
          <mxGeometry relative="1" as="geometry">
            <mxPoint as="offset" x="14" y="0"/>
          </mxGeometry>
        </mxCell>
        <mxCell id="e-location" style="ow:edge;exitX=0.5;exitY=1;exitDx=0;exitDy=0;entryX=1;entryY=0.5;entryDx=0;entryDy=0;" edge="1" parent="1" source="location" target="category">
          <mxGeometry relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="e-category" style="ow:edge" edge="1" parent="1" source="category" target="details">
          <mxGeometry relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="e-details" style="ow:edge" edge="1" parent="1" source="details" target="files">
          <mxGeometry relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="e-files" style="ow:edge" edge="1" parent="1" source="files" target="review">
          <mxGeometry relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="e-review" style="ow:edge" edge="1" parent="1" source="review" target="submit">
          <mxGeometry relative="1" as="geometry"/>
        </mxCell>
        <mxCell id="e-submit" style="ow:edge" edge="1" parent="1" source="submit" target="receipt">
          <mxGeometry relative="1" as="geometry"/>
        </mxCell>
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>
```

- [ ] **Step 4: Write the other four sources**

Same structure as Step 3. Coordinates are a starting point: the geometry test decides. When it reports a
problem, move the node or the label offset, never a constant in `diagram_geometry.py`. Edge columns read
`source → target · label · style overrides · label offset`.

**`case-lifecycle.drawio`.** Nodes (id, role, label, x, y, w, h):

| id | role | label | x | y | w | h |
| --- | --- | --- | --- | --- | --- | --- |
| submitted | ow:start | Report submitted | 240 | 0 | 200 | 40 |
| received | ow:step | received | 240 | 90 | 200 | 40 |
| in_review | ow:step | in_review | 240 | 200 | 200 | 40 |
| pending_feedback | ow:step | pending_feedback | 240 | 310 | 200 | 40 |
| closed | ow:step | closed | 0 | 200 | 160 | 40 |
| ack | ow:note | HinSchG: acknowledge&#xa;within 7 days | 500 | 84 | 200 | 52 |
| feedback | ow:note | HinSchG: feedback&#xa;within 3 months | 500 | 304 | 200 | 52 |

Edges:

| source | target | label | style overrides | label offset |
| --- | --- | --- | --- | --- |
| submitted | received | | | |
| received | in_review | | `exitX=0.35;exitY=1;entryX=0.35;entryY=0;` | |
| in_review | received | | `exitX=0.65;exitY=0;entryX=0.65;entryY=1;` | |
| in_review | pending_feedback | | `exitX=0.35;exitY=1;entryX=0.35;entryY=0;` | |
| pending_feedback | in_review | | `exitX=0.65;exitY=0;entryX=0.65;entryY=1;` | |
| received | closed | | `exitX=0;exitY=0.5;entryX=0.5;entryY=0;` | |
| in_review | closed | | `exitX=0;exitY=0.7;entryX=1;entryY=0.7;` | |
| closed | in_review | reopen | `exitX=1;exitY=0.3;entryX=0;entryY=0.3;` | y=-10 |
| pending_feedback | closed | | `exitX=0;exitY=0.5;entryX=0.5;entryY=1;` | |
| received | ack | | role `ow:edge-optional`; `exitX=1;exitY=0.5;entryX=0;entryY=0.5;` | |
| pending_feedback | feedback | | role `ow:edge-optional`; `exitX=1;exitY=0.5;entryX=0;entryY=0.5;` | |

Every `exitX/exitY/entryX/entryY` above also gets `exitDx=0;exitDy=0;entryDx=0;entryDy=0;` as in Step 3.

**`admin-login.drawio`.** Nodes:

| id | role | label | x | y | w | h |
| --- | --- | --- | --- | --- | --- | --- |
| start | ow:start | Admin login | 220 | 0 | 220 | 40 |
| first-factor | ow:decision | First factor | 220 | 72 | 220 | 72 |
| database | ow:store | Database | 0 | 200 | 180 | 56 |
| ldap | ow:step | LDAP server | 240 | 200 | 180 | 56 |
| idp | ow:step | External identity&#xa;provider | 480 | 200 | 180 | 56 |
| verified | ow:step | First factor verified | 220 | 320 | 220 | 40 |
| totp-enrolled | ow:decision | TOTP enrolled? | 220 | 392 | 220 | 72 |
| enroll | ow:step | Enroll TOTP&#xa;mandatory for every account | 480 | 400 | 230 | 56 |
| totp | ow:step | Enter TOTP code | 220 | 500 | 220 | 40 |
| forced | ow:decision | Password set by&#xa;someone else? | 220 | 572 | 220 | 80 |
| change | ow:step | Choose own password&#xa;at /admin/account,&#xa;nothing else opens | 480 | 580 | 230 | 68 |
| admin | ow:end | Admin area | 220 | 700 | 220 | 40 |

Edges:

| source | target | label | style overrides | label offset |
| --- | --- | --- | --- | --- |
| start | first-factor | | `entryX=0.5;entryY=0;` | |
| first-factor | database | username + password | `exitX=0;exitY=0.5;entryX=0.5;entryY=0;` | y=-11 |
| first-factor | ldap | LDAP | `exitX=0.5;exitY=1;entryX=0.5;entryY=0;` | x=22 |
| first-factor | idp | OIDC | `exitX=1;exitY=0.5;entryX=0.5;entryY=0;` | y=-11 |
| database | verified | | `exitX=0.5;exitY=1;entryX=0;entryY=0.5;` | |
| ldap | verified | | `exitX=0.5;exitY=1;entryX=0.5;entryY=0;` | |
| idp | verified | | `exitX=0.5;exitY=1;entryX=1;entryY=0.5;` | |
| verified | totp-enrolled | | `entryX=0.5;entryY=0;` | |
| totp-enrolled | enroll | no | `exitX=1;exitY=0.5;entryX=0;entryY=0.5;` | y=-11 |
| totp-enrolled | totp | yes | `exitX=0.5;exitY=1;` | x=16 |
| enroll | totp | | `exitX=0.5;exitY=1;entryX=1;entryY=0.5;` | |
| totp | forced | | `entryX=0.5;entryY=0;` | |
| forced | admin | no | `exitX=0.5;exitY=1;` | x=14 |
| forced | change | yes | `exitX=1;exitY=0.5;entryX=0;entryY=0.5;` | y=-11 |
| change | admin | | `exitX=0.5;exitY=1;entryX=1;entryY=0.5;` | |

**`architecture.drawio`.** A child cell's `x`/`y` are relative to its group (`parent="<group id>"`). Nodes:

| id | role | parent | label | x | y | w | h |
| --- | --- | --- | --- | --- | --- | --- | --- |
| client | ow:step | 1 | Browser / Tor Browser | 240 | 0 | 220 | 40 |
| edge | ow:group | 1 | nginx | 100 | 80 | 500 | 110 |
| tls | ow:step | edge | TLS :443&#xa;:80 redirects to :443 | 20 | 40 | 220 | 52 |
| onion | ow:step | edge | Onion :8080&#xa;127.0.0.1 only | 260 | 40 | 220 | 52 |
| app | ow:step | 1 | app (FastAPI)&#xa;stateless | 240 | 230 | 220 | 52 |
| required | ow:group | 1 | required | 0 | 330 | 230 | 112 |
| pg | ow:store | required | PostgreSQL | 16 | 38 | 104 | 60 |
| redis | ow:store | required | Redis | 128 | 38 | 88 | 60 |
| optional | ow:group | 1 | optional | 250 | 330 | 230 | 112 |
| clamav | ow:step | optional | ClamAV&#xa;scan | 16 | 42 | 96 | 52 |
| s3 | ow:store | optional | S3&#xa;store | 124 | 38 | 90 | 60 |
| outbound | ow:group | 1 | outbound | 500 | 330 | 360 | 112 |
| github | ow:step | outbound | GitHub API&#xa;update check, opt-in | 16 | 42 | 170 | 52 |
| telemetry | ow:step | outbound | telemetry.wdkro.de&#xa;opt-in | 196 | 42 | 150 | 52 |

Edges:

| source | target | label | style overrides | label offset |
| --- | --- | --- | --- | --- |
| client | tls | | `exitX=0.3;exitY=1;entryX=0.5;entryY=0;` | |
| client | onion | onion service | role `ow:edge-optional`; `exitX=0.7;exitY=1;entryX=0.5;entryY=0;` | x=48 |
| tls | app | | `exitX=0.5;exitY=1;entryX=0.3;entryY=0;` | |
| onion | app | | `exitX=0.5;exitY=1;entryX=0.7;entryY=0;` | |
| app | required | | `exitX=0.2;exitY=1;entryX=0.5;entryY=0;` | |
| app | optional | | role `ow:edge-optional`; `exitX=0.5;exitY=1;entryX=0.5;entryY=0;` | |
| app | outbound | | role `ow:edge-optional`; `exitX=0.8;exitY=1;entryX=0.5;entryY=0;` | |

**`architecture.de.drawio`.** The same ids, geometry and edges. Labels:

| id | label |
| --- | --- |
| client | Browser / Tor-Browser |
| edge | nginx |
| tls | TLS :443&#xa;:80 leitet um auf :443 |
| onion | Onion :8080&#xa;nur 127.0.0.1 |
| app | app (FastAPI)&#xa;zustandslos |
| required | erforderlich |
| pg | PostgreSQL |
| redis | Redis |
| optional | optional |
| clamav | ClamAV&#xa;Virenscan |
| s3 | S3&#xa;Speicher |
| outbound | ausgehend |
| github | GitHub-API&#xa;Update-Prüfung, opt-in |
| telemetry | telemetry.wdkro.de&#xa;opt-in |
| client → onion (label) | Onion-Dienst |

If a German label does not fit, widen that node and its group in **both** sources, so the two pictures keep
one layout.

- [ ] **Step 5: Render and iterate until legible**

Run: `uv run python scripts/render_diagrams.py submission-flow case-lifecycle admin-login architecture architecture.de`
Expected: exit 0. Every problem printed names a cell. Fix that cell's geometry or label offset in the source and
re-run, until the exit is 0.

Then look at every light and dark SVG yourself, side by side, on a dark and on a light background. Use
Chromium via Playwright, the way the brainstorm probe did:

```bash
uv run python - <<'EOF'
from pathlib import Path
from playwright.sync_api import sync_playwright
d = Path("docs/img/diagrams")
html = "".join(
    f'<div style="display:flex"><div style="background:#08080a;padding:24px">{(d / f"{n}-dark.svg").read_text()}</div>'
    f'<div style="background:#fff;padding:24px">{(d / f"{n}-light.svg").read_text()}</div></div>'
    for n in ["submission-flow", "case-lifecycle", "admin-login", "architecture", "architecture.de"])
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(viewport={"width": 1920, "height": 1080})
    pg.set_content(html); pg.screenshot(path="/tmp/ow-diagrams.png", full_page=True); b.close()
EOF
```

Read `/tmp/ow-diagrams.png`. Check what the geometry test cannot judge:

- an arrow that takes a detour;
- two edges drawn on top of each other;
- a label that is clear of the line but sits beside the wrong edge;
- unbalanced spacing.

Fix those in the source too, and record each fix in the report.

- [ ] **Step 6: Update the embeds**

Print the new sizes: `grep -o '<svg [^>]*' docs/img/diagrams/*-light.svg | grep -o 'width="[0-9.]*" height="[0-9.]*"'`.

In every `<img class="diagram-light|diagram-dark">` that shows one of the five diagrams, set `width` and `height`
to the SVG's values. The files are listed under **Files** above.

In `docs/de/blog/interne-meldestelle-kostenlos.html`, change `architecture-light.svg` and `architecture-dark.svg`
to `architecture.de-light.svg` and `architecture.de-dark.svg`. Keep the alt texts: they describe the same
content.

- [ ] **Step 7: Remove the Mermaid pipeline**

```bash
git rm docs/_diagrams/*.mmd docs/_diagrams/README.md scripts/render_diagrams.mjs
```

- [ ] **Step 8: Write `docs-tech/diagrams.md`**

```markdown
# Diagrams

How-to and reference for the maintainer. Every diagram is a draw.io XML source rendered to a committed light
and dark SVG; CI checks the SVGs and never runs draw.io.

| Source | Rendered to | Shown by |
| --- | --- | --- |
| `docs/_diagrams/<name>.drawio`, German pages `<name>.de.drawio` | `docs/img/diagrams/<name>-{light,dark}.svg` | two `<img>`, CSS picks one from `data-theme` |
| `docs-tech/_diagrams/<name>.drawio` | `docs-tech/img/diagrams/<name>-{light,dark}.svg` | `<picture>` with `prefers-color-scheme`, as GitHub renders it |

## Add or change a diagram

1. Write the source. Copy `docs/_diagrams/submission-flow.drawio`: one `mxCell` per element, ids that are words.
2. Give every cell a role as its style, then only layout overrides: `style="ow:edge;exitX=1;exitY=0.5"`.
   A colour in a source is refused.
3. `uv run python scripts/render_diagrams.py <name>`. Needs podman or docker; exit 0 means legible.
4. Look at both SVGs on a dark and a light background.
5. `uv run pytest tests/test_diagrams.py --no-cov`, then commit the source and both SVGs together.

## Roles

| Role | Draws |
| --- | --- |
| `ow:start`, `ow:end` | emerald pill: where a flow begins and ends |
| `ow:step` | filled card |
| `ow:result` | ink card: the one thing the reader keeps (case number + PIN) |
| `ow:decision` | outlined diamond with explicit ports |
| `ow:store` | database cylinder |
| `ow:note` | dashed note: a deadline, a rule |
| `ow:group`, `ow:lane` | box or swimlane that holds other cells |
| `ow:lifeline`, `ow:message` | sequence diagram |
| `ow:edge`, `ow:edge-optional` | arrow, solid or dashed |

Style C was chosen by the maintainer from three rendered variants. Start and end in emerald make two accents per
diagram, an exception to "one accent per screen" that DESIGN.md records.

## Rules the tests hold

| Rule | Why |
| --- | --- |
| An edge label has `<mxPoint as="offset" …/>` beside its line | "yes" on the arrow is a production defect; `problems()` measures it |
| A decision uses explicit `exitX/exitY` ports | Without them edges start inside the diamond and cross its label |
| Line breaks by hand (`&#xa;`); never `whiteSpace=wrap` | `wrap` exports `foreignObject`, which an `<img>` does not render reliably |
| Only glyphs Sora has: no `→`, `✓` | A fallback font breaks the measured layout |
| A German page shows `.de` diagrams, an English page none | `test_pages_show_diagrams_in_their_own_language` |
| `--theme light` on every export | `auto` writes `light-dark()`, which follows the OS, not the site's toggle |

## Why

- **Roles, not hex.** `#ffffff` is canvas, surface-2 and accent-ink in light, with three different dark values,
  so a colour map is ambiguous. Colours live in DESIGN.md's front matter; the renderer reads them.
- **Two `<img>`, not `<picture>`, on the site.** The site's theme is the `data-theme` toggle. A
  `prefers-color-scheme` source follows the OS and disagrees as soon as someone toggles. GitHub has no toggle,
  so `docs-tech/` uses `<picture>`.
- **Stamp.** `data-ow-stamp` hashes source, roles, palette, image and fonts; any change makes the SVG stale.
- **Image bump.** Renovate moves tag and digest of the draw.io image together; every stamp goes stale and the PR
  stays red until re-rendered.
```

- [ ] **Step 9: Update the references**

- `CONTRIBUTING.md` § Documentation: replace the "Diagrams" paragraph with:

  ```markdown
  **Diagrams** are draw.io sources in `docs/_diagrams/` (German pages: `<name>.de.drawio`) and
  `docs-tech/_diagrams/`, rendered by `scripts/render_diagrams.py` to committed `-light.svg` and `-dark.svg`.
  Rules and roles: `docs-tech/diagrams.md`.
  ```

- `docs/assets/css/figures.css` line 3 and `docs/assets/css/docs.css` line 646: `docs/_diagrams/README.md` →
  `docs-tech/diagrams.md`.
- `grep -rn "_diagrams/README\|render_diagrams.mjs\|\.mmd\b" --exclude-dir=.git . | grep -v CHANGELOG.md`
  lists only `docs-tech/plans/` and `docs-tech/specs/` (history, left as written).

- [ ] **Step 10: Run the tests**

Run:

```bash
uv run pytest tests/test_diagrams.py tests/test_docs_figures.py tests/test_docs_boundary.py -q --no-cov \
  && npx --yes markdownlint-cli2 docs-tech/diagrams.md CONTRIBUTING.md
```

Expected: all PASS.

- [ ] **Step 11: Commit**

```bash
git add -A docs/_diagrams docs/img/diagrams docs-tech/diagrams.md tests/test_diagrams.py CONTRIBUTING.md \
  docs/assets/css/figures.css docs/assets/css/docs.css docs/en docs/de
git commit -m "feat(site): the site diagrams are draw.io in style C, the German post gets German labels; Mermaid pipeline removed"
```

---

### Task 5: Home-page flow, EN and DE

**Files:**

- Create: `docs/_diagrams/home-flow.drawio`, `docs/_diagrams/home-flow.de.drawio`, their four SVGs
- Modify: `docs/en/index.html`, `docs/de/index.html` (the `flows-grid` block becomes one figure)
- Modify: `docs/assets/css/home.css`, `docs/assets/css/home-de.css` (the `.flows-grid` / `.flow-*` rules go),
  `docs/assets/css/home-de-figures.css` (add the `.diagram img` sizing that `figures.css` has)
- Test: `tests/test_diagrams.py`

**Interfaces:**

- Consumes: Task 4's pipeline and tests.

- [ ] **Step 1: Write the failing test**

Add `page` to the existing `from tests.built_site import ...` line at the top of `tests/test_diagrams.py`, then
append:

```python
@pytest.mark.parametrize(("url", "name"), [("/en/", "home-flow"), ("/de/", "home-flow.de")])
def test_the_home_page_shows_the_reporting_flow_as_a_diagram(url: str, name: str) -> None:
    html = page(url)
    assert name in _diagram_srcs(html), f"{url} does not show {name}"
    assert "flows-grid" not in html, f"{url} still carries the HTML flow next to the diagram"
```

Run: `uv run pytest tests/test_diagrams.py -k home_page -q --no-cov`
Expected: FAIL. Neither page shows the diagram.

- [ ] **Step 2: Write both sources**

Two lanes. A child's coordinates are relative to its lane.

**`home-flow.drawio`:**

| id | role | parent | label | x | y | w | h |
| --- | --- | --- | --- | --- | --- | --- | --- |
| wb | ow:lane | 1 | Whistleblower | 0 | 0 | 300 | 340 |
| wb-form | ow:step | wb | Fill in the form&#xa;anonymous or confidential,&#xa;no account, no e-mail | 20 | 48 | 260 | 72 |
| wb-receipt | ow:result | wb | Note case number + PIN&#xa;shown exactly once,&#xa;lost means lost | 20 | 148 | 260 | 72 |
| wb-status | ow:step | wb | Check status and reply&#xa;at /status: status,&#xa;deadlines, answers | 20 | 248 | 260 | 72 |
| office | ow:lane | 1 | Reporting office | 400 | 0 | 300 | 340 |
| of-login | ow:step | office | Log in&#xa;password, LDAP or OIDC,&#xa;then always TOTP | 20 | 48 | 260 | 72 |
| of-ack | ow:step | office | Acknowledge receipt&#xa;within 7 days&#xa;§ 17 (1) no. 1 HinSchG | 20 | 148 | 260 | 72 |
| of-feedback | ow:step | office | Review and give feedback&#xa;within 3 months&#xa;§ 17 (2) HinSchG | 20 | 248 | 260 | 72 |

Edges:

| source | target | label | style overrides | label offset |
| --- | --- | --- | --- | --- |
| wb-form | wb-receipt | | | |
| wb-receipt | wb-status | | | |
| of-login | of-ack | | | |
| of-ack | of-feedback | | | |
| wb-form | of-ack | report | `exitX=1;exitY=0.5;entryX=0;entryY=0.5;` | y=-11 |
| of-feedback | wb-status | feedback | `exitX=0;exitY=0.5;entryX=1;entryY=0.5;` | y=-11 |

**`home-flow.de.drawio`:** same ids, geometry and edges. Labels:

| id | label |
| --- | --- |
| wb | Hinweisgeber |
| wb-form | Formular ausfüllen&#xa;anonym oder vertraulich,&#xa;kein Konto, keine E-Mail |
| wb-receipt | Fallnummer + PIN notieren&#xa;erscheinen genau einmal,&#xa;verloren heißt verloren |
| wb-status | Status prüfen, antworten&#xa;unter /status: Status,&#xa;Fristen, Antworten |
| office | Meldestelle |
| of-login | Anmelden&#xa;Passwort, LDAP oder OIDC,&#xa;danach immer TOTP |
| of-ack | Eingang bestätigen&#xa;innerhalb von 7 Tagen&#xa;§ 17 Abs. 1 Nr. 1 HinSchG |
| of-feedback | Prüfen und zurückmelden&#xa;innerhalb von 3 Monaten&#xa;§ 17 Abs. 2 HinSchG |
| edge labels | Meldung · Rückmeldung |

Run: `uv run python scripts/render_diagrams.py home-flow home-flow.de` until exit 0. Then check both themes by
eye, as in Task 4 Step 5.

- [ ] **Step 3: Replace the HTML flow on both pages**

In `docs/en/index.html`, replace the whole `<div class="flows-grid">…</div>` (through its closing `</div>`,
before `</div></section>`) with:

```html
        <figure class="diagram">
          <img class="diagram-light" src="/img/diagrams/home-flow-light.svg" alt="Two lanes. Whistleblower: fill in the form, anonymous or confidential, with no account and no e-mail; note the case number and PIN, shown exactly once; check status and reply at /status. Reporting office: log in with password, LDAP or OIDC, then always TOTP; acknowledge receipt within 7 days; review and give feedback within 3 months. The report goes from the form to the acknowledgement, the feedback back to the status page." width="W" height="H" loading="lazy">
          <img class="diagram-dark" src="/img/diagrams/home-flow-dark.svg" alt="(the same alt text)" width="W" height="H" loading="lazy">
          <figcaption>Acknowledging a report starts the three-month feedback clock.</figcaption>
        </figure>
```

`W`/`H` are the SVG's width and height (Task 4 Step 6). The dark twin's `alt` is the same full sentence as
the light twin's: `docs-tech/diagrams.md` explains why an empty alt on the hidden twin fails dark-theme
screen-reader users.

In `docs/de/index.html`, the same figure with `home-flow.de-light.svg` / `home-flow.de-dark.svg` and:

- alt:

  ```text
  Zwei Bahnen. Hinweisgeber: Formular ausfüllen, anonym oder vertraulich, ohne Konto und ohne E-Mail; Fallnummer und PIN notieren, die genau einmal erscheinen; unter /status Status prüfen und antworten. Meldestelle: anmelden mit Passwort, LDAP oder OIDC, danach immer TOTP; den Eingang innerhalb von 7 Tagen bestätigen; prüfen und innerhalb von drei Monaten zurückmelden. Die Meldung geht vom Formular zur Eingangsbestätigung, die Rückmeldung zurück zur Statusseite.
  ```

- caption: `Die Eingangsbestätigung startet die Rückmeldefrist von drei Monaten.`

The EN home's case-lifecycle diagram lived inside the flow column and leaves with it. The docs keep showing it
(`/en/docs/`).

- [ ] **Step 4: Drop the dead CSS**

Delete every rule whose selector starts with `.flows-grid`, `.flow-column`, `.flow-header`, `.flow-steps`,
`.flow-step` (including `[data-theme="dark"] .flow-*` variants) from `docs/assets/css/home.css` and
`docs/assets/css/home-de.css`. `grep -n "flow-\|flows-grid" docs/assets/css/home*.css` prints nothing afterwards.

Add to `docs/assets/css/home-de-figures.css`, after line 3:

```css
    .diagram { margin: 0; }
    .diagram img { max-width: 100%; height: auto; margin: 0 auto; }
    .diagram figcaption { font-size: 0.82rem; color: var(--text-muted); text-align: center; margin-top: var(--space-3); }
```

- [ ] **Step 5: Run the tests**

Run:

```bash
uv run pytest tests/test_diagrams.py tests/test_docs_figures.py tests/test_docs_prose.py tests/test_seo.py tests/test_v160_design.py -q --no-cov
```

Expected: all PASS. If a test in `test_v160_design.py` or `test_docs_site.py` pinned the old flow markup, it
pinned a layout that no longer exists. Delete that test and name it in the report; do not keep the HTML to
satisfy it.

- [ ] **Step 6: Commit**

```bash
git add docs/_diagrams/home-flow*.drawio docs/img/diagrams/home-flow* docs/en/index.html docs/de/index.html \
  docs/assets/css/home.css docs/assets/css/home-de.css docs/assets/css/home-de-figures.css tests/test_diagrams.py
git commit -m "feat(site): the home page shows the reporting flow as one diagram, in English and German"
```

---

### Task 6: Maintainer docs: every Mermaid block becomes a diagram

**Files:**

- Create: 10 sources in `docs-tech/_diagrams/` and their SVGs in `docs-tech/img/diagrams/`
- Modify: `docs-tech/release.md`, `docs-tech/plans/2026-09-24-v1.6-hardening.md`,
  `docs-tech/specs/2026-09-24-v1.6-hardening-design.md`, `docs-tech/specs/2026-10-01-website-redesign-design.md`
- Modify: `.markdownlint.json`, `tests/test_local_review.py` (docstring only), `tests/test_diagrams.py`

**Interfaces:**

- Consumes: Task 4's `ALL`, `_svg`, `renderer()`.

- [ ] **Step 1: Write the failing tests**

Add `import subprocess` to the imports at the top of `tests/test_diagrams.py`, then append:

```python
DOCS_TECH = ROOT / "docs-tech"
_FENCE = re.compile(r"^```mermaid", re.M)


def _tracked() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    return [ROOT / line for line in out.splitlines()]


def test_no_mermaid_anywhere() -> None:
    found = []
    for path in _tracked():
        if path.suffix == ".mmd":
            found.append(f"{path.relative_to(ROOT)}: a Mermaid source")
        if (
            path.suffix in {".md", ".html"}
            and path.is_file()
            and _FENCE.search(path.read_text(encoding="utf-8"))
        ):
            found.append(f"{path.relative_to(ROOT)}: a fenced Mermaid block")
    tooling = [
        ROOT / "renovate.json",
        ROOT / "pyproject.toml",
        *ROOT.glob("scripts/*"),
        *ROOT.glob(".github/**/*.yml"),
    ]
    for path in tooling:
        if path.is_file() and re.search(
            r"mermaid-cli|@mermaid-js", path.read_text(encoding="utf-8")
        ):
            found.append(f"{path.relative_to(ROOT)}: a mermaid-cli reference")
    assert not found, "\n  ".join(["Mermaid is gone (maintainer's decision, 2026-10-02):", *found])


DOCS_TECH_DIAGRAMS = [(s, o) for s, o in ALL if o == DOCS_TECH / "img" / "diagrams"]


@pytest.mark.parametrize(
    ("source", "out"), DOCS_TECH_DIAGRAMS, ids=[s.name for s, _ in DOCS_TECH_DIAGRAMS]
)
def test_every_maintainer_diagram_is_embedded_as_a_picture(source: Path, out: Path) -> None:
    name = source.name.removesuffix(".drawio")
    pattern = re.compile(
        rf'<picture>\s*<source media="\(prefers-color-scheme: dark\)" srcset="[./]*img/diagrams/{re.escape(name)}-dark\.svg">'
        rf'\s*<img src="[./]*img/diagrams/{re.escape(name)}-light\.svg" alt="[^"]+">\s*</picture>'
    )
    hits = [p for p in DOCS_TECH.rglob("*.md") if pattern.search(p.read_text(encoding="utf-8"))]
    assert hits, f"no page in docs-tech/ shows {name} as a <picture> with both themes and alt text"
    for page_file in hits:
        target = page_file.parent / re.search(
            rf'src="([^"]*{re.escape(name)}-light\.svg)"', page_file.read_text()
        ).group(1)
        assert target.resolve() == (out / f"{name}-light.svg").resolve(), (
            f"{page_file}: wrong relative path"
        )
```

Run: `uv run pytest tests/test_diagrams.py -k "mermaid or maintainer" -q --no-cov`
Expected: FAIL. `test_no_mermaid_anywhere` lists the 10 fenced blocks; the maintainer-diagram test collects
nothing yet. Collecting nothing is not a pass: Step 5 requires 10 ids.

- [ ] **Step 2: Allow the picture elements in markdownlint**

`.markdownlint.json` gains:

```json
  "MD033": {
    "allowed_elements": ["picture", "source", "img"]
  },
```

- [ ] **Step 3: Write the 10 sources**

Same conventions as Task 4. Vertical (top-down) unless stated; nodes 72 px apart; width = longest line + 32 px,
rounded up to 10. Content comes from the Mermaid block each one replaces, read in full before writing.
Labels below; `A → B` is an edge (a source-format note, never a label).

| Source | Replaces | Content |
| --- | --- | --- |
| `release-gates` | `release.md` | `ow:start` "Mutation audit" → `ow:step` "UI check" → "Chrome check" → "Release PR" → "No open security alert" → "Tag vX.Y.Z" → `ow:end` "Verify images" |
| `key-hierarchy` | v1.6 plan, block 1 | left to right. `ow:step` "ENCRYPTION_KEY" and "ENCRYPTION_KEY_PREVIOUS …" → "MultiFernet&#xa;current key first"; that → (label "wraps") "per-report DEK" → `ow:result` "description, messages,&#xa;notes, attachments"; MultiFernet → (label "crypto.encrypt") `ow:result` "confidential name, contact, e-mail,&#xa;TOTP secret, reveal reasons"; separately "SECRET_KEY" → "JWT only" |
| `identity-reveal-handler` | v1.6 plan, block 2 | `ow:start` "GET case" → (label "REPORT_VIEWED") "Page: identity hidden" → (label "POST /identity + CSRF + reason") `ow:decision` "Handler?" → yes (label "assigned to me, or&#xa;unassigned and I am admin") "IDENTITY_REVEALED&#xa;+ encrypted reason" → `ow:end` "Same page, identity in&#xa;this response only"; no → `ow:result` "403" |
| `admin-layout` | v1.6 plan, block 3 | "admin/_layout.html" → (label "extends") "base.html"; "11 admin pages" → (label "extend") layout; "admin_nav(user)" → (label "groups filtered by role") layout; layout → (label "≥ 1024 px") "Sidebar"; layout → (label "< 1024 px") "details menu, closed" |
| `setup-token` | v1.6 spec, block 1 | sequence. `ow:lifeline` "App (any replica)", "Redis", "Operator"; `ow:message`s in order: App→App "startup: no admin exists?"; App→Redis "SET setup-token NX"; App→App "log the token once&#xa;(the replica whose SET won)"; Operator→App "POST /setup + token"; App→Redis "GET, compare_digest"; App→Redis "DEL on success". A self-message is an edge with source = target and two `mxPoint` waypoints 40 px to the right |
| `identity-reveal` | v1.6 spec, block 2 | `ow:start` "Open case" → (label "name and contact&#xa;not decrypted") "Show identity button" → (label "POST + CSRF + reason") `ow:decision` "Role may&#xa;view case?" → no: `ow:result` "404, as today"; yes: "Audit IDENTITY_REVEALED&#xa;user, reason" → `ow:end` "Identity in this response&#xa;only, no cache" |
| `law-profiles` | redesign spec, Positioning | `ow:result` "Core: ISO 37002" → "EU Directive 2019/1937" → "HinSchG (deepest)"; core → `ow:note` "Further jurisdictions: one&#xa;nav.yml entry each (UK PIDA,&#xa;US SOX §301, FR Sapin II,&#xa;BR Lei 12.846)" |
| `site-architecture` | redesign spec, Architecture and deploy | "docs/: Markdown + Jinja2 layouts&#xa;_data/nav.yml, i18n, config.yml,&#xa;redirects.yml" → "scripts/build_site.py&#xa;_site/ (gitignored)" → "Tests, Pagefind index,&#xa;page budget" → "ghcr.io/openwhistle/website&#xa;nginx-unprivileged, digest-pinned,&#xa;nginx.conf from the repo" → `ow:result` "Container on root01xvp&#xa;127.0.0.1:port"; `ow:step` "Host nginx :443&#xa;access_log off, error_log /dev/null" → container |
| `diagram-pipeline` | redesign spec, Diagrams | "docs/_diagrams/*.drawio&#xa;roles, not colours" → "scripts/render_diagrams.py" → three: `ow:result` "*-light.svg"; (label "dark palette") `ow:result` "*-dark.svg"; `ow:note` "stamp: hash of source, roles,&#xa;palette, image, fonts" |
| `delivery` | redesign spec, Delivery | P0 → P1; P1 → P2; P1 → P3; P2 → P4; P3 → P4; P4 → P5. Labels: "P0 spike&#xa;draw.io, Pagefind, CSP" · "P1 build system&#xa;layouts, nav, i18n, redirects" · "P2 design&#xa;K3, DESIGN.md, fonts, diagrams" · "P3 content&#xa;docs split, compliance, legal" · "P4 container&#xa;nginx.conf, image, counter" · `ow:end` "P5 move&#xa;vhost, DNS, HSTS preload" |

Run:

```bash
uv run python scripts/render_diagrams.py release-gates key-hierarchy identity-reveal-handler admin-layout setup-token identity-reveal law-profiles site-architecture diagram-pipeline delivery
```

Repeat until exit 0, then check by eye as in Task 4 Step 5 (`docs-tech/img/diagrams`).

- [ ] **Step 4: Replace each Mermaid block**

For each block, delete the fenced block and put in its place, at the same spot. Use `img/diagrams/` from
`docs-tech/release.md` and `../img/diagrams/` from `plans/` and `specs/`:

```markdown
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../img/diagrams/delivery-dark.svg">
  <img src="../img/diagrams/delivery-light.svg" alt="Delivery order: P0 spike, then P1 build system; P2 design and P3 content both follow P1; P4 container follows both; P5 move comes last.">
</picture>
```

Every `alt` is one sentence that carries the diagram's content, not "diagram".

In `docs-tech/release.md`, section 6 "Tag and verify", after the `cosign verify` block and before "Then create
the GitHub release", add:

````markdown
Until the site moves off GitHub Pages (website P5), Pages must build from the workflow, not from `main:/docs`:
after P1 the legacy setting served the raw sources for 15 minutes.

```bash
gh api repos/openwhistle/OpenWhistle/pages -q .build_type     # workflow
curl -s -o /dev/null -w '%{http_code}\n' https://openwhistle.net/en/   # 200
```
````

In `tests/test_local_review.py`, change the docstring of `test_release_md_names_the_chrome_check_before_the_release_pr`
to: `"""The numbered step itself, not just the diagram: dropping the section while the release-gates diagram
still says "Chrome check" must fail."""`

- [ ] **Step 5: Run the tests**

Run:

```bash
uv run pytest tests/test_diagrams.py tests/test_local_review.py tests/test_docs_boundary.py -q --no-cov \
  && npx --yes markdownlint-cli2 docs-tech/release.md docs-tech/plans/2026-09-24-v1.6-hardening.md docs-tech/specs/2026-09-24-v1.6-hardening-design.md docs-tech/specs/2026-10-01-website-redesign-design.md
```

Expected: all PASS. `test_every_maintainer_diagram_is_embedded_as_a_picture` shows 10 ids. Also confirm
`test_docs_boundary.py` still passes: `docs-tech/img/` is not published.

- [ ] **Step 6: Commit**

```bash
git add .markdownlint.json docs-tech tests/test_diagrams.py tests/test_local_review.py
git commit -m "docs(tech): every Mermaid block is a draw.io diagram; the release check covers the Pages build type"
```

---

### Task 7: Mutation audit, full suite, changelog

**Files:**

- Create: `docs-tech/mutations/v2.1.1-site-p2a.json`
- Modify: `CHANGELOG.md` (`[Unreleased]`)

**Interfaces:**

- Consumes: the final text of every file above. Each `old` snippet below must match exactly once; if one reads
  STALE, adjust the snippet to the code as written. Never weaken the mutation.

- [ ] **Step 1: Write the mutation spec**

`docs-tech/mutations/v2.1.1-site-p2a.json`:

```json
{
  "test_groups": {
    "RENDER": ["tests/test_render_diagrams.py"],
    "GEOMETRY": ["tests/test_diagram_geometry.py"],
    "COMMITTED": ["tests/test_diagrams.py"]
  },
  "mutations": [
    {"id": "ROLE-UNKNOWN", "file": "scripts/render_diagrams.py", "tests": "RENDER",
     "old": "    if role not in ROLES:\n        raise DiagramError", "new": "    if False:\n        raise DiagramError"},
    {"id": "COLOUR-KEY", "file": "scripts/render_diagrams.py", "tests": "RENDER",
     "old": "    if m := _COLOR_KEY.search(rest):", "new": "    if m := None:"},
    {"id": "NO-ROLE", "file": "scripts/render_diagrams.py", "tests": "RENDER",
     "old": "        if not cell.get(\"style\"):\n            raise", "new": "        if False:\n            raise"},
    {"id": "GLYPH-RENDER", "file": "scripts/render_diagrams.py", "tests": "RENDER",
     "old": "        if missing := geometry.missing_glyphs(label, 400) or geometry.missing_glyphs(label, 700):",
     "new": "        if missing := []:"},
    {"id": "ALIAS-DARK", "file": "scripts/render_diagrams.py", "tests": "RENDER",
     "old": "\"dark\": \"surface-2\"", "new": "\"dark\": \"surface\""},
    {"id": "STAMP-PALETTE", "file": "scripts/render_diagrams.py", "tests": "RENDER",
     "old": "\"palette\": palette()[theme], ", "new": ""},
    {"id": "STAMP-ROLES", "file": "scripts/render_diagrams.py", "tests": "RENDER",
     "old": "\"roles\": ROLES, ", "new": ""},
    {"id": "DOCTYPE", "file": "scripts/render_diagrams.py", "tests": "RENDER",
     "old": "    svg = re.sub(r\"<!DOCTYPE[^>]*>\\s*\", \"\", svg)\n", "new": ""},
    {"id": "PX", "file": "scripts/render_diagrams.py", "tests": "RENDER",
     "old": "r'\\1=\"\\2\"', root.group(0))", "new": "r'\\1=\"\\2px\"', root.group(0))"},
    {"id": "FONT-EMBED", "file": "scripts/render_diagrams.py", "tests": "COMMITTED",
     "old": "    style = f\"<defs><style>{font_faces(svg)}</style></defs>\"", "new": "    style = \"\""},
    {"id": "OFFLINE", "file": "scripts/render_diagrams.py", "tests": "RENDER",
     "old": "\"--network=none\",", "new": ""},
    {"id": "THEME-LIGHT", "file": "scripts/render_diagrams.py", "tests": "RENDER",
     "old": "\"--theme\", \"light\"", "new": "\"--theme\", \"auto\""},
    {"id": "ENGINE-DOCKER", "file": "scripts/render_diagrams.py", "tests": "RENDER",
     "old": "for name in (\"podman\", \"docker\"):", "new": "for name in (\"podman\",):"},
    {"id": "LINE-CLEAR", "file": "scripts/diagram_geometry.py", "tests": "GEOMETRY",
     "old": "for lid, s in lines if _hits(near, s)]", "new": "for lid, s in lines if False]"},
    {"id": "FIT", "file": "scripts/diagram_geometry.py", "tests": "GEOMETRY",
     "old": "            if role and role not in EDGES and not _fits(t, cell, role):",
     "new": "            if False:"},
    {"id": "DIAMOND", "file": "scripts/diagram_geometry.py", "tests": "GEOMETRY",
     "old": "    if role == \"ow:decision\" and cell.filled:", "new": "    if False:"},
    {"id": "ARROWHEAD", "file": "scripts/diagram_geometry.py", "tests": "GEOMETRY",
     "old": "for hid, b in heads if near.overlaps(b)]", "new": "for hid, b in heads if False]"},
    {"id": "LABEL-NODE", "file": "scripts/diagram_geometry.py", "tests": "GEOMETRY",
     "old": "for nid, b in solid.items() if near.overlaps(b)]", "new": "for nid, b in solid.items() if False]"},
    {"id": "NODE-OVERLAP", "file": "scripts/diagram_geometry.py", "tests": "GEOMETRY",
     "old": "if solid[a].overlaps(solid[b])]", "new": "if False]"},
    {"id": "GLYPH-GEOMETRY", "file": "scripts/diagram_geometry.py", "tests": "GEOMETRY",
     "old": "            if missing := missing_glyphs(t.text, t.weight):", "new": "            if missing := []:"},
    {"id": "NESTED-CELL", "file": "scripts/diagram_geometry.py", "tests": "GEOMETRY",
     "old": "            cell = found.setdefault(cid, Cell(cid))", "new": "            cell = cell or found.setdefault(cid, Cell(cid))"},
    {"id": "PATH-LOUD", "file": "scripts/diagram_geometry.py", "tests": "GEOMETRY",
     "old": "        raise ValueError(f\"path command not understood: {leftover!r} in {d!r}\")", "new": "        return []"},
    {"id": "LANGUAGE", "file": "tests/test_diagrams.py", "tests": "COMMITTED",
     "old": "            if lang and (lang.group(1) == \"de\") != german:", "new": "            if False:"},
    {"id": "ORPHANS", "file": "tests/test_diagrams.py", "tests": "COMMITTED",
     "old": "    assert not orphans,", "new": "    assert True or orphans,"},
    {"id": "MERMAID-FENCE", "file": "docs-tech/release.md", "tests": "COMMITTED",
     "old": "<picture>", "new": "```mermaid\nflowchart LR\n  A --> B\n```\n\n<picture>"}
  ]
}
```

The `LANGUAGE` and `ORPHANS` mutations change a test, not a guard. They prove the test can fail: `ORPHANS` goes
red only together with a planted orphan. Run it once by hand:
`touch docs/img/diagrams/stray-light.svg && uv run pytest tests/test_diagrams.py -k orphan --no-cov -q; rm docs/img/diagrams/stray-light.svg`
Expected: FAIL naming `stray-light.svg`. Then remove `ORPHANS` and `LANGUAGE` from the JSON. A mutation of the
test itself proves nothing in an automated audit. Replace `LANGUAGE` with a mutation of the German post's
embed:

```json
    {"id": "LANGUAGE", "file": "docs/de/blog/interne-meldestelle-kostenlos.html", "tests": "COMMITTED",
     "old": "src=\"/img/diagrams/architecture.de-light.svg\"", "new": "src=\"/img/diagrams/architecture-light.svg\""}
```

- [ ] **Step 2: Run the audit**

Run: `uv run python scripts/mutation_audit.py docs-tech/mutations/v2.1.1-site-p2a.json`
Expected: every line `RED`. For a `GREEN`, write the test that catches it in the owning task's test file,
then re-run. Read which test fired: a guard caught by an unrelated test is caught by luck.

- [ ] **Step 3: CHANGELOG**

Under `## [Unreleased]`, `### Changed`, add:

```markdown
- Website and maintainer docs: every diagram is a draw.io SVG in one style, light and dark, checked for labels on
  lines and clipped text; the German blog post shows German labels; the home page shows the reporting flow as one
  diagram. Mermaid is gone.
```

- [ ] **Step 4: Full suite and lint**

```bash
uv run pytest -q -p no:cacheprovider
uv run ruff check scripts tests
uv run mypy
npx --yes markdownlint-cli2 "**/*.md" "#node_modules" "#.venv"
uv lock --check
uvx codespell
```

Expected:

- the full suite passes with coverage ≥ 90 %;
- `ruff check`, `mypy`, markdownlint and codespell are clean;
- `uv lock --check` passes.

- [ ] **Step 5: Commit**

```bash
git add docs-tech/mutations/v2.1.1-site-p2a.json CHANGELOG.md
git commit -m "test(site): mutation audit of the diagram guards, all red"
```

- [ ] **Step 6: Hand over to the controller**

The controller (not the implementer) does the rest:

- builds the site;
- runs the Chrome check of every page that shows a diagram, in dark **and** light at 1920 px and 390 px
  (`docs-tech/local-review.md`), on a dark system theme first;
- checks `gh api …/code-scanning/alerts?state=open` is 0;
- opens the PR.

## Self-review record

- **Spec coverage:**
  - P2-2/P2-3/P2-4/P2-5 → Task 1 ROLES/ALIASES;
  - P2-6 → Task 2;
  - P2-7 → Task 5;
  - P2-8 → Tasks 4 and 6 (+ the guard);
  - pipeline bullets → Tasks 1 and 3;
  - embedding table → Tasks 4, 5 and 6;
  - every row of the diagrams table → Tasks 4–6;
  - "Removed" → Task 4 Steps 7 and 9;
  - every guard row → Task 4 tests (stamp, legible, palette, self-contained, language, embedded), Task 6
    (no Mermaid, picture);
  - "Also in P2a" (Pages check) → Task 6 Step 4.
  - P2-1, P2-9 and P2-10 belong to P2b.
- **Placeholders:**
  - `W`/`H` in Task 5 Step 3 are defined in place: the numbers come from the render.
  - `(the same alt text)` means copying the full light alt, stated in the step.
- **Types:**
  - `problems(svg, roles)`, `texts(svg)`, `text_box(...)`, `expand(source, theme, colors)`,
    `stamp(source, theme)`, `svg_path(source, out, theme)` and `sources(names)` have the same signatures in
    every task.
