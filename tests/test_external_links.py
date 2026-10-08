"""scripts/check_external_links.py: what it collects and how it judges a status (no network)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).parents[1]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "check_external_links", ROOT / "scripts" / "check_external_links.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


C = _load()


def test_collect_keeps_external_http_links_once_with_their_pages(tmp_path: Path) -> None:
    (tmp_path / "en").mkdir()
    (tmp_path / "en" / "index.html").write_text(
        '<a href="https://example.org/a#one">a</a> <a href="https://example.org/a#two">a</a>'
        '<a href="https://openwhistle.net/en/">own</a> <a href="/en/docs/">internal</a>'
        '<a href="mailto:x@example.org">mail</a> <img src="http://example.net/i.png" alt="">',
        encoding="utf-8",
    )
    (tmp_path / "404.html").write_text('<a href="https://example.org/a">a</a>', encoding="utf-8")
    assert C.collect(tmp_path, "openwhistle.net") == {
        "https://example.org/a": ["/404.html", "/en/index.html"],
        "http://example.net/i.png": ["/en/index.html"],
    }


def test_the_site_host_is_the_configured_one() -> None:
    assert C.HOST == "openwhistle.net"


@pytest.mark.parametrize(
    ("status", "verdict"),
    [
        (200, "ok"),
        (301, "ok"),
        (None, "broken"),
        (404, "broken"),
        (410, "broken"),
        (500, "broken"),
        (503, "broken"),
        (401, "unverifiable"),
        (403, "unverifiable"),
        (429, "unverifiable"),
    ],
)
def test_classify(status: int | None, verdict: str) -> None:
    assert C.classify(status) == verdict


def test_a_failure_is_retried_once(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = iter([None, 200])
    monkeypatch.setattr(C, "fetch", lambda _url: next(answers))
    monkeypatch.setattr(C.time, "sleep", lambda _s: None)
    assert C.status_of("https://example.org/") == 200
