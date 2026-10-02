"""Every URL the site served on 2026-10-01 still reaches a page (spec: every old URL gets a 301)."""

import hashlib
from pathlib import Path

import pytest
import yaml

from tests.built_site import builder, built

ROOT = Path(__file__).parents[1]
OLD = (ROOT / "tests/data/sitemap-2026-10-01.txt").read_text().split()
REDIRECTS = yaml.safe_load((ROOT / "docs/_data/redirects.yml").read_text())

# sha256 of `git show main:docs/<file>` before the port; a hash, because CI checks out one
# commit and has no `main` to show.
# Until P4's nginx 301s them, GitHub Pages serves these old URLs byte for byte as they were.
OLD_MARKDOWN = {
    "/hinschg_reference.md":
        "9396abe9c4e3c104a25a8098cb0624f8cd2dcf2cdd5d6168e5933ed6bab0e7c0",
    "/security/security_policy.md":
        "3913550b5092f63bf83bbac9b7ac3be29b913cee0480acda4f599672d8836dea",
    "/security/dpa_template.md":
        "0458f2bb9e482330e8083bba9b504f0780ee2b353ca39842f810c072198c7943",
}


def _served(url: str) -> bool:
    path = built() / url.lstrip("/")
    return (path / "index.html").is_file() if url.endswith("/") else path.is_file()


@pytest.mark.parametrize("url", OLD)
def test_every_old_url_reaches_a_page(url: str) -> None:
    if url in {"/", "/index.html"}:
        return  # the language choice: a stub on Pages (Task 8 tests it), nginx from P4 on
    target = REDIRECTS.get(url, url)
    assert _served(target), f"{url} -> {target} serves nothing; add it to docs/_data/redirects.yml"


@pytest.fixture(scope="module")
def pages_site(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The build GitHub Pages deploys: pages plus a stub or passthrough file per old URL."""
    out = tmp_path_factory.mktemp("pages") / "site"
    builder().build(ROOT / "docs", out, redirect_stubs=True)
    return out


@pytest.mark.parametrize("url", OLD)
def test_github_pages_serves_every_old_url(pages_site: Path, url: str) -> None:
    served = builder().output_file(pages_site, url) if url.endswith(("/", ".html")) else (
        pages_site / url.lstrip("/")
    )
    assert served.is_file(), f"GitHub Pages would answer {url} with a 404"


@pytest.mark.parametrize("url", sorted(OLD_MARKDOWN))
def test_an_old_markdown_url_serves_its_text_unchanged(pages_site: Path, url: str) -> None:
    served = (pages_site / url.lstrip("/")).read_bytes()
    assert hashlib.sha256(served).hexdigest() == OLD_MARKDOWN[url], (
        f"{url} no longer serves the text it served on 2026-10-01"
    )


def test_the_old_list_is_complete() -> None:
    assert len(OLD) == 28
