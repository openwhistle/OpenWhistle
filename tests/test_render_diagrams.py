"""scripts/render_diagrams.py turns role names into style C, one theme at a time."""

from __future__ import annotations

import base64
import io
import json
import re
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from fontTools.ttLib import TTFont

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
    cells = ET.fromstring(xml).iter("mxCell")  # noqa: S314 (the test's own constant)
    return {c.get("id"): c.get("style") for c in cells if c.get("style")}


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


EXPORTED = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" '
    '"http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">\n'
    '<svg xmlns="http://www.w3.org/2000/svg" style="color-scheme: light;" version="1.1" '
    'width="498px" height="745px" viewBox="0 0 498 745"><defs/><g>'
    '<g data-cell-id="a"><g fill="#ffffff" font-family="Sora" font-weight="bold" '
    'text-anchor="middle" '
    'font-size="13px"><text x="60" y="25">Submit</text></g></g>'
    '<g data-cell-id="b"><g fill="#0a0a0b" font-family="Sora" text-anchor="middle" '
    'font-size="13px">'
    '<text x="60" y="105">Größe § 1</text></g></g></g></svg>'
)


def _faces(svg: str) -> dict[int, TTFont]:
    out = {}
    pattern = r"font-weight:(\d+);src:url\(data:font/woff2;base64,([^)]+)\)"
    for weight, data in re.findall(pattern, svg):
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
    only_docker = {"docker": "/usr/bin/docker"}
    monkeypatch.setattr(r.shutil, "which", only_docker.get)
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
