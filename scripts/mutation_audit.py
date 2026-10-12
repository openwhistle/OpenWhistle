"""Mutation audit: break each guard, run the tests meant to catch it, restore.

    python scripts/mutation_audit.py docs-tech/mutations/v1.4.0.json [id ...]

Each mutation is an exact text replacement that must match once, or, with
"create", a file that must not exist yet (a guard against an extra file). A mutation
the tests do not notice (GREEN) is a place where the code can be broken
without a test failing; see docs-tech/release.md. Needs the test database
environment (DATABASE_URL, REDIS_URL, SECRET_KEY) that the suite needs.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def inside_root(name: str) -> bool:
    """True when a spec's `file` resolves under the repository: no absolute path, no `../`."""
    return (ROOT / name).resolve().is_relative_to(ROOT)


def pytest(tests: list[str], limit: int) -> subprocess.CompletedProcess[str]:
    """One pytest run with a fresh bytecode cache.

    Python trusts a .pyc whose source has the same size and mtime second, so a same-length
    mutation written within a second of the last one ran the last one's code (out-inside-src
    was GREEN that way).
    """
    pycache = tempfile.mkdtemp(prefix="mutation-pyc-")
    try:
        return subprocess.run(  # noqa: S603 — pytest on test paths from a repo file
            [
                sys.executable,
                "-m",
                "pytest",
                "-x",
                "-q",
                "--no-cov",
                "-p",
                "no:cacheprovider",
                *tests,
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=limit,
            env={**os.environ, "PYTHONPYCACHEPREFIX": pycache},
        )
    finally:
        shutil.rmtree(pycache, ignore_errors=True)


def baseline_fails(spec: dict, only: set[str], limit: int) -> bool:  # type: ignore[type-arg]
    """Run each test group the audit uses once, unmutated: it must be GREEN.

    Without a database or SECRET_KEY every run errors out, exits nonzero and every mutation
    reads RED: the audit then reports "all caught" having judged nothing.
    """
    groups = sorted({m["tests"] for m in spec["mutations"] if not only or m["id"] in only})
    failed = False
    for group in groups:
        run = pytest(spec["test_groups"][group], limit)
        if run.returncode != 0:
            failed = True
            tail = "\n".join(run.stdout.splitlines()[-8:])
            print(f"BASELINE {group}: unmutated tests exit {run.returncode}, not 0\n{tail}")
    return failed


def main() -> int:
    spec = json.loads(Path(sys.argv[1]).read_text())
    only = set(sys.argv[2:])
    # A mutation that removes a timeout hangs its test; a spec can bound the wait.
    limit = spec.get("timeout_seconds", 900)
    if baseline_fails(spec, only, limit):
        print("The unmutated tests are not green: fix the environment (DATABASE_URL, REDIS_URL,")
        print("SECRET_KEY) first; every verdict below would be meaningless. Nothing was mutated.")
        return 2
    green = 0
    for m in spec["mutations"]:
        if only and m["id"] not in only:
            continue
        if not inside_root(m["file"]):
            print(f"{m['id']:28} STALE  {m['file']} is outside the repository")
            green += 1
            continue
        path = ROOT / m["file"]
        if "create" not in m and not path.is_file():
            # A guard whose file is gone guards nothing; the rest of the spec still runs.
            print(f"{m['id']:28} STALE  {m['file']} does not exist")
            green += 1
            continue
        original = None if "create" in m else path.read_text()
        if original is None and path.exists():
            print(f"{m['id']:28} STALE  {m['file']} already exists")
            green += 1
            continue
        if original is not None and original.count(m["old"]) != 1:
            print(f"{m['id']:28} STALE  snippet matches {original.count(m['old'])}x in {m['file']}")
            green += 1
            continue
        made = []  # directories this mutation creates; removed again with the file
        if original is None:
            made = [p for p in reversed(path.parents) if not p.exists() and p != ROOT]
            path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(m["create"] if original is None else original.replace(m["old"], m["new"]))
        try:
            run = pytest(spec["test_groups"][m["tests"]], limit)
        except subprocess.TimeoutExpired:
            # A mutation that hangs the tests is caught: CI would time out too.
            print(f"{m['id']:28} RED    TIMEOUT after {limit} s", flush=True)
            continue
        finally:
            if original is None:
                path.unlink()
                for directory in reversed(made):
                    directory.rmdir()
            else:
                path.write_text(original)
        fired = next(
            (
                line.split(" - ")[0]
                for line in run.stdout.splitlines()
                if line.startswith(("FAILED ", "ERROR tests"))
            ),
            "",
        )
        # Only exit 1 (a test failed) is a catch. 2 (interrupted / collection error), 3, 4 (a
        # test path that does not exist) and 5 (no test selected) mean no test judged the
        # mutation; an environment error used to read RED.
        verdict = {0: "GREEN", 1: "RED"}.get(run.returncode, "STALE")
        if verdict == "STALE":
            fired = f"pytest exit {run.returncode}: no test ran"
        green += verdict != "RED"
        print(f"{m['id']:28} {verdict:6} {fired}", flush=True)
    return 1 if green else 0


if __name__ == "__main__":
    sys.exit(main())
