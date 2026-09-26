"""Two documentations, one boundary: docs/ is published for whoever runs
OpenWhistle, docs-tech/ is for whoever maintains the repository and never is."""

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_the_technical_docs_are_not_published() -> None:
    tech = ROOT / "docs-tech"
    assert tech.is_dir() and any(tech.iterdir()), "docs-tech/ is missing or empty"

    for name in ("docs-tech", "technical", "internal"):
        assert not (ROOT / "docs" / name).exists(), (
            f"docs/{name} exists — everything under docs/ is published by pages.yml"
        )

    # The Pages build uploads exactly docs/. Any other path, or a second
    # upload, is a change of scope that has to be noticed here.
    workflow = (ROOT / ".github/workflows/pages.yml").read_text()
    upload = r"upload-pages-artifact@\S+(?:[ \t]+#[^\n]*)?\s+with:\s+path:\s*\"?([^\"\s]+)"
    uploads = re.findall(upload, workflow)
    assert uploads == ["docs"], f"pages.yml publishes {uploads}; only docs/ may be published"


_DOCS_TECH_HREF = re.compile(r'(?:href|src)=["\']([^"\']*docs-tech/[^"\']*)["\']')


def test_no_published_page_links_docs_tech() -> None:
    """A *relative* link into docs-tech/ from a published page 404s once the
    site ships (docs-tech/ is never uploaded — see the test above). Naming a
    docs-tech/ file in running text (a citation, a `<code>` mention), or a
    full URL to it on GitHub, is fine — only a same-site href/src is not."""
    offenders = []
    for p in (ROOT / "docs").rglob("*.html"):
        for m in _DOCS_TECH_HREF.finditer(p.read_text()):
            if not m.group(1).startswith(("http://", "https://")):
                offenders.append(f"{p.relative_to(ROOT)}: {m.group(1)}")
    assert not offenders, f"published page(s) link docs-tech/ relatively: {offenders}"
