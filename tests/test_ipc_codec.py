"""M2-A: IPC frame codec tests.

Covers:
- encode_frame / decode_envelope_body round-trip
- Golden byte fixture (prefix + known body length)
- FrameTooLargeError, EmptyFrameError, TruncatedFrameError
- UnknownVersionError, MalformedEnvelopeError
- read_frame via asyncio.StreamReader mock
"""

from __future__ import annotations

import asyncio
import json
import struct
import uuid
from datetime import UTC, datetime

import pytest

from telemetria.domain.events import Event
from telemetria.ipc.codec import (
    IPC_MAX_FRAME_BYTES,
    PROTOCOL_VERSION,
    EmptyFrameError,
    FrameTooLargeError,
    MalformedEnvelopeError,
    TruncatedFrameError,
    UnknownVersionError,
    decode_envelope_body,
    encode_frame,
    read_frame,
)

_NOW = datetime(2026, 9, 18, 17, 0, 0, 0, tzinfo=UTC)
_UUID1 = uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
_UUID2 = uuid.UUID("00000000-0000-0000-0000-000000000001")
_UUID3 = uuid.UUID("00000000-0000-0000-0000-000000000002")


def _make_event(**kwargs) -> Event:
    defaults = dict(
        id=_UUID1,
        project_id=_UUID2,
        project_slug="proj",
        app_id=_UUID3,
        app_slug="app",
        received_at=_NOW,
        timestamp=_NOW,
        level="info",
        message="test",
        payload={},
    )
    defaults.update(kwargs)
    return Event(**defaults)


# ---------------------------------------------------------------------------
# encode / decode round-trip
# ---------------------------------------------------------------------------


def test_round_trip():
    event = _make_event(message="hello", payload={"x": 1})
    frame = encode_frame(event)
    # Strip prefix
    (length,) = struct.unpack("!I", frame[:4])
    body = frame[4:]
    assert len(body) == length
    decoded = decode_envelope_body(body)
    assert decoded.id == event.id
    assert decoded.message == event.message
    assert decoded.payload == event.payload
    assert decoded.received_at == event.received_at
    assert decoded.timestamp == event.timestamp


def test_timestamp_serializes_with_z():
    event = _make_event()
    frame = encode_frame(event)
    body = frame[4:]
    envelope = json.loads(body)
    assert envelope["event"]["received_at"].endswith("Z")
    assert envelope["event"]["timestamp"].endswith("Z")


# ---------------------------------------------------------------------------
# Golden fixture — prefix carries exact body length
# ---------------------------------------------------------------------------


def test_golden_prefix_is_4_bytes():
    event = _make_event()
    frame = encode_frame(event)
    (declared_length,) = struct.unpack("!I", frame[:4])
    assert declared_length == len(frame) - 4


def test_golden_envelope_version():
    event = _make_event()
    frame = encode_frame(event)
    body = frame[4:]
    envelope = json.loads(body)
    assert envelope["v"] == PROTOCOL_VERSION
    assert "event" in envelope


# ---------------------------------------------------------------------------
# decode_envelope_body errors
# ---------------------------------------------------------------------------


def test_unknown_version():
    body = json.dumps({"v": 99, "event": {}}).encode()
    with pytest.raises(UnknownVersionError) as exc_info:
        decode_envelope_body(body)
    assert exc_info.value.version == 99


def test_missing_version():
    body = json.dumps({"event": {}}).encode()
    with pytest.raises(UnknownVersionError):
        decode_envelope_body(body)


def test_malformed_json():
    with pytest.raises(MalformedEnvelopeError):
        decode_envelope_body(b"not json{{{")


def test_not_an_object():
    with pytest.raises(MalformedEnvelopeError):
        decode_envelope_body(b"[1, 2, 3]")


def test_missing_event_field():
    body = json.dumps({"v": PROTOCOL_VERSION}).encode()
    with pytest.raises(MalformedEnvelopeError):
        decode_envelope_body(body)


def test_invalid_event_payload():
    body = json.dumps({"v": PROTOCOL_VERSION, "event": {"id": "not-a-uuid"}}).encode()
    with pytest.raises(MalformedEnvelopeError):
        decode_envelope_body(body)


# ---------------------------------------------------------------------------
# read_frame via StreamReader
# ---------------------------------------------------------------------------


def _make_reader(data: bytes) -> asyncio.StreamReader:
    reader = asyncio.StreamReader()
    reader.feed_data(data)
    reader.feed_eof()
    return reader


@pytest.mark.asyncio
async def test_read_frame_success():
    event = _make_event()
    frame = encode_frame(event)
    reader = _make_reader(frame)
    body = await read_frame(reader)
    decoded = decode_envelope_body(body)
    assert decoded.id == event.id


@pytest.mark.asyncio
async def test_read_frame_empty_body():
    prefix = struct.pack("!I", 0)
    reader = _make_reader(prefix)
    with pytest.raises(EmptyFrameError):
        await read_frame(reader)


@pytest.mark.asyncio
async def test_read_frame_too_large():
    oversized = IPC_MAX_FRAME_BYTES + 1
    prefix = struct.pack("!I", oversized)
    reader = _make_reader(prefix)
    with pytest.raises(FrameTooLargeError) as exc_info:
        await read_frame(reader)
    assert exc_info.value.length == oversized


@pytest.mark.asyncio
async def test_read_frame_truncated():
    # Declare 100 bytes but only provide 10
    prefix = struct.pack("!I", 100)
    reader = _make_reader(prefix + b"x" * 10)
    with pytest.raises(TruncatedFrameError) as exc_info:
        await read_frame(reader)
    assert exc_info.value.expected == 100
    assert exc_info.value.got == 10


@pytest.mark.asyncio
async def test_read_frame_custom_max():
    # Max of 10 bytes, body is 20 — should reject
    prefix = struct.pack("!I", 20)
    reader = _make_reader(prefix + b"x" * 20)
    with pytest.raises(FrameTooLargeError):
        await read_frame(reader, max_bytes=10)
