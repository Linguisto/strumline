# Sinks

The processor forwards event batches to a configurable sink. The sink is the only component that touches external storage or log aggregation — PostgreSQL, the IPC layer, and the ingest HTTP server have no sink dependency.

## Sink contract

Every provider implements the `EventSink` ABC from `telemetria.sinks`:

```python
class EventSink(ABC):
    name: str                                        # used in metrics labels

    async def write(self, batch: EventBatch) -> None: ...
    async def close(self) -> None: ...               # called on graceful shutdown
```

`write()` must raise one of two typed errors or return cleanly:

| Error                | Meaning                                    | Processor action                       |
|----------------------|--------------------------------------------|----------------------------------------|
| `RetryableSinkError` | Transient failure — network, rate-limit, server error | Retry with exponential backoff + ±10 % jitter, up to `SINK_MAX_RETRIES` |
| `PermanentSinkError` | Non-recoverable — bad request, auth failure, config error | Discard batch immediately, increment `events_dropped` counter |

After `SINK_MAX_RETRIES` retryable attempts the batch is also discarded and counted.
Bare `Exception` from `write()` is treated as permanent — it is caught, logged, and the batch discarded.

`BatchProcessor` never inspects HTTP status codes or provider internals. All provider-specific logic lives behind this interface.

## Providers

### `null` (discard)

Drops every event silently. Useful for testing the ingest/processor pipeline without a running log backend, or for benchmarking throughput with zero sink overhead.

```
SINK_PROVIDER=null
```

### `loki` (Grafana Loki — default)

Pushes batches to the [Loki push API](https://grafana.com/docs/loki/latest/reference/loki-http-api/#ingest-logs).

```
SINK_PROVIDER=loki
LOKI_URL=http://loki:3100
```

See [configuration reference](configuration.md#loki-sink-sink_providerloki) for all Loki settings.

#### Loki mapping

Each event becomes one log line in a stream. Streams are keyed on low-cardinality labels:

| Loki label  | Value                                      |
|-------------|--------------------------------------------|
| `service`   | `telemetria` (constant)                    |
| `project`   | `Event.project_slug`                       |
| `app`       | `Event.app_slug`                           |
| `level`     | `Event.level`                              |

The JSON log line contains:

```json
{
  "id": "<uuid>",
  "received_at": "2026-09-18T17:00:00.000000Z",
  "timestamp": "2026-09-18T16:59:59.123456Z",
  "level": "info",
  "message": "...",
  "payload": { ... }
}
```

The **entry timestamp** (the value Loki uses for storage ordering) is always `received_at` expressed as integer nanoseconds. The client `timestamp` is metadata inside the line only and never controls Loki ordering.

#### Error mapping

| Condition                                    | Error raised           |
|----------------------------------------------|------------------------|
| Network error, connection refused, DNS failure | `RetryableSinkError`  |
| Request timeout (`LOKI_TIMEOUT_SECONDS`)     | `RetryableSinkError`   |
| HTTP 429 Too Many Requests                   | `RetryableSinkError`   |
| HTTP 5xx                                     | `RetryableSinkError`   |
| HTTP 4xx (other than 429)                    | `PermanentSinkError`   |

#### Loki compose service

The bundled `loki` service starts with the base stack (`docker compose up -d`). You can also point `LOKI_URL` at an external Loki instance and remove the bundled service entirely.

## Failure taxonomy

OTLP success acknowledges queue admission, not sink delivery. Later failures
cannot change that HTTP response. Ingest rejections are reported synchronously:

| Stage                     | Counter                          | Cause                                      |
|---------------------------|----------------------------------|--------------------------------------------|
| Ingest queue full         | HTTP `503` (retryable, no admission) | Insufficient batch capacity |
| Normalized size rejection | `ingest_events_dropped_total{reason="otlp_normalized_size"}` | Records exceeding per-frame or cumulative payload limits; reported as OTLP partial success |
| IPC write failure         | `ingest_events_dropped_total{reason="ipc_write_failure"}` | Writer disconnected mid-write and the event could not be re-queued for retry (queue full) |
| Processor queue full      | `processor_events_dropped_total{reason="queue_full"}` | UDS server queue at capacity               |
| Sink permanent failure    | `processor_events_dropped_total{reason="sink_permanent"}` | Provider rejects batch permanently         |
| Sink retries exhausted    | `processor_events_dropped_total{reason="sink_retries_exhausted"}` | All `SINK_MAX_RETRIES` attempts failed     |

Retries may produce duplicate event IDs in the sink (e.g. Loki accepted the batch but the ACK was lost). The event `id` field allows downstream deduplication.

## Adding a new provider

1. Create `telemetria/sinks/<name>.py` implementing `EventSink`.
2. Add `"<name>": "telemetria.sinks.<name>.<ClassName>"` to `_LAZY_PROVIDERS` in `telemetria/sinks/__init__.py`.
3. Add provider settings to `telemetria/config.py` as a new `<Name>Settings` class.
4. Document the provider in this file and in `docs/configuration.md`.
5. Add unit tests in `tests/test_<name>.py` — at minimum: happy path, retryable errors, permanent errors, and a round-trip payload test.

The processor does **not** need to change. `BatchProcessor` calls `get_sink(settings.sink_provider)` once at startup; everything else flows through the `EventSink` interface.
