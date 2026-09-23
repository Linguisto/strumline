# IPC protocol

Telemetria uses a lightweight length-prefixed binary protocol over a
Unix-domain socket (UDS). Ingest is the single writer; processor is the
single reader.

This document is sufficient to implement a compatible writer or reader in any
language without reading Python source. See `tests/fixtures/ipc/` for
language-neutral conformance fixtures.

## Wire format

Each frame:

```
[ 4 bytes big-endian uint32 body_length ][ body_length bytes UTF-8 JSON ]
```

The body is a JSON envelope:

```json
{ "v": 1, "event": { <serialized Event> } }
```

The prefix is an unsigned 32-bit integer in network byte order (big-endian).
It carries the byte length of the following JSON body only — not including the
4-byte prefix itself. A reader must:

1. Read exactly 4 bytes to obtain the prefix.
2. Decode it as a big-endian `uint32` to get `body_length`.
3. Reject if `body_length == 0` (`EmptyFrameError`).
4. Reject if `body_length > IPC_MAX_FRAME_BYTES` (`FrameTooLargeError`) — do
   this before allocating any buffer.
5. Read exactly `body_length` bytes. EOF before that many bytes is
   `TruncatedFrameError`.
6. Decode as UTF-8 JSON and validate the envelope.

Step 5 may require multiple `read()` calls (split reads). Buffer until the
full body is available before attempting JSON parse.

## Constants

| Name | Value |
|---|---|
| `PROTOCOL_VERSION` | `1` |
| `IPC_MAX_FRAME_BYTES` | 1 048 576 (1 MiB) |
| Prefix size | 4 bytes, big-endian uint32 |
| Body encoding | UTF-8 JSON, compact (no required whitespace) |

## Envelope schema

```json
{
  "v": <integer — must equal PROTOCOL_VERSION>,
  "event": { <Event object> }
}
```

Both fields are required. Unknown top-level fields must be ignored for forward
compatibility. An envelope with an unknown `v` value must be counted and
discarded without closing the connection (see Error behavior below).

## Event object schema

| Field | JSON type | Constraints | Description |
|---|---|---|---|
| `id` | string | UUID, lowercase hex with hyphens | Server-generated event ID |
| `project_id` | string | UUID, lowercase hex with hyphens | Project UUID |
| `project_slug` | string | non-empty | Project slug at ingest time |
| `app_id` | string | UUID, lowercase hex with hyphens | App UUID |
| `app_slug` | string | non-empty | App slug at ingest time |
| `received_at` | string | ISO-8601 UTC, trailing `Z` | Server receipt timestamp |
| `timestamp` | string | ISO-8601 UTC, trailing `Z` | Client timestamp normalized to UTC |
| `level` | string | one of: `trace`, `debug`, `info`, `warn`, `error`, `fatal`, `unspecified` | Normalized log level |
| `message` | string | may be empty | Human-readable event message |
| `payload` | object | arbitrary JSON object | Event payload (OTLP data lives here) |

### UTC encoding invariant

Both `received_at` and `timestamp` **must** be serialized with a trailing `Z`
(not `+00:00` or any other offset notation). Example:

```
"received_at": "2026-09-18T17:00:00.000000Z"   ✓
"received_at": "2026-09-18T17:00:00+00:00"      ✗ rejected on decode
"received_at": "2026-09-18T17:00:00"            ✗ rejected on decode (naive)
```

Precision is microseconds (6 decimal places). The trailing `Z` is enforced by
`_assert_utc()` in the domain entity and by `Event.to_dict()` on serialization.

### OTLP payload structure

When the event originates from an OTLP log record, `payload` contains an `otlp`
key with the following structure:

```json
{
  "otlp": {
    "resource": { <OTLP Resource as typed JSON> },
    "resourceSchemaUrl": "<string>",
    "scope": { <OTLP InstrumentationScope as typed JSON> },
    "scopeSchemaUrl": "<string>",
    "logRecord": { <OTLP LogRecord as typed JSON> }
  }
}
```

All OTLP objects use typed OTLP JSON conventions: `AnyValue` wrappers are
preserved, 64-bit integers are decimal strings, bytes are base64, trace/span
IDs are lowercase hex. All-zero trace/span IDs are omitted. Exact nanosecond
timestamps are preserved as decimal strings in `logRecord.timeUnixNano` and
`logRecord.observedTimeUnixNano`.

## Example frame

Full frame for a minimal event (prefix + body):

```json
{
  "v": 1,
  "event": {
    "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "project_id": "00000000-0000-0000-0000-000000000001",
    "project_slug": "my-project",
    "app_id": "00000000-0000-0000-0000-000000000002",
    "app_slug": "my-app",
    "received_at": "2026-09-18T17:00:00.000000Z",
    "timestamp": "2026-09-18T16:59:59.000000Z",
    "level": "error",
    "message": "Something went wrong",
    "payload": {}
  }
}
```

The 4-byte prefix contains the byte length of this JSON body as a big-endian
`uint32`. See `tests/fixtures/ipc/` for binary-exact conformance fixtures.

## Error behavior

| Condition | Error | Connection action |
|---|---|---|
| Body length == 0 | `EmptyFrameError` | Close connection |
| Body length > `IPC_MAX_FRAME_BYTES` | `FrameTooLargeError` | Close connection |
| EOF before full body | `TruncatedFrameError` | Close connection |
| `v` field != `PROTOCOL_VERSION` | `UnknownVersionError` | Count, discard frame body, keep connection |
| Invalid JSON or missing/invalid fields | `MalformedEnvelopeError` | Count, discard frame body, keep connection |

On close-worthy errors the server closes the accepted connection; the ingest
writer will reconnect with exponential backoff.

## Socket ownership

- **Processor** owns `IPC_SOCKET_PATH`: creates, binds, listens, sets
  permissions `0o600`, accepts the single ingest writer.
- **Ingest** connects as the sole client, writes frames sequentially,
  reconnects with exponential backoff on any failure.
- On processor startup with a stale socket file: if the path exists and is a
  socket, unlink it before binding. Never unlink a regular file or symlink.
- On processor shutdown: stop accepting, close the accepted connection, unlink
  the socket.
- On ingest writer failure: events already removed from the queue before
  reconnect are lost (best-effort).

## Reconnect behavior

Ingest reconnects with exponential backoff on any write or connection failure:

| Attempt | Base delay |
|---|---|
| 1 | 0.1 s |
| 2 | 0.2 s |
| 3 | 0.4 s |
| n | min(0.1 × 2ⁿ, 30 s) |

±10 % jitter is applied to each delay to avoid thundering herd on simultaneous
restarts.

## Conformance fixtures

Language-neutral test fixtures live in `tests/fixtures/ipc/fixtures.json`.
Each fixture is a JSON object with:

- `name` — descriptive test case name
- `frame_hex` — hex-encoded frame bytes (prefix + body) for valid frames; hex
  prefix only for error cases
- `valid` — `true` if the frame should decode successfully
- `error` — error class name when `valid` is `false`
- `event` — expected decoded event fields (only for `valid: true`)
- `description` — human-readable explanation

Run `pytest tests/test_ipc_codec.py` to verify all fixtures against the Python
implementation.

## Version history

| Version | Changes |
|---|---|
| 1 | Initial protocol. 4-byte big-endian length prefix + UTF-8 JSON envelope. |
