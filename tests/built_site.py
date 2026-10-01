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
    return builder().output_file(built(), url).read_text(encoding="utf-8")


def pages() -> list[Path]:
    return sorted(built().rglob("*.html"))


def source(url: str) -> Path:
    return _build()[1][url]


def css_of(html: str) -> str:
    inline = re.findall(r"<style[^>]*>(.*?)</style>", html, re.S)
    linked = [
        (built() / href.lstrip("/")).read_text(encoding="utf-8")
        for href in re.findall(r'<link rel="stylesheet" href="(/assets/css/[^"]+)"', html)
    ]
    return "\n".join(inline + linked)
