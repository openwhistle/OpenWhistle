"""scripts/package_site.py: what nginx needs beside the built site."""

from __future__ import annotations

import gzip
import importlib.util
import sys
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


@pytest.mark.parametrize("bad", ['/x";', "/x\n", "relative"])
def test_a_path_nginx_could_misread_is_refused(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ValueError, match="redirect"):
        P.package(_site(tmp_path), {bad: "/en/"}, tmp_path / "redirects.map")


def test_the_real_redirects_all_reach_the_map(tmp_path: Path) -> None:
    import yaml

    redirects = yaml.safe_load((ROOT / "docs/_data/redirects.yml").read_text())
    out = tmp_path / "redirects.map"
    P.package(_site(tmp_path), redirects, out)
    assert len(out.read_text().splitlines()) == len(redirects)


def test_the_gz_bytes_do_not_depend_on_the_clock(tmp_path: Path) -> None:
    import time

    site = _site(tmp_path)
    # First package
    P.package(site, {}, tmp_path / "redirects.map")
    first_gz_bytes = (site / "en" / "index.html.gz").read_bytes()
    # Extract mtime field from gzip header (bytes 4-7)
    first_mtime = int.from_bytes(first_gz_bytes[4:8], "little")

    # Reset the .gz file and wait until next second
    (site / "en" / "index.html.gz").unlink()
    start = time.time()
    while time.time() - start < 2.0:
        time.sleep(0.01)

    # Second package with same content
    P.package(site, {}, tmp_path / "redirects.map")
    second_gz_bytes = (site / "en" / "index.html.gz").read_bytes()
    # Extract mtime field from gzip header (bytes 4-7)
    second_mtime = int.from_bytes(second_gz_bytes[4:8], "little")

    # Bytes must be identical, and mtime must be 0 (proving mtime=0 is used)
    assert first_gz_bytes == second_gz_bytes
    assert first_mtime == 0, f"Expected mtime=0, got {first_mtime}"
    assert second_mtime == 0, f"Expected mtime=0, got {second_mtime}"
