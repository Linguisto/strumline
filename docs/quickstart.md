# First logs with external PostgreSQL and Loki

Already have PostgreSQL, Loki, and Grafana? Deploy the published Strumline image,
create an app token, and send OTLP logs over HTTP. An OpenTelemetry SDK/exporter
is optional. PostgreSQL stores projects, apps, and token hashes only — raw
telemetry never touches it.
Loki is the recommended v1 sink; use your existing Grafana to explore the logs.
PostgreSQL and Loki are external dependencies. Grafana and Prometheus are optional
external integrations, not bundled production components.

## 1. Deploy Strumline

Use Docker with Compose v2. In a new deployment directory (no source checkout
required), copy [the production Compose example](../docker/compose.production.yaml)
as `compose.yaml`. This is the supported single-host topology:
three containers from one release image, with a shared socket volume. The CLI runs
only when invoked. No observability stack is created.

Use a fixed release tag or digest for every container. Copy
[the production environment example](../docker/.env.production) as `.env`
alongside it and replace the example hosts and secrets with your own. The
`STRUMLINE_` prefix avoids collisions with other services' settings; Compose maps
these deployment variables to Strumline's existing runtime variable names.

The database must already exist and be reachable from the containers. Use its
schema-owning application role for migrations. Preserve `STRUMLINE_APP_KEY` across restarts
and upgrades so existing tokens keep working. Ingest receives only the read-only
role; the processor receives no database credentials.

Pull the image, migrate, provision the ingest role, then start the services:

```bash
docker compose pull
docker compose run --rm strumline-cli strumline migrate
docker compose run --rm strumline-cli python -m strumline.db.bootstrap
docker compose up -d
```

Bootstrap needs permission to create roles and grant access to the migrated
tables. If the app role lacks it, have your DBA run that one job with suitable
credentials (override `DB_USER`/`DB_PASSWORD` for the job only). Re-running bootstrap
keeps an existing role password unchanged.

This example binds HTTP ports to localhost. For remote exporters, put ingest
behind your TLS reverse proxy and route `/v1/logs` to port **8001**. Keep the admin
API (8000) and unauthenticated `/metrics` endpoints private. See
[Production deployment](production.md), [Configuration](configuration.md),
and [Security](security.md) for operational details.

## 2. Create a project, app, and token

Run on the deployment host (token extraction uses `jq`):

```bash
docker compose run --rm strumline-cli strumline project create demo --name "Demo"
APP_JSON=$(docker compose run --rm -T strumline-cli strumline app create demo web --name "Web")
export STRUMLINE_TOKEN=$(printf '%s' "$APP_JSON" | jq -r '.token_key')
unset APP_JSON
```

Both creation commands print JSON; `app create` includes its first ingestion
token under `token_key`. Save it in your application's secret store. It is shown
only once; if lost, create a replacement with `strumline token create <app-id>`.
The token alone determines project/app routing, regardless of resource attributes.

## 3. Send a log

Send standard OTLP logs to `POST /v1/logs` with your `x-strumline-token` header.
You can use any HTTP client directly; an SDK, exporter, or Collector is optional.
Strumline accepts OTLP JSON (`application/json`) and Protobuf
(`application/x-protobuf`), with optional `Content-Encoding: gzip`.
The request body must follow the OTLP logs format, as in this example.

**Direct HTTP:** send your first event from the deployment host:

```bash
curl --fail-with-body http://localhost:8001/v1/logs \
  -H "x-strumline-token: ${STRUMLINE_TOKEN}" \
  -H 'Content-Type: application/json' \
  --data '{"resourceLogs":[{"scopeLogs":[{"logRecords":[
    {"severityNumber":9,"body":{"stringValue":"strumline-first-log"}}
  ]}]}]}'
```

Full success returns `200` with `{}`: **in-memory admission, not durable delivery**.
Partial success reports rejected records. Queue saturation returns retryable `503`;
retry with backoff. Delivery to Loki is best-effort.

**Optional SDK/exporter:** if you already use OpenTelemetry or want its logging
integration, configure any compatible OTLP/HTTP logs SDK/exporter in your
application's environment:

```bash
export OTEL_EXPORTER_OTLP_LOGS_ENDPOINT=http://localhost:8001/v1/logs
export OTEL_EXPORTER_OTLP_LOGS_HEADERS="x-strumline-token=${STRUMLINE_TOKEN}"
export OTEL_EXPORTER_OTLP_LOGS_PROTOCOL=http/protobuf   # or http/json
export OTEL_EXPORTER_OTLP_LOGS_COMPRESSION=gzip
export OTEL_BLRP_MAX_EXPORT_BATCH_SIZE=128
```

These variables configure an installed exporter; enable your SDK's logs pipeline
and emit a log through its logging bridge. SDK support for environment variables
varies; equivalent explicit options also work. For a remote application, replace
the local URL in either approach with your HTTPS ingest URL. See the
[OTLP contract and exporter setup](api/otlp-logs.md) for payload details,
batch limits, and Collector configuration.

## 4. Verify delivery in Loki/Grafana

In your existing Grafana's Explore view, select the Loki data source and query:

```logql
{project="demo",app="web"} |= "strumline-first-log"
```

Or query your Loki directly (replace the URL; use your normal gateway auth and
`X-Scope-OrgID` header if applicable):

```bash
curl --get http://loki.internal.example:3100/loki/api/v1/query_range \
  --data-urlencode 'query={project="demo",app="web"} |= "strumline-first-log"' \
  --data-urlencode 'limit=10'
```

Allow a few seconds for batching. The result must contain `strumline-first-log`;
process health and an ingest `200` alone do not prove delivery.

For optional monitoring, inspect or copy the repository's examples into your
existing Prometheus/Grafana setup:

- [Prometheus scrape configuration](../docker/observability/prometheus.yml) — scrape each Strumline process's `/metrics` endpoint.
- [Grafana data sources](../docker/observability/grafana/provisioning/datasources/datasources.yaml) — Loki for logs and Prometheus for metrics.
- [Grafana dashboard JSON](../docker/observability/grafana/provisioning/dashboards/strumline.json) — import the Strumline metrics dashboard, or use the [dashboard provisioning configuration](../docker/observability/grafana/provisioning/dashboards/dashboards.yaml).

These examples use local Compose hostnames and paths; adapt them to your service
addresses and Grafana provisioning layout. Set or remove the example Loki tenant
header to match your Loki setup. Keep the dashboard's data source UIDs aligned
with your Grafana data sources. Prometheus needs private network access
to ports 8000, 8001, and 8002; the deployment above keeps them private and does not
publish processor port 8002. See [Observability](observability.md) for details.

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
| Migrations out of date | Schema not applied | Run `docker compose run --rm strumline-cli strumline migrate`. |

See [Security](security.md), [Observability](observability.md), and
[Production deployment and recovery](production.md) for deeper diagnostics.

