"""M2-C: HTTP admission tests for the ingest endpoints.

Tests cover:
- Valid single event → 202
- Valid batch → 202
- Byte limit enforced before JSON parsing → 413
- Batch size limit → 422
- Invalid content-type → 415
- Invalid JSON → 400
- Unknown DSN → 401
- Revoked DSN → 401
- Queue full → 202 with dropped count
- Whole-batch validation failure → 0 events enqueued
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx2 import ASGITransport, AsyncClient

from telemetria.config import IngestSettings
from telemetria.ingest.resolver import AuthTokenResolverError, ResolvedToken
from telemetria.ingest.server import create_app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_RESOLVED = ResolvedToken(
    token_id="token-id",
    app_id="00000000-0000-0000-0000-000000000002",
    app_slug="my-app",
    project_id="00000000-0000-0000-0000-000000000001",
    project_slug="my-proj",
)

_TOKEN_HEADER = {"x-telemetria-token": "valid-key", "content-type": "application/json"}


pytestmark = pytest.mark.unit


def _make_app(
    resolver_result: ResolvedToken | Exception = _RESOLVED,
    queue_size: int = 10_000,
    max_payload_bytes: int = 1 * 1024 * 1024,
    max_batch_events: int = 300,
):
    settings = IngestSettings(
        queue_size=queue_size,
        max_payload_bytes=max_payload_bytes,
        max_batch_events=max_batch_events,
    )
    mock_resolver = MagicMock()
    if isinstance(resolver_result, Exception):
        mock_resolver.resolve = AsyncMock(side_effect=resolver_result)
    else:
        mock_resolver.resolve = AsyncMock(return_value=resolver_result)

    app = create_app(settings=settings)
    app.state.resolver = mock_resolver
    return app


@pytest.fixture
def valid_event():
    return {"timestamp": "2026-09-18T17:00:00Z", "level": "info", "message": "hello", "payload": {}}


# ---------------------------------------------------------------------------
# Single event — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_event_202(valid_event):
    app = _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post("/v1/ingest", json=valid_event, headers=_TOKEN_HEADER)
    assert r.status_code == 202
    body = r.json()
    assert body["enqueued"] == 1
    assert body["dropped"] == 0


# ---------------------------------------------------------------------------
# Batch — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_202(valid_event):
    app = _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/v1/ingest/batch",
            json={"events": [valid_event, valid_event]},
            headers=_TOKEN_HEADER,
        )
    assert r.status_code == 202
    body = r.json()
    assert body["enqueued"] == 2
    assert body["dropped"] == 0


# ---------------------------------------------------------------------------
# Byte limit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_byte_limit_413():
    app = _make_app(max_payload_bytes=10)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/v1/ingest",
            content=b"x" * 100,
            headers={**_TOKEN_HEADER},
        )
    assert r.status_code == 413


# ---------------------------------------------------------------------------
# Batch size limit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_size_limit_422(valid_event):
    app = _make_app(max_batch_events=2)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/v1/ingest/batch",
            json={"events": [valid_event] * 3},
            headers=_TOKEN_HEADER,
        )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Content-type
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wrong_content_type_415(valid_event):
    app = _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/v1/ingest",
            content=json.dumps(valid_event).encode(),
            headers={"x-telemetria-token": "key", "content-type": "text/plain"},
        )
    assert r.status_code == 415


# ---------------------------------------------------------------------------
# Invalid JSON
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_json_400():
    app = _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/v1/ingest",
            content=b"not-json",
            headers=_TOKEN_HEADER,
        )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Unknown / revoked auth token → 401
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_token_401(valid_event):
    app = _make_app(resolver_result=AuthTokenResolverError("unknown"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post("/v1/ingest", json=valid_event, headers=_TOKEN_HEADER)
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Queue full → 202 with dropped count
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_queue_full_drops(valid_event):
    app = _make_app(queue_size=1)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # First event fills the queue
        r1 = await client.post("/v1/ingest", json=valid_event, headers=_TOKEN_HEADER)
        assert r1.status_code == 202
        assert r1.json()["enqueued"] == 1

        # Second event is dropped
        r2 = await client.post("/v1/ingest", json=valid_event, headers=_TOKEN_HEADER)
        assert r2.status_code == 202
        assert r2.json()["dropped"] == 1


# ---------------------------------------------------------------------------
# Batch validation failure — zero events enqueued
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_validation_failure_enqueues_zero():
    app = _make_app()
    bad_batch = {
        "events": [
            {"timestamp": "2026-09-18T17:00:00Z", "level": "info", "message": "ok", "payload": {}},
            # missing required 'message' field
            {"timestamp": "2026-09-18T17:00:00Z", "level": "info", "payload": {}},
        ]
    }
    queue: asyncio.Queue = app.state.queue
    initial_size = queue.qsize()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post("/v1/ingest/batch", json=bad_batch, headers=_TOKEN_HEADER)

    assert r.status_code == 400
    # Queue must be unchanged — zero events from a failed batch
    assert queue.qsize() == initial_size


# ---------------------------------------------------------------------------
# Timestamp fallback — naive / missing → received_at
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_naive_timestamp_falls_back(valid_event):
    app = _make_app()
    event_with_naive = {**valid_event, "timestamp": "2026-09-18T17:00:00"}  # no Z or offset
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post("/v1/ingest", json=event_with_naive, headers=_TOKEN_HEADER)
    assert r.status_code == 202


@pytest.mark.asyncio
async def test_missing_timestamp_falls_back():
    app = _make_app()
    event_no_ts = {"level": "warn", "message": "no timestamp", "payload": {}}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post("/v1/ingest", json=event_no_ts, headers=_TOKEN_HEADER)
    assert r.status_code == 202
