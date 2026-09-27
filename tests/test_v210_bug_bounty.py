"""Regression tests for the v2.1.0 bug bounty.

Each test reproduces a defect that looked right while reading: it fails on the
code as it was and passes on the fix.
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _dockerfile_cmd() -> list[str]:
    for line in (ROOT / "Dockerfile").read_text().splitlines():
        if line.startswith("CMD "):
            return list(json.loads(line[4:]))
    raise AssertionError("Dockerfile has no CMD")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_the_image_command_writes_no_request_line() -> None:
    """The shipped CMD, run for real: a request leaves no trace in stdout.

    ``--no-access-log`` only empties uvicorn's access handlers; importing the
    app then gave them a handler back, so every path and query string was
    logged, the setup token included.
    """
    port = _free_port()
    cmd = _dockerfile_cmd()
    cmd[cmd.index("--host") + 1] = "127.0.0.1"
    cmd[cmd.index("--port") + 1] = str(port)
    proc = subprocess.Popen(  # noqa: S603 - the Dockerfile's own command
        cmd,
        cwd=ROOT,
        env=os.environ.copy(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        base = f"http://127.0.0.1:{port}"
        for _ in range(120):
            try:
                urllib.request.urlopen(f"{base}/health", timeout=1)  # noqa: S310
                break
            except OSError:
                time.sleep(0.25)
        else:
            raise AssertionError("app did not start")
        try:
            urllib.request.urlopen(f"{base}/setup?token=PROBE-SECRET-TOKEN", timeout=5)  # noqa: S310
        except OSError:
            pass  # the status code is irrelevant; the log line is what is measured
    finally:
        proc.terminate()
        output, _ = proc.communicate(timeout=20)
    assert "PROBE-SECRET-TOKEN" not in output
    assert not re.search(r'"GET /health', output), output[-2000:]
