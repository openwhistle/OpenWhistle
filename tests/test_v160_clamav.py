"""v1.6.0 Task 20: optional ClamAV virus scan of uploads, fail-closed.

clamd is spoken to over its INSTREAM protocol via a tiny in-process fake
server (asyncio.start_server) — no real clamd needed for these tests.
"""

from __future__ import annotations

import asyncio
import io
import re
from pathlib import Path

import pytest
from starlette.datastructures import Headers, UploadFile

from app.config import settings
from app.services.attachment import read_upload_files
from app.services.virus_scan import scan_bytes

ROOT = Path(__file__).parents[1]


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
async def test_a_reply_longer_than_the_bound_is_not_trusted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A terminated reply past _MAX_REPLY_BYTES is no answer clamd gives: the
    scan counts as unavailable instead of being parsed."""
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        assert await reader.readexactly(10) == b"zINSTREAM\0"
        while True:
            size = int.from_bytes(await reader.readexactly(4), "big")
            if size == 0:
                break
            await reader.readexactly(size)
        writer.write(b"stream: " + b"x" * 5000 + b" FOUND\0")
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


# ── Docs: Helm ships no clamd (fix round 2, re-review required) ─────────────


def test_virus_scan_docs_warn_that_helm_ships_no_clamd() -> None:
    """The chart deploys no clamav pod; enabling CLAMAV_HOST via Helm without
    pointing it at a real, reachable clamd fails every upload closed. RED if
    this warning is ever removed from the how-to."""
    text = (ROOT / "docs/docs.html").read_text()
    section = text.split('id="virus-scanning"')[1].split('id="first-run"')[0]
    assert "Helm" in section
    assert "no clamav pod" in section
    assert "clamavHost" in section
    assert "reachable" in section and "refused" in section


def test_helm_values_warn_that_the_chart_ships_no_clamd() -> None:
    """Same warning, at the point an operator actually sets clamavHost."""
    values = (ROOT / "charts/openwhistle/values.yaml").read_text()
    match = re.search(r"((?:^  #.*\n)+)  clamavHost:", values, re.M)
    assert match, "no comment block directly above clamavHost"
    comment = match.group(1)
    assert "does not deploy a clamav pod" in comment
    assert "reachable clamd" in comment


@pytest.mark.asyncio
async def test_scan_unavailable_when_connecting_hangs(monkeypatch: pytest.MonkeyPatch) -> None:
    """A clamd host that never completes the TCP handshake (a dropped SYN) must
    not hang the upload: the connect is bounded like the reply read."""
    never = asyncio.Event()

    async def _hanging_connect(*args: object, **kwargs: object) -> None:
        await never.wait()

    monkeypatch.setattr(settings, "clamav_host", "192.0.2.1")
    monkeypatch.setattr(settings, "clamav_timeout_seconds", 1)
    monkeypatch.setattr(asyncio, "open_connection", _hanging_connect)
    from app.services.virus_scan import ScanUnavailableError

    with pytest.raises(ScanUnavailableError):
        await scan_bytes(b"x" * 100)
