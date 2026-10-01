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

Create a project and app. Both commands print JSON on stdout; `app create`
emits its first ingestion token exactly once, under `token_key`. Capture that
value into your shell without committing it:

```bash
docker compose run --rm strumline-cli strumline project create demo --name "Demo"

# app create prints JSON: {"id": ..., "slug": "web", "token_id": ..., "token_key": "..."}
APP_JSON=$(docker compose run --rm -T strumline-cli strumline app create demo web --name "Web")
export STRUMLINE_TOKEN=$(printf '%s' "$APP_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["token_key"])')
```

The `-T` flag disables Compose's TTY allocation so the JSON is captured cleanly.
The token is shown only at creation — `app show`/`info` never print it again. If
you lose it, create a new token with `strumline token create <app-id>`.

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

## Troubleshooting

Run `strumline doctor` first — it checks process health, database connectivity,
migration state, and (when `SINK_PROVIDER=loki`) Loki reachability, and prints a
next step for every failing check. It is read-only and does **not** verify sink
delivery; use the Loki query above for that.

| Symptom | Likely cause | What to do |
|---|---|---|
| `401`/`403` on `/v1/logs` | Missing/invalid/revoked token, or `APP_KEY` changed | Confirm `x-strumline-token`; recreate a token with `strumline token create <app-id>`. Changing `APP_KEY` invalidates existing token hashes. |
| Retryable `503` from ingest | Queue saturated (backpressure) | Retry with backoff; the event was not admitted. Sustained `503` means the processor/sink is not draining — check `strumline doctor` and processor logs. |
| Ingest returns `200` but nothing in Loki | `200` is in-memory admission, not delivery; sink/IPC/processor issue, or wrong labels | Check `strumline doctor` (loki reachable), processor `events_dropped` metrics, and that the Loki query uses the correct `project`/`app` labels. |
| CLI hangs or exits non-zero | Missing input in a non-interactive shell, or DB unreachable | Pass all required args (see `--help`); an "Operational error" on stderr means a dependency/config problem — run `strumline doctor`. |
| Migrations out of date | Schema not applied | Run `make migrate` (or `strumline migrate`). |

See [Security](docs/security.md), [Observability](docs/observability.md), and
[Production deployment and recovery](docs/production.md) for deeper diagnostics.

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
make build.dev      # dev image — includes pytest, ruff, mypy; used by lint/test
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
- [OTLP logs and exporter configuration](docs/api/otlp-logs.md) — endpoint, auth header, JSON/Protobuf/gzip, SDK/Collector setup
- The [Quickstart](#quickstart) and [Send logs](#send-logs) walkthrough above

**Operators** (deploy, configure, diagnose):
- [Production deployment and recovery](docs/production.md)
- [Configuration reference](docs/configuration.md)
- [Security](docs/security.md)
- [Observability](docs/observability.md) and [Observability recipes](docs/observability-recipes.md)
- [Troubleshooting](#troubleshooting) above (`strumline doctor`)

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
