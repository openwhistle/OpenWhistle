#!/usr/bin/env python3
"""Generate the file-integrity manifest for the ``app/`` package.

Run at Docker build time over the exact shipped bytes:

    python -B scripts/generate_integrity_manifest.py

Thin wrapper around ``app.services.integrity.build_file_index`` so the build and
the runtime verifier share one walk/hash implementation (they must never
diverge). Writes ``integrity-manifest.json`` at the repo/image root.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

# Ensure the repo root is importable when invoked as a script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.integrity import (  # noqa: E402
    APP_ROOT,
    DEFAULT_MANIFEST_PATH,
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
    index = build_file_index(APP_ROOT)
    manifest = {
        "generated_at": datetime.now(UTC).isoformat(),
        "version": _app_version(),
        "algorithm": "sha256",
        "files": index,
    }
    DEFAULT_MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(f"Wrote {DEFAULT_MANIFEST_PATH} ({len(index)} files)")


if __name__ == "__main__":
    main()
