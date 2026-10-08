"""The AI disclosure: what AGENTS.md and the templates ask for is what the workflow labels.

Issue #120 and PR #121 (2026-10-04) were written by bots and said nothing about it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
WORKFLOW = (ROOT / ".github/workflows/ai-disclosure.yml").read_text()
ASKING = [
    "AGENTS.md",
    "CONTRIBUTING.md",
    ".github/pull_request_template.md",
    ".github/ISSUE_TEMPLATE/bug_report.md",
    ".github/ISSUE_TEMPLATE/feature_request.md",
]


def _pattern() -> re.Pattern[str]:
    found = re.search(r"grep -Pzq '([^']+)'", WORKFLOW)
    assert found, "the workflow no longer matches with grep -Pzq '<pattern>'"
    return re.compile(found.group(1))


def _marker(text: str) -> str:
    """The two-line disclosure as a file shows it, indentation stripped."""
    lines = [line.strip() for line in text.splitlines()]
    start = lines.index("> [!WARNING]")
    return "\n".join(lines[start : start + 2])


@pytest.mark.parametrize("path", ASKING)
def test_every_place_asks_for_what_the_workflow_detects(path: str) -> None:
    assert _pattern().search(_marker((ROOT / path).read_text())), path


def test_the_templates_hide_the_request_in_a_comment() -> None:
    for path in ASKING[2:]:
        text = (ROOT / path).read_text()
        comment = re.search(r"<!--(.*?)-->", text, re.S)
        assert comment and "AI-generated" in comment.group(1), path
        assert "AI-generated" not in text.replace(comment.group(0), ""), path


def test_ordinary_text_is_not_labelled() -> None:
    for text in ("Fixes #1.", "> [!WARNING]\n> Breaking change", "This is not AI-generated."):
        assert not _pattern().search(text), text


def test_the_workflow_never_checks_out_or_interpolates_the_text() -> None:
    assert "actions/checkout" not in WORKFLOW
    run = WORKFLOW.split("run: |", 1)[1]
    assert "${{" not in run, "event text must reach the shell only through env"


def test_the_match_is_not_the_end_of_a_pipe() -> None:
    """Under pipefail (`shell: bash`), grep -q quitting early fails a pipe's writer."""
    assert not re.search(r"\|\s*grep\b", WORKFLOW)
