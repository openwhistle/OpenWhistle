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
@pytest.mark.parametrize("reply", [
    b"INSTREAM size limit exceeded. ERROR\0",  # clamd's own StreamMaxLength rejection
    b"stream: UNKNOWN COMMAND ERROR\0",  # any other clamd ERROR reply
    b"\x00\x01\xffnonsense\xfe\x00",  # garbage: neither OK, FOUND, nor readable text
])
async def test_scan_unavailable_on_non_ok_non_found_reply(
    monkeypatch: pytest.MonkeyPatch, reply: bytes
) -> None:
    """Anything that isn't a clean or infected verdict is not a scan result —
    treat it as unavailable, same as an unreachable daemon (fail closed)."""
    server = await _fake_clamd(reply)
    monkeypatch.setattr(settings, "clamav_host", "127.0.0.1")
    monkeypatch.setattr(settings, "clamav_port", server.sockets[0].getsockname()[1])
    async with server:
        from app.services.virus_scan import ScanUnavailableError

        with pytest.raises(ScanUnavailableError):
            await scan_bytes(b"x" * 100_000)


@pytest.mark.asyncio
async def test_empty_signature_name_is_still_treated_as_infected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`str | None` means only None is clean — a FOUND reply with a blank
    signature name (extra whitespace, a clamd bug) must not become a falsy
    empty string that a naive `if await scan_bytes(...)` reads as clean."""
    server = await _fake_clamd(b"stream:  FOUND\0")
    monkeypatch.setattr(settings, "clamav_host", "127.0.0.1")
    monkeypatch.setattr(settings, "clamav_port", server.sockets[0].getsockname()[1])
    async with server:
        result = await scan_bytes(b"x" * 100)
    assert result is not None
    assert result == "unknown"


@pytest.mark.asyncio
async def test_scan_unavailable_when_reply_has_no_terminator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """clamd closes the connection mid-reply, before the '\\0' terminator ever
    arrives — an incomplete reply, not a verdict."""
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        assert await reader.readexactly(10) == b"zINSTREAM\0"
        while True:
            size = int.from_bytes(await reader.readexactly(4), "big")
            if size == 0:
                break
            await reader.readexactly(size)
        writer.write(b"stream: O")  # no trailing \0 — then just disappear
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    monkeypatch.setattr(settings, "clamav_host", "127.0.0.1")
    monkeypatch.setattr(settings, "clamav_port", server.sockets[0].getsockname()[1])
    async with server:
        from app.services.virus_scan import ScanUnavailableError

        with pytest.raises(ScanUnavailableError):
            await scan_bytes(b"x" * 100)


@pytest.mark.asyncio
async def test_scan_unavailable_on_over_long_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    """A reply longer than the bounded receive buffer and still no '\\0' must
    raise promptly (asyncio.LimitOverrunError) rather than buffer without limit
    or hang — a compromised or badly broken clamd must not stall the request."""
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        assert await reader.readexactly(10) == b"zINSTREAM\0"
        while True:
            size = int.from_bytes(await reader.readexactly(4), "big")
            if size == 0:
                break
            await reader.readexactly(size)
        writer.write(b"x" * 100_000)  # far past the reply size bound, no '\0'
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    monkeypatch.setattr(settings, "clamav_host", "127.0.0.1")
    monkeypatch.setattr(settings, "clamav_port", server.sockets[0].getsockname()[1])
    async with server:
        from app.services.virus_scan import ScanUnavailableError

        with pytest.raises(ScanUnavailableError):
            await scan_bytes(b"x" * 100)


@pytest.mark.asyncio
async def test_scan_unavailable_on_drain_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """clamd accepts the connection but stops reading after the protocol
    header: with nothing draining the socket, a large-enough upload fills the
    client's own send buffer and `writer.drain()` must time out too — not
    just the reply read."""
    stop_reading = asyncio.Event()

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readexactly(10)  # protocol header only, then go silent
        await stop_reading.wait()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    monkeypatch.setattr(settings, "clamav_host", "127.0.0.1")
    monkeypatch.setattr(settings, "clamav_port", server.sockets[0].getsockname()[1])
    monkeypatch.setattr(settings, "clamav_timeout_seconds", 1)
    try:
        from app.services.virus_scan import ScanUnavailableError

        # Large enough that the un-drained transport write buffer actually
        # fills (default high-water mark is 64 KiB) — a real stall, not a
        # coincidence of timing.
        with pytest.raises(ScanUnavailableError):
            await scan_bytes(b"x" * 8_000_000)
    finally:
        stop_reading.set()
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_scan_unavailable_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """clamd accepts the connection but never replies: the read must time out
    and be treated as unavailable, not hang forever.

    The fake handler parks on an Event rather than a bare `sleep(3600)`, and
    the test wakes + reaps it in `finally`. `pyproject.toml` runs the whole
    suite on one session-scoped event loop, so a handler task left running
    here would keep an open socket alive for the rest of the session instead
    of just this test.
    """
    released = asyncio.Event()
    handler_done = asyncio.Event()

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await reader.readexactly(10)
            while True:
                size = int.from_bytes(await reader.readexactly(4), "big")
                if size == 0:
                    break
                await reader.readexactly(size)
            await released.wait()
        finally:
            writer.close()
            handler_done.set()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    monkeypatch.setattr(settings, "clamav_host", "127.0.0.1")
    monkeypatch.setattr(settings, "clamav_port", server.sockets[0].getsockname()[1])
    monkeypatch.setattr(settings, "clamav_timeout_seconds", 1)
    # Not `async with server:` — its __aexit__ awaits wait_closed(), which
    # would block until the handler task above finishes; it is deliberately
    # parked until `released` is set below.
    try:
        from app.services.virus_scan import ScanUnavailableError

        with pytest.raises(ScanUnavailableError):
            await scan_bytes(b"x" * 1000)
    finally:
        released.set()
        server.close()
        await asyncio.wait_for(handler_done.wait(), 5)
        await server.wait_closed()
