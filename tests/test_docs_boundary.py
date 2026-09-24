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
    uploads = re.findall(r"upload-pages-artifact@\S+\s+with:\s+path:\s*\"?([^\"\s]+)", workflow)
    assert uploads == ["docs"], f"pages.yml publishes {uploads}; only docs/ may be published"
