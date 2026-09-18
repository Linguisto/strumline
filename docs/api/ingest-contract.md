# Ingest HTTP contract

## Endpoints

```
POST /v1/ingest
POST /v1/ingest/batch
```

Both endpoints require the header:

```
X-Telemetria-DSN: <dsn-key>
Content-Type: application/json
```

## Limits

| Parameter | Value | Enforced |
|---|---|---|
| `MAX_PAYLOAD_BYTES` | 1 MiB (1 048 576 bytes) | Before JSON parsing, on raw request bytes |
| `MAX_BATCH_EVENTS` | 300 | After parsing, before any enqueue |
| Queue size | 10 000 events | `put_nowait` — never blocks the request |
| DSN cache TTL | 60 s | After TTL, revoked DSNs are rejected |

## Single event — `POST /v1/ingest`

### Request

```json
{
  "timestamp": "2026-09-18T17:00:00Z",
  "level": "error",
  "message": "Something went wrong",
  "payload": { "user_id": 42 }
}
```

`timestamp` must include `Z` or an explicit UTC offset (e.g. `+03:00`).  
Missing, naive, malformed, or out-of-range values fall back to server `received_at`.

`level` is normalized to lowercase. Unknown values are accepted as-is.

`payload` must be a JSON object. Nesting depth is limited to 10 levels.

### Response `202 Accepted`

```json
{ "enqueued": 1, "dropped": 0 }
```

`202` means authentication and validation succeeded and enqueue was attempted.
It does **not** guarantee delivery. See best-effort semantics below.

## Batch — `POST /v1/ingest/batch`

### Request

```json
{
  "events": [
    { "timestamp": "2026-09-18T17:00:00Z", "level": "info", "message": "ok", "payload": {} },
    { "timestamp": "2026-09-18T17:00:01Z", "level": "warn", "message": "slow", "payload": {} }
  ]
}
```

### Response `202 Accepted`

```json
{ "enqueued": 2, "dropped": 0 }
```

`dropped` reflects queue-full drops after validation. The entire batch is
validated before any event is enqueued — validation failures enqueue zero events.

## Error responses

| Status | Condition |
|---|---|
| `400 Bad Request` | Invalid JSON, missing required fields, invalid field types, nesting depth exceeded |
| `401 Unauthorized` | Unknown, inactive, or revoked DSN |
| `413 Request Entity Too Large` | Raw body exceeds `MAX_PAYLOAD_BYTES` |
| `415 Unsupported Media Type` | `Content-Type` is not `application/json` |
| `422 Unprocessable Entity` | Batch exceeds `MAX_BATCH_EVENTS` |

## Timestamp rules

1. Client timestamps **must** include `Z` or an explicit UTC offset.
2. They are normalized to UTC on receipt.
3. Missing, naive, malformed, or out-of-range values are silently replaced with server `received_at`.
4. The original offset string is never stored — only the normalized UTC instant.
5. `received_at` is always server-generated UTC, independent of the client value.

## Best-effort semantics

`202` means the server accepted and validated the request, and attempted to
enqueue each event. It does **not** guarantee delivery. The following may lose
events without surfacing an error to the HTTP caller:

- Queue pressure (`QueueFull` increments the drop counter)
- IPC transport failure between ingest and processor
- Process restart before the queue is drained
- Sink retry exhaustion in the processor

Retries may produce duplicate event IDs. Event IDs are not general idempotency keys.

## Security

- DSN keys are never logged at normal log levels.
- Raw telemetry payloads are never logged at normal log levels.
- The ingest process uses the read-only database role — it cannot write metadata.
