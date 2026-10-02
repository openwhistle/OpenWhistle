"""scripts/diagram_geometry.py finds every way a rendered label stops being readable."""

from __future__ import annotations

from tests.diagram_tools import geometry

HEAD = '<svg xmlns="http://www.w3.org/2000/svg" width="600" height="400" viewBox="0 0 600 400"><g>'
TAIL = "</g></svg>"


def _text(x: float, y: float, text: str, size: int = 13, bold: bool = False, anchor: str = "middle") -> str:
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


def edge(cid: str, points: list[tuple[float, float]], label: str = "", at: tuple[float, float] = (0, 0)) -> str:
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
    assert any(p.startswith("d: ") and "touches a line" in p for p in geometry().problems(picture, ROLES))


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
    picture = svg('<g data-cell-id="e"><g><path d="m 0 0 l 10 10" fill="none" stroke="#000"/></g></g>')
    try:
        geometry().problems(picture, ROLES)
    except ValueError as err:
        assert "path command" in str(err)
    else:
        raise AssertionError("a relative path command was silently ignored")
