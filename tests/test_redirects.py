"""Every URL the site served on 2026-10-01 still reaches a page (spec: every old URL gets a 301)."""

from pathlib import Path

import pytest
import yaml

from tests.built_site import built

ROOT = Path(__file__).parents[1]
OLD = (ROOT / "tests/data/sitemap-2026-10-01.txt").read_text().split()
REDIRECTS = yaml.safe_load((ROOT / "docs/_data/redirects.yml").read_text())


def _served(url: str) -> bool:
    path = built() / url.lstrip("/")
    return (path / "index.html").is_file() if url.endswith("/") else path.is_file()


@pytest.mark.parametrize("url", OLD)
def test_every_old_url_reaches_a_page(url: str) -> None:
    if url in {"/", "/index.html"}:
        return  # the language choice: nginx negotiates it
    target = REDIRECTS.get(url, url)
    assert _served(target), f"{url} -> {target} serves nothing; add it to docs/_data/redirects.yml"


def test_the_old_list_is_complete() -> None:
    assert len(OLD) == 28
