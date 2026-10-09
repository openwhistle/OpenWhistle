"""The workflows hold what zizmor checks, and every job has its own time limit.

Without a time limit GitHub allows six hours: on 2026-10-09 four E2E runs of one pull request sat
for an hour each while a module fixture rebuilt the site again and again.
"""

import re
from pathlib import Path

import yaml

WORKFLOWS = sorted((Path(__file__).parents[1] / ".github" / "workflows").glob("*.yml"))


def test_every_runner_job_has_a_timeout() -> None:
    # A job that calls a reusable workflow (`uses:`) takes no runner and no timeout-minutes.
    jobs = [
        (wf.name, name, job)
        for wf in WORKFLOWS
        for name, job in yaml.safe_load(wf.read_text())["jobs"].items()
        if "uses" not in job
    ]
    assert jobs, "no workflow job found: the check reaches nothing"
    missing = [f"{wf}:{name}" for wf, name, job in jobs if "timeout-minutes" not in job]
    assert not missing, f"jobs without timeout-minutes: {missing}"


def test_the_browser_tests_build_the_site_once() -> None:
    """A narrower scope rebuilds the site whenever pytest's parametrised order switches
    module: that turned a 19-minute E2E run into hours."""
    conftest = (Path(__file__).parent / "e2e" / "conftest.py").read_text()
    assert '@pytest.fixture(scope="session")\ndef docs_server_url(' in conftest


def _steps() -> list[tuple[str, dict]]:
    return [
        (f"{wf.name}:{name}", step)
        for wf in WORKFLOWS
        for name, job in yaml.safe_load(wf.read_text())["jobs"].items()
        for step in job.get("steps", [])
    ]


def test_no_checkout_leaves_its_token_on_disk() -> None:
    """zizmor artipacked: a persisted token in .git/config reaches every later step."""
    checkouts = [
        (where, s) for where, s in _steps() if s.get("uses", "").startswith("actions/checkout@")
    ]
    assert checkouts, "no checkout found: the check reaches nothing"
    kept = [
        where
        for where, s in checkouts
        if (s.get("with") or {}).get("persist-credentials") is not False
    ]
    assert not kept, f"checkouts that keep their credentials: {kept}"


def test_no_script_expands_event_text() -> None:
    """zizmor template-injection: `${{ github.event.* }}` inside `run:` is pasted into the
    script before the shell parses it; it reaches a script only through `env:`."""
    pasted = [where for where, s in _steps() if "${{ github.event." in s.get("run", "")]
    assert not pasted, f"run scripts that expand event data: {pasted}"


def test_no_called_workflow_inherits_every_secret() -> None:
    """zizmor secrets-inherit: a called workflow gets the secrets it names, not all of them."""
    inherit = [
        wf.name
        for wf in WORKFLOWS
        if re.search(r"^\s*secrets:\s*inherit\s*$", wf.read_text(), re.M)
    ]
    assert not inherit, f"workflows passing `secrets: inherit`: {inherit}"
