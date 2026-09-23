# M3 — Loki Sink Provider

**Type:** Core  
**Depends on:** M2b  
**Unlocks:** M4  
**Goal:** Register a production-capable Loki provider without coupling processor logic to Loki.

## Provider implementation

`LokiSink(EventSink)` lives in `strumline/sinks/loki.py` and is created through the M2b registry when `SINK_PROVIDER=loki`. `NullSink` remains supported. No `sink_configs` table or per-app routing is introduced.

```text
SINK_PROVIDER=loki
LOKI_URL=http://loki:3100
LOKI_TENANT_ID=          # optional
LOKI_TIMEOUT_SECONDS=5
LOKI_COMPRESSION=gzip
```

Loki-specific response handling is translated at the provider boundary:

- network timeouts, connection errors, HTTP 429, and HTTP 5xx → `RetryableSinkError`
- other HTTP 4xx and invalid provider configuration → `PermanentSinkError`

`BatchProcessor` retains ownership of retry/backoff and does not inspect HTTP status codes.

## Loki mapping

Each event line contains event ID, canonical UTC `received_at`, canonical UTC client `timestamp`, level, message, and payload. Labels are low-cardinality: service, project slug, app slug, and level. IDs, users, trace IDs, request IDs, and arbitrary payload keys remain in the JSON line.

The Loki entry timestamp is server-generated `received_at` converted to integer nanoseconds. Client time is preserved in the line but never controls Loki storage ordering. Events are grouped by identical label sets and sorted by the selected entry timestamp for deterministic requests.

Compute epoch nanoseconds using integer arithmetic and serialize them as a decimal **string** in each Loki JSON `values` entry. Sending a JSON number is invalid for this endpoint. UTC wall-clock time does not guarantee monotonic ordering across requests, clock adjustments, or retries; do not claim it eliminates out-of-order ingestion.

Build the JSON bytes first. When compression is enabled, gzip those bytes and set matching `Content-Encoding: gzip` and `Content-Type: application/json` headers. Tests inspect the decoded request body rather than assuming the HTTP client compressed it.

## Development Compose service

The development Compose stack supplies a pinned single-node Loki configuration
and persistent development volume. Production deployments set `LOKI_URL` to an
operator-managed Loki instance or select another supported sink.

## Acceptance criteria

- [ ] `SINK_PROVIDER=loki` selects Loki through the registry; `null` still works without processor changes.
- [ ] Loki request bodies contain correct labels, JSON lines, and decimal-string nanosecond `received_at` timestamps computed with integer arithmetic.
- [ ] Valid client timestamps remain canonical UTC metadata and never replace the entry timestamp.
- [ ] Gzip bytes and headers agree and round-trip in tests.
- [ ] Timeouts, 429, and 5xx raise retryable errors; other 4xx raise permanent errors.
- [ ] Sink error/retry metrics use `sink="loki"` and bounded reason labels.
- [ ] An integration test ingests and queries an event using the bundled development Loki.
- [ ] Loki absence is a supported configuration through NullSink or an external provider URL.
