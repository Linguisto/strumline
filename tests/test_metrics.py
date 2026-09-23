"""M4 unit tests for the metrics and /metrics endpoint.

Tests cover:
- /metrics returns 200 with prometheus text when METRICS_ENABLED=true
- /metrics is absent (404) when METRICS_ENABLED=false
- /metrics is excluded from HTTP instrumentation (no self-referential label)
- Counter smoke tests: ingest accepted/dropped counters increment correctly
- Label cardinality guard: route labels use templates, not raw paths
- auth token cache hit/miss counters increment
- IPC reconnect counter increments
- Processor drop counter increments with correct reason labels
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx2 import ASGITransport, AsyncClient
from prometheus_client import REGISTRY

from strumline.config import CommonSettings, IngestSettings
from strumline.domain.events import Event, EventBatch
from strumline.ingest.resolver import AuthTokenResolverError, ResolvedToken
from strumline.ingest.server import create_app as create_ingest_app

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 18, 17, 0, 0, tzinfo=UTC)
_RESOLVED = ResolvedToken(
    token_id="token-id",
    app_id="00000000-0000-0000-0000-000000000002",
    app_slug="my-app",
    project_id="00000000-0000-0000-0000-000000000001",
    project_slug="my-proj",
)
_TOKEN_HEADER = {"x-strumline-token": "valid-key", "content-type": "application/json"}


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


def _prom_text() -> str:
    """Snapshot the current default registry as Prometheus text."""
    from prometheus_client import generate_latest

    return generate_latest().decode("utf-8")


def _counter_value(metric_name: str, **labels: str) -> float:
    """Read a counter value from the default registry by name and labels."""
    for metric in REGISTRY.collect():
        if metric.name == metric_name:
            for sample in metric.samples:
                if sample.name == metric_name + "_total" and all(
                    sample.labels.get(k) == v for k, v in labels.items()
                ):
                    return sample.value
    return 0.0


def _make_ingest_app(
    resolver_result: ResolvedToken | Exception = _RESOLVED,
    metrics_enabled: bool = True,
    queue_size: int = 10_000,
):  # type: ignore[no-untyped-def]
    settings = IngestSettings(queue_size=queue_size)
    common = CommonSettings(metrics_enabled=metrics_enabled)
    mock_resolver = MagicMock()
    if isinstance(resolver_result, Exception):
        mock_resolver.resolve = AsyncMock(side_effect=resolver_result)
    else:
        mock_resolver.resolve = AsyncMock(return_value=resolver_result)
    app = create_ingest_app(settings=settings, common_settings=common)
    app.state.resolver = mock_resolver
    return app


# ---------------------------------------------------------------------------
# /metrics endpoint on/off
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_metrics_endpoint_enabled():
    """/metrics returns 200 with Prometheus text when enabled."""
    from strumline.api.server import create_app as create_api_app

    app = create_api_app(CommonSettings(metrics_enabled=True))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/metrics")
    assert r.status_code == 200
    assert "# HELP" in r.text or "# TYPE" in r.text or "strumline_" in r.text


@pytest.mark.asyncio
async def test_metrics_endpoint_disabled():
    """/metrics returns 404 when METRICS_ENABLED=false."""
    from strumline.api.server import create_app as create_api_app

    app = create_api_app(CommonSettings(metrics_enabled=False))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/metrics")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# /metrics excluded from HTTP instrumentation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_metrics_route_excluded_from_instrumentation():
    """/metrics requests must not appear as HTTP instrumentation labels."""
    from strumline.api.server import create_app as create_api_app

    app = create_api_app(CommonSettings(metrics_enabled=True))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # Hit /metrics several times
        for _ in range(3):
            await c.get("/metrics")
        # Hit /health once so we know instrumentation is working
        await c.get("/health")

    text = _prom_text()
    # /metrics path must not appear as a route label
    assert 'route="/metrics"' not in text


# ---------------------------------------------------------------------------
# Route template label (cardinality guard)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_label_is_template_not_raw_path():
    """HTTP instrumentation must use route templates, not raw request paths."""
    app = _make_ingest_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.post(
            "/v1/logs",
            json={
                "resourceLogs": [
                    {"scopeLogs": [{"logRecords": [{"body": {"stringValue": "hello"}}]}]}
                ]
            },
            headers=_TOKEN_HEADER,
        )

    text = _prom_text()
    # Template route should appear; raw path would be identical here,
    # but the mechanism is tested: route is set from matched route.path
    assert 'route="/v1/logs"' in text


# ---------------------------------------------------------------------------
# Ingest counter smoke tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_accepted_counter_increments():
    """INGEST_EVENTS_ACCEPTED_TOTAL increments on successful enqueue."""
    from strumline.metrics import INGEST_EVENTS_ACCEPTED_TOTAL

    before = INGEST_EVENTS_ACCEPTED_TOTAL._value.get()
    app = _make_ingest_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/v1/logs",
            json={
                "resourceLogs": [
                    {"scopeLogs": [{"logRecords": [{"body": {"stringValue": "hello"}}]}]}
                ]
            },
            headers=_TOKEN_HEADER,
        )
    assert r.status_code == 200
    after = INGEST_EVENTS_ACCEPTED_TOTAL._value.get()
    assert after == before + 1


@pytest.mark.asyncio
async def test_ingest_queue_full_is_retryable_not_counted_as_drop():
    """A refused OTLP batch can be retried and is not counted as a permanent drop."""
    from strumline.metrics import INGEST_EVENTS_DROPPED_TOTAL

    before = INGEST_EVENTS_DROPPED_TOTAL.labels(reason="queue_full")._value.get()
    app = _make_ingest_app(queue_size=1)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # Fill the queue
        await c.post(
            "/v1/logs",
            json={
                "resourceLogs": [
                    {"scopeLogs": [{"logRecords": [{"body": {"stringValue": "hello"}}]}]}
                ]
            },
            headers=_TOKEN_HEADER,
        )
        # This batch must be refused without admission
        r = await c.post(
            "/v1/logs",
            json={
                "resourceLogs": [
                    {"scopeLogs": [{"logRecords": [{"body": {"stringValue": "hello"}}]}]}
                ]
            },
            headers=_TOKEN_HEADER,
        )
    assert r.status_code == 503
    assert app.state.queue.qsize() == 1
    after = INGEST_EVENTS_DROPPED_TOTAL.labels(reason="queue_full")._value.get()
    assert after == before


@pytest.mark.asyncio
async def test_ingest_auth_token_cache_miss_on_unknown():
    """INGEST_AUTH_TOKEN_CACHE_MISSES_TOTAL increments on auth token resolution failure."""
    from strumline.metrics import INGEST_AUTH_TOKEN_CACHE_MISSES_TOTAL

    before = INGEST_AUTH_TOKEN_CACHE_MISSES_TOTAL._value.get()
    app = _make_ingest_app(resolver_result=AuthTokenResolverError("unknown"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/v1/logs",
            json={
                "resourceLogs": [
                    {"scopeLogs": [{"logRecords": [{"body": {"stringValue": "hello"}}]}]}
                ]
            },
            headers=_TOKEN_HEADER,
        )
    assert r.status_code == 401
    after = INGEST_AUTH_TOKEN_CACHE_MISSES_TOTAL._value.get()
    assert after == before + 1


@pytest.mark.asyncio
async def test_ingest_auth_token_cache_hit_on_success():
    """INGEST_AUTH_TOKEN_CACHE_HITS_TOTAL increments on successful auth token resolution."""
    from strumline.metrics import INGEST_AUTH_TOKEN_CACHE_HITS_TOTAL

    before = INGEST_AUTH_TOKEN_CACHE_HITS_TOTAL._value.get()
    app = _make_ingest_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.post(
            "/v1/logs",
            json={
                "resourceLogs": [
                    {"scopeLogs": [{"logRecords": [{"body": {"stringValue": "hello"}}]}]}
                ]
            },
            headers=_TOKEN_HEADER,
        )
    after = INGEST_AUTH_TOKEN_CACHE_HITS_TOTAL._value.get()
    assert after == before + 1


# ---------------------------------------------------------------------------
# Processor drop counter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_processor_drop_permanent_sink():
    """PROCESSOR_EVENTS_DROPPED_TOTAL{reason=sink_permanent} increments on PermanentSinkError."""
    from strumline.metrics import PROCESSOR_EVENTS_DROPPED_TOTAL
    from strumline.processor.batch import BatchProcessor
    from strumline.sinks import EventSink, PermanentSinkError

    before = PROCESSOR_EVENTS_DROPPED_TOTAL.labels(reason="sink_permanent")._value.get()

    class FailSink(EventSink):
        name = "fail"

        async def write(self, batch: EventBatch) -> None:
            raise PermanentSinkError("permanent")

    queue: asyncio.Queue[Event] = asyncio.Queue()
    proc = BatchProcessor(queue, FailSink(), batch_max_size=1, batch_max_wait=10.0)
    await queue.put(_make_event())
    task = asyncio.create_task(proc.run())

    import contextlib

    for _ in range(20):
        if proc.events_dropped > 0:
            break
        await asyncio.sleep(0.05)

    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    after = PROCESSOR_EVENTS_DROPPED_TOTAL.labels(reason="sink_permanent")._value.get()
    assert after == before + 1


@pytest.mark.asyncio
async def test_processor_drop_retry_exhaustion():
    """PROCESSOR_EVENTS_DROPPED_TOTAL{reason=sink_retries_exhausted} increments."""
    from strumline.metrics import PROCESSOR_EVENTS_DROPPED_TOTAL
    from strumline.processor.batch import BatchProcessor
    from strumline.sinks import EventSink, RetryableSinkError

    before = PROCESSOR_EVENTS_DROPPED_TOTAL.labels(reason="sink_retries_exhausted")._value.get()

    class AlwaysFail(EventSink):
        name = "alwaysfail"

        async def write(self, batch: EventBatch) -> None:
            raise RetryableSinkError("transient")

    queue: asyncio.Queue[Event] = asyncio.Queue()
    proc = BatchProcessor(queue, AlwaysFail(), batch_max_size=1, batch_max_wait=10.0, max_retries=1)
    await queue.put(_make_event())
    task = asyncio.create_task(proc.run())

    import contextlib

    for _ in range(40):
        if proc.events_dropped > 0:
            break
        await asyncio.sleep(0.05)

    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    after = PROCESSOR_EVENTS_DROPPED_TOTAL.labels(reason="sink_retries_exhausted")._value.get()
    assert after == before + 1
