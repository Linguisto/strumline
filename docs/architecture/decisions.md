# Architecture decisions

This document records accepted invariants, topology, and deferred scope for Telemetria.
It is established in M0 and expanded per feature milestone.

## Topology (v1)

One host, one image, three containers:

```
telemetria-api        :8000  control plane health; admin REST API (M6b)
telemetria-ingest     :8001  HTTP ingestion and IPC writer
telemetria-processor  :8002  IPC reader, batching, sink dispatch
```

Ingest and processor share a Unix-domain-socket directory via a named Docker volume.
PostgreSQL stores control-plane metadata only. Raw telemetry is never written to PostgreSQL.

## UTC storage invariant

- Every persisted, transmitted, logged, and sink-facing canonical timestamp is timezone-aware UTC.
- PostgreSQL columns use `TIMESTAMPTZ`; sessions run in UTC (`SET TIME ZONE 'UTC'`).
- JSON APIs serialize canonical timestamps with a trailing `Z`.
- Client timestamps must include `Z` or an explicit offset and are normalized to UTC on receipt.
  Missing, naive, or unparseable client timestamps fall back to server `received_at` (UTC).
- Loki uses server `received_at` as its entry timestamp.
  A valid client timestamp remains event data/metadata and never controls storage ordering.
- `App.timezone` is an optional IANA key used exclusively for human-facing display.
  Display precedence: app timezone → `APP_TIMEZONE` env var → UTC.
  Localized display fields are explicit additions and never replace canonical UTC fields.

## Import boundaries

```
ingest/     may import: domain/, ipc/, metrics/, db/ (read-only auth token resolver)
processor/  may import: domain/, ipc/, metrics/, sinks/ (contract + factory only)
control/    shared by cli/ and api/; neither imports the data plane
ipc/        may import: domain/ only
```

Import-linter enforces these boundaries from the milestone where each package appears.
Boundary contracts expand as packages are added; they are never retroactively relaxed.

## Sink contract

```python
class EventSink(ABC):
    name: str
    async def write(self, batch: EventBatch) -> None: ...
    async def close(self) -> None: ...

class RetryableSinkError(Exception): ...
class PermanentSinkError(Exception): ...
```

`BatchProcessor` depends only on this contract, not on provider implementations.
`telemetria.sinks` owns the registry/factory; provider is selected by `SINK_PROVIDER`.
Retryable failures use exponential backoff with jitter.
Permanent failures and retry-exhausted batches are counted and discarded.

## Best-effort semantics

`202 Accepted` means authentication and validation succeeded and enqueue was attempted.
It does not guarantee delivery. The following may lose events without surfacing an error
to the HTTP caller: queue pressure, process failure, IPC failure, exhausted sink retries.
Retries may produce duplicate event IDs. See `docs/sinks.md` for the full failure taxonomy.

## Deferred scope

- Per-app sink routing, multi-sink fan-out, persistent sink configuration
- Sink providers beyond Loki and NullSink
- Event replay and durable/dead-letter storage
- Local Unix-socket ingestion (M5), gRPC, WebSocket transports
- Web admin application
- Go/Rust ingest rewrite (pending profiling evidence)
- msgpack framing (pending JSON bottleneck evidence)
