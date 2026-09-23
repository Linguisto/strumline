"""IPC frame codec — versioned binary protocol over Unix-domain sockets.

Wire format
-----------
Each frame is:

    [ 4 bytes big-endian uint32 body_length ][ body_length bytes UTF-8 JSON ]

The JSON body is an envelope::

    { "v": 1, "event": { <Event.to_dict()> } }

Constants
---------
``IPC_MAX_FRAME_BYTES`` — maximum body size accepted by both sides. Frames
exceeding this limit are rejected before allocation.

Errors
------
All codec errors are subclasses of ``IPCError``.  Each carries enough context
for the caller to log or count the failure without re-parsing.
"""

from __future__ import annotations

import asyncio
import json
import struct
from typing import Any

from strumline.domain.events import Event

# Protocol version embedded in every envelope
PROTOCOL_VERSION: int = 1

# Reject frames whose body exceeds this size before allocating
IPC_MAX_FRAME_BYTES: int = 1 * 1024 * 1024  # 1 MiB

# Fixed 4-byte big-endian prefix carrying the body length
_PREFIX_FORMAT = "!I"
_PREFIX_SIZE = struct.calcsize(_PREFIX_FORMAT)  # 4


# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------


class IPCError(Exception):
    """Base for all IPC codec errors."""


class FrameTooLargeError(IPCError):
    """Body length prefix exceeds ``IPC_MAX_FRAME_BYTES``."""

    def __init__(self, length: int, max_bytes: int) -> None:
        super().__init__(f"Frame body {length} bytes exceeds limit {max_bytes}")
        self.length = length
        self.max_bytes = max_bytes


class EmptyFrameError(IPCError):
    """Body length prefix is zero."""


class TruncatedFrameError(IPCError):
    """EOF received before the full body was read."""

    def __init__(self, expected: int, got: int) -> None:
        super().__init__(f"Expected {expected} bytes, got {got} before EOF")
        self.expected = expected
        self.got = got


class UnknownVersionError(IPCError):
    """Envelope ``v`` field is not a known protocol version."""

    def __init__(self, version: Any) -> None:
        super().__init__(f"Unknown IPC protocol version: {version!r}")
        self.version = version


class MalformedEnvelopeError(IPCError):
    """Body is not valid JSON or missing required envelope fields."""


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------


def encode_frame(event: Event) -> bytes:
    """Encode *event* into a length-prefixed IPC frame.

    Returns the complete frame (4-byte prefix + JSON body) as a ``bytes``
    object safe to write to a UDS stream.
    """
    envelope: dict[str, Any] = {"v": PROTOCOL_VERSION, "event": event.to_dict()}
    body = json.dumps(envelope, separators=(",", ":")).encode("utf-8")
    prefix = struct.pack(_PREFIX_FORMAT, len(body))
    return prefix + body


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------


async def read_frame(
    reader: asyncio.StreamReader,
    max_bytes: int = IPC_MAX_FRAME_BYTES,
) -> bytes:
    """Read one frame body from *reader*.

    Reads the 4-byte prefix, validates the declared length, then reads
    exactly that many bytes.  Returns the raw body bytes (prefix already
    consumed) for the caller to pass to ``decode_envelope_body``.

    Raises
    ------
    EmptyFrameError
        Body length is zero.
    FrameTooLargeError
        Declared body length exceeds *max_bytes*.
    TruncatedFrameError
        EOF before the full body arrived.
    asyncio.IncompleteReadError
        EOF before the prefix was fully read (propagated as-is so the
        caller can distinguish connection close from protocol error).
    """
    prefix = await reader.readexactly(_PREFIX_SIZE)
    (length,) = struct.unpack(_PREFIX_FORMAT, prefix)

    if length == 0:
        raise EmptyFrameError("Frame body length is zero")
    if length > max_bytes:
        raise FrameTooLargeError(length, max_bytes)

    try:
        return await reader.readexactly(length)
    except asyncio.IncompleteReadError as exc:
        raise TruncatedFrameError(length, len(exc.partial)) from exc


def decode_envelope_body(body: bytes) -> Event:
    """Decode a raw frame body into an ``Event``.

    The length prefix must already be consumed (i.e. this is called after
    ``read_frame`` returns the body).

    Raises
    ------
    UnknownVersionError
        The ``v`` field is not ``PROTOCOL_VERSION``.
    MalformedEnvelopeError
        Body is not valid UTF-8 JSON, or the envelope is missing fields.
    """
    try:
        envelope = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise MalformedEnvelopeError(f"Invalid JSON body: {exc}") from exc

    if not isinstance(envelope, dict):
        raise MalformedEnvelopeError("Envelope is not a JSON object")

    version = envelope.get("v")
    if version != PROTOCOL_VERSION:
        raise UnknownVersionError(version)

    event_dict = envelope.get("event")
    if not isinstance(event_dict, dict):
        raise MalformedEnvelopeError("Missing or invalid 'event' field in envelope")

    try:
        return Event.from_dict(event_dict)
    except (KeyError, ValueError, TypeError) as exc:
        raise MalformedEnvelopeError(f"Invalid event payload: {exc}") from exc
