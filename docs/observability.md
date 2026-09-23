# Observability

Telemetria exposes Prometheus metrics on every process. In production you bring
your own Prometheus and Grafana — only the app image is deployed alongside your
managed PostgreSQL and Loki instances.

## Metrics endpoint

Each process exposes `GET /metrics` when `METRICS_ENABLED=true` (default):

| Process              | URL                              |
|----------------------|----------------------------------|
| `telemetria-api`     | `http://<host>:8000/metrics`     |
| `telemetria-ingest`  | `http://<host>:8001/metrics`     |
| `telemetria-processor` | `http://<host>:8002/metrics`   |

Set `METRICS_ENABLED=false` to disable the endpoint without affecting health
checks or event processing.

## BYO Prometheus and Grafana

The base Compose stack does not start Prometheus or Grafana. Add these jobs to
your existing `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: telemetria-api
    static_configs:
      - targets: ["<api-host>:8000"]
    metrics_path: /metrics

  - job_name: telemetria-ingest
    static_configs:
      - targets: ["<ingest-host>:8001"]
    metrics_path: /metrics

  - job_name: telemetria-processor
    static_configs:
      - targets: ["<processor-host>:8002"]
    metrics_path: /metrics
```

A standalone copy lives at `docker/observability/prometheus.yml`.

Import the dashboard from `docker/observability/grafana/provisioning/dashboards/telemetria.json`
into your Grafana. The dashboard uses data source UIDs `prometheus` and `loki`.
If your data sources have different UIDs, either rename them in Grafana or
find-and-replace the UIDs in the JSON before importing.

## Bundled observability stack (optional)

Start the bundled Prometheus and Grafana with the `observability` profile:

```bash
docker compose --profile observability up -d
```

| Service    | URL                        |
|------------|----------------------------|
| Prometheus | http://localhost:9090       |
| Grafana    | http://localhost:3000       |

The `loki` profile and `observability` profile are independent and work
together or separately.

## Key metrics reference

| Metric | Labels | Description |
|--------|--------|-------------|
| `telemetria_http_requests_total` | `process`, `method`, `route`, `status_class` | HTTP request count |
| `telemetria_http_request_duration_seconds` | `process`, `method`, `route` | HTTP latency histogram |
| `telemetria_ingest_events_accepted_total` | — | Events admitted to the ingest queue |
| `telemetria_ingest_events_dropped_total` | `reason` | Events permanently rejected at ingest (see reasons below) |
| `telemetria_ingest_queue_depth` | — | Current ingest queue depth |
| `telemetria_ingest_queue_capacity` | — | Ingest queue max capacity (`QUEUE_SIZE`) |
| `telemetria_ingest_token_cache_hits_total` | — | Auth token cache hits |
| `telemetria_ingest_token_cache_misses_total` | — | Auth token cache misses (DB queries) |
| `telemetria_ingest_ipc_reconnects_total` | — | IPC writer reconnect attempts |
| `telemetria_processor_queue_depth` | — | Current processor queue depth |
| `telemetria_processor_queue_capacity` | — | Processor queue max capacity |
| `telemetria_processor_events_dropped_total` | `reason` | Events dropped by the processor (see reasons below) |
| `telemetria_processor_batches_total` | `sink` | Batches successfully written to the sink |
| `telemetria_processor_batch_size` | `sink` | Batch size histogram |
| `telemetria_processor_batch_duration_seconds` | `sink` | Batch write latency histogram |
| `telemetria_processor_sink_writes_total` | `sink`, `outcome` | Sink write attempts (success, retryable, permanent) |
| `telemetria_ipc_frames_total` | `direction`, `outcome` | IPC frames processed |
| `telemetria_ipc_protocol_errors_total` | `error_type` | IPC protocol errors |

### Drop reason labels

`telemetria_ingest_events_dropped_total{reason=...}`:

| Reason | When |
|---|---|
| `otlp_normalized_size` | Record exceeds per-frame or cumulative normalized-size limit; reported as OTLP partial success |
| `ipc_write_failure` | IPC writer disconnected mid-write and the event could not be re-queued for retry because the ingest queue was full |

Note: ingest queue saturation returns a retryable HTTP `503` without admitting
records — it does **not** increment this counter. Queue pressure is observable
via `INGEST_QUEUE_DEPTH / INGEST_QUEUE_CAPACITY` and HTTP 503 response counts.

`telemetria_processor_events_dropped_total{reason=...}`:

| Reason | When |
|---|---|
| `queue_full` | Processor's internal queue was full when a frame arrived from the UDS |
| `sink_permanent` | Sink raised `PermanentSinkError` |
| `sink_retries_exhausted` | All `SINK_MAX_RETRIES` retryable attempts failed |

## Production guidance

**Authentication.** The `/metrics` endpoints are unauthenticated. Restrict
access at the network level or bind processes to a non-public interface. See
[`docs/security.md`](security.md).

**Label cardinality.** All labels are bounded low-cardinality values. Never add
raw paths, token keys, event IDs, project/app names, or payload values as
labels.

**Alerting suggestions:**

- `rate(telemetria_ingest_events_dropped_total{reason="otlp_normalized_size"}[5m]) > 0`
  → events are being rejected for size; check `MAX_PAYLOAD_BYTES` and client batch sizes
- `rate(telemetria_processor_events_dropped_total{reason="sink_retries_exhausted"}[5m]) > 0`
  → Loki is unavailable or rejecting batches
- `telemetria_ingest_queue_depth / telemetria_ingest_queue_capacity > 0.8`
  → ingest backpressure; consider increasing `QUEUE_SIZE` or scaling ingest
