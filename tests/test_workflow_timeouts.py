"""Every job that takes a runner has its own time limit.

Without one GitHub allows six hours: on 2026-10-09 four E2E runs of one pull request sat
for an hour each while a module fixture rebuilt the site again and again.
"""

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
