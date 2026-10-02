"""The built openwhistle.net, for tests: docs/ is sources, the site is what ships.

Built once per test session into a temporary directory (no redirect stubs: a
stub is not a page). The build is plain Python and takes well under a second.
"""

from __future__ import annotations

import atexit
import importlib.util
import re
import shutil
import sys
import tempfile
from functools import cache
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]


@cache
def builder() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_site", ROOT / "scripts" / "build_site.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # @dataclass looks its module up here
    spec.loader.exec_module(module)
    return module


@cache
def _build() -> tuple[Path, dict[str, Path]]:
    tmp = Path(tempfile.mkdtemp(prefix="ow-site-"))
    atexit.register(shutil.rmtree, tmp, True)
    out = tmp / "site"
    built_pages = builder().build(ROOT / "docs", out)
    return out, {p.url: ROOT / "docs" / p.source for p in built_pages}


def built() -> Path:
    return _build()[0]


def page(url: str) -> str:
    return Path(builder().output_file(built(), url)).read_text(encoding="utf-8")


def pages() -> list[Path]:
    found = sorted(built().rglob("*.html"))
    # The 23 pages ported in P1: fewer means the build moved, not that the site shrank.
    assert len(found) >= 23, f"only {len(found)} built pages: {found}"
    return found


def source(url: str) -> Path:
    return _build()[1][url]


def stylesheets(html: str) -> list[Path]:
    """Every stylesheet the page links, as a built file. A link this cannot read fails."""
    tags = [t for t in re.findall(r"<link\b[^>]*>", html) if re.search(r'rel="stylesheet"', t)]
    sheets = []
    for tag in tags:
        m = re.fullmatch(r'<link rel="stylesheet" href="(/assets/css/[^"]+)">', tag)
        assert m, f"stylesheet link not of the form /assets/css/...: {tag}"
        sheets.append(built() / m.group(1).lstrip("/"))
    return sheets


def css_of(html: str) -> str:
    inline = re.findall(r"<style[^>]*>(.*?)</style>", html, re.S)
    linked = [sheet.read_text(encoding="utf-8") for sheet in stylesheets(html)]
    return "\n".join(inline + linked)
