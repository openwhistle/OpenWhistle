"""Guards on the GitHub workflows that no unit test would otherwise see."""

from pathlib import Path

WORKFLOWS = Path(__file__).parents[1] / ".github" / "workflows"


def test_self_hosted_workflows_never_run_on_pull_requests() -> None:
    """A self-hosted runner sits inside the intranet and this repo is public.

    Any `pull_request` / `pull_request_target` trigger in a workflow with a
    self-hosted job would run a fork's code on that runner. Matching the text,
    comments included, is deliberately strict.
    """
    offenders = [
        wf.name
        for wf in WORKFLOWS.glob("*.y*ml")
        if "self-hosted" in (text := wf.read_text()) and "pull_request" in text
    ]
    assert not offenders, f"self-hosted workflow triggered by pull requests: {offenders}"
