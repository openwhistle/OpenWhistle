"""Two documentations, one boundary: docs/ is published for whoever runs
OpenWhistle, docs-tech/ is for whoever maintains the repository and never is."""

import hashlib
import re
from pathlib import Path

import yaml

from tests.built_site import builder, built, page, pages

ROOT = Path(__file__).parents[1]


def test_the_technical_docs_are_not_published() -> None:
    tech = ROOT / "docs-tech"
    assert tech.is_dir() and any(tech.iterdir()), "docs-tech/ is missing or empty"

    for name in ("docs-tech", "technical", "internal"):
        assert not (ROOT / "docs" / name).exists(), (
            f"docs/{name} exists — everything under docs/ is published by pages.yml"
        )


_DOCS_TECH_HREF = re.compile(r'(?:href|src)=["\']([^"\']*docs-tech/[^"\']*)["\']')


def test_no_published_page_links_docs_tech() -> None:
    """docs-tech/ is never uploaded, so a relative link 404s; and a GitHub URL
    sends an operator to a maintainer page. Naming a docs-tech/ file in
    running text is fine, a link is not."""
    offenders = [
        f"{p.relative_to(built())}: {m.group(1)}"
        for p in pages()
        for m in _DOCS_TECH_HREF.finditer(p.read_text())
    ]
    assert not offenders, f"published page(s) link docs-tech/: {offenders}"


def test_the_public_roadmap_holds_no_test_chores() -> None:
    """Test infrastructure changes nothing a user sees; it is planned in
    docs-tech/test-infrastructure.md, not on the published roadmap."""
    roadmap = page("/en/roadmap/")
    assert not re.search(r"\btests/|\btest_\w+", roadmap)
    assert (ROOT / "docs-tech/test-infrastructure.md").exists()


def _pages_steps() -> list[dict]:
    workflow = yaml.safe_load((ROOT / ".github/workflows/pages.yml").read_text())
    return workflow["jobs"]["deploy"]["steps"]


def test_pages_publishes_the_built_site_and_nothing_else() -> None:
    steps = _pages_steps()
    uploads = [s for s in steps if "upload-pages-artifact" in s.get("uses", "")]
    assert [u["with"]["path"] for u in uploads] == ["_site"]
    build = next(s for s in steps if "build_site.py" in s.get("run", ""))
    assert "--src" not in build["run"], "the build must read docs/ and nothing else"
    assert "--redirect-stubs" in build["run"], "without the stubs every old URL 404s on Pages"


def test_pages_checks_out_the_full_history() -> None:
    """Shallow history makes every sitemap lastmod the deploy date, silently."""
    checkout = next(s for s in _pages_steps() if "actions/checkout" in s.get("uses", ""))
    assert checkout.get("with", {}).get("fetch-depth") == 0


def test_no_built_file_comes_from_docs_tech(tmp_path: Path) -> None:
    """Neither by name nor by content, in the plain build or the stubbed one."""
    tech_files = [p for p in (ROOT / "docs-tech").rglob("*") if p.is_file()]
    tech_names = {p.name for p in tech_files}
    # An empty file says nothing; it would only collide with the empty built .nojekyll.
    tech_hashes = {
        hashlib.sha256(p.read_bytes()).hexdigest() for p in tech_files if p.stat().st_size
    }

    stubbed = tmp_path / "stubbed"
    builder().build(ROOT / "docs", stubbed, redirect_stubs=True)

    leaked = sorted(
        str(p)
        for root in (built(), stubbed)
        for p in root.rglob("*")
        if p.is_file()
        and (
            (p.suffix == ".md" and p.name in tech_names)
            or hashlib.sha256(p.read_bytes()).hexdigest() in tech_hashes
        )
    )
    assert not leaked, leaked
