# Strumline

Strumline is an opinionated, ready-to-use telemetry ingress layer for OTLP/HTTP
logs. Point any standard OpenTelemetry SDK/exporter at Strumline, set an app
token, and send logs to your existing Loki/Grafana setup.

Strumline handles authentication, token-based project/app routing, batching,
retries, and best-effort delivery to Loki. No Collector configuration or
Strumline-specific SDK is required. You can also send OTLP directly over HTTP,
which is useful for smoke tests.

## Quickstart

Have PostgreSQL and Loki already? Strumline uses your existing services; view logs
in your existing Grafana. Loki is the recommended v1 sink. Raw telemetry never
touches PostgreSQL.

1. Copy [compose.production.yaml](docker/compose.production.yaml) as `compose.yaml`
   and [.env.production](docker/.env.production) as `.env` into a
   deployment directory. The Compose file uses `ghcr.io/linguisto/strumline:1.0.0`.
2. Fill in the `STRUMLINE_` settings in `.env` for your database, Loki, and secrets.
   The database must exist and be reachable from Docker; bootstrap needs role
   creation and grant permissions. Keep `STRUMLINE_APP_KEY` for future restarts.
3. With Docker Compose v2 and `jq` installed, deploy Strumline and create an app:

```bash
docker compose pull
docker compose run --rm strumline-cli strumline migrate
docker compose run --rm strumline-cli python -m strumline.db.bootstrap
docker compose up -d

docker compose run --rm strumline-cli strumline project create demo --name "Demo"
APP_JSON=$(docker compose run --rm -T strumline-cli strumline app create demo web --name "Web")
export STRUMLINE_TOKEN=$(printf '%s' "$APP_JSON" | jq -r '.token_key')
unset APP_JSON
```

Save the token securely; it is shown once and routes logs to this project/app.
Configure any OTLP/HTTP logs SDK/exporter you already use, then emit a log through
your application's normal logging integration:

```bash
export OTEL_EXPORTER_OTLP_LOGS_ENDPOINT=http://localhost:8001/v1/logs
export OTEL_EXPORTER_OTLP_LOGS_HEADERS="x-strumline-token=${STRUMLINE_TOKEN}"
export OTEL_EXPORTER_OTLP_LOGS_PROTOCOL=http/protobuf
export OTEL_EXPORTER_OTLP_LOGS_COMPRESSION=gzip
```

For remote applications, replace the endpoint with the HTTPS URL in front of
ingest port 8001. SDK configuration varies by language; equivalent explicit
exporter options work too. No Strumline-specific SDK is needed. To test without
an SDK, use the [direct HTTP smoke test](docs/quickstart.md#direct-http-smoke-test).

In Grafana Explore, select your Loki data source and query for the log you sent,
for example:

```logql
{project="demo",app="web"} |= "strumline-first-log"
```

The event should appear within a few seconds. Strumline accepts OTLP/HTTP JSON and
Protobuf with gzip support. A `200` means **in-memory admission, not durable
delivery**; queue saturation returns retryable `503`. Raw telemetry never touches
PostgreSQL.

[Detailed setup and troubleshooting](docs/quickstart.md) ·
[OTLP exporter configuration](docs/api/otlp-logs.md) ·
[Production operations](docs/production.md) · [Configuration](docs/configuration.md) ·
[Security](docs/security.md) · [Observability](docs/observability.md)

## Local development

The repository's bundled Compose stack is for development, testing, and local
demos. It builds the dev image and includes PostgreSQL, Loki, Prometheus, and
Grafana with development defaults and automatic code reload:

```bash
make up             # build, migrate, provision read-only ingest, start stack
```

Local endpoints: API `http://localhost:8000/health`, ingest
`http://localhost:8001/health`, processor `http://localhost:8002/health`,
Loki `http://localhost:3100`, Prometheus `http://localhost:9090`, and
Grafana `http://localhost:3000`. Use the creation and send commands above;
query the local Loki through Grafana or its HTTP API.

```bash
make down           # stop the local stack (keeps volumes)
make migrate        # run database migrations
make bootstrap      # verify/provision the read-only ingest DB role
make lint           # ruff + mypy + import-linter
make test           # full suite, needs Docker
make test.unit      # unit tests only
make build.dev      # dev image with lint/test tools
make build          # non-root production image, no dev dependencies
```

Development requires Docker with Compose v2 and `make`. Python 3.14+ with `uv`
is needed only for IDE tooling or local checks via `DC_EXEC="uv run"`.
See [Contributing](CONTRIBUTING.md) and the
[Architecture overview](docs/architecture/overview.md) for internals.

## Roadmap

OTLP/HTTP logs are implemented: Protobuf/JSON, gzip, app-token routing, and
metadata preservation through the existing pipeline. The v1 hardening and
release gate (M7) is complete. M7b (public-release preparation) completes the
mandatory `M7 → M7b → v1.0` path; M7c is an optional CLI/docs/DX polish pass and
is not a release prerequisite.

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

Start here based on what you are doing:

**Application developers** (send logs from your app):

- [OTLP logs and exporter configuration](docs/api/otlp-logs.md) — endpoint, auth header, JSON/Protobuf/gzip,
  SDK/Collector setup
- The [Quickstart](#quickstart) walkthrough above

**Operators** (deploy, configure, diagnose):

- [Production deployment and recovery](docs/production.md)
- [Configuration reference](docs/configuration.md)
- [Security](docs/security.md)
- [Observability](docs/observability.md) and [Observability recipes](docs/observability-recipes.md)
- [Troubleshooting](docs/quickstart.md#troubleshooting) (`strumline doctor`)

**Contributors** (build, test, extend):

- [Architecture overview](docs/architecture/overview.md) and [decisions](docs/architecture/decisions.md)
- [Contributing guide](CONTRIBUTING.md) — environment, quality gates, workflow
- [Benchmarks and methodology](docs/benchmarks.md)

**Sink implementers** (add a delivery backend):

- [Sinks](docs/sinks.md) — `EventSink` contract and registry
- [IPC protocol](docs/ipc-protocol.md)
- [Ingest replacement guide](docs/ingest-replacement.md)

**Release and support:**

- [v1 release checklist](docs/release-checklist.md)
- [Support](SUPPORT.md) and [Security reporting](SECURITY.md)
