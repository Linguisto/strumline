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

Both canonical datetimes are UTC and serialize with `Z`. OTLP epoch nanoseconds
are preserved exactly in the typed payload; the datetime projection uses event
time, then observed time, then server receipt time. Invalid wire timestamps
are payload errors; absent/zero values use the documented fallback.

Including project/app IDs and slugs in the event keeps the processor independent from PostgreSQL and gives every sink the routing metadata it needs.

## HTTP ingestion

`POST /v1/logs` is the only ingestion endpoint, for both single records and
batches. Authenticate with `x-strumline-token`. The
[OTLP contract](../../docs/api/otlp-logs.md) defines Protobuf/JSON, gzip, typed
field preservation, body/record/normalized-size limits, and response encoding.

- Decode and validate before admission. Malformed payloads enqueue nothing.
- Resolve tokens through the read-only database role and TTL cache.
- Preserve resource/scope/record data and generate server receipt time and event IDs.
- Return `200` for full acceptance or permanent normalized-size partial rejection.
- Return `400` for malformed data or invalid batch count/capacity, `401` for invalid
  tokens, `413` for body limits, and `415` for unsupported encoding/media type.
- Return retryable `503` for resolver outages or insufficient queue capacity.
- Never log tokens or raw telemetry at normal log levels.

## Bounded queue and IPC writer

The handler checks capacity and uses `put_nowait` without an intervening await.
Insufficient space rejects the whole batch with `503`; nothing is admitted and
no permanent-drop counter is incremented. Normalized size rejections use OTLP
partial-success counts and the `otlp_normalized_size` drop reason.

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

- [ ] Valid single and batch requests return `200` and create IPC frames containing IDs, slugs, and UTC timestamps.
- [ ] Raw/decompressed bytes are bounded before decoding; batch and normalized sizes are checked before admission.
- [ ] Invalid batch members cause zero events from that batch to enqueue.
- [ ] OTLP timestamp fallback and exact nanosecond preservation are tested.
- [ ] Queue-full handling rejects atomically with `503` and never waits for capacity.
- [ ] Revoked DSNs become invalid within the documented cache TTL.
- [ ] Frame-size, version, malformed-body, and truncated-read tests cover the shared protocol.
- [ ] Socket failure keeps HTTP serving and records reconnect/drop behavior consistent with best-effort semantics.
