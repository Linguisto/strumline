"""M7 resilience tests.

Covers:
- Processor restart with stale UDS socket (ingest writer reconnects)
- Queue saturation under OTLP load (atomic retryable 503, no partial admission)
- Graceful shutdown drain (BatchProcessor drains queue before stopping)
- UTC invariant: IPC frames carry Z-suffixed timestamps
- UTC invariant: Loki entry timestamp uses received_at, not client timestamp
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from telemetria.config import IngestSettings
from telemetria.domain.events import Event, EventBatch
from telemetria.ingest.resolver import ResolvedToken
from telemetria.ingest.server import create_app
from telemetria.ingest.writer import IPCWriter
from telemetria.ipc.codec import decode_envelope_body, encode_frame
from telemetria.processor.batch import BatchProcessor
from telemetria.processor.uds_server import UDSServer
from telemetria.sinks import EventSink
from telemetria.sinks.loki import build_push_payload

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 18, 17, 0, 0, tzinfo=UTC)
_RESOLVED = ResolvedToken(
    token_id="tok",
    app_id="00000000-0000-0000-0000-000000000002",
    app_slug="app",
    project_id="00000000-0000-0000-0000-000000000001",
    project_slug="proj",
)


def _make_event(**kwargs) -> Event:  # type: ignore[no-untyped-def]
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


def _make_ingest_app(**settings: object) -> object:
    app = create_app(settings=IngestSettings(**settings))
    app.state.resolver = MagicMock(resolve=AsyncMock(return_value=_RESOLVED))  # type: ignore[attr-defined]
    return app


# ---------------------------------------------------------------------------
# Processor restart with stale UDS socket
# ---------------------------------------------------------------------------


async def test_processor_restart_reconnects_writer() -> None:
    """Ingest writer reconnects when the processor restarts and recreates the socket.

    Sequence:
    1. Start UDS server (processor side) and writer.
    2. Write one event — verify it arrives.
    3. Stop the UDS server (simulates processor crash / stale socket).
    4. Start a new UDS server on the same path immediately.
    5. Write another event — writer should reconnect and deliver it.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        sock_path = str(Path(tmpdir) / "ipc.sock")
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=100)

        # First server
        server1 = UDSServer(sock_path, queue)
        await server1.start()

        ingest_queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=100)
        writer = IPCWriter(ingest_queue, sock_path)
        writer_task = asyncio.create_task(writer.run())

        # Send first event and confirm delivery
        event1 = _make_event(message="before-restart")
        await ingest_queue.put(event1)
        received1 = await asyncio.wait_for(queue.get(), timeout=3.0)
        assert received1.message == "before-restart"

        # Simulate processor crash: stop server1 with a timeout since it has an
        # active connection; the handler will be interrupted when the server closes.
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(server1.stop(), timeout=1.0)

        # Start second server immediately — writer will reconnect on next attempt
        server2 = UDSServer(sock_path, queue)
        await server2.start()

        # Enqueue the second event; writer will deliver it once reconnected
        event2 = _make_event(message="after-restart")
        await ingest_queue.put(event2)
        received2 = await asyncio.wait_for(queue.get(), timeout=8.0)
        assert received2.message == "after-restart"

        # Cleanup
        writer_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await writer_task
        await writer.close()
        await server2.stop()


# ---------------------------------------------------------------------------
# Queue saturation under OTLP load
# ---------------------------------------------------------------------------


async def test_queue_saturation_is_atomic_no_partial_admission() -> None:
    """Under OTLP load, queue-full returns 503 without admitting any records.

    Send enough batches to fill the queue completely, then verify:
    - All admitted batches return 200.
    - The first batch that can't fit returns 503.
    - Queue depth never exceeds maxsize.
    - After draining, a new batch is accepted.
    """
    from httpx2 import ASGITransport, AsyncClient

    from telemetria.ingest.otlp import encode_frame as _ef  # noqa: F401 — local encode check

    queue_size = 3
    app = _make_ingest_app(queue_size=queue_size)

    single_record = {
        "resourceLogs": [
            {"scopeLogs": [{"logRecords": [{"severityNumber": 9, "body": {"stringValue": "x"}}]}]}
        ]
    }
    headers = {"x-telemetria-token": "t", "content-type": "application/json"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Fill the queue exactly
        for _ in range(queue_size):
            r = await client.post("/v1/logs", json=single_record, headers=headers)
            assert r.status_code == 200

        assert app.state.queue.qsize() == queue_size  # type: ignore[attr-defined]

        # One more must fail retryably without admission
        r = await client.post("/v1/logs", json=single_record, headers=headers)
        assert r.status_code == 503
        assert app.state.queue.qsize() == queue_size  # unchanged  # type: ignore[attr-defined]

        # Drain one event
        app.state.queue.get_nowait()  # type: ignore[attr-defined]

        # Now it fits again
        r = await client.post("/v1/logs", json=single_record, headers=headers)
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Graceful shutdown drain
# ---------------------------------------------------------------------------


async def test_graceful_shutdown_drains_queue() -> None:
    """BatchProcessor.stop() waits for the queue to drain before returning."""

    class CountingSink(EventSink):
        name = "counting"
        written = 0

        async def write(self, batch: EventBatch) -> None:
            await asyncio.sleep(0.02)  # simulate a small write delay
            self.written += len(batch)

    sink = CountingSink()
    queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=50)
    processor = BatchProcessor(queue, sink, batch_max_size=5, batch_max_wait=0.05)
    proc_task = asyncio.create_task(processor.run())

    # Enqueue 10 events
    for _ in range(10):
        await queue.put(_make_event())

    # Stop — should drain all events before returning
    await processor.stop()
    with contextlib.suppress(asyncio.CancelledError):
        await asyncio.wait_for(proc_task, timeout=3.0)

    assert sink.written == 10


# ---------------------------------------------------------------------------
# UTC invariant: IPC serialization emits Z
# ---------------------------------------------------------------------------


def test_ipc_timestamps_use_utc_z_suffix() -> None:
    """encode_frame must emit both timestamps with trailing Z."""
    event = _make_event(
        received_at=datetime(2026, 9, 18, 17, 0, 0, 0, tzinfo=UTC),
        timestamp=datetime(2026, 9, 18, 16, 59, 59, 123456, tzinfo=UTC),
    )
    frame = encode_frame(event)
    body = json.loads(frame[4:])
    assert body["event"]["received_at"].endswith("Z")
    assert body["event"]["timestamp"].endswith("Z")
    # Roundtrip: decoded timestamps must be UTC-aware
    decoded = decode_envelope_body(frame[4:])
    assert decoded.received_at.tzinfo is not None
    assert decoded.received_at.utcoffset() == timedelta(0)
    assert decoded.timestamp.tzinfo is not None
    assert decoded.timestamp.utcoffset() == timedelta(0)


# ---------------------------------------------------------------------------
# UTC invariant: Loki uses received_at as entry timestamp
# ---------------------------------------------------------------------------


def test_loki_entry_timestamp_uses_received_at_not_client_timestamp() -> None:
    """Loki push payload must use received_at for the entry timestamp.

    The client timestamp is preserved inside the JSON line as metadata
    but never controls Loki storage ordering.
    """
    received_at = datetime(2026, 9, 18, 17, 0, 0, 0, tzinfo=UTC)
    client_ts = datetime(2026, 9, 17, 12, 0, 0, 0, tzinfo=UTC)  # day before
    event = _make_event(received_at=received_at, timestamp=client_ts)

    push = build_push_payload(EventBatch((event,)))
    stream = push["streams"][0]
    entry_ts_ns, line_json = stream["values"][0]

    # Entry timestamp must be received_at in nanoseconds (decimal string)
    expected_ns = str(int(received_at.timestamp() * 1e9))
    assert entry_ts_ns == expected_ns

    # Client timestamp must be in the line metadata, not controlling entry order
    line = json.loads(line_json)
    assert line["received_at"].endswith("Z")
    assert line["timestamp"].endswith("Z")
    assert line["received_at"] != line["timestamp"]
    # received_at in line must match the entry timestamp
    assert "2026-09-18" in line["received_at"]
    assert "2026-09-17" in line["timestamp"]
