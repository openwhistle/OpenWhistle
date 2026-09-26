"""Mutation audit: break each guard, run the tests meant to catch it, restore.

    python scripts/mutation_audit.py docs-tech/mutations/v1.4.0.json [id ...]

Each mutation is an exact text replacement that must match once. A mutation
the tests do not notice (GREEN) is a place where the code can be broken
without a test failing; see docs-tech/release.md. Needs the test database
environment (DATABASE_URL, REDIS_URL, SECRET_KEY) that the suite needs.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    spec = json.loads(Path(sys.argv[1]).read_text())
    only = set(sys.argv[2:])
    green = 0
    for m in spec["mutations"]:
        if only and m["id"] not in only:
            continue
        path = ROOT / m["file"]
        original = path.read_text()
        if original.count(m["old"]) != 1:
            print(f"{m['id']:28} STALE  snippet matches {original.count(m['old'])}x in {m['file']}")
            green += 1
            continue
        path.write_text(original.replace(m["old"], m["new"]))
        try:
            run = subprocess.run(  # noqa: S603 — pytest on test paths from a repo file
                [sys.executable, "-m", "pytest", "-x", "-q", "--no-cov", "-p", "no:cacheprovider",
                 *spec["test_groups"][m["tests"]]],
                cwd=ROOT, capture_output=True, text=True, timeout=900,
            )
        except subprocess.TimeoutExpired:
            # A mutation that hangs the tests is caught: CI would time out too.
            print(f"{m['id']:28} RED    TIMEOUT after 900 s", flush=True)
            continue
        finally:
            path.write_text(original)
        fired = next((line.split(" - ")[0] for line in run.stdout.splitlines()
                      if line.startswith(("FAILED ", "ERROR tests"))), "")
        verdict = "RED" if run.returncode else "GREEN"
        green += verdict == "GREEN"
        print(f"{m['id']:28} {verdict:6} {fired}", flush=True)
    return 1 if green else 0


if __name__ == "__main__":
    sys.exit(main())
