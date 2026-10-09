"""The website lives in openwhistle/website: no site file and no reader of one is left here.

A half-moved site would build nothing and test nothing while looking present (spec
2026-10-09-website-repo-split-design.md, "Guards"). URLs into openwhistle.net/en/docs/
are links, not readers, and stay allowed.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# A path into docs/: "docs" after `/`, `(` or `,` (ROOT / "docs", Path("docs"), .joinpath("docs"),
# os.path.join(ROOT, "docs")), "docs" before `/`, or a literal starting with docs/.
# docs-tech/ is this repository's own.
READS_DOCS = re.compile(r"""[/(,]\s*["']docs["']|["']docs["']\s*/|["']docs/""")


def test_the_reader_scan_sees_a_docs_path_and_passes_a_link() -> None:
    for reader in (
        'ROOT / "docs"',
        "parents[1] / 'docs'",
        '"docs/en/index.html"',
        'Path("docs")',
        'ROOT.joinpath("docs")',
        'os.path.join(ROOT, "docs")',
        '"docs" / "en"',
    ):
        assert READS_DOCS.search(reader), reader
    for other in ('"docs-tech/release.md"', '"https://openwhistle.net/en/docs/install/"'):
        assert not READS_DOCS.search(other), other


def test_no_website_file_or_reader_is_left() -> None:
    site = [d for d in ("docs", "website") if (ROOT / d).exists()]
    assert not site, site
    tests = list((ROOT / "tests").rglob("*.py"))
    assert len(tests) > 100, "the test walk found almost nothing: the check reaches nothing"
    readers = [
        path.relative_to(ROOT).as_posix()
        for path in tests
        if path.name != "test_repository_split.py"
        and READS_DOCS.search(path.read_text(encoding="utf-8"))
    ]
    assert not readers, readers
