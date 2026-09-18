# M2 — Ingest Process

**Type:** Core  
**Depends on:** M1  
**Unlocks:** M2b  
**Goal:** Authenticate and validate HTTP events, normalize them to UTC, enqueue without blocking, and write versioned IPC frames.

## Event contract

```python
@dataclass
class Event:
    id: UUID
    project_id: UUID
    project_slug: str
    app_id: UUID
    app_slug: str
    received_at: datetime       # server-generated, aware UTC
    timestamp: datetime         # client time normalized to UTC or received_at
    level: str
    message: str
    payload: dict[str, Any]
```

Both timestamps are canonical UTC values. A client timestamp is accepted only with `Z` or an explicit offset, then normalized to UTC. Missing, naive, malformed, or out-of-range values use `received_at`. Serialization always emits `Z`. Do not automatically retain the original offset-bearing timestamp string in metadata; no localized timestamp field crosses IPC.

Including project/app IDs and slugs in the event keeps the processor independent from PostgreSQL and gives every sink the routing metadata it needs.

## HTTP ingestion

```text
POST /v1/ingest
POST /v1/ingest/batch
X-Telemetria-DSN: <key>
```

- Enforce `MAX_PAYLOAD_BYTES` on raw request bytes before JSON parsing/decompression expansion can allocate an unbounded object.
- Enforce content type, JSON shape, allowed scalar/container types, nesting limits, and `MAX_BATCH_EVENTS`.
- Resolve the DSN through the read-only database role and TTL cache.
- Validate and normalize an entire batch before enqueueing any member. Validation failures enqueue zero events.
- Generate one server UTC `received_at` per accepted event and a UUID event ID.
- Do not log DSN keys or raw telemetry at normal log levels.

Response semantics:

- `202`: authentication and validation succeeded; enqueue was attempted for each normalized event.
- `400`/`413`/`415`: invalid request, batch limit, byte limit, or media type.
- `401`: unknown, inactive, or revoked DSN.

`202` is best-effort acknowledgement, not a durability promise. Responses may include accepted/dropped counts for batches without exposing internal details.

## Bounded queue and IPC writer

The request handler uses `asyncio.Queue.put_nowait`; it never awaits capacity. `QueueFull` increments the ingest-specific drop counter and the handler continues according to the documented batch response semantics.

A dedicated writer task owns the UDS connection, drains the queue, calls shared `encode_frame`, and uses `write()` plus `drain()` while handling partial transport failure and reconnecting with bounded exponential backoff. Stream writes are not described as atomic. Events already removed from the queue may be lost on failure, consistent with best-effort delivery.

## IPC protocol ownership

M2 implements the shared protocol instead of leaving safety checks to M7:

```text
4-byte big-endian unsigned body length | UTF-8 JSON envelope body
{ "v": 1, "event": { ... } }
```

- `encode_frame(envelope) -> bytes`
- `read_frame(reader, max_bytes) -> bytes` reads prefix and exact body.
- `decode_envelope_body(body) -> Envelope` parses a body whose prefix is already consumed.
- `IPC_MAX_FRAME_BYTES` rejects oversized bodies before allocation.
- Unknown versions, zero-length bodies, malformed JSON, and truncation have explicit typed errors.

## Metrics introduced with the feature

M2 defines the ingest counters/gauges it emits; M4 integrates dashboards and sample infrastructure. At minimum: requests, events accepted, `ingest_events_dropped_total{reason}`, queue depth/capacity, auth-cache hits/misses, validation failures, IPC reconnects, and request latency. HTTP labels use route templates, not raw paths, DSNs, projects, or apps.

## Acceptance criteria

- [ ] Valid single and batch requests return `202` and create IPC frames containing IDs, slugs, and UTC timestamps.
- [ ] Raw byte and batch limits are applied before expensive parsing and before any enqueue.
- [ ] Invalid batch members cause zero events from that batch to enqueue.
- [ ] Naive/invalid timestamps fall back to server UTC `received_at`; offset timestamps normalize to `Z`.
- [ ] Queue-full handling uses `put_nowait`, never blocks the request, and increments the ingest drop counter.
- [ ] Revoked DSNs become invalid within the documented cache TTL.
- [ ] Frame-size, version, malformed-body, and truncated-read tests cover the shared protocol.
- [ ] Socket failure keeps HTTP serving and records reconnect/drop behavior consistent with best-effort semantics.
