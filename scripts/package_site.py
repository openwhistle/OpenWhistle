#!/usr/bin/env python3
"""What nginx needs beside the built site (docs-tech/specs/2026-10-09-website-p4-design.md).

    python scripts/package_site.py SITE_DIR MAP_OUT

Writes a .gz beside every text file for gzip_static, and MAP_OUT, the body of
nginx's `map $uri $moved` from docs/_data/redirects.yml.
"""

from __future__ import annotations

import gzip
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".html", ".css", ".js", ".svg", ".xml", ".txt", ".json"}
# A path nginx reads back exactly: absolute, no quote, no backslash, no $, no control character.
_SAFE = re.compile(r'/[^"\\$\x00-\x1f\x7f]*')


def package(site: Path, redirects: dict[str, str], map_out: Path) -> None:
    for path in sorted(site.rglob("*")):
        if path.is_file() and path.suffix in TEXT_SUFFIXES:
            # mtime=0: the same site gives the same bytes, so the image layer is reproducible.
            path.with_name(path.name + ".gz").write_bytes(
                gzip.compress(path.read_bytes(), compresslevel=9, mtime=0)
            )
    lines = []
    for old, new in sorted(redirects.items()):
        if not isinstance(old, str) or not isinstance(new, str):
            raise ValueError(f"redirect keys and values must be strings, got {old!r} -> {new!r}")
        for part in (old, new):
            if not _SAFE.fullmatch(part):
                raise ValueError(f"redirect {old!r} -> {new!r}: {part!r} is no plain absolute path")
        lines.append(f'"{old}" "{new}";')
    map_out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python scripts/package_site.py SITE_DIR MAP_OUT", file=sys.stderr)
        return 2
    site, map_out = Path(argv[0]), Path(argv[1])
    redirects = yaml.safe_load((ROOT / "docs" / "_data" / "redirects.yml").read_text())
    package(site, redirects, map_out)
    print(f"packaged {site}: {len(redirects)} redirects -> {map_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
