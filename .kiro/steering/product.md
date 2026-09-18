---
title: Product — what Telemetria is
inclusion: always
---

# What Telemetria is

Non-blocking, lightning-fast structured telemetry collector. Best-effort by design.

`202 Accepted` means authentication and validation succeeded and enqueue was attempted. It does not guarantee delivery. Queue pressure, process failure, IPC failure, and exhausted sink retries may silently lose events. Retries may produce duplicate event IDs. Never promise stronger semantics than this.

## v1 deployment topology

One host, one Docker image, three containers:

```
telemetria-api        :8000  control plane + optional admin REST API
telemetria-ingest     :8001  HTTP ingestion + IPC writer
telemetria-processor  :8002  IPC reader, batching, sink dispatch, health/metrics
```

Ingest and processor share a Unix-domain-socket directory (`/var/run/telemetria/`) via a named Docker volume. PostgreSQL stores control-plane metadata only. Raw telemetry is never written to PostgreSQL.

## Control plane model

Three entities, all immutable after creation except soft states:

- `Project` — top-level namespace (slug + name)
- `App` — belongs to a project; optional IANA `timezone` for display only
- `DSN` — bearer token scoped to an app; can be revoked

DSN keys are `secrets.token_urlsafe(32)`, stored as plaintext in v1, revealed once at creation.

## Sink model

`BatchProcessor` depends only on the `EventSink` ABC and its two error classes — never a concrete provider. `SINK_PROVIDER` env var selects the provider at startup. v1 ships `null` (default) and `loki`. Provider registry lives in `telemetria.sinks`.

## v1 success criteria (non-negotiable)

1. `docker compose up` starts PostgreSQL + three containers from one tagged image.
2. Optional `loki` and `observability` profiles work independently and together.
3. Project/App/DSN management works via CLI and runtime-enabled REST API.
4. Create resources, ingest an event, observe it through the sink in < 5 minutes.
5. Ingest sustains ≥ 1,000 events/sec; HTTP receipt-to-enqueue P99 < 5 ms.
6. Overload and sink failures preserve service health; drop/error counters explain losses.
7. UTC invariants, import boundaries, and IPC conformance suite pass in CI.
8. Milestones M0–M4, M6, M6b, M7 complete. M5 (local UDS ingest) is post-v1.

## Deferred (do not add unless a milestone explicitly unblocks it)

- Per-app sink routing, multi-sink fan-out, persistent sink config
- Sink providers beyond Loki and NullSink
- Event replay, dead-letter storage
- Local Unix-socket ingestion (M5), gRPC, WebSocket
- Web admin application
- Go/Rust rewrite (pending profiling evidence)
- msgpack framing (pending JSON bottleneck evidence)
