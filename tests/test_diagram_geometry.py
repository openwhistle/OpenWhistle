"""scripts/diagram_geometry.py finds every way a rendered label stops being readable."""

from __future__ import annotations

from collections.abc import Sequence

from tests.diagram_tools import geometry

HEAD = '<svg xmlns="http://www.w3.org/2000/svg" width="600" height="400" viewBox="0 0 600 400"><g>'
TAIL = "</g></svg>"


def _text(
    x: float, y: float, text: str, size: int = 13, bold: bool = False, anchor: str = "middle"
) -> str:
    weight = ' font-weight="bold"' if bold else ""
    return (
        f'<g><g fill="#0a0a0b" font-family="Sora"{weight} text-anchor="{anchor}" '
        f'font-size="{size}px">'
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
    cid: str,
    points: Sequence[tuple[float, float]],
    label: str = "",
    at: tuple[float, float] = (0, 0),
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
    assert "e: text 'yes' touches a line of e" in geometry().problems(picture, ROLES)


def test_a_label_beside_its_line_is_fine() -> None:
    picture = svg(edge("e", [(0, 100), (300, 100)], "yes", at=(150, 88)))
    assert geometry().problems(picture, ROLES) == []


def test_a_line_through_a_decision_label_is_found() -> None:
    picture = svg(
        decision("d", 150, 100, 230, 80, "Locations"),
        edge("e", [(150, 100), (400, 100)]),
    )
    assert "d: text 'Locations' touches a line of e" in geometry().problems(picture, ROLES)


def test_text_wider_than_its_box_is_found() -> None:
    picture = svg(node("a", 0, 0, 60, 40, "Choose own password"))
    assert geometry().problems(picture, ROLES) == [
        "a: text 'Choose own password' does not fit its shape"
    ]


def test_text_in_a_decision_corner_is_found() -> None:
    """The bounding box would hold it; the diamond does not."""
    picture = svg(decision("d", 150, 100, 160, 50, "Password set by some"))
    assert "d: text 'Password set by some' does not fit its shape" in geometry().problems(
        picture, ROLES
    )


def test_a_label_on_an_arrowhead_is_found() -> None:
    picture = svg(edge("e", [(100, 0), (100, 100)], "x", at=(108, 97)))
    assert "e: text 'x' touches an arrowhead of e" in geometry().problems(picture, ROLES)


def test_node_text_beside_an_arrowhead_is_found() -> None:
    """The arrowhead is 8 px wide; the line it ends clears the text, the head does not."""
    text = _text(145, 14, "Start", anchor="end")
    picture = svg(node("a", 0, 0, 200, 40, inner=text), edge("e", [(150, -60), (150, 10)]))
    assert geometry().problems(picture, ROLES) == ["a: text 'Start' touches an arrowhead of e"]


def test_a_label_over_a_node_is_found() -> None:
    picture = svg(
        node("a", 0, 0, 200, 40, "Start"),
        edge("e", [(250, 0), (250, 100)], "username", at=(205, 20)),
    )
    assert "e: label 'username' overlaps a" in geometry().problems(picture, ROLES)


def test_overlapping_nodes_are_found() -> None:
    picture = svg(node("a", 0, 0, 200, 40, "One"), node("b", 150, 20, 200, 40, "Two"))
    assert geometry().problems(picture, ROLES) == ["a and b overlap"]


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
    assert "a: Sora has no glyph for ['→'] in '80 → 443'" in geometry().problems(picture, ROLES)


def test_text_in_another_font_is_refused() -> None:
    """Only Sora is measured: a text drawn in any other font would make every check fiction."""
    sora = svg(node("a", 0, 0, 200, 40, "Start"))
    picture = sora.replace('font-family="Sora"', 'font-family="Arial"')
    try:
        geometry().problems(picture, ROLES)
    except ValueError as err:
        assert "'Arial'" in str(err) and "not Sora" in str(err)
    else:
        raise AssertionError("a text in Arial was measured as Sora")


def test_bold_is_measured_wider() -> None:
    g = geometry()
    regular = g.text_box("Submit", 0, 0, 13, 400, "start")
    bold = g.text_box("Submit", 0, 0, 13, 700, "start")
    assert bold.x1 > regular.x1 > 30


def test_an_unknown_path_command_fails_loudly() -> None:
    path = '<path d="m 0 0 l 10 10" fill="none" stroke="#000"/>'
    picture = svg(f'<g data-cell-id="e"><g>{path}</g></g>')
    try:
        geometry().problems(picture, ROLES)
    except ValueError as err:
        assert "path command" in str(err)
    else:
        raise AssertionError("a relative path command was silently ignored")


# --- what draw.io writes: a group is an unfilled rect, a lane three unfilled paths ---


def group(
    cid: str, x: float, y: float, w: float, h: float, label: str, inner: str = "", dy: float = 23
) -> str:
    return (
        f'<g data-cell-id="{cid}"><g><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="7" ry="7" '
        f'fill="none" stroke="#e6e6e4"/></g>{_text(x + 14, y + dy, label, 11, True, "start")}'
        f"{inner}</g>"
    )


def lane(
    cid: str, x: float, y: float, w: float, h: float, label: str, inner: str = "", ty: float = 21
) -> str:
    r, b, head = x + w, y + h, y + 32  # right edge, bottom edge, header separator
    outline = (
        f"M {r} {head} L {r} {y + 7} Q {r} {y} {r - 7} {y} L {x + 7} {y} Q {x} {y} {x} {y + 7} "
        f"L {x} {head}"
    )
    rest = (
        f"M {x} {head} L {x} {b - 7} Q {x} {b} {x + 7} {b} L {r - 7} {b} Q {r} {b} {r} {b - 7} "
        f"L {r} {head}"
    )
    paths = "".join(
        f'<path d="{d}" fill="none" stroke="#e6e6e4"/>'
        for d in (outline, rest, f"M {x} {head} L {r} {head}")
    )
    return (
        f'<g data-cell-id="{cid}"><g>{paths}</g>'
        f"{_text(x + w / 2, y + ty, label, 12, True)}{inner}</g>"
    )


ROLES |= {"l": "ow:lane", "g2": "ow:group", "e2": "ow:edge", "z": "ow:step"}


def test_groups_and_lanes_with_their_content_are_clean() -> None:
    picture = svg(
        group("g", 20, 20, 300, 160, "Group", node("a", 40, 60, 120, 40, "Inside")),
        lane("l", 20, 220, 300, 160, "Lane", node("b", 40, 270, 120, 40, "In lane")),
    )
    assert geometry().problems(picture, ROLES | {"b": "ow:step"}) == []


def test_a_container_header_may_sit_close_to_its_own_border() -> None:
    """Only the container's own text is exempt from its border; a header is always inside it."""
    picture = svg(group("g", 20, 20, 300, 100, "Group", dy=10.6))
    assert geometry().problems(picture, ROLES) == []


def test_a_lane_title_on_its_own_header_separator_is_found() -> None:
    """Only the outer border is exempt; the separator runs through the lane, under its title."""
    picture = svg(lane("l", 20, 20, 400, 200, "Lane", ty=36))
    assert "l: text 'Lane' touches a line of l" in geometry().problems(picture, ROLES)


def test_a_label_on_a_group_border_is_found() -> None:
    picture = svg(
        group("g", 20, 20, 400, 200, "Group"), edge("e", [(500, 0), (500, 90)], "x", at=(220, 22))
    )
    assert "e: text 'x' touches a line of g" in geometry().problems(picture, ROLES)


def test_a_label_on_a_lane_separator_or_border_is_found() -> None:
    g = geometry()
    far = [(500, 0), (500, 90)]
    on_separator = svg(lane("l", 20, 20, 400, 200, "Lane"), edge("e", far, "x", at=(220, 54)))
    assert "e: text 'x' touches a line of l" in g.problems(on_separator, ROLES)
    on_border = svg(lane("l", 20, 20, 400, 200, "Lane"), edge("e", far, "x", at=(21, 120)))
    assert "e: text 'x' touches a line of l" in g.problems(on_border, ROLES)


def test_a_node_sticking_out_of_its_group_is_found() -> None:
    picture = svg(group("g", 20, 20, 200, 100, "Group", node("a", 150, 50, 120, 40, "Inside")))
    assert "a sticks out of g" in geometry().problems(picture, ROLES)


def test_sibling_groups_overlapping_are_found() -> None:
    picture = svg(group("g", 0, 0, 200, 100, "One"), group("g2", 150, 50, 200, 100, "Two"))
    assert geometry().problems(picture, ROLES) == ["g and g2 overlap"]


def test_a_cell_without_a_role_is_refused() -> None:
    try:
        geometry().problems(svg(node("nope", 0, 0, 200, 40, "Start")), ROLES)
    except ValueError as err:
        assert "'nope'" in str(err)
    else:
        raise AssertionError("a cell missing from roles was silently skipped")


def test_a_label_over_another_label_is_found() -> None:
    picture = svg(
        edge("e", [(0, 100), (300, 100)], "yes", at=(150, 88)),
        edge("e2", [(0, 200), (300, 200)], "no", at=(152, 90)),
    )
    assert "e: label 'yes' overlaps text of e2" in geometry().problems(picture, ROLES)


def test_a_positioned_tspan_is_refused() -> None:
    tspan = (
        '<g data-cell-id="a"><g><rect x="0" y="0" width="200" height="40"/></g>'
        '<text x="5" y="5"><tspan x="9" y="9">hi</tspan></text></g>'
    )
    try:
        geometry().problems(svg(tspan), ROLES)
    except ValueError as err:
        assert "tspan" in str(err)
    else:
        raise AssertionError("a positioned tspan was measured as one line")


def test_one_problem_is_reported_once_however_many_segments_it_touches() -> None:
    long_label = "yes yes yes yes"
    points = [(0, 100), (130, 100), (150, 100), (170, 100), (300, 100)]
    picture = svg(edge("e", points, long_label, at=(150, 104)))
    found = geometry().problems(picture, ROLES)
    assert found.count(f"e: text '{long_label}' touches a line of e") == 1


def test_curves_are_sampled_not_reduced_to_their_end_points() -> None:
    g = geometry()
    quad = g._subpaths("M 0 0 Q 10 0 10 10")[0]
    assert len(quad) == 1 + g.CURVE_STEPS and quad[-1] == (10, 10)
    assert quad[g.CURVE_STEPS // 2] == (7.5, 2.5)  # t = 1/2
    cubic = g._subpaths("M 0 0 C 0 10 10 10 10 0")[0]
    assert len(cubic) == 1 + g.CURVE_STEPS and cubic[-1] == (10, 0)
    assert cubic[g.CURVE_STEPS // 2] == (5, 7.5)


def test_a_label_grazing_a_rounded_elbow_is_found() -> None:
    """The chord of the corner passes the label; the curve itself does not."""
    d = "M 0 100 L 90 100 Q 100 100 100 90 L 100 0"
    picture = svg(
        f'<g data-cell-id="e"><g><path d="{d}" fill="none" stroke="#0a0a0b"/></g>'
        f"{_text(104, 101, 'x', 11)}</g>"
    )
    assert "e: text 'x' touches a line of e" in geometry().problems(picture, ROLES)


def test_the_end_anchor_measures_leftwards() -> None:
    g = geometry()
    end = g.text_box("abc", 100, 0, 13, 400, "end")
    start = g.text_box("abc", 0, 0, 13, 400, "start")
    assert round(end.x1, 6) == 100 and round(end.x1 - end.x0, 6) == round(start.x1, 6)


def test_a_translate_shifts_the_shapes_inside_it() -> None:
    inner = '<rect x="10" y="20" width="100" height="40" fill="#fff"/>'
    shifted = (
        '<svg xmlns="http://www.w3.org/2000/svg"><g data-cell-id="a">'
        f'<g transform="translate(0.5,0.5)">{inner}</g></g></svg>'
    )
    assert geometry().content_box(shifted) == geometry().Box(10.5, 20.5, 110.5, 60.5)


def test_content_box_unites_shapes_lines_and_text_ink() -> None:
    g = geometry()
    picture = svg(node("a", 10, 10, 100, 40, "Hi"), edge("e", [(60, 50), (60, 120)]))
    box = g.content_box(picture)
    assert (box.x0, box.y0, box.x1) == (10, 10, 110) and box.y1 == 120.5  # edge stroke
    assert g.content_box(svg()) is None


def test_content_box_includes_half_the_stroke_width() -> None:
    def picture(attrs: str) -> str:
        return (
            '<svg xmlns="http://www.w3.org/2000/svg"><g data-cell-id="a"><g>'
            f'<rect x="10" y="10" width="100" height="40" {attrs}/></g></g></svg>'
        )

    g = geometry()
    assert g.content_box(picture('fill="#fff" stroke="none"')) == g.Box(10, 10, 110, 50)
    assert g.content_box(picture('fill="none" stroke="#000"')) == g.Box(9.5, 9.5, 110.5, 50.5)
    wide = picture('fill="none" stroke="#000" stroke-width="2"')
    assert g.content_box(wide) == g.Box(9, 9, 111, 51)
