"""scripts/check_external_links.py: what it collects and how it judges a status (no network)."""

from __future__ import annotations

import http.client
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
import yaml

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


def test_an_ok_answer_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = iter([200])
    monkeypatch.setattr(C, "fetch", lambda _url: next(answers))
    monkeypatch.setattr(C.time, "sleep", lambda _s: pytest.fail("retried an ok link"))
    assert C.status_of("https://example.org/") == 200


@pytest.mark.parametrize(
    "error",
    [
        http.client.BadStatusLine("garbage"),
        http.client.InvalidURL("bad port"),
        http.client.RemoteDisconnected("closed"),
        ValueError("unknown url type"),
    ],
    ids=lambda e: type(e).__name__,
)
def test_a_bad_host_is_no_connection_not_a_crash(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], error: Exception
) -> None:
    def refuse(*_a: object, **_k: object) -> None:
        raise error

    monkeypatch.setattr(C.urllib.request, "urlopen", refuse)
    assert C.fetch("https://example.org/") is None
    # The reason reaches the log: a timeout and a refused connection need different fixes.
    assert f"https://example.org/: {type(error).__name__}" in capsys.readouterr().err


@pytest.mark.parametrize(("dead", "code"), [(set(), 0), ({"https://example.org/b"}, 1)])
def test_main_fails_exactly_when_a_link_is_broken(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], dead: set[str], code: int
) -> None:
    def build(_src: Path, out: Path) -> None:
        out.mkdir(parents=True)
        (out / "index.html").write_text(
            '<a href="https://example.org/a">a</a><a href="https://example.org/b">b</a>'
        )

    monkeypatch.setattr(C.build_site, "build", build)
    monkeypatch.setattr(C, "status_of", lambda url: 404 if url in dead else 200)
    assert C.main() == code
    assert f"2 external links, {len(dead)} broken" in capsys.readouterr().out


def test_the_workflow_check_step_keeps_the_scripts_exit_status() -> None:
    """Without `shell: bash` a step runs `bash -e` with no pipefail: a pipe would hide a failure."""
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "links.yml").read_text())
    (check,) = [s for s in workflow["jobs"]["links"]["steps"] if s.get("id") == "check"]
    assert "scripts/check_external_links.py" in check["run"]
    assert "|" not in check["run"] or check.get("shell") == "bash", check
    assert check["continue-on-error"] is True


def test_only_the_scheduled_issue_job_can_write_issues() -> None:
    """PR and dispatch runs get a read-only token, and checkout keeps none in .git/config."""
    jobs = yaml.safe_load((ROOT / ".github" / "workflows" / "links.yml").read_text())["jobs"]
    writers = {name for name, job in jobs.items() if job["permissions"].get("issues") == "write"}
    assert writers == {"issue"}, writers
    assert jobs["issue"]["needs"] == "links"
    assert "github.event_name == 'schedule'" in jobs["issue"]["if"]
    assert "steps" in jobs["issue"] and all("uses" not in s for s in jobs["issue"]["steps"])
    for name, job in jobs.items():
        for step in job["steps"]:
            if step.get("uses", "").startswith("actions/checkout@"):
                assert step["with"]["persist-credentials"] is False, name
