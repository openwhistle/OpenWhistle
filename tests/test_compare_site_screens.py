"""scripts/compare_site_screens.py: which pages, and when two screenshots count as the same."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "compare_site_screens", ROOT / "scripts/compare_site_screens.py"
)
assert _spec and _spec.loader
cs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cs)


def _png(
    path: Path,
    size: tuple[int, int],
    colour: tuple[int, int, int],
    dot: tuple[int, int] | None = None,
) -> Path:
    img = Image.new("RGB", size, colour)
    if dot:
        img.putpixel(dot, (255, 0, 0))
    img.save(path)
    return path


def test_identical_screens_have_no_difference(tmp_path: Path) -> None:
    a = _png(tmp_path / "a.png", (40, 30), (8, 8, 10))
    b = _png(tmp_path / "b.png", (40, 30), (8, 8, 10))
    assert cs.same_image(a, b, tmp_path / "d.png") == 0
    assert not (tmp_path / "d.png").exists()


def test_one_pixel_is_a_difference_and_leaves_a_diff_image(tmp_path: Path) -> None:
    a = _png(tmp_path / "a.png", (40, 30), (8, 8, 10))
    b = _png(tmp_path / "b.png", (40, 30), (8, 8, 10), dot=(3, 4))
    assert cs.same_image(a, b, tmp_path / "d.png") == 1
    assert (tmp_path / "d.png").is_file()


def test_a_different_height_is_a_difference(tmp_path: Path) -> None:
    a = _png(tmp_path / "a.png", (40, 30), (8, 8, 10))
    b = _png(tmp_path / "b.png", (40, 31), (8, 8, 10))
    assert cs.same_image(a, b, tmp_path / "d.png") > 0


def test_every_built_html_page_is_a_url(tmp_path: Path) -> None:
    for rel in ("en/index.html", "de/blog/x/index.html", "404.html", "assets/css/a.css"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("x")
    assert cs.page_urls(tmp_path) == ["/404.html", "/de/blog/x/", "/en/"]


def test_the_shots_cover_both_themes_at_desktop_and_phone() -> None:
    assert set(cs.SHOTS) == {("light", 1920), ("dark", 1920), ("light", 390), ("dark", 390)}


def test_a_shot_on_one_side_only_is_a_difference(tmp_path: Path) -> None:
    for d in ("base", "head"):
        (tmp_path / d).mkdir()
    _png(tmp_path / "base/gone-dark-390.png", (4, 4), (0, 0, 0))
    _png(tmp_path / "head/new-dark-390.png", (4, 4), (0, 0, 0))
    _png(tmp_path / "base/same-dark-390.png", (4, 4), (0, 0, 0))
    _png(tmp_path / "head/same-dark-390.png", (4, 4), (0, 0, 0))
    lines = cs.compare_dirs(tmp_path / "base", tmp_path / "head", tmp_path)
    assert lines == ["gone-dark-390.png: removed page", "new-dark-390.png: new page"]


def test_an_unknown_only_url_fails_and_a_used_out_dir_is_refused(tmp_path: Path) -> None:
    import pytest

    (tmp_path / "stale.png").write_text("x")
    with pytest.raises(SystemExit, match="not empty"):
        cs.main(["--out", str(tmp_path)])


def test_check_only_names_the_unknown_urls() -> None:
    import pytest

    cs.check_only(["/en/"], ["/en/", "/de/"])
    with pytest.raises(SystemExit, match="/en$"):
        cs.check_only(["/en/", "/en"], ["/en/"])
