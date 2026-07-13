"""File integrity check — verify the shipped application files against a manifest.

A SHA-256 manifest of the ``app/`` package is generated at Docker build time
(``scripts/generate_integrity_manifest.py``) over the exact shipped bytes. At
runtime we re-hash ``app/`` and diff it against the manifest to surface files
that are missing, modified, or unexpectedly present.

Scope / honesty: the manifest ships inside the same image (same trust boundary),
so this reliably detects accidental modification, incomplete/partial deploys and
corruption — but it is NOT tamper-proof against an attacker who can also rewrite
the manifest. The manifest's own SHA-256 is surfaced so it can optionally be
compared against a value published out-of-band (e.g. the signed release).

This module imports no settings and makes no network calls; it only reads local
files, so it is safe to run always.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from pathlib import Path, PurePosixPath
from typing import Any, TypedDict

from redis.asyncio import Redis

log = logging.getLogger(__name__)

_MANIFEST_NAME = "integrity-manifest.json"
_CACHE_KEY = "openwhistle:integrity"
_CACHE_TTL = 300  # 5 minutes
_CHUNK = 65536

# .../app/services/integrity.py -> APP_ROOT = .../app, REPO_ROOT = ...
APP_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = APP_ROOT.parent
DEFAULT_MANIFEST_PATH = REPO_ROOT / _MANIFEST_NAME


class ManifestEntry(TypedDict):
    sha256: str
    size: int


class IntegrityResult(TypedDict):
    available: bool
    ok: bool
    checked: int
    missing: list[str]
    modified: list[str]
    extra: list[str]
    generated_at: str | None
    version: str | None
    manifest_sha256: str | None


def _hash_file(path: Path) -> tuple[str, int]:
    """Streamed SHA-256 + byte size — never loads the whole file into memory."""
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as f:
        while chunk := f.read(_CHUNK):
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def build_file_index(root: Path) -> dict[str, ManifestEntry]:
    """Walk ``root`` and return ``{posix_relpath: {sha256, size}}``.

    Keys are POSIX paths relative to ``root``'s parent (e.g. ``app/main.py``).
    ``__pycache__`` dirs, ``*.pyc`` files and the manifest file are skipped;
    symlinked directories are not followed; unreadable files are omitted (they
    surface as ``missing`` during verification rather than aborting the walk).
    """
    base = root.parent
    index: dict[str, ManifestEntry] = {}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for filename in filenames:
            if filename.endswith(".pyc") or filename == _MANIFEST_NAME:
                continue
            file_path = Path(dirpath) / filename
            key = PurePosixPath(file_path.relative_to(base).as_posix()).as_posix()
            try:
                digest, size = _hash_file(file_path)
            except OSError:
                log.warning("Integrity: could not read %s", key)
                continue
            index[key] = {"sha256": digest, "size": size}
    return index


def load_manifest(manifest_path: Path) -> dict[str, Any] | None:
    """Load the manifest, or None if absent / malformed / empty."""
    try:
        raw = manifest_path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(parsed, dict) or not parsed.get("files"):
        return None
    return parsed


def _manifest_sha256(manifest_path: Path) -> str | None:
    try:
        return _hash_file(manifest_path)[0]
    except OSError:
        return None


def _unavailable() -> IntegrityResult:
    return {
        "available": False,
        "ok": False,
        "checked": 0,
        "missing": [],
        "modified": [],
        "extra": [],
        "generated_at": None,
        "version": None,
        "manifest_sha256": None,
    }


def verify_integrity(
    root: Path = APP_ROOT, manifest_path: Path = DEFAULT_MANIFEST_PATH
) -> IntegrityResult:
    """Diff the on-disk ``app/`` tree against the baked manifest (synchronous)."""
    manifest = load_manifest(manifest_path)
    if manifest is None:
        return _unavailable()

    files: dict[str, Any] = manifest.get("files", {})
    current = build_file_index(root)

    missing: list[str] = []
    modified: list[str] = []
    for path, entry in files.items():
        cur = current.get(path)
        if cur is None:
            missing.append(path)
        elif cur["sha256"] != entry.get("sha256") or cur["size"] != entry.get("size"):
            modified.append(path)
    extra = sorted(set(current) - set(files))
    missing.sort()
    modified.sort()

    return {
        "available": True,
        "ok": not (missing or modified or extra),
        "checked": len(current),
        "missing": missing,
        "modified": modified,
        "extra": extra,
        "generated_at": manifest.get("generated_at"),
        "version": manifest.get("version"),
        "manifest_sha256": _manifest_sha256(manifest_path),
    }


async def get_integrity_status(redis: Redis, recheck: bool = False) -> dict[str, Any]:
    """Cached integrity status for the admin page.

    Runs the (fast, local) verification in a thread so the event loop is never
    blocked, and caches the result in Redis. ``recheck`` busts the cache.
    """
    if recheck:
        try:
            await redis.delete(_CACHE_KEY)
        except Exception:  # noqa: BLE001, S110
            pass
    else:
        raw = await redis.get(_CACHE_KEY)
        if raw:
            try:
                cached = json.loads(raw)
            except (ValueError, TypeError):
                cached = None
            if isinstance(cached, dict):
                return cached

    result = await asyncio.to_thread(verify_integrity)
    try:
        await redis.setex(_CACHE_KEY, _CACHE_TTL, json.dumps(result))
    except Exception:  # noqa: BLE001, S110
        pass
    return dict(result)
