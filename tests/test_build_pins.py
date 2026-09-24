"""Build tool pins that live in several files must agree."""

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_uv_version_is_the_same_in_the_image_and_every_workflow() -> None:
    image = re.search(r"ghcr\.io/astral-sh/uv:([0-9.]+)", (ROOT / "Dockerfile").read_text())
    assert image, "Dockerfile no longer copies uv from ghcr.io/astral-sh/uv"
    pins = {
        wf.name: re.findall(r"uv==([0-9.]+)", wf.read_text())
        for wf in (ROOT / ".github" / "workflows").glob("*.yml")
    }
    stale = {name: found for name, found in pins.items() if set(found) - {image.group(1)}}
    assert not stale, f"uv pins differ from the Dockerfile's {image.group(1)}: {stale}"
    assert any(pins.values()), "no workflow pins uv — the check reaches nothing"


def _all(pattern: str, *globs: str) -> set[str]:
    return {
        m for g in globs for f in ROOT.glob(g) for m in re.findall(pattern, f.read_text())
    }


def test_python_version_is_the_same_everywhere() -> None:
    found = _all(r"python:(\d+\.\d+)-alpine", "Dockerfile")
    found |= _all(r'python-version: "(\d+\.\d+)"', ".github/workflows/*.yml")
    found |= _all(r'requires-python = ">=(\d+\.\d+)"', "pyproject.toml")
    assert len(found) == 1, f"Python versions disagree: {found}"


def test_postgres_and_redis_majors_are_the_same_everywhere() -> None:
    places = ("docker-compose*.yml", ".github/workflows/*.yml",
              "ansible/roles/openwhistle/templates/*.j2")
    for image in ("postgres", "redis"):
        found = _all(rf"image: {image}:([0-9a-z.\-]+)", *places)
        assert len(found) == 1, f"{image} tags disagree: {found}"
