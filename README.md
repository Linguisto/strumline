# Strumline

Non-blocking, lightning-fast structured telemetry collector. Application runtime event ingest — send what you
want, from anywhere, over OTLP/HTTP.

Point any OpenTelemetry SDK at Strumline, set a token, and your logs are accepted
for best-effort delivery.
No Collector to configure, no sink to wire up, no client library to install.

Your application calls `POST /v1/logs` with an `x-strumline-token` header and standard
OTLP JSON or Protobuf. Strumline handles authentication, routing, batching, retries,
and delivery to Loki. The token determines which project and app the events belong to —
everything else is automatic.

## Quickstart

```bash
make up             # build, migrate, provision read-only ingest, start stack
```

Services after startup:

- API → http://localhost:8000/health
- Ingest → http://localhost:8001/health
- Processor → http://localhost:8002/health
- Prometheus → http://localhost:9090
- Grafana → http://localhost:3000

This Compose stack is the bundled development environment. Production
deployments use the Strumline image with operator-managed PostgreSQL, sink,
and observability services. Loki is the recommended v1 sink; Prometheus and
Grafana remain optional external integrations in production.

Code changes in `strumline/` reload automatically inside the containers.

Create a project and app. App creation prints its first ingestion token exactly
once; copy that value into your shell without committing it:

```bash
docker compose run --rm strumline-cli strumline project create demo --name "Demo"
docker compose run --rm strumline-cli strumline app create demo web --name "Web"
export STRUMLINE_TOKEN='<token printed by app create>'
```

## Send logs

Use `POST /v1/logs` for one record or a batch. With an app ingestion token:

```bash
curl http://localhost:8001/v1/logs \
  -H "x-strumline-token: ${STRUMLINE_TOKEN}" \
  -H 'Content-Type: application/json' \
  --data '{"resourceLogs":[{"scopeLogs":[{"logRecords":[
    {"severityNumber":9,"body":{"stringValue":"strumline-five-minute-smoke"}}
  ]}]}]}'
```

Full success returns
`200` with `{}`; this acknowledges in-memory admission, not durable delivery.
Partial success reports rejected records; queue saturation returns retryable `503`.
Set `API_DOCS_ENABLED=true` to use the single-log and batch examples in Scalar at
http://localhost:8001/ (`/openapi.json` provides the OpenAPI document).
See the [OTLP contract](docs/api/otlp-logs.md) for limits, structured data,
Protobuf/gzip, and SDK/Collector configuration.

Confirm the event reached Loki:

```bash
curl --get http://localhost:3100/loki/api/v1/query_range \
  --data-urlencode 'query={project="demo",app="web"} |= "strumline-five-minute-smoke"' \
  --data-urlencode 'limit=10'
```

The response must contain `strumline-five-minute-smoke`. Process health and an
ingest `200` alone do not prove delivery. On a clean machine, resource creation
through this Loki result is the v1 five-minute smoke test; image download/build
and initial stack provisioning are measured separately.

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
export OTEL_EXPORTER_OTLP_LOGS_HEADERS="x-strumline-token=${STRUMLINE_TOKEN}"
export OTEL_EXPORTER_OTLP_LOGS_PROTOCOL=http/protobuf   # or http/json
export OTEL_EXPORTER_OTLP_LOGS_COMPRESSION=gzip
```

See the [OTLP contract](docs/api/otlp-logs.md) for full SDK and Collector examples.

## Common commands

```bash
make down           # stop the stack
make migrate        # run database migrations
make bootstrap      # verify/provision the read-only ingest DB role
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

One image, three containers — `strumline-api`, `strumline-ingest`, `strumline-processor` — built from a multi-stage
`docker/Dockerfile`:

- `builder` — installs dependencies at `/app` with `uv`
- `runtime` — minimal non-root image (`strumline` uid 10001), no dev tools
- `dev` — extends runtime with pytest, ruff, mypy, and hot-reload

Ingest and processor share a Unix-domain socket via a named volume (`/var/run/strumline/`). PostgreSQL stores
control-plane metadata only — raw telemetry never touches the database.

## Requirements

- Docker with Compose v2
- `make`

A local Python 3.14+ environment with `uv` is needed only for IDE tooling or `DC_EXEC=uv run` workflows.

## Roadmap

OTLP/HTTP logs are implemented: Protobuf/JSON, gzip, app-token routing, and
metadata preservation through the existing pipeline. The v1 hardening and
release gate (M7) is complete. M7b is the remaining public-release gate; M7c is
an optional usability pass.

After v1:

- **M5 — local ingestion:** expose the HTTP ingest API over a Unix socket.
- **M8 — deeper OpenTelemetry integration:** add OTLP/gRPC, first-class log
  metadata and correlation, then traces and metrics with signal-specific
  processing and compatible sinks. Expand SDK/Collector interoperability and
  operator diagnostics alongside each stage. Profiles remain a later candidate.

See the [full roadmap](.kiro/plans/roadmap.md) and
[M7b release preparation](.kiro/plans/m7b-release-preparation.md), plus the
[M8 scope and acceptance criteria](.kiro/plans/m8-otlp-integration.md).

## Docs

- [Architecture overview](docs/architecture/overview.md)
- [Architecture decisions](docs/architecture/decisions.md)
- [Configuration reference](docs/configuration.md)
- [OTLP logs and exporter configuration](docs/api/otlp-logs.md)
- [IPC protocol](docs/ipc-protocol.md)
- [Sinks](docs/sinks.md)
- [Security](docs/security.md)
- [Observability](docs/observability.md)
- [Observability recipes](docs/observability-recipes.md)
- [Ingest replacement guide](docs/ingest-replacement.md)
- [Benchmarks and methodology](docs/benchmarks.md)
- [Production deployment and recovery](docs/production.md)
- [v1 release checklist](docs/release-checklist.md)
- [Support](SUPPORT.md)
- [Security reporting](SECURITY.md)
