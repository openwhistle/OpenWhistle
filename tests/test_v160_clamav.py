"""v1.6.0 Task 20: optional ClamAV virus scan of uploads, fail-closed.

clamd is spoken to over its INSTREAM protocol via a tiny in-process fake
server (asyncio.start_server) — no real clamd needed for these tests.
"""

from __future__ import annotations

import asyncio
import io

import pytest
from starlette.datastructures import Headers, UploadFile

from app.config import settings
from app.services.attachment import read_upload_files
from app.services.virus_scan import scan_bytes


async def _fake_clamd(reply: bytes) -> asyncio.AbstractServer:
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        assert await reader.readexactly(10) == b"zINSTREAM\0"
        while True:
            size = int.from_bytes(await reader.readexactly(4), "big")
            if size == 0:
                break
            await reader.readexactly(size)
        writer.write(reply)
        await writer.drain()
        writer.close()

    return await asyncio.start_server(handle, "127.0.0.1", 0)


@pytest.mark.asyncio
@pytest.mark.parametrize(("reply", "expected"), [
    (b"stream: OK\0", None),
    (b"stream: Eicar-Test-Signature FOUND\0", "Eicar-Test-Signature"),
])
async def test_scan_reports_clean_and_infected(
    monkeypatch: pytest.MonkeyPatch, reply: bytes, expected: str | None
) -> None:
    server = await _fake_clamd(reply)
    monkeypatch.setattr(settings, "clamav_host", "127.0.0.1")
    monkeypatch.setattr(settings, "clamav_port", server.sockets[0].getsockname()[1])
    async with server:
        assert await scan_bytes(b"x" * 100_000) == expected


@pytest.mark.asyncio
async def test_upload_is_refused_when_the_scanner_is_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "clamav_host", "127.0.0.1")
    monkeypatch.setattr(settings, "clamav_port", 9)  # discard port: nothing listens
    upload = UploadFile(io.BytesIO(b"plain text"), filename="note.txt",
                        headers=Headers({"content-type": "text/plain"}))
    files, error = await read_upload_files([upload])
    assert files == [] and error is not None and error.key == "upload.error.scan_unavailable"


@pytest.mark.asyncio
async def test_infected_upload_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    server = await _fake_clamd(b"stream: Eicar-Test-Signature FOUND\0")
    monkeypatch.setattr(settings, "clamav_host", "127.0.0.1")
    monkeypatch.setattr(settings, "clamav_port", server.sockets[0].getsockname()[1])
    upload = UploadFile(io.BytesIO(b"plain text"), filename="note.txt",
                        headers=Headers({"content-type": "text/plain"}))
    async with server:
        files, error = await read_upload_files([upload])
    assert files == [] and error is not None and error.key == "upload.error.malware"


@pytest.mark.asyncio
async def test_scanning_off_by_default_never_connects(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "clamav_host", "")
    assert await scan_bytes(b"anything") is None


@pytest.mark.asyncio
async def test_scan_unavailable_on_size_limit_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    """A clamd StreamMaxLength rejection is not a clean/infected verdict — treat
    it as unavailable, same as an unreachable daemon (fail closed)."""
    server = await _fake_clamd(b"INSTREAM size limit exceeded. ERROR\0")
    monkeypatch.setattr(settings, "clamav_host", "127.0.0.1")
    monkeypatch.setattr(settings, "clamav_port", server.sockets[0].getsockname()[1])
    async with server:
        from app.services.virus_scan import ScanUnavailableError

        with pytest.raises(ScanUnavailableError):
            await scan_bytes(b"x" * 100_000)


@pytest.mark.asyncio
async def test_scan_unavailable_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """clamd accepts the connection but never replies: the read must time out
    and be treated as unavailable, not hang forever."""
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readexactly(10)
        while await reader.readexactly(4) != b"\0\0\0\0":
            pass
        await asyncio.sleep(3600)

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    monkeypatch.setattr(settings, "clamav_host", "127.0.0.1")
    monkeypatch.setattr(settings, "clamav_port", server.sockets[0].getsockname()[1])
    monkeypatch.setattr(settings, "clamav_timeout_seconds", 1)
    # Not `async with server:` — its __aexit__ awaits wait_closed(), which
    # would block on the handler above, deliberately stuck in sleep(3600).
    try:
        from app.services.virus_scan import ScanUnavailableError

        with pytest.raises(ScanUnavailableError):
            await scan_bytes(b"x" * 1000)
    finally:
        server.close()
