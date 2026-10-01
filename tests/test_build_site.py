"""scripts/build_site.py: the rules the site build promises (see its docstring)."""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "site"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_site", ROOT / "scripts" / "build_site.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # @dataclass looks its module up here
    spec.loader.exec_module(module)
    return module


B = _load()


@pytest.fixture
def src(tmp_path: Path) -> Path:
    """A writable copy of the fixture, so a test can break one file."""
    copy = tmp_path / "src"
    shutil.copytree(FIXTURE, copy)
    return copy


def _build(src: Path, tmp_path: Path, **kw: bool) -> Path:
    out = tmp_path / "out"
    B.build(src, out, **kw)
    return out


@pytest.mark.parametrize(
    ("rel", "url"),
    [
        ("en/index.html", "/en/"),
        ("en/docs/index.md", "/en/docs/"),
        ("de/blog/was-ist-neu.html", "/de/blog/was-ist-neu/"),
        ("404.html", "/404.html"),
    ],
)
def test_url_for(rel: str, url: str) -> None:
    assert B.url_for(Path(rel)) == url


def test_pages_land_at_their_url_and_statics_are_copied(src: Path, tmp_path: Path) -> None:
    out = _build(src, tmp_path)
    assert (out / "en" / "index.html").is_file()
    assert (out / "en" / "docs" / "index.html").is_file()
    assert (out / "de" / "index.html").is_file()
    assert (out / "404.html").is_file()
    assert (out / "img" / "pixel.png").read_bytes() == (src / "img" / "pixel.png").read_bytes()
    assert (out / ".nojekyll").is_file()


def test_underscore_paths_never_reach_the_output(src: Path, tmp_path: Path) -> None:
    out = _build(src, tmp_path)
    leaked = [p for p in out.rglob("*") if any(x.startswith("_") for x in p.relative_to(out).parts)]
    assert not leaked
    assert "secret" not in "".join(p.read_text(errors="ignore") for p in out.rglob("*.html"))


def test_markdown_renders_tables_and_keeps_raw_html_and_utf8(src: Path, tmp_path: Path) -> None:
    html = (_build(src, tmp_path) / "en" / "docs" / "index.html").read_text(encoding="utf-8")
    assert "<h1>Änderungsprotokoll</h1>" in html
    assert "<table>" in html
    assert '<div class="note">raw HTML stays</div>' in html


def test_a_body_is_never_evaluated_as_jinja(src: Path, tmp_path: Path) -> None:
    html = (_build(src, tmp_path) / "en" / "index.html").read_text(encoding="utf-8")
    assert "{{ .Values.image.tag }} {% raw %}" in html


def test_a_page_without_front_matter_fails(src: Path, tmp_path: Path) -> None:
    (src / "en" / "bare.html").write_text("<p>no front matter</p>", encoding="utf-8")
    with pytest.raises(B.BuildError, match=r"en/bare\.html.*front matter"):
        _build(src, tmp_path)


def test_an_unknown_front_matter_key_fails(src: Path, tmp_path: Path) -> None:
    page = src / "en" / "index.html"
    page.write_text(page.read_text().replace("title:", "titel: typo\ntitle:", 1), encoding="utf-8")
    with pytest.raises(B.BuildError, match="titel"):
        _build(src, tmp_path)


def test_a_missing_required_key_fails(src: Path, tmp_path: Path) -> None:
    page = src / "en" / "index.html"
    text = page.read_text().replace("description: The English home of the fixture site.\n", "")
    page.write_text(text, encoding="utf-8")
    with pytest.raises(B.BuildError, match="description"):
        _build(src, tmp_path)


def test_two_sources_for_one_url_fail(src: Path, tmp_path: Path) -> None:
    (src / "en" / "docs.md").write_text(
        "---\ntitle: t\ndescription: d\ntranslation_key: dup\n---\nx\n", encoding="utf-8"
    )
    with pytest.raises(B.BuildError, match="/en/docs/"):
        _build(src, tmp_path)


def test_a_page_outside_a_language_directory_needs_lang(src: Path, tmp_path: Path) -> None:
    page = src / "404.html"
    page.write_text(page.read_text().replace("lang: en\n", ""), encoding="utf-8")
    with pytest.raises(B.BuildError, match="404.html.*language"):
        _build(src, tmp_path)


def test_main_reports_a_build_error_as_exit_1(
    src: Path, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    (src / "en" / "bare.html").write_text("<p>x</p>", encoding="utf-8")
    assert B.main(["--src", str(src), "--out", str(tmp_path / "out")]) == 1
    assert "build failed" in capsys.readouterr().err
