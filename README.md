# Strumline

Strumline is an opinionated, ready-to-use telemetry ingress layer for OTLP/HTTP
logs. Point any standard OpenTelemetry SDK/exporter at Strumline, set an app
token, and send logs to your existing Loki/Grafana setup.

Strumline handles authentication, token-based project/app routing, batching,
retries, and best-effort delivery to Loki. No Collector configuration or
Strumline-specific SDK is required. Use any standard OTLP exporter, or send
standard OTLP JSON or Protobuf directly over HTTP.

## Quickstart

This path assumes you already run PostgreSQL and Loki. Grafana is optional and
external; use your existing instance to view the logs. You need Docker Compose
v2 on the deployment host.

### 1. Deploy Strumline

Copy [compose.production.yaml](docker/compose.production.yaml) as `compose.yaml`
and [.env.production](docker/.env.production) as `.env`. Fill in the
`STRUMLINE_` values, then run:

```bash
docker compose pull
docker compose run --rm strumline-cli strumline migrate
docker compose run --rm strumline-cli python -m strumline.db.bootstrap
docker compose up -d
```

The Compose file deploys `ghcr.io/linguisto/strumline:1.0.0` and connects to your
external PostgreSQL and Loki services. See the [detailed quickstart](docs/quickstart.md)
for prerequisites, permissions, TLS, and network exposure.

### 2. Create a destination

```bash
docker compose run --rm strumline-cli strumline project create demo --name "Demo"
docker compose run --rm strumline-cli strumline app create demo web --name "Web"
export STRUMLINE_TOKEN='<token_key from app create>'
```

The token is shown once. Store it securely; it routes every accepted log to this
project and app.

### 3. Send OTLP directly over HTTP

Strumline accepts standard OTLP requests at `POST /v1/logs`. Direct HTTP is a
supported integration path for any client that can produce OTLP JSON or Protobuf:

```bash
curl --fail-with-body http://localhost:8001/v1/logs \
  -H "x-strumline-token: ${STRUMLINE_TOKEN}" \
  -H 'Content-Type: application/json' \
  --data '{"resourceLogs":[{"scopeLogs":[{"logRecords":[
    {"severityNumber":9,"body":{"stringValue":"strumline-first-log"}}
  ]}]}]}'
```

### 4. Connect your application with an OTLP exporter

Use any standard OTLP/HTTP logs SDK/exporter:

```bash
export OTEL_EXPORTER_OTLP_LOGS_ENDPOINT=http://localhost:8001/v1/logs
export OTEL_EXPORTER_OTLP_LOGS_HEADERS="x-strumline-token=${STRUMLINE_TOKEN}"
export OTEL_EXPORTER_OTLP_LOGS_PROTOCOL=http/protobuf
export OTEL_EXPORTER_OTLP_LOGS_COMPRESSION=gzip
```

For application logging, exporters provide the usual SDK logging integration,
batching, and retry behavior. Emit `strumline-first-log` through your application's
logging integration. For a remote application, use the HTTPS endpoint in front of
ingest port 8001. SDKs may also accept these values as explicit exporter options.
No Strumline-specific SDK is required.

### 5. See the log in Loki

In Grafana Explore, select your Loki data source and run:

```logql
{project="demo",app="web"} |= "strumline-first-log"
```

The event should appear within a few seconds. Strumline accepts OTLP/HTTP JSON and
Protobuf with gzip. A `200` acknowledges **in-memory admission, not durable
delivery**; queue saturation returns retryable `503`. Delivery is best-effort,
and raw telemetry never touches PostgreSQL.

[Detailed setup and troubleshooting](docs/quickstart.md) ·
[OTLP exporter configuration](docs/api/otlp-logs.md) ·
[Production operations](docs/production.md) · [Configuration](docs/configuration.md) ·
[Security](docs/security.md) · [Observability](docs/observability.md)

## Local development

The repository's bundled Compose stack is for development, testing, and local
demos. It includes PostgreSQL, Loki, Prometheus, and Grafana with development
defaults and automatic code reload:

```bash
make up
```

Use `make down` to stop it. See [Contributing](CONTRIBUTING.md) for the development
workflow and commands.

## Documentation

- Send logs: [OTLP/HTTP contract and exporter configuration](docs/api/otlp-logs.md)
- Operate Strumline: [production](docs/production.md),
  [configuration](docs/configuration.md), [security](docs/security.md),
  [observability](docs/observability.md), and
  [troubleshooting](docs/quickstart.md#troubleshooting)
- Contribute: [contributing guide](CONTRIBUTING.md) and
  [architecture overview](docs/architecture/overview.md)
- Extend Strumline: [sinks](docs/sinks.md), [IPC protocol](docs/ipc-protocol.md),
  and [ingest replacement](docs/ingest-replacement.md)
- Get help: [support](SUPPORT.md) and [security reporting](SECURITY.md)
