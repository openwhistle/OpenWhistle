"""Tests for the file-integrity service and its admin System-page section."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.api.deps import get_current_admin
from app.main import app
from app.models.user import AdminRole, AdminUser
from app.services import integrity as ig


def _make_tree(tmp_path: Path) -> Path:
    """Build a small app-like tree with noise (pycache/pyc) that must be skipped."""
    appdir = tmp_path / "app"
    (appdir / "sub").mkdir(parents=True)
    (appdir / "a.py").write_text("print('a')", encoding="utf-8")
    (appdir / "sub" / "b.txt").write_text("hello", encoding="utf-8")
    (appdir / "empty.txt").write_text("", encoding="utf-8")
    (appdir / "__pycache__").mkdir()
    (appdir / "__pycache__" / "x.cpython-314.pyc").write_text("junk", encoding="utf-8")
    (appdir / "c.pyc").write_text("junk", encoding="utf-8")
    return appdir


def _write_manifest(path: Path, appdir: Path) -> None:
    idx = ig.build_file_index(appdir)
    path.write_text(
        json.dumps({"generated_at": "t", "version": "9.9.9", "algorithm": "sha256", "files": idx}),
        encoding="utf-8",
    )


def test_build_file_index_keys_and_skips(tmp_path: Path) -> None:
    appdir = _make_tree(tmp_path)
    idx = ig.build_file_index(appdir)
    # __pycache__ and *.pyc excluded; POSIX keys relative to the app parent.
    assert set(idx) == {"app/a.py", "app/sub/b.txt", "app/empty.txt"}
    assert idx["app/a.py"]["size"] == len("print('a')")
    assert idx["app/empty.txt"]["size"] == 0
    assert len(idx["app/a.py"]["sha256"]) == 64


def test_verify_ok_round_trip(tmp_path: Path) -> None:
    appdir = _make_tree(tmp_path)
    manifest = tmp_path / "m.json"
    _write_manifest(manifest, appdir)
    r = ig.verify_integrity(root=appdir, manifest_path=manifest)
    assert r["available"] is True
    assert r["ok"] is True
    assert r["checked"] == 3
    assert r["version"] == "9.9.9"
    assert r["manifest_sha256"] and len(r["manifest_sha256"]) == 64
    assert not r["missing"] and not r["modified"] and not r["extra"]


def test_verify_detects_missing_modified_extra(tmp_path: Path) -> None:
    appdir = _make_tree(tmp_path)
    manifest = tmp_path / "m.json"
    _write_manifest(manifest, appdir)
    m = json.loads(manifest.read_text())
    m["files"]["app/GONE.py"] = {"sha256": "0" * 64, "size": 1}  # missing on disk
    m["files"]["app/a.py"]["sha256"] = "deadbeef"                # hash mismatch → modified
    del m["files"]["app/sub/b.txt"]                              # on disk, not in manifest → extra
    manifest.write_text(json.dumps(m), encoding="utf-8")

    r = ig.verify_integrity(root=appdir, manifest_path=manifest)
    assert r["ok"] is False
    assert "app/GONE.py" in r["missing"]
    assert "app/a.py" in r["modified"]
    assert "app/sub/b.txt" in r["extra"]


def test_verify_detects_size_only_change(tmp_path: Path) -> None:
    appdir = _make_tree(tmp_path)
    manifest = tmp_path / "m.json"
    _write_manifest(manifest, appdir)
    m = json.loads(manifest.read_text())
    m["files"]["app/a.py"]["size"] = 99999  # size mismatch alone → modified
    manifest.write_text(json.dumps(m), encoding="utf-8")
    r = ig.verify_integrity(root=appdir, manifest_path=manifest)
    assert "app/a.py" in r["modified"]


@pytest.mark.parametrize(
    "content",
    [None, "{ not json", json.dumps({"files": {}}), json.dumps({"other": 1}), json.dumps([1, 2])],
)
def test_verify_unavailable(tmp_path: Path, content: str | None) -> None:
    appdir = _make_tree(tmp_path)
    manifest = tmp_path / "m.json"
    if content is not None:
        manifest.write_text(content, encoding="utf-8")
    r = ig.verify_integrity(root=appdir, manifest_path=manifest)
    assert r["available"] is False
    assert r["ok"] is False


@pytest.mark.asyncio
async def test_get_integrity_status_caches_result() -> None:
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.setex = AsyncMock()
    result = await ig.get_integrity_status(redis)
    assert "available" in result
    redis.setex.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_integrity_status_recheck_busts_cache() -> None:
    redis = AsyncMock()
    redis.delete = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.setex = AsyncMock()
    await ig.get_integrity_status(redis, recheck=True)
    redis.delete.assert_awaited_once()
    redis.get.assert_not_called()  # recheck skips the cache read


# ── Integration: admin System page renders the integrity section ───────────


@pytest_asyncio.fixture(loop_scope="function")
async def as_admin(client: AsyncClient):
    admin = AdminUser(
        id=uuid.uuid4(),
        username="sysadmin2",
        role=AdminRole.admin,
        is_active=True,
        totp_secret="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        totp_enabled=True,
    )
    app.dependency_overrides[get_current_admin] = lambda: admin
    yield client
    app.dependency_overrides.pop(get_current_admin, None)


@pytest.mark.asyncio
async def test_system_page_renders_integrity_section(as_admin: AsyncClient) -> None:
    # No manifest ships in the test env → the section renders as "unavailable".
    resp = await as_admin.get("/admin/system", follow_redirects=False)
    assert resp.status_code == 200
    assert "integrity" in resp.text.lower()
