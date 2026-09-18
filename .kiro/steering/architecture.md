---
title: Architecture invariants
inclusion: always
---

# Architecture invariants

These are non-negotiable. Import-linter enforces the boundary contracts in CI. Never relax them.

## Module layout

```
telemetria/
├── api/        health endpoint + optional /admin/v1 routes
├── cli/        Typer CLI (calls control/ only)
├── config.py   pydantic-settings, one class per process
├── control/    application services shared by cli/ and api/
├── db/         ORM models, async session factory, repositories, DSN resolver
├── domain/     pure entities + errors (no I/O, no frameworks)
├── ingest/     HTTP receiver + asyncio queue + IPCWriter
├── ipc/        versioned length-prefixed framing over UDS
├── metrics/    shared metric definitions
├── processor/  UDS server + BatchProcessor + sink dispatch
└── sinks/      EventSink ABC, error classes, NullSink, registry/factory
```

## Import boundaries (enforced by import-linter)

```
domain/     → nothing in telemetria (pure)
ipc/        → domain/ only
ingest/     → domain/, ipc/, metrics/, db/ (read-only DSN resolver)
processor/  → domain/, ipc/, metrics/, sinks/ (contract + factory only, NOT loki directly)
control/    → db/, domain/
cli/        → control/, domain/
api/        → control/, domain/
```

Contracts currently active:

1. `telemetria.ipc` must not import `api`, `cli`, `ingest`, or `processor`
2. `telemetria.domain` must not import `api`, `cli`, `ingest`, `processor`, `ipc`, or `metrics`
3. `telemetria.processor` must not import `telemetria.sinks.loki` directly

Never add a cross-boundary import. If a new provider needs plumbing, put it behind the registry.

## UTC storage invariant

Every timestamp that is persisted, transmitted, logged, or sink-facing **must be timezone-aware UTC**.

- PostgreSQL columns: `TIMESTAMPTZ`; sessions run with `SET TIME ZONE 'UTC'`
- JSON serialization: trailing `Z` (not `+00:00`)
- Client timestamps: normalized to UTC on receipt; missing/naive/malformed → fall back to server `received_at`
- Loki: uses server `received_at` as the entry timestamp; client timestamp is event metadata only
- `App.timezone`: optional IANA key, used exclusively for human-facing display. Never a storage or transmission timezone.

Enforce this with `_assert_utc()` in domain entities and events. Any datetime that escapes those checks without `tzinfo` is a bug.

## IPC wire format

```
[ 4 bytes big-endian uint32 body_length ][ body_length bytes UTF-8 JSON ]
```

Envelope: `{"v": 1, "event": { <Event.to_dict()> }}`

Max frame size: 1 MiB (`IPC_MAX_FRAME_BYTES`). Protocol version is `PROTOCOL_VERSION = 1`. Bump the version field and handle both in `decode_envelope_body` when the protocol changes — never silently accept unknown versions.

## Sink contract

```python
class EventSink(ABC):
    name: str
    async def write(self, batch: EventBatch) -> None: ...   # RetryableSinkError | PermanentSinkError
    async def close(self) -> None: ...
```

`BatchProcessor` never imports concrete providers. `telemetria.sinks.get_sink(provider)` is the only factory call. Retry policy: exponential backoff with ±10 % jitter, cap at `SINK_MAX_RETRIES`. Permanent failures and retry-exhausted batches are counted (`events_dropped`) and discarded — no crash, no queue stall.

## Ingest admission limits

- Body: `MAX_PAYLOAD_BYTES` (default 1 MiB) — hard 413 before any allocation beyond the stream
- Batch size: `MAX_BATCH_EVENTS` (default 300) — 422 if exceeded
- Queue: `QUEUE_SIZE` (default 10 000) — `QueueFull` → drop event, log warning, return `dropped=1`
- Payload nesting: max 10 levels deep

## Process entry points

Each process has its own `main()` called by a console script:

| Script | Entry point |
|---|---|
| `telemetria` | `telemetria.cli.main:app` |
| `telemetria-api` | `telemetria.api.server:main` |
| `telemetria-ingest` | `telemetria.ingest.server:main` |
| `telemetria-processor` | `telemetria.processor.server:main` |

Each `main()` configures logging first, then starts uvicorn. `SIGTERM` and `SIGINT` are handled explicitly.

## Database roles

- App role (`DB_USER`): full read/write — used by CLI, migrations, API
- Ingest role (`INGEST_DB_USER`): read-only — used only by `DSNResolver` in the ingest process

Never give the ingest process write access to the database.
