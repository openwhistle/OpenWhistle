"""scripts/package_site.py: what nginx needs beside the built site."""

from __future__ import annotations

import gzip
import importlib.util
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("package_site", ROOT / "scripts" / "package_site.py")
assert spec and spec.loader
P = importlib.util.module_from_spec(spec)
sys.modules["package_site"] = P
spec.loader.exec_module(P)


def _site(tmp_path: Path) -> Path:
    site = tmp_path / "site"
    (site / "en").mkdir(parents=True)
    (site / "en" / "index.html").write_text("<p>hello</p>" * 50)
    (site / "app.css").write_text("body{}")
    (site / "og.png").write_bytes(b"\x89PNG")
    (site / "pagefind").mkdir()
    (site / "pagefind" / "x.pf_meta").write_bytes(b"\x00")
    return site


def test_every_text_file_gets_an_identical_gz(tmp_path: Path) -> None:
    site = _site(tmp_path)
    P.package(site, {}, tmp_path / "redirects.map")
    for name in ("en/index.html", "app.css"):
        original = (site / name).read_bytes()
        assert gzip.decompress((site / f"{name}.gz").read_bytes()) == original, name


def test_binary_files_get_no_gz(tmp_path: Path) -> None:
    site = _site(tmp_path)
    P.package(site, {}, tmp_path / "redirects.map")
    assert not (site / "og.png.gz").exists()
    assert not (site / "pagefind" / "x.pf_meta.gz").exists()


def test_a_second_run_writes_no_gz_of_a_gz(tmp_path: Path) -> None:
    site = _site(tmp_path)
    P.package(site, {}, tmp_path / "redirects.map")
    P.package(site, {}, tmp_path / "redirects.map")
    assert not list(site.rglob("*.gz.gz"))


def test_the_map_has_one_quoted_line_per_redirect(tmp_path: Path) -> None:
    out = tmp_path / "redirects.map"
    P.package(_site(tmp_path), {"/blog/": "/de/blog/", "/a b.html": "/en/"}, out)
    assert out.read_text().splitlines() == ['"/a b.html" "/en/";', '"/blog/" "/de/blog/";']


@pytest.mark.parametrize(
    "bad,side",
    [
        ('/x";', "old"),
        ("/x\n", "old"),
        ("relative", "old"),
        ("/x$y", "old"),
        ("/x$y", "new"),
    ],
)
def test_a_path_nginx_could_misread_is_refused(tmp_path: Path, bad: str, side: str) -> None:
    with pytest.raises(ValueError, match="redirect"):
        redirects = {bad: "/en/"} if side == "old" else {"/en/": bad}
        P.package(_site(tmp_path), redirects, tmp_path / "redirects.map")


def test_the_real_redirects_all_reach_the_map(tmp_path: Path) -> None:
    import yaml

    redirects = yaml.safe_load((ROOT / "docs/_data/redirects.yml").read_text())
    out = tmp_path / "redirects.map"
    P.package(_site(tmp_path), redirects, out)
    assert len(out.read_text().splitlines()) == len(redirects)


def test_the_gz_bytes_do_not_depend_on_the_clock(tmp_path: Path) -> None:
    site = _site(tmp_path)
    P.package(site, {}, tmp_path / "redirects.map")
    first_gz_bytes = (site / "en" / "index.html.gz").read_bytes()
    time.sleep(1.1)
    P.package(site, {}, tmp_path / "redirects.map")
    second_gz_bytes = (site / "en" / "index.html.gz").read_bytes()
    assert first_gz_bytes == second_gz_bytes


def test_non_string_redirect_key_raises_valueerror(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="redirect"):
        P.package(_site(tmp_path), {123: "/en/"}, tmp_path / "redirects.map")


def test_non_string_redirect_value_raises_valueerror(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="redirect"):
        P.package(_site(tmp_path), {"/old": 456}, tmp_path / "redirects.map")


def test_main_refuses_wrong_argument_count(tmp_path: Path) -> None:
    assert P.main([]) == 2
    assert P.main([str(tmp_path)]) == 2
    assert P.main([str(tmp_path), str(tmp_path / "map"), "extra"]) == 2
