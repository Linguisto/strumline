# Observability

Strumline exposes Prometheus metrics on every process. The development Compose
stack includes Prometheus and Grafana for immediate local inspection. In
production, deploy the Strumline image with your own monitoring services.

## Metrics endpoint

Each process exposes `GET /metrics` when `METRICS_ENABLED=true` (default):

| Process              | URL                              |
|----------------------|----------------------------------|
| `strumline-api`     | `http://<host>:8000/metrics`     |
| `strumline-ingest`  | `http://<host>:8001/metrics`     |
| `strumline-processor` | `http://<host>:8002/metrics`   |

Set `METRICS_ENABLED=false` to disable the endpoint without affecting health
checks or event processing.

## BYO Prometheus and Grafana

In production, add these jobs to your existing `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: strumline-api
    static_configs:
      - targets: ["<api-host>:8000"]
    metrics_path: /metrics

  - job_name: strumline-ingest
    static_configs:
      - targets: ["<ingest-host>:8001"]
    metrics_path: /metrics

  - job_name: strumline-processor
    static_configs:
      - targets: ["<processor-host>:8002"]
    metrics_path: /metrics
```

A standalone copy lives at `docker/observability/prometheus.yml`.

Import the dashboard from `docker/observability/grafana/provisioning/dashboards/strumline.json`
into your Grafana. The dashboard uses data source UIDs `prometheus` and `loki`.
If your data sources have different UIDs, either rename them in Grafana or
find-and-replace the UIDs in the JSON before importing.

## Bundled development observability stack

The repository's development stack starts Prometheus and Grafana with the rest
of the services:

```bash
docker compose up -d
```

| Service    | URL                        |
|------------|----------------------------|
| Prometheus | http://localhost:9090       |
| Grafana    | http://localhost:3000       |

These bundled services are development conveniences, not production runtime
dependencies. Production deployments may use any compatible Prometheus and
Grafana installation or omit them entirely.

## Key metrics reference

| Metric | Labels | Description |
|--------|--------|-------------|
| `strumline_http_requests_total` | `process`, `method`, `route`, `status_class` | HTTP request count |
| `strumline_http_request_duration_seconds` | `process`, `method`, `route` | HTTP latency histogram |
| `strumline_ingest_events_accepted_total` | — | Events admitted to the ingest queue |
| `strumline_ingest_events_dropped_total` | `reason` | Events permanently rejected at ingest (see reasons below) |
| `strumline_ingest_queue_depth` | — | Current ingest queue depth |
| `strumline_ingest_queue_capacity` | — | Ingest queue max capacity (`QUEUE_SIZE`) |
| `strumline_ingest_auth_token_cache_hits_total` | — | Auth token cache hits |
| `strumline_ingest_auth_token_cache_misses_total` | — | Auth token cache misses (DB queries) |
| `strumline_ingest_ipc_reconnects_total` | — | IPC writer reconnect attempts |
| `strumline_processor_queue_depth` | — | Current processor queue depth |
| `strumline_processor_queue_capacity` | — | Processor queue max capacity |
| `strumline_processor_events_dropped_total` | `reason` | Events dropped by the processor (see reasons below) |
| `strumline_processor_batches_total` | `sink` | Batches successfully written to the sink |
| `strumline_processor_batch_size` | `sink` | Batch size histogram |
| `strumline_processor_batch_duration_seconds` | `sink` | Batch write latency histogram |
| `strumline_processor_sink_writes_total` | `sink`, `outcome` | Sink write attempts (success, retryable, permanent) |
| `strumline_ipc_frames_total` | `direction`, `outcome` | IPC frames processed |
| `strumline_ipc_protocol_errors_total` | `error_type` | IPC protocol errors |

### Drop reason labels

`strumline_ingest_events_dropped_total{reason=...}`:

| Reason | When |
|---|---|
| `otlp_normalized_size` | Record exceeds per-frame or cumulative normalized-size limit; reported as OTLP partial success |
| `ipc_write_failure` | IPC writer disconnected mid-write and the event could not be re-queued for retry because the ingest queue was full |

Note: ingest queue saturation returns a retryable HTTP `503` without admitting
records — it does **not** increment this counter. Queue pressure is observable
via `INGEST_QUEUE_DEPTH / INGEST_QUEUE_CAPACITY` and HTTP 503 response counts.

`strumline_processor_events_dropped_total{reason=...}`:

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

- `rate(strumline_ingest_events_dropped_total{reason="otlp_normalized_size"}[5m]) > 0`
  → events are being rejected for size; check `MAX_PAYLOAD_BYTES` and client batch sizes
- `rate(strumline_processor_events_dropped_total{reason="sink_retries_exhausted"}[5m]) > 0`
  → Loki is unavailable or rejecting batches
- `strumline_ingest_queue_depth / strumline_ingest_queue_capacity > 0.8`
  → ingest backpressure; consider increasing `QUEUE_SIZE` or scaling ingest
