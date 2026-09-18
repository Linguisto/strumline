"""M2-D: IPC writer tests.

Tests cover:
- Writer sends golden frames to a fake UDS server
- Reconnects after connection failure
- Handles missing server gracefully (no hang)
"""

from __future__ import annotations

import asyncio
import contextlib
import struct
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from telemetria.domain.events import Event
from telemetria.ingest.writer import IPCWriter
from telemetria.ipc.codec import decode_envelope_body

_NOW = datetime(2026, 9, 18, 17, 0, 0, tzinfo=UTC)


def _make_event(**kwargs) -> Event:
    defaults = dict(
        id=uuid.uuid4(),
        project_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        project_slug="proj",
        app_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
        app_slug="app",
        received_at=_NOW,
        timestamp=_NOW,
        level="info",
        message="test",
        payload={},
    )
    defaults.update(kwargs)
    return Event(**defaults)


async def _read_one_frame(reader: asyncio.StreamReader) -> Event:
    """Read one length-prefixed frame and decode it."""
    prefix = await asyncio.wait_for(reader.readexactly(4), timeout=2.0)
    (length,) = struct.unpack("!I", prefix)
    body = await asyncio.wait_for(reader.readexactly(length), timeout=2.0)
    return decode_envelope_body(body)


async def _cancel(task: asyncio.Task) -> None:  # type: ignore[type-arg]
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_writer_sends_golden_frames():
    """Writer encodes and delivers events to the UDS server."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sock_path = str(Path(tmpdir) / "ipc.sock")
        received: list[Event] = []
        ready = asyncio.Event()

        async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            ready.set()
            with contextlib.suppress(asyncio.IncompleteReadError, asyncio.TimeoutError):
                while True:
                    received.append(await _read_one_frame(reader))
            writer.close()

        server = await asyncio.start_unix_server(handler, path=sock_path)

        queue: asyncio.Queue[Event] = asyncio.Queue()
        writer = IPCWriter(queue, sock_path)
        task = asyncio.create_task(writer.run())

        events = [_make_event(message=f"msg-{i}") for i in range(3)]
        for e in events:
            await queue.put(e)

        # Wait until all 3 frames arrive (poll, max 3s)
        for _ in range(30):
            if len(received) >= 3:
                break
            await asyncio.sleep(0.1)

        await _cancel(task)
        server.close()
        await writer.close()

        assert len(received) == 3
        for sent, got in zip(events, received, strict=True):
            assert got.id == sent.id
            assert got.message == sent.message


@pytest.mark.asyncio
async def test_writer_reconnects_after_server_restart():
    """Writer reconnects after the server closes the connection."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sock_path = str(Path(tmpdir) / "ipc.sock")
        received: list[Event] = []
        connection_count = 0

        async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            nonlocal connection_count
            connection_count += 1
            if connection_count == 1:
                # Immediately close to trigger reconnect
                writer.close()
                return
            with contextlib.suppress(asyncio.IncompleteReadError, asyncio.TimeoutError):
                while True:
                    received.append(await _read_one_frame(reader))
            writer.close()

        server = await asyncio.start_unix_server(handler, path=sock_path)
        queue: asyncio.Queue[Event] = asyncio.Queue()
        writer = IPCWriter(queue, sock_path)
        task = asyncio.create_task(writer.run())

        # Wait for first connection to be made and closed
        for _ in range(20):
            if connection_count >= 1:
                break
            await asyncio.sleep(0.1)

        # Send event — should arrive after reconnect
        event = _make_event(message="after-reconnect")
        await queue.put(event)

        for _ in range(30):
            if received:
                break
            await asyncio.sleep(0.1)

        await _cancel(task)
        server.close()
        await writer.close()

        assert len(received) == 1
        assert received[0].message == "after-reconnect"


@pytest.mark.asyncio
async def test_writer_handles_missing_server():
    """Writer retries when the socket doesn't exist — does not hang."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sock_path = str(Path(tmpdir) / "missing.sock")
        queue: asyncio.Queue[Event] = asyncio.Queue()
        writer = IPCWriter(queue, sock_path)
        task = asyncio.create_task(writer.run())

        # Give it time to attempt and back off
        await asyncio.sleep(0.3)
        await _cancel(task)
        await writer.close()
        # No assertion — passes if it returns promptly without hanging
