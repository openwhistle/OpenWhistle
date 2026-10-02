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
    return {c.get("id"): c.get("style") for c in ET.fromstring(xml).iter("mxCell") if c.get("style")}


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
    assert "fontColor=#06120d" in r.expand_style("ow:start", dark)   # accent-ink
    assert "fillColor=#1b1b1e" in r.expand_style("ow:step", dark)    # node = surface-2


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


def test_the_stamp_covers_source_theme_roles_image_and_fonts(monkeypatch: pytest.MonkeyPatch) -> None:
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
