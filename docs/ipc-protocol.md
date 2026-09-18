# IPC protocol

Telemetria uses a lightweight length-prefixed binary protocol over a
Unix-domain socket (UDS). Ingest is the single writer; processor is the
single reader.

## Wire format

Each frame:

```
[ 4 bytes big-endian uint32 body_length ][ body_length bytes UTF-8 JSON ]
```

The body is a JSON envelope:

```json
{ "v": 1, "event": { <serialized Event> } }
```

## Constants

| Name | Value |
|---|---|
| `PROTOCOL_VERSION` | `1` |
| `IPC_MAX_FRAME_BYTES` | 1 048 576 (1 MiB) |
| Prefix size | 4 bytes |
| Body encoding | UTF-8 JSON |

## Event envelope fields

| Field | Type | Description |
|---|---|---|
| `id` | UUID string | Server-generated event ID |
| `project_id` | UUID string | Project UUID |
| `project_slug` | string | Project slug at ingest time |
| `app_id` | UUID string | App UUID |
| `app_slug` | string | App slug at ingest time |
| `received_at` | ISO-8601 UTC string (trailing `Z`) | Server receipt timestamp |
| `timestamp` | ISO-8601 UTC string (trailing `Z`) | Client timestamp normalized to UTC |
| `level` | string | Log level (normalized lowercase) |
| `message` | string | Human-readable event message |
| `payload` | object | Arbitrary JSON payload |

Example:

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
    "payload": { "user_id": 42 }
  }
}
```

## Golden fixture (hex)

For a minimal event with known field values the encoded frame prefix bytes are:

```
00 00 00 XX  (4-byte big-endian body length)
```

followed by the UTF-8 JSON body. See `tests/test_ipc_codec.py` for
byte-level golden fixture tests.

## Error behavior

| Condition | Error | Action |
|---|---|---|
| Body length == 0 | `EmptyFrameError` | Close connection |
| Body length > `IPC_MAX_FRAME_BYTES` | `FrameTooLargeError` | Close connection |
| EOF before full body | `TruncatedFrameError` | Discard incomplete frame, keep server alive |
| `v` field != `PROTOCOL_VERSION` | `UnknownVersionError` | Count, discard frame, keep connection |
| Invalid JSON or missing fields | `MalformedEnvelopeError` | Count, discard frame, keep connection |

## Ownership

- **Processor** owns `IPC_SOCKET_PATH`: binds, listens, sets permissions `0o600`, accepts the single ingest writer.
- **Ingest** connects as the client, writes frames, reconnects with exponential backoff on failure.
- On processor shutdown: stop accepting, close connection, unlink socket.
- On ingest writer failure: events already removed from queue are lost (best-effort).

## Reconnect behavior

Ingest reconnects with exponential backoff on any write or connection failure:

| Attempt | Base delay |
|---|---|
| 1 | 0.1 s |
| 2 | 0.2 s |
| 3 | 0.4 s |
| n | min(0.1 × 2^n, 30 s) |

Jitter of ±10% is applied to each delay to avoid thundering herd.

## Version history

| Version | Changes |
|---|---|
| 1 | Initial protocol. Length prefix + JSON envelope. |
