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
_PILL = "rounded=1;arcSize=50;fillColor={accent};strokeColor=none;fontColor={accent-ink};fontStyle=1;"

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
    "ow:note": _BOX + "fillColor=none;strokeColor={muted};dashed=1;dashPattern=4 3;fontColor={muted};fontSize=12;",
    "ow:group": _BOX + (
        "container=1;fillColor=none;strokeColor={hairline};verticalAlign=top;align=left;"
        "spacingLeft=12;spacingTop=6;fontColor={muted};fontSize=11;fontStyle=1;"
    ),
    "ow:lane": "swimlane;startSize=32;" + _BOX + (
        "fillColor=none;swimlaneFillColor=none;strokeColor={hairline};fontColor={ink};fontStyle=1;"
    ),
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
        {"source": source, "theme": theme, "common": COMMON, "roles": ROLES, "aliases": ALIASES,
         "palette": palette()[theme], "image": IMAGE, "fonts": fonts},
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
