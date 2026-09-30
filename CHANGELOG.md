# Changelog

All notable changes to Strumline are documented through GitHub releases. The
release workflow generates per-commit notes from Conventional Commits with
`git-cliff`; the human-readable summary for each release lives below.

## Unreleased — v1.0.0 (preparing)

First stable release: a best-effort structured-logs collector that accepts
OTLP/HTTP, resolves a project and app from an ingestion token, batches events,
and delivers them to a replaceable sink (Loki in v1).

### Capabilities

- OTLP/HTTP logs at `POST /v1/logs` — JSON and Protobuf, optional gzip, single
  records or batches, with app-token routing and resource/scope/record
  preservation.
- Control plane for projects, apps, and ingestion tokens via CLI and the
  runtime-gated admin REST API. Token keys are shown once at creation.
- One image, three containers (`api`, `ingest`, `processor`) with a read-only
  ingest database role, integrated `/metrics`, and a `strumline doctor`
  read-only diagnostic.

### Intentional limitations

- An OTLP `200` acknowledges **in-memory admission, not durable delivery**.
  Process, IPC, or exhausted-retry failures may drop accepted records, and
  retries may produce duplicate event IDs. Queue saturation returns retryable
  `503` with no admission.
- v1 ships the `null` and `loki` sinks only. Per-app routing, fan-out, durable
  storage, replay, OTLP/gRPC, traces, and metrics are post-v1 (see the roadmap).
- Published throughput/latency numbers measure HTTP receipt-to-enqueue with
  in-process transport, not end-to-end sink delivery. See
  [Benchmarks and methodology](docs/benchmarks.md).

### Install and first event

- [Quickstart](README.md#quickstart) — `make up`, then create a project and app.
- [Send logs](README.md#send-logs) — submit the sample and confirm it in Loki
  (the five-minute smoke test).

### Upgrade

- This is the first release; there is no prior version to upgrade from.
- Preserve `APP_KEY` across restarts and upgrades — changing it invalidates the
  hashes of existing ingestion tokens. See
  [Production deployment and recovery](docs/production.md).
