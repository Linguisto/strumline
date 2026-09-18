# Observability

Telemetria exposes Prometheus metrics on every process. In production you bring your own Prometheus and Grafana — only the app image is deployed alongside your managed Postgres and Loki instances.

## Metrics endpoint

Each process exposes `GET /metrics` when `METRICS_ENABLED=true` (default):

| Process              | URL                              |
|----------------------|----------------------------------|
| `telemetria-api`     | `http://<host>:8000/metrics`     |
| `telemetria-ingest`  | `http://<host>:8001/metrics`     |
| `telemetria-processor` | `http://<host>:8002/metrics`   |

Set `METRICS_ENABLED=false` to disable the endpoint without affecting health checks or event processing.

## Prometheus scrape config

Add these jobs to your `prometheus.yml`. A standalone copy lives at `docker/observability/prometheus.yml`.

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

## Grafana dashboard

Import `docker/observability/grafana/provisioning/dashboards/telemetria.json`.

The dashboard uses data source UIDs `prometheus` and `loki`. If your data sources have different UIDs, either rename them in Grafana or find-and-replace the UIDs in the JSON before importing.

## Key metrics reference

| Metric | Labels | Description |
|--------|--------|-------------|
| `telemetria_http_requests_total` | `process`, `method`, `route`, `status_class` | HTTP request count |
| `telemetria_http_request_duration_seconds` | `process`, `method`, `route` | HTTP latency histogram |
| `telemetria_ingest_events_accepted_total` | — | Events accepted and enqueued |
| `telemetria_ingest_events_dropped_total` | `reason` | Events dropped (queue_full, validation_error, auth_error) |
| `telemetria_ingest_queue_depth` | — | Current ingest queue depth |
| `telemetria_ingest_queue_capacity` | — | Ingest queue max capacity |
| `telemetria_ingest_dsn_cache_hits_total` | — | DSN cache hits |
| `telemetria_ingest_dsn_cache_misses_total` | — | DSN cache misses (DB queries) |
| `telemetria_ingest_ipc_reconnects_total` | — | IPC writer reconnect attempts |
| `telemetria_processor_queue_depth` | — | Current processor queue depth |
| `telemetria_processor_queue_capacity` | — | Processor queue max capacity |
| `telemetria_processor_events_dropped_total` | `reason` | Events dropped (queue_full, sink_permanent, sink_retries_exhausted) |
| `telemetria_processor_batches_total` | `sink` | Batches successfully written |
| `telemetria_processor_batch_size` | `sink` | Batch size histogram |
| `telemetria_processor_batch_duration_seconds` | `sink` | Batch write latency histogram |
| `telemetria_processor_sink_writes_total` | `sink`, `outcome` | Sink write attempts (success, retryable, permanent) |
| `telemetria_ipc_frames_total` | `direction`, `outcome` | IPC frames processed |
| `telemetria_ipc_protocol_errors_total` | `error_type` | IPC protocol errors |

## Production guidance

**Authentication.** The `/metrics` endpoints are unauthenticated. Restrict access at the network level or bind processes to a non-public interface.

**Label cardinality.** All labels are bounded low-cardinality values. Never add raw paths, DSN keys, event IDs, project/app names, or payload values as labels.

**Alerting suggestions:**
- `telemetria_ingest_events_dropped_total{reason="queue_full"}` rising → increase `QUEUE_SIZE` or scale ingest
- `telemetria_processor_events_dropped_total{reason="sink_retries_exhausted"}` rising → investigate Loki availability
- `telemetria_ingest_queue_depth / telemetria_ingest_queue_capacity > 0.8` → backpressure warning
