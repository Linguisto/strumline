"""M2b tests: UDS server, BatchProcessor, and end-to-end HTTP → NullSink."""

from __future__ import annotations

import asyncio
import contextlib
import os
import stat
import struct
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from telemetria.domain.events import Event, EventBatch
from telemetria.ipc.codec import PROTOCOL_VERSION, encode_frame
from telemetria.processor.batch import BatchProcessor
from telemetria.processor.uds_server import UDSServer
from telemetria.sinks import (
    EventSink,
    NullSink,
    PermanentSinkError,
    RetryableSinkError,
    get_sink,
)

_NOW = datetime(2026, 9, 18, 17, 0, 0, tzinfo=UTC)


pytestmark = pytest.mark.unit


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


async def _write_frame(writer: asyncio.StreamWriter, event: Event) -> None:
    writer.write(encode_frame(event))
    await writer.drain()


# ===========================================================================
# UDS Server tests
# ===========================================================================


@pytest.mark.asyncio
async def test_uds_server_receives_events():
    """Events written to the socket appear in the queue."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sock_path = str(Path(tmpdir) / "ipc.sock")
        queue: asyncio.Queue[Event] = asyncio.Queue()
        server = UDSServer(sock_path, queue)
        await server.start()

        _, writer = await asyncio.open_unix_connection(sock_path)
        event = _make_event(message="hello")
        await _write_frame(writer, event)

        received = await asyncio.wait_for(queue.get(), timeout=2.0)
        assert received.id == event.id

        writer.close()
        await server.stop()


@pytest.mark.asyncio
async def test_uds_server_removes_stale_socket():
    """Server removes a stale socket file on startup."""
    import socket as _socket

    with tempfile.TemporaryDirectory() as tmpdir:
        sock_path = str(Path(tmpdir) / "stale.sock")
        # Create a real socket file without binding a server to it
        raw = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
        raw.bind(sock_path)
        raw.close()

        assert Path(sock_path).exists()
        assert stat.S_ISSOCK(os.stat(sock_path).st_mode)

        queue: asyncio.Queue[Event] = asyncio.Queue()
        server = UDSServer(sock_path, queue)
        await server.start()  # should remove stale and rebind successfully
        assert Path(sock_path).exists()
        await server.stop()


@pytest.mark.asyncio
async def test_uds_server_refuses_non_socket_path():
    """Server refuses to remove a regular file at the socket path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sock_path = str(Path(tmpdir) / "regular_file")
        Path(sock_path).write_text("not a socket")

        queue: asyncio.Queue[Event] = asyncio.Queue()
        server = UDSServer(sock_path, queue)
        with pytest.raises(RuntimeError, match="not a socket"):
            await server.start()


@pytest.mark.asyncio
async def test_uds_server_socket_permissions():
    """Socket is created with mode 0o600."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sock_path = str(Path(tmpdir) / "ipc.sock")
        queue: asyncio.Queue[Event] = asyncio.Queue()
        server = UDSServer(sock_path, queue)
        await server.start()

        mode = stat.S_IMODE(os.stat(sock_path).st_mode)
        assert mode == 0o600, f"Expected 0o600, got {oct(mode)}"

        await server.stop()


@pytest.mark.asyncio
async def test_uds_server_unlinks_on_stop():
    """Socket is removed when the server stops."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sock_path = str(Path(tmpdir) / "ipc.sock")
        queue: asyncio.Queue[Event] = asyncio.Queue()
        server = UDSServer(sock_path, queue)
        await server.start()
        assert Path(sock_path).exists()
        await server.stop()
        assert not Path(sock_path).exists()


@pytest.mark.asyncio
async def test_uds_server_eof_mid_frame_discards():
    """EOF mid-frame does not crash the server; remaining events still arrive."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sock_path = str(Path(tmpdir) / "ipc.sock")
        queue: asyncio.Queue[Event] = asyncio.Queue()
        server = UDSServer(sock_path, queue)
        await server.start()

        _, writer = await asyncio.open_unix_connection(sock_path)
        # Write truncated frame (prefix claims 100 bytes, only 4 sent)
        writer.write(struct.pack("!I", 100) + b"x" * 4)
        await writer.drain()
        writer.close()

        await asyncio.sleep(0.2)
        assert queue.empty()  # no corrupt event enqueued
        await server.stop()


@pytest.mark.asyncio
async def test_uds_server_malformed_frame_keeps_alive():
    """Malformed frame is discarded; server stays up for next connection."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sock_path = str(Path(tmpdir) / "ipc.sock")
        queue: asyncio.Queue[Event] = asyncio.Queue()
        server = UDSServer(sock_path, queue)
        await server.start()

        # Send a well-formed frame with invalid JSON
        bad_body = b'{"v":' + str(PROTOCOL_VERSION).encode() + b',"event":invalid}'
        prefix = struct.pack("!I", len(bad_body))
        _, writer = await asyncio.open_unix_connection(sock_path)
        writer.write(prefix + bad_body)
        await writer.drain()
        writer.close()

        await asyncio.sleep(0.2)
        assert queue.empty()

        # Server still accepts a new connection
        _, writer2 = await asyncio.open_unix_connection(sock_path)
        good_event = _make_event(message="after-error")
        await _write_frame(writer2, good_event)
        received = await asyncio.wait_for(queue.get(), timeout=2.0)
        assert received.id == good_event.id
        writer2.close()

        await server.stop()


@pytest.mark.asyncio
async def test_uds_server_queue_full_increments_drops():
    """Queue overflow increments the drop counter."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sock_path = str(Path(tmpdir) / "ipc.sock")
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=1)
        server = UDSServer(sock_path, queue)
        await server.start()

        _, writer = await asyncio.open_unix_connection(sock_path)
        for _ in range(3):
            await _write_frame(writer, _make_event())
        await asyncio.sleep(0.2)

        assert server.drops >= 2
        writer.close()
        await server.stop()


# ===========================================================================
# Sink registry
# ===========================================================================


def test_get_null_sink():
    sink = get_sink("null")
    assert isinstance(sink, NullSink)


def test_unknown_provider_raises():
    with pytest.raises(ValueError, match="Unknown SINK_PROVIDER"):
        get_sink("nonexistent")


# ===========================================================================
# BatchProcessor tests
# ===========================================================================


class SpySink(EventSink):
    """Records every batch written to it."""

    name = "spy"

    def __init__(self) -> None:
        self.batches: list[EventBatch] = []
        self.side_effect: Exception | None = None

    async def write(self, batch: EventBatch) -> None:
        if self.side_effect is not None:
            raise self.side_effect
        self.batches.append(batch)


@pytest.mark.asyncio
async def test_batch_flush_on_size():
    """Processor flushes when batch reaches max size."""
    queue: asyncio.Queue[Event] = asyncio.Queue()
    sink = SpySink()
    proc = BatchProcessor(queue, sink, batch_max_size=3, batch_max_wait=10.0)

    task = asyncio.create_task(proc.run())
    for _ in range(3):
        await queue.put(_make_event())

    # Wait for flush
    for _ in range(20):
        if sink.batches:
            break
        await asyncio.sleep(0.05)

    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    assert len(sink.batches) >= 1
    assert sum(len(b) for b in sink.batches) == 3


@pytest.mark.asyncio
async def test_batch_flush_on_time():
    """Processor flushes after max_wait even with a partial batch."""
    queue: asyncio.Queue[Event] = asyncio.Queue()
    sink = SpySink()
    proc = BatchProcessor(queue, sink, batch_max_size=100, batch_max_wait=0.1)

    task = asyncio.create_task(proc.run())
    await queue.put(_make_event())

    for _ in range(20):
        if sink.batches:
            break
        await asyncio.sleep(0.05)

    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    assert len(sink.batches) >= 1


@pytest.mark.asyncio
async def test_retryable_error_retries():
    """RetryableSinkError triggers retries up to max_retries."""
    queue: asyncio.Queue[Event] = asyncio.Queue()
    call_count = 0

    class CountingSink(EventSink):
        name = "counting"

        async def write(self, batch: EventBatch) -> None:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise RetryableSinkError("transient")

    sink = CountingSink()
    proc = BatchProcessor(queue, sink, batch_max_size=1, batch_max_wait=10.0, max_retries=3)

    await queue.put(_make_event())
    task = asyncio.create_task(proc.run())

    for _ in range(40):
        if call_count >= 3:
            break
        await asyncio.sleep(0.05)

    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    assert call_count >= 3


@pytest.mark.asyncio
async def test_permanent_error_discards():
    """PermanentSinkError causes the batch to be discarded immediately."""
    queue: asyncio.Queue[Event] = asyncio.Queue()
    sink = SpySink()
    sink.side_effect = PermanentSinkError("fatal")
    proc = BatchProcessor(queue, sink, batch_max_size=1, batch_max_wait=10.0)

    await queue.put(_make_event())
    task = asyncio.create_task(proc.run())

    for _ in range(20):
        if proc.events_dropped > 0:
            break
        await asyncio.sleep(0.05)

    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    assert proc.events_dropped == 1
    assert proc.events_sent == 0


@pytest.mark.asyncio
async def test_retry_exhaustion_discards():
    """Exhausting all retries discards the batch."""
    queue: asyncio.Queue[Event] = asyncio.Queue()

    class AlwaysFails(EventSink):
        name = "always"

        async def write(self, batch: EventBatch) -> None:
            raise RetryableSinkError("always fails")

    proc = BatchProcessor(
        queue, AlwaysFails(), batch_max_size=1, batch_max_wait=10.0, max_retries=2
    )

    await queue.put(_make_event())
    task = asyncio.create_task(proc.run())

    for _ in range(60):
        if proc.events_dropped > 0:
            break
        await asyncio.sleep(0.05)

    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    assert proc.events_dropped == 1


@pytest.mark.asyncio
async def test_shutdown_drain():
    """stop() causes the processor to drain pending events before exiting."""
    queue: asyncio.Queue[Event] = asyncio.Queue()
    sink = SpySink()
    proc = BatchProcessor(queue, sink, batch_max_size=10, batch_max_wait=5.0)

    for _ in range(5):
        await queue.put(_make_event())

    task = asyncio.create_task(proc.run())
    await asyncio.sleep(0.05)
    await proc.stop()
    await asyncio.wait_for(task, timeout=3.0)

    assert proc.events_sent == 5


# ===========================================================================
# End-to-end: HTTP → ingest → UDS → processor → NullSink
# ===========================================================================


@pytest.mark.asyncio
async def test_end_to_end_http_to_null_sink():
    """Full pipeline: HTTP POST → ingest queue → UDS → processor → NullSink."""
    from unittest.mock import MagicMock

    from httpx2 import ASGITransport, AsyncClient

    from telemetria.config import IngestSettings
    from telemetria.ingest.resolver import ResolvedToken
    from telemetria.ingest.server import create_app
    from telemetria.ingest.writer import IPCWriter

    with tempfile.TemporaryDirectory() as tmpdir:
        sock_path = str(Path(tmpdir) / "e2e.sock")

        # --- Processor side ---
        proc_queue: asyncio.Queue[Event] = asyncio.Queue()
        uds_server = UDSServer(sock_path, proc_queue)
        await uds_server.start()

        null_sink = NullSink()
        processor = BatchProcessor(proc_queue, null_sink, batch_max_size=10, batch_max_wait=0.2)
        proc_task = asyncio.create_task(processor.run())

        # --- Ingest side ---
        ingest_settings = IngestSettings(queue_size=100, ipc_socket_path=sock_path)
        mock_resolver = MagicMock()
        mock_resolver.resolve = AsyncMock(
            return_value=ResolvedToken(
                token_id="token-1",
                app_id="00000000-0000-0000-0000-000000000002",
                app_slug="app",
                project_id="00000000-0000-0000-0000-000000000001",
                project_slug="proj",
            )
        )
        app = create_app(settings=ingest_settings)
        app.state.resolver = mock_resolver

        writer = IPCWriter(app.state.queue, sock_path)
        writer_task = asyncio.create_task(writer.run())

        headers = {"x-telemetria-token": "key", "content-type": "application/json"}
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                "/v1/ingest/batch",
                json={
                    "events": [
                        {"level": "info", "message": f"e2e-{i}", "payload": {}} for i in range(5)
                    ]
                },
                headers=headers,
            )
        assert r.status_code == 202
        assert r.json()["enqueued"] == 5

        # Wait for processor to consume all events
        for _ in range(40):
            if null_sink.written >= 5:
                break
            await asyncio.sleep(0.1)

        # Cleanup
        writer_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await writer_task
        await writer.close()

        await processor.stop()
        await asyncio.wait_for(proc_task, timeout=3.0)
        await uds_server.stop()

        assert null_sink.written == 5
