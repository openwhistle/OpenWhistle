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
LINES = EDGES | {"ow:lifeline"}                     # their unfilled paths are lines text must clear
CONTAINERS = {"ow:group", "ow:lane", "ow:lifeline"}  # boxes that hold other cells
PAD_X = 6.0  # room between a text line and the side of its shape
PAD_Y = 2.0
CLEAR = 3.0  # gap between any text and any line, arrowhead or foreign node

_INHERITED = (
    "font-family", "font-size", "font-weight", "text-anchor", "fill", "stroke", "stroke-width"
)
_NUMBER = r"-?(?:\d+\.?\d*|\.\d+)(?:[eE]-?\d+)?"
_TRANSLATE = re.compile(rf"translate\(\s*({_NUMBER})\s*[, ]?\s*({_NUMBER})?\s*\)")
_PATH_TOKEN = re.compile(rf"[MLQCZ]|{_NUMBER}")
_ARGS = {"M": 2, "L": 2, "Q": 4, "C": 6}
CURVE_STEPS = 8  # points a rounded elbow is sampled at; a label grazing the curve is still found
# ElementTree parses only the repository's own exports; expat resolves no external entities
# (so no defusedxml, see global constraints).

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
    parent: str | None = None
    unfilled: list[list[Point]] = field(default_factory=list)
    texts: list[Text] = field(default_factory=list)
    ink: list[Box] = field(default_factory=list)  # shapes and lines with half their stroke


def _bounds(points: list[Point]) -> Box:
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return Box(min(xs), min(ys), max(xs), max(ys))


def _union(boxes: list[Box]) -> Box | None:
    if not boxes:
        return None
    return Box(min(b.x0 for b in boxes), min(b.y0 for b in boxes),
               max(b.x1 for b in boxes), max(b.y1 for b in boxes))


def _num(value: str | None) -> float:
    m = re.match(_NUMBER, value or "0")
    return float(m.group(0)) if m else 0.0


def _curve(start: Point, args: list[float]) -> list[Point]:
    """CURVE_STEPS points along a quadratic (4 args) or cubic (6 args) Bezier, end point last."""
    pts = [start, *zip(args[0::2], args[1::2], strict=True)]
    out: list[Point] = []
    for i in range(1, CURVE_STEPS + 1):
        t = i / CURVE_STEPS
        level = pts
        while len(level) > 1:  # de Casteljau
            level = [
                (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
                for a, b in zip(level, level[1:], strict=False)
            ]
        out.append(level[0])
    return out


def _subpaths(d: str) -> list[list[Point]]:
    """A draw.io path as point lists; curves are sampled, so a rounded elbow is not its chord."""
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
        elif cmd in "QC":
            out[-1].extend(_curve(out[-1][-1], args))
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

    def walk(
        el: ET.Element, inherited: dict[str, str], cell: Cell | None, off: Point = (0.0, 0.0)
    ) -> None:
        attrs = {**inherited, **{k: v for k in _INHERITED if (v := el.get(k)) is not None}}
        if (cid := el.get("data-cell-id")) is not None:
            cell = found.setdefault(cid, Cell(cid, parent=cell.id if cell else None))
        tag = _local(el.tag)
        if m := _TRANSLATE.search(el.get("transform", "")):  # draw.io shifts shapes by 0.5
            off = (off[0] + float(m.group(1)), off[1] + float(m.group(2) or 0))
        ox, oy = off
        stroked = attrs.get("stroke", "none") != "none"
        half = _num(attrs.get("stroke-width", "1")) / 2 if stroked else 0.0
        if cell is not None and tag == "rect":
            x, y = _num(el.get("x")) + ox, _num(el.get("y")) + oy
            cell.rects.append(Box(x, y, x + _num(el.get("width")), y + _num(el.get("height"))))
            cell.ink.append(cell.rects[-1].grow(half))
        elif cell is not None and tag == "ellipse":
            cx, cy, rx, ry = (_num(el.get(k)) for k in ("cx", "cy", "rx", "ry"))
            cx, cy = cx + ox, cy + oy
            cell.rects.append(Box(cx - rx, cy - ry, cx + rx, cy + ry))
            cell.ink.append(cell.rects[-1].grow(half))
        elif cell is not None and tag == "path":
            target = cell.unfilled if attrs.get("fill", "black") == "none" else cell.filled
            shifted = [[(px + ox, py + oy) for px, py in sub] for sub in _subpaths(el.get("d", ""))]
            target.extend(sub for sub in shifted if len(sub) > 1)
            cell.ink += [_bounds(sub).grow(half) for sub in shifted if len(sub) > 1]
        elif cell is not None and tag == "text":
            for span in el:
                if _local(span.tag) == "tspan" and {"x", "y", "dx", "dy"} & set(span.attrib):
                    raise ValueError(f"cell {cell.id}: a positioned <tspan> is not measured")
            weight = 700 if attrs.get("font-weight") in ("bold", "700") else 400
            line = "".join(el.itertext())
            if (family := attrs.get("font-family")) != "Sora":
                raise ValueError(f"cell {cell.id}: {line!r} is drawn in {family!r}, not Sora")
            size = _num(attrs.get("font-size", "12"))
            box = text_box(line, _num(el.get("x")) + ox, _num(el.get("y")) + oy, size, weight,
                           attrs.get("text-anchor", "start"))
            cell.texts.append(Text(line, box, weight))
            return
        for child in el:
            walk(child, attrs, cell, off)

    walk(ET.fromstring(svg), {}, None)  # noqa: S314
    return found


def texts(svg: str) -> list[Text]:
    return [t for cell in _cells(svg).values() for t in cell.texts]


def content_box(svg: str) -> Box | None:
    """Everything the picture draws (shapes, lines with their stroke, text ink); None if empty."""
    cells = _cells(svg).values()
    return _union([b for c in cells for b in [*c.ink, *(t.box for t in c.texts)]])


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


def _edges_of(box: Box) -> list[Segment]:
    c = box.corners()
    return list(zip(c, c[1:] + c[:1], strict=True))


def _ancestors(found: dict[str, Cell], cid: str) -> list[str]:
    out, parent = [], found[cid].parent
    while parent is not None:
        out.append(parent)
        parent = found[parent].parent
    return out


def _on_border(seg: Segment, box: Box) -> bool:
    """A side or a rounded corner of the box, not a line across it (a lane's header separator)."""
    mx, my = (seg[0][0] + seg[1][0]) / 2, (seg[0][1] + seg[1][1]) / 2
    return min(mx - box.x0, box.x1 - mx, my - box.y0, box.y1 - my) <= CLEAR  # corner: ~2 px in


def _lines(found: dict[str, Cell], roles: dict[str, str]) -> list[tuple[str, Segment]]:
    """Every line a text must clear: edges, lifelines, and the borders of groups and lanes."""
    lines = []
    for cid, c in found.items():
        role = roles.get(cid)
        if role in LINES or role in CONTAINERS:
            lines += [(cid, s) for s in _segments(c.unfilled)]
        if role in CONTAINERS:  # a group's border is an unfilled rect
            lines += [(cid, s) for r in c.rects for s in _edges_of(r)]
    return lines


@dataclass
class _Context:
    """What every text is checked against; built once per problems() call."""

    found: dict[str, Cell]
    lines: list[tuple[str, Segment]]
    heads: list[tuple[str, Box]]
    solid: dict[str, Box]


def _context(found: dict[str, Cell], roles: dict[str, str]) -> _Context:
    return _Context(
        found,
        _lines(found, roles),
        [(h, _bounds(p)) for h, c in found.items() if roles.get(h) in EDGES for p in c.filled],
        {
            n: b
            for n, c in found.items()
            if roles.get(n) and roles[n] not in EDGES | CONTAINERS and (b := _outline(c))
        },
    )


def _text_problems(cid: str, cell: Cell, role: str, ctx: _Context) -> list[str]:
    lines, heads, solid, found = ctx.lines, ctx.heads, ctx.solid, ctx.found
    out: list[str] = []
    for t in cell.texts:
        if missing := missing_glyphs(t.text, t.weight):
            out.append(f"{cid}: Sora has no glyph for {missing} in {t.text!r}")
        if role not in EDGES and not _fits(t, cell, role):
            out.append(f"{cid}: text {t.text!r} does not fit its shape")
        near = t.box.grow(CLEAR)
        outline = _outline(cell)
        for lid, seg in lines:
            if lid == cid and role in CONTAINERS and outline and _on_border(seg, outline):
                continue  # a container's own header sits inside its own outer border
            if _hits(near, seg):
                out.append(f"{cid}: text {t.text!r} touches a line of {lid}")
        out += [f"{cid}: text {t.text!r} touches an arrowhead of {hid}" for hid, b in heads
                if near.overlaps(b)]
        if role in EDGES:
            out += [
                f"{cid}: label {t.text!r} overlaps {nid}"
                for nid, b in solid.items()
                if near.overlaps(b)
            ]
        for oid, other in found.items():
            if oid > cid:  # each pair once
                out += [
                    f"{cid}: label {t.text!r} overlaps text of {oid}"
                    for o in other.texts
                    if t.box.grow(CLEAR / 2).overlaps(o.box.grow(CLEAR / 2))
                ]
    return out


def problems(svg: str, roles: dict[str, str]) -> list[str]:
    """Everything that makes a label unreadable; an empty list means the diagram is legible."""
    found = _cells(svg)
    for cid, cell in found.items():
        if cid not in roles and (cell.texts or _outline(cell)):
            raise ValueError(f"cell {cid!r} has shapes or text but no role in the source")
    out: list[str] = []
    ctx = _context(found, roles)
    for cid, cell in found.items():
        out += _text_problems(cid, cell, roles[cid], ctx) if cid in roles else []
    shapes = {
        cid: box
        for cid, c in found.items()
        if roles.get(cid) not in EDGES and (box := _outline(c)) is not None
    }
    for cid, box in shapes.items():
        parent = found[cid].parent or ""
        if roles.get(parent) in CONTAINERS and parent in shapes and not box.within(shapes[parent]):
            out.append(f"{cid} sticks out of {parent}")
    ids = sorted(shapes)
    out += [
        f"{a} and {b} overlap"
        for i, a in enumerate(ids)
        for b in ids[i + 1 :]
        if shapes[a].overlaps(shapes[b])
        and a not in _ancestors(found, b)
        and b not in _ancestors(found, a)
    ]
    return list(dict.fromkeys(out))
