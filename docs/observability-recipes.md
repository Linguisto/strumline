# Observability recipes

Telemetria exposes standard Prometheus metrics on `/metrics` at each process port. This document shows how to wire those metrics into common observability stacks, from the simplest possible setup to fully-managed cloud observability.

All recipes assume you have Telemetria running with `METRICS_ENABLED=true` (the default). The BYO artifacts live in `docker/observability/` — a ready-to-use Prometheus scrape config and a Grafana dashboard JSON you can import into any Grafana instance.

---

## Prometheus + Grafana (self-hosted, first-class)

This is the reference setup. Everything in `docker/observability/` is built for it.

### Prometheus

Add to your `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: telemetria-api
    static_configs:
      - targets: ["<api-host>:8000"]

  - job_name: telemetria-ingest
    static_configs:
      - targets: ["<ingest-host>:8001"]

  - job_name: telemetria-processor
    static_configs:
      - targets: ["<processor-host>:8002"]
```

A standalone copy is at `docker/observability/prometheus.yml` — use it as-is if your Prometheus can reach the Telemetria containers by hostname.

### Grafana

Import `docker/observability/grafana/provisioning/dashboards/telemetria.json` into any Grafana instance (≥ 11):

1. **Dashboards → Import → Upload JSON file** → select `telemetria.json`
2. Set the Prometheus data source UID to `prometheus` (or find-and-replace the UID in the JSON)
3. If you have Loki, add a Loki data source with UID `loki` — the log panel activates automatically

The dashboard covers all key signals across the three processes: ingest rate, drop rate, queue saturation, batch throughput, sink outcomes, HTTP latency P99, IPC health, and auth token cache hit rate.

### Provisioning automatically

If you provision Grafana via config files, copy the contents of `docker/observability/grafana/provisioning/` into your Grafana provisioning directory. It includes datasource and dashboard provider definitions that work with any Grafana ≥ 11 instance.

---

## Grafana Agent (no separate Prometheus)

Grafana Agent can scrape Prometheus metrics and push them directly to Grafana Cloud or a Mimir instance without running a standalone Prometheus.

```yaml
# agent.yaml
metrics:
  global:
    scrape_interval: 15s
  configs:
    - name: telemetria
      scrape_configs:
        - job_name: telemetria-api
          static_configs:
            - targets: ["<api-host>:8000"]
        - job_name: telemetria-ingest
          static_configs:
            - targets: ["<ingest-host>:8001"]
        - job_name: telemetria-processor
          static_configs:
            - targets: ["<processor-host>:8002"]
      remote_write:
        - url: <your-mimir-or-grafana-cloud-url>
          basic_auth:
            username: <username>
            password: <api-key>
```

The Grafana dashboard JSON works unchanged — it uses standard PromQL that runs against any Prometheus-compatible backend.

---

## Grafana Cloud

Grafana Cloud accepts Prometheus remote_write and Loki push directly.

### Metrics

Use Grafana Agent (above) or the Grafana Cloud Agent with `remote_write` pointed at your Grafana Cloud Prometheus endpoint. The metrics and dashboard are identical.

### Logs

Point `LOKI_URL` at your Grafana Cloud Loki endpoint:

```
LOKI_URL=https://logs-prod-xxx.grafana.net
LOKI_TENANT_ID=<your-org-id>
```

Set `LOKI_TENANT_ID` to your Grafana Cloud org ID. Telemetria sends it as `X-Scope-OrgID` on every push request.

---

## Victoria Metrics

Victoria Metrics is a drop-in Prometheus-compatible TSDB. The scrape config is identical to the Prometheus recipe above — use `vmagent` instead of Prometheus:

```yaml
# vmagent scrape config
scrape_configs:
  - job_name: telemetria
    static_configs:
      - targets:
          - "<api-host>:8000"
          - "<ingest-host>:8001"
          - "<processor-host>:8002"
```

The Grafana dashboard works unchanged against a Victoria Metrics data source.

---

## Datadog

Datadog's OpenMetrics integration scrapes Prometheus endpoints via the Agent.

```yaml
# conf.d/openmetrics.d/conf.yaml
instances:
  - openmetrics_endpoint: http://<api-host>:8000/metrics
    namespace: telemetria
    metrics:
      - telemetria_.*
    type_overrides:
      telemetria_http_request_duration_seconds: histogram
      telemetria_processor_batch_size: histogram
      telemetria_processor_batch_duration_seconds: histogram

  - openmetrics_endpoint: http://<ingest-host>:8001/metrics
    namespace: telemetria
    metrics:
      - telemetria_.*

  - openmetrics_endpoint: http://<processor-host>:8002/metrics
    namespace: telemetria
    metrics:
      - telemetria_.*
```

Metrics appear in Datadog under `telemetria.*`. Build dashboards and monitors using the same metric names with `.` replacing `_` as needed by Datadog's naming convention.

---

## New Relic

New Relic's Prometheus remote write integration or the OpenTelemetry Collector can scrape and forward Telemetria metrics.

### Via Prometheus remote_write

Configure Prometheus to remote_write to New Relic:

```yaml
remote_write:
  - url: https://metric-api.newrelic.com/prometheus/v1/write?prometheus_server=telemetria
    bearer_token: <your-new-relic-license-key>
```

### Via OpenTelemetry Collector

```yaml
receivers:
  prometheus:
    config:
      scrape_configs:
        - job_name: telemetria
          static_configs:
            - targets: ["<api-host>:8000", "<ingest-host>:8001", "<processor-host>:8002"]

exporters:
  otlp:
    endpoint: otlp.nr-data.net:4317
    headers:
      api-key: <license-key>

service:
  pipelines:
    metrics:
      receivers: [prometheus]
      exporters: [otlp]
```

---

## AWS CloudWatch

Use the CloudWatch Agent with the Prometheus scraper plugin, or the AWS Distro for OpenTelemetry (ADOT).

### CloudWatch Agent

```json
{
  "agent": { "metrics_collection_interval": 60 },
  "logs": {
    "metrics_collected": {
      "prometheus": {
        "prometheus_config_path": "/opt/aws/amazon-cloudwatch-agent/etc/prometheus.yaml",
        "emf_processor": {
          "metric_namespace": "Telemetria",
          "metric_declaration": [
            {
              "source_labels": ["job"],
              "label_matcher": "^telemetria.*",
              "dimensions": [["process", "route"]],
              "metric_selectors": ["telemetria_http_requests_total", "telemetria_ingest_events_dropped_total"]
            }
          ]
        }
      }
    }
  }
}
```

With a `prometheus.yaml` pointing at the three Telemetria endpoints.

---

## OpenTelemetry Collector (generic)

The OTel Collector can scrape Prometheus endpoints and export to any backend.

```yaml
receivers:
  prometheus:
    config:
      scrape_configs:
        - job_name: telemetria-api
          static_configs:
            - targets: ["<api-host>:8000"]
        - job_name: telemetria-ingest
          static_configs:
            - targets: ["<ingest-host>:8001"]
        - job_name: telemetria-processor
          static_configs:
            - targets: ["<processor-host>:8002"]

processors:
  batch: {}

exporters:
  # Replace with your backend: otlp, prometheusremotewrite, datadog, etc.
  prometheusremotewrite:
    endpoint: http://<your-backend>/api/v1/write

service:
  pipelines:
    metrics:
      receivers: [prometheus]
      processors: [batch]
      exporters: [prometheusremotewrite]
```

---

## Alerting rules (PromQL)

Copy these into your Prometheus or compatible alerting system. Adjust thresholds to match your traffic volume.

```yaml
groups:
  - name: telemetria
    rules:

      # Ingest queue saturation — warn before events start dropping
      - alert: IngestQueueSaturated
        expr: |
          telemetria_ingest_queue_depth / telemetria_ingest_queue_capacity > 0.8
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Ingest queue above 80% capacity"
          description: "Queue at {{ $value | humanizePercentage }}. Events will drop at 100%."

      # Ingest drops — events already being lost
      - alert: IngestEventsDroppingFast
        expr: |
          rate(telemetria_ingest_events_dropped_total[5m]) > 10
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Ingest dropping events ({{ $labels.reason }})"
          description: "{{ $value | humanize }} drops/s. Increase QUEUE_SIZE or scale ingest."

      # Sink retries exhausted — processor discarding events
      - alert: ProcessorEventsDropping
        expr: |
          rate(telemetria_processor_events_dropped_total[5m]) > 0
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Processor dropping events ({{ $labels.reason }})"
          description: "Check Loki availability and SINK_MAX_RETRIES."

      # IPC disconnect — ingest writer reconnecting repeatedly
      - alert: IPCReconnectingFrequently
        expr: |
          rate(telemetria_ingest_ipc_reconnects_total[5m]) > 0.1
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "IPC writer reconnecting frequently"
          description: "Check processor health and socket path."

      # HTTP error rate — ingest returning 4xx/5xx
      - alert: IngestHighErrorRate
        expr: |
          rate(telemetria_http_requests_total{process="ingest", status_class=~"4xx|5xx"}[5m])
          /
          rate(telemetria_http_requests_total{process="ingest"}[5m])
          > 0.05
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Ingest HTTP error rate above 5%"

      # Ingest P99 latency
      - alert: IngestHighLatency
        expr: |
          histogram_quantile(0.99,
            rate(telemetria_http_request_duration_seconds_bucket{process="ingest"}[5m])
          ) > 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Ingest P99 latency above 100ms"
```

---

## Key metrics quick reference

| What you want to know | Metric | Notes |
|---|---|---|
| Ingest throughput | `rate(telemetria_ingest_events_accepted_total[1m])` | events/s accepted |
| Drop rate | `rate(telemetria_ingest_events_dropped_total[1m])` | split by `reason` |
| Queue fill % | `telemetria_ingest_queue_depth / telemetria_ingest_queue_capacity` | alert at 0.8 |
| auth token cache effectiveness | `rate(hits[5m]) / (rate(hits[5m]) + rate(misses[5m]))` | lower = more DB load |
| IPC stability | `rate(telemetria_ingest_ipc_reconnects_total[5m])` | non-zero = socket issues |
| Sink throughput | `rate(telemetria_processor_batches_total[1m])` | batches/s by `sink` |
| Sink success rate | `telemetria_processor_sink_writes_total{outcome="success"}` vs `retryable` + `permanent` | |
| Processor drops | `rate(telemetria_processor_events_dropped_total[1m])` | split by `reason` |
| HTTP P99 latency | `histogram_quantile(0.99, rate(telemetria_http_request_duration_seconds_bucket[5m]))` | by `process` and `route` |
