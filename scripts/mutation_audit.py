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
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def inside_root(name: str) -> bool:
    """True when a spec's `file` resolves under the repository: no absolute path, no `../`."""
    return (ROOT / name).resolve().is_relative_to(ROOT)


def main() -> int:
    spec = json.loads(Path(sys.argv[1]).read_text())
    only = set(sys.argv[2:])
    # A mutation that removes a timeout hangs its test; a spec can bound the wait.
    limit = spec.get("timeout_seconds", 900)
    green = 0
    for m in spec["mutations"]:
        if only and m["id"] not in only:
            continue
        if not inside_root(m["file"]):
            print(f"{m['id']:28} STALE  {m['file']} is outside the repository")
            green += 1
            continue
        path = ROOT / m["file"]
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
            run = subprocess.run(  # noqa: S603 — pytest on test paths from a repo file
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-x",
                    "-q",
                    "--no-cov",
                    "-p",
                    "no:cacheprovider",
                    *spec["test_groups"][m["tests"]],
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=limit,
            )
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
        verdict = "RED" if run.returncode else "GREEN"
        green += verdict == "GREEN"
        print(f"{m['id']:28} {verdict:6} {fired}", flush=True)
    return 1 if green else 0


if __name__ == "__main__":
    sys.exit(main())
