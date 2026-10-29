#!/usr/bin/env python3
"""Generate the file-integrity manifest of the shipped trees (``app/``, ``migrations/``,
``scripts/``).

Run at Docker build time over the exact shipped bytes:

    python -B scripts/generate_integrity_manifest.py

Thin wrapper around ``app.services.integrity.build_file_index`` so the build and
the runtime verifier share one walk/hash implementation (they must never
diverge). Writes ``integrity-manifest.json`` at the repo/image root and prints its
SHA-256: run in a checkout of a release tag, it prints the hash the image's System
page shows. The manifest holds no build time, so the same files give the same hash.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

# Ensure the repo root is importable when invoked as a script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.integrity import (  # noqa: E402
    APP_ROOT,
    DEFAULT_MANIFEST_PATH,
    SHIPPED_ROOTS,
    build_file_index,
)


def _app_version() -> str:
    """Read app_version from the config source.

    Parsed from text rather than imported: importing app.config would run the
    module-level ``settings = Settings()``, which requires SECRET_KEY (>=32) —
    not available during a plain image build.
    """
    import re

    try:
        source = (APP_ROOT / "config.py").read_text(encoding="utf-8")
    except OSError:
        return "unknown"
    match = re.search(r'app_version:\s*str\s*=\s*"([^"]+)"', source)
    return match.group(1) if match else "unknown"


def main() -> None:
    index = build_file_index(SHIPPED_ROOTS)
    manifest = {
        "version": _app_version(),
        "algorithm": "sha256",
        "files": index,
    }
    body = json.dumps(manifest, indent=2, sort_keys=True).encode()
    DEFAULT_MANIFEST_PATH.write_bytes(body)
    sha = hashlib.sha256(body).hexdigest()
    print(f"Wrote {DEFAULT_MANIFEST_PATH} ({len(index)} files), SHA-256 {sha}")


if __name__ == "__main__":
    main()
