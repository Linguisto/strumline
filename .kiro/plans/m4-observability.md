# M4 — Observability Integration

**Type:** Enhancement  
**Depends on:** M3  
**Unlocks:** M6  
**Goal:** Stabilize cross-process metrics and provide optional, first-class Prometheus/Grafana support for bundled and bring-your-own deployments.

## Metrics contract

Metrics are added with the features that emit them in M2/M2b/M3. M4 audits names, labels, documentation, and dashboards across all processes. `/metrics` is available when `METRICS_ENABLED=true`; disabling it does not affect health or event processing.

Required families include:

- HTTP request count/latency by process, method, route template, and status class
- ingest accepted events and `ingest_events_dropped_total{reason}`
- ingest and processor queue depth/capacity
- IPC connections, reconnects, bytes/frames, and protocol errors
- `processor_events_dropped_total{reason}`
- batches, batch sizes, and flush latency
- sink writes, retries, permanent failures, exhausted retries, and latency by provider name
- DSN cache hits/misses and control-plane operation counts

Labels must be bounded. Raw paths, DSNs, event IDs, project/app names, messages, and payload values are forbidden labels. `/metrics` itself is excluded from request instrumentation recursion.

## Optional sample stack

Base `docker compose up` starts neither Prometheus nor Grafana. A single `observability` profile starts pinned sample versions of both:

```text
docker compose --profile observability up -d
```

Prometheus scrapes `telemetria-api:8000`, `telemetria-ingest:8001`, and `telemetria-processor:8002` over the Compose network. Grafana is provisioned with the Prometheus data source and dashboard JSON. If the separate `loki` profile is active, Grafana also provisions Loki and enables log panels; otherwise those panels display an explicit unavailable state while metric panels remain useful.

## Bring your own

Ship standalone, documented artifacts:

- Prometheus scrape configuration with the three targets and path
- Grafana dashboard JSON without hard-coded data-source UIDs
- optional Loki data-source/dashboard fragment
- production guidance for authentication/network controls around metrics endpoints

External URLs such as `PROMETHEUS_URL`, `GRAFANA_URL`, and `LOKI_URL` are optional hints for `doctor`/TUI. Telemetria does not require these services to process events.

## Acceptance criteria

- [ ] Each process serves valid Prometheus text when enabled and does not expose the route when disabled.
- [ ] Ingest and processor drops have distinct counters and reasons.
- [ ] Sink labels use the selected provider's stable `name`.
- [ ] Route labels are templates; a cardinality test rejects dynamic identifiers.
- [ ] The `observability` profile starts pinned Prometheus and Grafana and scrapes all three processes.
- [ ] Grafana metric panels work without Loki; log panels degrade clearly.
- [ ] `loki` and `observability` profiles work independently and together.
- [ ] BYO scrape config and dashboard JSON import without using the bundled services.
