"""Fail a CI run in which a test skipped: it never runs there.

A pytest plugin of its own so a test can load it into a throwaway pytest session
(`-p tests.ci_skip_guard`); conftest.py re-exports the hooks.
"""

from __future__ import annotations

import os

import pytest

# A test that skips on every CI run is a test that does not exist. Nine did: the
# wizard and admin-page tests skipped whenever setup was already done, which in
# the shared database was always, and CI printed only "12 skipped".
_SKIPS_ALLOWED_IN_CI = (
    "OW_PRIVATE_STRINGS is not set",  # the operator's data is not in CI
    # Ubuntu's libldap is GnuTLS-backed and refuses TLS 1.1 itself; the image's
    # (Alpine, OpenSSL) does not, and the test runs where libldap uses OpenSSL.
    "libldap's TLS backend refuses TLS 1.1 by itself",
)
_ci_skips: list[str] = []


def _note_skip(nodeid: str, report: pytest.TestReport | pytest.CollectReport) -> None:
    if report.skipped and isinstance(report.longrepr, tuple):
        reason = str(report.longrepr[2])
        if not any(allowed in reason for allowed in _SKIPS_ALLOWED_IN_CI):
            _ci_skips.append(f"{nodeid}: {reason}")


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    _note_skip(report.nodeid, report)


def pytest_collectreport(report: pytest.CollectReport) -> None:
    # A module-level skip (pytest.skip(allow_module_level=True), importorskip) is a
    # CollectReport: no test of the module ever produces a runtest report, so the hook
    # above never saw it and CI stayed green with the whole module not running.
    _note_skip(report.nodeid, report)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if os.environ.get("CI") == "true" and _ci_skips and exitstatus == 0:
        print("\nTests skipped in CI (they never run there):\n  " + "\n  ".join(_ci_skips))
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
