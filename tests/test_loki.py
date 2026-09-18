"""M3 unit tests for the Loki sink provider.

Tests cover:
- build_push_payload: labels, grouping, sorting, nanosecond timestamps
- Nanosecond strings are decimal strings, not JSON numbers
- Client timestamp preserved in line, received_at drives entry timestamp
- Gzip: compressed body + Content-Encoding header
- No compression: plain body, no Content-Encoding
- Tenant header set / not set
- Error mapping: timeout, network error, 429, 5xx → RetryableSinkError
- Error mapping: 4xx (not 429) → PermanentSinkError
- 2xx success → no error
- get_sink("loki") returns a LokiSink instance
"""

from __future__ import annotations

import gzip
import json
import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from telemetria.config import LokiSettings
from telemetria.domain.events import Event, EventBatch
from telemetria.sinks import get_sink
from telemetria.sinks.loki import LokiSink, _to_nanoseconds, build_push_payload

pytestmark = pytest.mark.unit

_T0 = datetime(2026, 9, 18, 17, 0, 0, 0, tzinfo=UTC)
_T1 = datetime(2026, 9, 18, 17, 0, 1, 0, tzinfo=UTC)
_UUID = uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")


def _event(
    *,
    project: str = "proj",
    app: str = "app",
    level: str = "info",
    message: str = "hello",
    received_at: datetime = _T0,
    timestamp: datetime = _T0,
    payload: dict[str, Any] | None = None,
) -> Event:
    return Event(
        id=uuid.uuid4(),
        project_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        project_slug=project,
        app_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
        app_slug=app,
        received_at=received_at,
        timestamp=timestamp,
        level=level,
        message=message,
        payload=payload or {},
    )


# ---------------------------------------------------------------------------
# build_push_payload — structure
# ---------------------------------------------------------------------------


def test_payload_stream_labels():
    """Labels on each stream contain service, project, app, level."""
    batch = EventBatch((_event(project="myproj", app="myapp", level="warn"),))
    payload = build_push_payload(batch)
    assert len(payload["streams"]) == 1
    labels = payload["streams"][0]["stream"]
    assert labels["service"] == "telemetria"
    assert labels["project"] == "myproj"
    assert labels["app"] == "myapp"
    assert labels["level"] == "warn"


def test_payload_groups_by_label_set():
    """Events with different label sets produce separate streams."""
    batch = EventBatch(
        (
            _event(project="p", app="a", level="info"),
            _event(project="p", app="a", level="error"),
            _event(project="p", app="b", level="info"),
        )
    )
    payload = build_push_payload(batch)
    assert len(payload["streams"]) == 3


def test_payload_merges_same_labels():
    """Events with identical labels are merged into one stream."""
    batch = EventBatch(
        (
            _event(project="p", app="a", level="info", message="first"),
            _event(project="p", app="a", level="info", message="second"),
        )
    )
    payload = build_push_payload(batch)
    assert len(payload["streams"]) == 1
    assert len(payload["streams"][0]["values"]) == 2


def test_payload_sorted_by_received_at():
    """Values within a stream are sorted by received_at ascending."""
    batch = EventBatch(
        (
            _event(received_at=_T1, message="later"),
            _event(received_at=_T0, message="earlier"),
        )
    )
    payload = build_push_payload(batch)
    values = payload["streams"][0]["values"]
    ts0 = int(values[0][0])
    ts1 = int(values[1][0])
    assert ts0 < ts1


# ---------------------------------------------------------------------------
# Timestamp: nanoseconds
# ---------------------------------------------------------------------------


def test_nanoseconds_is_string():
    """_to_nanoseconds must return a str, not int — Loki rejects JSON numbers."""
    ns = _to_nanoseconds(_event())
    assert isinstance(ns, str)
    # Must be parseable as a large integer
    assert int(ns) > 0


def test_nanoseconds_uses_received_at():
    """Entry timestamp is derived from received_at, not client timestamp."""
    client_ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    server_ts = datetime(2026, 9, 18, 17, 0, 0, tzinfo=UTC)
    event = _event(received_at=server_ts, timestamp=client_ts)
    ns = _to_nanoseconds(event)
    expected_ns = int(server_ts.timestamp() * 1_000_000_000)
    assert ns == str(expected_ns)


def test_client_timestamp_in_line_not_entry():
    """Client timestamp appears in the JSON line, never as the Loki entry timestamp."""
    client_ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    server_ts = datetime(2026, 9, 18, 17, 0, 0, tzinfo=UTC)
    event = _event(received_at=server_ts, timestamp=client_ts)
    batch = EventBatch((event,))
    payload = build_push_payload(batch)
    entry_ts_ns, line_json = payload["streams"][0]["values"][0]

    # Entry timestamp → received_at
    assert entry_ts_ns == str(int(server_ts.timestamp() * 1_000_000_000))

    # JSON line contains both timestamps
    line = json.loads(line_json)
    assert "received_at" in line
    assert "timestamp" in line
    assert "2026-01-01" in line["timestamp"]


def test_nanosecond_value_in_payload_is_string():
    """The value in the Loki push payload must be a JSON string, not number."""
    batch = EventBatch((_event(),))
    payload = build_push_payload(batch)
    raw = json.dumps(payload)
    # The nanosecond value should appear as a quoted string in the JSON
    ns = payload["streams"][0]["values"][0][0]
    assert f'"{ns}"' in raw


# ---------------------------------------------------------------------------
# Gzip compression
# ---------------------------------------------------------------------------


def _make_settings(**kwargs: Any) -> LokiSettings:
    defaults: dict[str, Any] = {
        "loki_url": "http://loki:3100",
        "loki_tenant_id": "",
        "loki_timeout_seconds": 5.0,
        "loki_compression": "gzip",
    }
    defaults.update(kwargs)
    return LokiSettings(**defaults)


async def _capture_request(
    sink: LokiSink,
    batch: EventBatch,
) -> tuple[dict[str, str], bytes]:
    """Run sink.write and capture the headers and raw body sent."""
    captured: dict[str, Any] = {}

    async def fake_post(url: str, content: bytes, headers: dict[str, str]) -> MagicMock:
        captured["headers"] = headers
        captured["body"] = content
        resp = MagicMock()
        resp.is_success = True
        resp.status_code = 204
        return resp

    sink._client.post = AsyncMock(side_effect=fake_post)  # type: ignore[method-assign]
    await sink.write(batch)
    return captured["headers"], captured["body"]


@pytest.mark.asyncio
async def test_gzip_body_and_header():
    """With compression=gzip, body is gzip bytes and Content-Encoding is set."""
    sink = LokiSink(_make_settings(loki_compression="gzip"))
    batch = EventBatch((_event(),))
    headers, body = await _capture_request(sink, batch)

    assert headers.get("Content-Encoding") == "gzip"
    # Body must be valid gzip
    decoded = gzip.decompress(body)
    payload = json.loads(decoded)
    assert "streams" in payload
    await sink.close()


@pytest.mark.asyncio
async def test_no_compression():
    """With compression off, body is plain JSON and no Content-Encoding header."""
    sink = LokiSink(_make_settings(loki_compression=""))
    batch = EventBatch((_event(),))
    headers, body = await _capture_request(sink, batch)

    assert "Content-Encoding" not in headers
    payload = json.loads(body)
    assert "streams" in payload
    await sink.close()


# ---------------------------------------------------------------------------
# Tenant header
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tenant_header_set():
    """X-Scope-OrgID header is added when loki_tenant_id is non-empty."""
    sink = LokiSink(_make_settings(loki_tenant_id="mytenant", loki_compression=""))
    batch = EventBatch((_event(),))
    headers, _ = await _capture_request(sink, batch)
    assert headers.get("X-Scope-OrgID") == "mytenant"
    await sink.close()


@pytest.mark.asyncio
async def test_no_tenant_header_when_empty():
    """X-Scope-OrgID is absent when loki_tenant_id is empty."""
    sink = LokiSink(_make_settings(loki_tenant_id="", loki_compression=""))
    batch = EventBatch((_event(),))
    headers, _ = await _capture_request(sink, batch)
    assert "X-Scope-OrgID" not in headers
    await sink.close()


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------


def _sink_with_response(status: int, text: str = "") -> LokiSink:
    """Return a LokiSink whose HTTP client returns a fixed response."""
    import httpx2

    sink = LokiSink(_make_settings(loki_compression=""))

    resp = MagicMock(spec=httpx2.Response)
    resp.is_success = 200 <= status < 300
    resp.status_code = status
    resp.text = text

    sink._client.post = AsyncMock(return_value=resp)  # type: ignore[method-assign]
    return sink


@pytest.mark.asyncio
async def test_success_204():
    """2xx response does not raise."""
    sink = _sink_with_response(204)
    await sink.write(EventBatch((_event(),)))
    await sink.close()


@pytest.mark.asyncio
async def test_429_retryable():
    """HTTP 429 raises RetryableSinkError."""
    from telemetria.sinks import RetryableSinkError

    sink = _sink_with_response(429)
    with pytest.raises(RetryableSinkError):
        await sink.write(EventBatch((_event(),)))
    await sink.close()


@pytest.mark.asyncio
async def test_500_retryable():
    """HTTP 500 raises RetryableSinkError."""
    from telemetria.sinks import RetryableSinkError

    sink = _sink_with_response(500)
    with pytest.raises(RetryableSinkError):
        await sink.write(EventBatch((_event(),)))
    await sink.close()


@pytest.mark.asyncio
async def test_503_retryable():
    """HTTP 503 raises RetryableSinkError."""
    from telemetria.sinks import RetryableSinkError

    sink = _sink_with_response(503)
    with pytest.raises(RetryableSinkError):
        await sink.write(EventBatch((_event(),)))
    await sink.close()


@pytest.mark.asyncio
async def test_400_permanent():
    """HTTP 400 raises PermanentSinkError."""
    from telemetria.sinks import PermanentSinkError

    sink = _sink_with_response(400)
    with pytest.raises(PermanentSinkError):
        await sink.write(EventBatch((_event(),)))
    await sink.close()


@pytest.mark.asyncio
async def test_401_permanent():
    """HTTP 401 raises PermanentSinkError."""
    from telemetria.sinks import PermanentSinkError

    sink = _sink_with_response(401)
    with pytest.raises(PermanentSinkError):
        await sink.write(EventBatch((_event(),)))
    await sink.close()


@pytest.mark.asyncio
async def test_timeout_retryable():
    """Network timeout raises RetryableSinkError."""
    import httpx2

    from telemetria.sinks import RetryableSinkError

    sink = LokiSink(_make_settings(loki_compression=""))
    sink._client.post = AsyncMock(  # type: ignore[method-assign]
        side_effect=httpx2.TimeoutException("timed out")
    )
    with pytest.raises(RetryableSinkError):
        await sink.write(EventBatch((_event(),)))
    await sink.close()


@pytest.mark.asyncio
async def test_network_error_retryable():
    """Network error raises RetryableSinkError."""
    import httpx2

    from telemetria.sinks import RetryableSinkError

    sink = LokiSink(_make_settings(loki_compression=""))
    sink._client.post = AsyncMock(  # type: ignore[method-assign]
        side_effect=httpx2.NetworkError("connection refused")
    )
    with pytest.raises(RetryableSinkError):
        await sink.write(EventBatch((_event(),)))
    await sink.close()


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_get_sink_loki_returns_loki_sink():
    """get_sink('loki') returns a LokiSink without crashing."""
    with patch("telemetria.sinks.loki.LokiSettings", return_value=_make_settings()):
        sink = get_sink("loki")
    assert isinstance(sink, LokiSink)
    assert sink.name == "loki"
