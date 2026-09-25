"""Upload virus scan through clamd's INSTREAM command. No dependency: the
protocol is length-prefixed chunks over one TCP connection."""

from __future__ import annotations

import asyncio
import struct

from app.config import settings

_CHUNK = 64 * 1024


class ScanUnavailableError(Exception):
    """clamd is configured but could not give an answer."""


async def scan_bytes(data: bytes) -> str | None:
    if not settings.clamav_host:
        return None
    timeout = settings.clamav_timeout_seconds
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(settings.clamav_host, settings.clamav_port), timeout
        )
    except (OSError, TimeoutError) as exc:
        raise ScanUnavailableError(str(exc)) from exc
    try:
        writer.write(b"zINSTREAM\0")
        for start in range(0, len(data), _CHUNK):
            chunk = data[start:start + _CHUNK]
            writer.write(struct.pack("!I", len(chunk)) + chunk)
        writer.write(struct.pack("!I", 0))
        # Bounded like the connect and the reply read: a clamd that stops
        # draining its receive buffer must not hang the request forever.
        await asyncio.wait_for(writer.drain(), timeout)
        reply = await asyncio.wait_for(reader.readuntil(b"\0"), timeout)
    except (OSError, TimeoutError, asyncio.IncompleteReadError) as exc:
        raise ScanUnavailableError(str(exc)) from exc
    finally:
        writer.close()
    text = reply.rstrip(b"\0").decode("utf-8", "replace").removeprefix("stream: ")
    if text == "OK":
        return None
    if text.endswith(" FOUND"):
        return text.removesuffix(" FOUND")
    raise ScanUnavailableError(text)
