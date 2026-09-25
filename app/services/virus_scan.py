"""Upload virus scan through clamd's INSTREAM command. No dependency: the
protocol is length-prefixed chunks over one TCP connection."""

from __future__ import annotations

import asyncio
import struct

from app.config import settings

_CHUNK = 64 * 1024


class ScanUnavailableError(Exception):
    """clamd is configured but could not give an answer."""


# A clamd reply is a few dozen bytes ("stream: OK\0" or "stream: <signature>
# FOUND\0"). Bound the receive buffer well below that so a reply with no "\0"
# terminator (truncated, garbled, or a hostile daemon) hits
# asyncio.LimitOverrunError quickly instead of buffering up to the default
# 64 KiB before giving up.
_MAX_REPLY_BYTES = 4096


async def scan_bytes(data: bytes) -> str | None:
    if not settings.clamav_host:
        return None
    timeout = settings.clamav_timeout_seconds
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(
                settings.clamav_host, settings.clamav_port, limit=_MAX_REPLY_BYTES
            ),
            timeout,
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
    except (
        OSError,
        TimeoutError,
        asyncio.IncompleteReadError,
        asyncio.LimitOverrunError,
    ) as exc:
        raise ScanUnavailableError(str(exc)) from exc
    finally:
        writer.close()
    text = reply.rstrip(b"\0").decode("utf-8", "replace").removeprefix("stream: ")
    if text == "OK":
        return None
    if text.endswith(" FOUND"):
        # A blank or whitespace-only signature name must still read as
        # infected — the interface is "None means clean", nothing else does.
        return text.removesuffix(" FOUND").strip() or "unknown"
    raise ScanUnavailableError(text)
