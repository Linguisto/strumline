# Replacing the ingest process

This guide describes everything needed to replace `telemetria-ingest` with a
compatible implementation in Go, Rust, or any other language. The replacement
must satisfy two public contracts: the HTTP ingest API and the IPC wire
protocol. No Python source reading is required.

## What the ingest process does

1. Accepts `POST /v1/logs` with an `x-telemetria-token` header.
2. Resolves the token against PostgreSQL (read-only role, TTL cache).
3. Validates and decodes the OTLP/HTTP body.
4. Normalises each log record into an `Event`.
5. Enqueues events atomically into a bounded in-process queue.
6. Writes queued events as length-prefixed IPC frames to a Unix-domain socket.

A replacement must implement all six steps and nothing more. The processor and
all downstream components are unchanged.

## HTTP contract

Full reference: [`docs/api/otlp-logs.md`](api/otlp-logs.md).

**Endpoint:** `POST /v1/logs` on the ingest port (default 8001).

**Auth:** `x-telemetria-token: <key>` header. Resolve via PostgreSQL
`auth_tokens` JOIN `apps` JOIN `projects` using the read-only ingest role.
The key is hashed as HMAC-SHA256(key, APP_KEY) before lookup. Cache results
with a 60-second TTL. On DB failure during a cache miss, return 503.

**Encodings:** `application/json` and `application/x-protobuf`. Optional
`Content-Encoding: gzip`. Use the official OpenTelemetry proto packages for
your language — do not reimplement the schema.

**Limits:**
- Raw body: reject with 413 if > `MAX_PAYLOAD_BYTES` (default 1 MiB) while
  reading the stream — before any allocation beyond the stream buffer.
- Decompressed body: same limit applied after decompression.
- Records: reject with 400 if total records across all resourceLogs/scopeLogs
  > `MAX_BATCH_EVENTS` (default 300).
- Normalized batch: sum of IPC frame bodies must not exceed `MAX_PAYLOAD_BYTES`.
  Records that exceed either the per-frame or batch limit are reported as OTLP
  partial success rejections, not as errors.

**Responses:**
- `200 {}` — all records admitted (in-memory, not durable).
- `200 {"partialSuccess": {...}}` — some records rejected due to size; do not
  retry rejected records.
- `400` — malformed payload, invalid gzip, too many records, or batch larger
  than queue capacity.
- `401` — missing or invalid token.
- `413` — body exceeds byte limit.
- `415` — unsupported content type or encoding.
- `503` — DB unavailable on cache miss, or queue capacity insufficient for
  batch; retry with backoff.

All error responses use `google.rpc.Status` encoded in the same format as the
request (`{"message": "..."}` for JSON, serialized protobuf for binary).
**Never echo parser diagnostics** — use fixed error strings.

**Admission atomicity:** check queue capacity and call `put_nowait` (or
equivalent non-blocking enqueue) with no I/O between check and enqueue. Either
the whole admitted sub-batch enters the queue or none of it does. A batch
larger than the total queue capacity is a permanent 400, not a retryable 503.

## IPC contract

Full reference: [`docs/ipc-protocol.md`](ipc-protocol.md).

Connect to the Unix-domain socket at `IPC_SOCKET_PATH` (default
`/var/run/telemetria/ipc.sock`). The processor owns the socket; the ingest
process connects as the client.

**Frame format:**
```
[ 4 bytes big-endian uint32 body_length ][ body_length bytes UTF-8 JSON ]
```

**Envelope:**
```json
{ "v": 1, "event": { <Event fields> } }
```

**Event fields** (all required):

| Field | Type | Notes |
|---|---|---|
| `id` | UUID string | Fresh UUID per event |
| `project_id` | UUID string | From token resolution |
| `project_slug` | string | From token resolution |
| `app_id` | UUID string | From token resolution |
| `app_slug` | string | From token resolution |
| `received_at` | ISO-8601 UTC, trailing `Z` | Server time at receipt |
| `timestamp` | ISO-8601 UTC, trailing `Z` | Client time (see below) |
| `level` | string | See level mapping below |
| `message` | string | May be empty |
| `payload` | object | OTLP data under `payload.otlp` |

**Timestamp:** use `time_unix_nano`, then `observed_time_unix_nano`, then
`received_at` as fallback. Project to microsecond precision for the datetime
field; preserve exact nanoseconds in `payload.otlp.logRecord.timeUnixNano`.
Both `received_at` and `timestamp` must be UTC with trailing `Z`.

**Level mapping** (OTLP `severity_number`):

| Range | Level |
|---|---|
| 1–4 | `trace` |
| 5–8 | `debug` |
| 9–12 | `info` |
| 13–16 | `warn` |
| 17–20 | `error` |
| 21–24 | `fatal` |
| 0 or > 24 | `unspecified` |

**OTLP payload structure** (in `payload.otlp`):

```json
{
  "resource": { <OTLP Resource — typed JSON> },
  "resourceSchemaUrl": "<string>",
  "scope": { <OTLP InstrumentationScope — typed JSON> },
  "scopeSchemaUrl": "<string>",
  "logRecord": { <OTLP LogRecord — typed JSON> }
}
```

AnyValue wrappers stay intact. 64-bit integers are decimal strings. Bytes are
base64. Trace/span IDs are canonical lowercase hex — all-zero IDs are omitted.

**Reconnect:** retry with exponential backoff (base 0.1 s, cap 30 s, ±10%
jitter) on any connection or write failure. Events already dequeued before
failure are lost — this is the documented best-effort behaviour.

## Database access

Use the `INGEST_DB_USER` / `INGEST_DB_PASSWORD` credentials. This role has
`SELECT` on `auth_tokens` and `apps` only. Never use the app role in the
ingest process.

Token hash: `HMAC-SHA256(key_bytes, APP_KEY_bytes)`, hex-encoded. Look up by
`auth_tokens.key_hash`. Join `apps` and then `projects` for routing metadata.
Reject revoked tokens (`auth_tokens.is_active = false`).

## Health endpoint

Expose `GET /health` returning:

```json
{"process": "ingest", "version": "<version>", "status": "ok"}
```

The processor health check at `:8002/health` and the base stack health checks
depend on this endpoint.

## Conformance

Validate your implementation against:

1. `tests/fixtures/ipc/fixtures.json` — language-neutral IPC frame fixtures.
2. The OpenAPI spec at `http://localhost:8001/openapi.json` (set
   `API_DOCS_ENABLED=true`) — request/response contract for `/v1/logs`.
3. `tests/test_otlp.py` — the full Python test suite documents all edge cases.
