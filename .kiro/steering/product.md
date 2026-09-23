---
title: Product — what Telemetria is
inclusion: always
---

# What Telemetria is

Application runtime structured event ingest — send what you want, from anywhere, over HTTP.

One endpoint for single logs and batches. An SDK, agent, or sidecar is optional. Your application calls `POST /v1/logs` with an `x-telemetria-token` header and OTLP JSON or Protobuf; Telemetria handles authentication, batching, routing, retries, and delivery to Loki. The sink, the storage, and the dashboards are yours — Telemetria is the ingest layer between your application code and your observability stack.

**Not for:** infrastructure logs (nginx, systemd, container stdout) — use Fluent Bit or Vector for those. **For:** application-level structured events where you control what you send and when.

OTLP `200` without partial rejection acknowledges in-memory admission, not durable delivery. Partial success reports permanent size rejections; queue pressure returns retryable `503` with no admission. Process failure, IPC failure, and exhausted sink retries may lose accepted records. Retries may produce duplicate event IDs. Never promise stronger semantics than this.

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
- `AuthToken` — bearer token scoped to an app; can be revoked

Auth token keys are `secrets.token_urlsafe(32)` (256-bit entropy). The raw key is shown once at creation and never stored — only its HMAC-SHA256 hash (`APP_KEY` required in production) is persisted.

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
