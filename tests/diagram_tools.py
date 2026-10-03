"""The two diagram scripts as importable modules, for tests (scripts/ is not a package)."""

from __future__ import annotations

import importlib.util
import sys
from functools import cache
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # @dataclass looks its module up here
    spec.loader.exec_module(module)
    return module


@cache
def geometry() -> ModuleType:
    return _load("diagram_geometry")


@cache
def renderer() -> ModuleType:
    geometry()  # render_diagrams imports it by name
    return _load("render_diagrams")
