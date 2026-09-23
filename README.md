# Telemetria

Non-blocking, lightning-fast structured telemetry collector. Application runtime event ingest — send what you
want, from anywhere, over OTLP/HTTP.

Point any OpenTelemetry SDK at Telemetria, set a token, and your logs are delivered.
No Collector to configure, no sink to wire up, no client library to install.

Your application calls `POST /v1/logs` with an `x-telemetria-token` header and standard
OTLP JSON or Protobuf. Telemetria handles authentication, routing, batching, retries,
and delivery to Loki. The token determines which project and app the events belong to —
everything else is automatic.

## Quickstart

```bash
make up             # build dev image + start stack + run migrations
```

Services after startup:

- API → http://localhost:8000/health
- Ingest → http://localhost:8001/health
- Processor → http://localhost:8002/health
- Prometheus → http://localhost:9090
- Grafana → http://localhost:3000

Code changes in `telemetria/` reload automatically inside the containers.

## Send logs

Use `POST /v1/logs` for one record or a batch. With an app ingestion token:

```bash
curl http://localhost:8001/v1/logs \
  -H "x-telemetria-token: ${TELEMETRIA_TOKEN}" \
  -H 'Content-Type: application/json' \
  --data '{"resourceLogs":[{"scopeLogs":[{"logRecords":[
    {"severityNumber":9,"body":{"stringValue":"Application started"}},
    {"severityNumber":9,"body":{"stringValue":"Ready to accept requests"}}
  ]}]}]}'
```

Keep just one item in `logRecords` to send a single log. Full success returns
`200` with `{}`; this acknowledges in-memory admission, not durable delivery.
Partial success reports rejected records; queue saturation returns retryable `503`.
Set `API_DOCS_ENABLED=true` to use the single-log and batch examples in Scalar at
http://localhost:8001/ (`/openapi.json` provides the OpenAPI document).
See the [OTLP contract](docs/api/otlp-logs.md) for limits, structured data,
Protobuf/gzip, and SDK/Collector configuration.

**Using Protobuf or an SDK exporter?** The wire models come from the official
OpenTelemetry packages — find the one for your language at
[github.com/open-telemetry](https://github.com/open-telemetry), or install
directly:

```bash
# Python
pip install opentelemetry-exporter-otlp-proto-http

# Go
go get go.opentelemetry.io/otel/exporters/otlp/otlplog/otlploghttp

# Node
npm install @opentelemetry/exporter-logs-otlp-http
```

Configure with environment variables:

```bash
export OTEL_EXPORTER_OTLP_LOGS_ENDPOINT=http://localhost:8001/v1/logs
export OTEL_EXPORTER_OTLP_LOGS_HEADERS="x-telemetria-token=${TELEMETRIA_TOKEN}"
export OTEL_EXPORTER_OTLP_LOGS_PROTOCOL=http/protobuf   # or http/json
export OTEL_EXPORTER_OTLP_LOGS_COMPRESSION=gzip
```

See the [OTLP contract](docs/api/otlp-logs.md) for full SDK and Collector examples.

## Common commands

```bash
make down           # stop the stack
make migrate        # run database migrations
make lint           # ruff + mypy + import-linter
make test           # pytest (full suite, needs Docker)
make test.unit      # unit tests only, no Docker required
```

## Building the image

```bash
make build.dev      # dev image — includes pytest, ruff, mypy; used by make install
make build          # production image — runtime stage only, no dev deps
```

The production image is a minimal non-root image built from `docker/Dockerfile`.
Tag and push it manually, or let the release workflow handle it on a `vX.Y.Z` tag.

`lint` and `test` run inside the container by default. Run locally with `DC_EXEC="uv run"`.

## Docker

One image, three containers — `telemetria-api`, `telemetria-ingest`, `telemetria-processor` — built from a multi-stage
`docker/Dockerfile`:

- `builder` — installs dependencies at `/app` with `uv`
- `runtime` — minimal non-root image (`telemetria` uid 10001), no dev tools
- `dev` — extends runtime with pytest, ruff, mypy, and hot-reload

Ingest and processor share a Unix-domain socket via a named volume (`/var/run/telemetria/`). PostgreSQL stores
control-plane metadata only — raw telemetry never touches the database.

## Requirements

- Docker with Compose v2
- `make`

A local Python 3.14+ environment with `uv` is needed only for IDE tooling or `DC_EXEC=uv run` workflows.

## Roadmap

OTLP/HTTP logs are implemented: Protobuf/JSON, gzip, app-token routing, and
metadata preservation through the existing pipeline. M7 remains the v1
hardening and release gate.

After v1:

- **M5 — local ingestion:** expose the HTTP ingest API over a Unix socket.
- **M8 — deeper OpenTelemetry integration:** add OTLP/gRPC, first-class log
  metadata and correlation, then traces and metrics with signal-specific
  processing and compatible sinks. Expand SDK/Collector interoperability and
  operator diagnostics alongside each stage. Profiles remain a later candidate.

See the [full roadmap](.kiro/plans/roadmap.md) and
[M8 scope and acceptance criteria](.kiro/plans/m8-otlp-integration.md).

## Docs

- [Architecture overview](docs/architecture/overview.md)
- [Architecture decisions](docs/architecture/decisions.md)
- [Configuration reference](docs/configuration.md)
- [OTLP logs and exporter configuration](docs/api/otlp-logs.md)
- [IPC protocol](docs/ipc-protocol.md)
- [Sinks](docs/sinks.md)
- [Observability](docs/observability.md)
- [Observability recipes](docs/observability-recipes.md)
