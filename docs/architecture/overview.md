# Architecture overview

This document explains how Telemetria works end to end — the design decisions, data flows, and the reasoning behind each component boundary.

## The fundamental design choice: best-effort, non-blocking

Telemetria is built around a single constraint: the ingest HTTP path must never block waiting for downstream systems. A `202 Accepted` response means the event passed authentication and validation and was placed into an in-process queue. Everything after that — IPC transport, batching, sink delivery — happens asynchronously and may fail silently.

This is a deliberate trade-off. It means:
- Ingest latency is bounded by queue insertion time, not by Loki write latency
- A Loki outage does not propagate back to your application as HTTP errors
- Events can be lost; the system counts losses but does not recover them

If you need guaranteed delivery, you need a different system. Telemetria optimises for throughput and isolation over durability.

## Process topology

Three processes share one Docker image, one host, and one Unix-domain socket:

```
Your application
      │
      │  HTTP POST /v1/ingest
      │  X-Telemetria-auth token: <key>
      ▼
┌─────────────────────┐
│  telemetria-ingest  │  :8001
│                     │
│  1. Auth (auth token)      │
│  2. Validate        │──────────────── PostgreSQL (read-only)
│  3. Normalize UTC   │  auth token resolution
│  4. Enqueue         │
│  5. IPC write ──────┼────────────────── Unix socket
└─────────────────────┘                        │
                                               │
┌─────────────────────┐                        │
│ telemetria-processor│  :8002                 │
│                     │◄───────────────────────┘
│  1. Read frames     │
│  2. Decode events   │
│  3. Batch           │
│  4. Sink dispatch ──┼──────────────── Loki (or null)
└─────────────────────┘

┌─────────────────────┐
│   telemetria-api    │  :8000
│                     │
│  /health            │──── PostgreSQL (read-write)
│  /metrics           │  control plane
│  admin routes (M6b) │
└─────────────────────┘
```

The processes are separated by design:
- **Ingest** is untrusted and read-only at the database level. It cannot write metadata. If compromised, it cannot corrupt Projects, Apps, or auth tokens.
- **Processor** has no HTTP surface for telemetry data. It only reads from the socket.
- **API** handles control-plane operations (CRUD) and is kept completely separate from the data path.

## Authentication and the auth token model

Every ingest request carries a auth token (Data Source Name) key in the `X-Telemetria-auth token` header. A auth token is a bearer token scoped to one App. The ingest process resolves it through the read-only database role using a TTL cache (60 seconds by default).

The resolution query looks up `token → app → project` and returns routing metadata — project ID, project slug, app ID, app slug — which is embedded directly into the event. This means the processor never needs to touch the database. The event carries all the context needed for Loki labelling.

The cache serves two purposes: it keeps hot paths off the database, and it provides a grace period after revocation (a revoked auth token remains valid for up to one TTL period). On a cache miss with a database failure, the resolver fails closed — it returns 401 rather than accepting events for an unvalidated auth token.

auth token keys use `secrets.token_urlsafe(32)`: 32 bytes of random data, 256 bits of entropy, encoded as approximately 43 URL-safe characters. They are stored as plaintext in v1 and revealed once at creation.

## The ingest queue

Between the HTTP handler and the IPC writer sits an `asyncio.Queue` with a configurable maximum size (default 10,000 events). This is the backpressure boundary.

When the queue is full:
- The HTTP handler calls `put_nowait`, which raises `QueueFull` immediately
- The handler increments the drop counter and returns `202` with `dropped: 1`
- The request never blocks

This means the ingest HTTP server is always responsive under load. The cost is event loss under sustained overload. The `INGEST_QUEUE_DEPTH` and `INGEST_QUEUE_CAPACITY` metrics let you observe queue saturation before events start dropping.

## The IPC transport

Ingest and processor communicate over a Unix-domain socket (UDS). The processor creates and owns the socket; ingest connects as the client.

Why a Unix socket instead of a network socket or an in-process queue?

The processes are intentionally separated so they can be managed independently, restarted independently, and scaled independently in future. The UDS gives near-zero-overhead IPC (no TCP/TLS overhead, no loopback routing) while preserving process isolation. The 1 MiB frame limit prevents a single malformed or oversized event from consuming unbounded memory.

The protocol is simple on purpose: a 4-byte big-endian length prefix followed by a UTF-8 JSON body. The envelope carries a version field (`v: 1`) so the protocol can evolve without breaking existing connections. See `docs/ipc-protocol.md` for the full wire format.

The IPC writer in the ingest process reconnects automatically on failure with capped exponential backoff (0.1s base, 30s cap, ±10% jitter). Events already removed from the queue before a failure are lost — this is consistent with best-effort semantics.

## The processor: batching and sink dispatch

The processor drains events from its internal queue and accumulates them into batches. A batch is flushed when either:
- It reaches `BATCH_MAX_SIZE` events (default 500), or
- `BATCH_MAX_WAIT_SECONDS` has elapsed since the first event in the current batch (default 1.0s)

This dual-trigger design balances latency and throughput. Under high load, batches flush by size. Under low load, they flush by time so events don't sit in memory indefinitely.

`BatchProcessor` depends only on the `EventSink` ABC — it never imports `LokiSink` or any concrete provider. The registry (`SINK_PROVIDER` env var) selects the provider at startup. This means adding a new sink provider requires no changes to the processor.

## The sink retry policy

When a sink write fails:

- `RetryableSinkError` (network timeout, HTTP 429, HTTP 5xx): retry with exponential backoff and ±10% jitter, up to `SINK_MAX_RETRIES` attempts (default 3). Delay starts at `SINK_RETRY_BASE_SECONDS` (0.25s), capped at `SINK_RETRY_MAX_SECONDS` (10s).
- `PermanentSinkError` (HTTP 4xx other than 429, configuration error): discard immediately, no retry.
- Retry exhaustion: discard, count as dropped.

The processor never crashes on sink failures. It counts and discards, logs the error, and moves on to the next batch. This ensures sink outages don't stall the event pipeline.

Retries can produce duplicate event IDs in the sink (the sink accepted the first write but the ACK was lost). The `id` field in every event allows downstream deduplication.

## The Loki sink

Events are grouped into Loki streams by `(project_slug, app_slug, level)`. Each stream gets low-cardinality labels:

```
service=telemetria  project=<slug>  app=<slug>  level=<level>
```

IDs, trace IDs, user IDs, and arbitrary payload fields stay in the JSON log line, not in labels. This is intentional: Loki's performance degrades sharply with high-cardinality labels. Putting user IDs in labels would create a new stream per user.

The entry timestamp sent to Loki is always `received_at` — the server-generated UTC instant. The client-provided `timestamp` is preserved as metadata inside the JSON line. This means Loki's storage ordering is deterministic and unaffected by clock skew on client machines.

Timestamps are serialised as decimal nanosecond strings (not JSON numbers) because Loki's push API requires this format.

## The control plane

The API process handles Projects, Apps, and auth tokens through the `telemetria/control/` service layer. The same services are used by both the CLI and the future admin REST API (M6b), preventing business logic from being duplicated.

The two-model split keeps the domain layer clean:
- `telemetria/db/models.py` — SQLAlchemy ORM models, used only inside `telemetria/db/`
- `telemetria/domain/entities.py` — frozen dataclasses, used everywhere else

Repositories translate between them. Nothing outside `telemetria/db/` ever sees an ORM model.

## UTC everywhere

Every timestamp that crosses a process boundary, gets persisted, or enters a sink is timezone-aware UTC. The enforcement points are:

- `_assert_utc()` in domain entities raises on construction if a datetime is naive or non-UTC
- PostgreSQL columns are `TIMESTAMPTZ`; the session timezone is UTC
- JSON serialisation always emits a trailing `Z`
- The ingest process normalises client timestamps to UTC on receipt; missing/naive/malformed values fall back to server `received_at`
- Loki always uses `received_at` as the entry timestamp

`App.timezone` is an IANA identifier used exclusively for human-facing display in the CLI. It never affects any stored or transmitted timestamp.

## Import boundaries

The module layout enforces a strict dependency order, checked by `import-linter` in CI:

```
domain/     ← no telemetria imports (pure Python)
    ↑
ipc/        ← domain/ only
    ↑
ingest/     ← domain/, ipc/, metrics/, db/ (read-only)
processor/  ← domain/, ipc/, metrics/, sinks/ (contract only, never loki directly)
    ↑
sinks/      ← domain/ only
control/    ← db/, domain/
cli/        ← control/, domain/
api/        ← control/, domain/
```

`processor` is explicitly forbidden from importing `telemetria.sinks.loki`. It may only import the `EventSink` ABC and the two error classes. The `get_sink()` factory in `telemetria.sinks` does the concrete import at runtime via `importlib`, keeping the static dependency graph clean.

## Failure taxonomy

Events can be lost at several points. None surface as HTTP errors to the caller:

| Stage | What drops | Counter |
|---|---|---|
| Ingest queue full | `put_nowait` raises `QueueFull` | `ingest_events_dropped_total{reason="queue_full"}` |
| IPC write failure | Event removed from queue before reconnect | Logged, no counter in v1 |
| Processor queue full | UDS server calls `put_nowait`, fails | `processor_events_dropped_total{reason="queue_full"}` |
| Permanent sink error | Batch discarded immediately | `processor_events_dropped_total{reason="sink_permanent"}` |
| Sink retries exhausted | Batch discarded after N attempts | `processor_events_dropped_total{reason="sink_retries_exhausted"}` |

The `ingest_events_dropped_total` and `processor_events_dropped_total` counters are distinct because the two queues are owned by different processes with different failure modes. Ingest drops happen because the producer is too fast; processor drops happen because the sink is too slow or unavailable.

## What Telemetria deliberately does not do

- **No durability.** There is no WAL, no replay, no dead-letter store. Dropped events are gone.
- **No backpressure to callers.** The HTTP layer always returns promptly. Overload signals are metrics, not errors.
- **No per-app sink routing.** All apps go to the same sink. Multi-sink fan-out is deferred.
- **No event deduplication.** The `id` field is present for downstream use, but Telemetria itself does not deduplicate on retry.
- **No raw telemetry in PostgreSQL.** The database stores metadata only (Projects, Apps, auth tokens). Events flow ingest → IPC → processor → sink and never touch the database.
