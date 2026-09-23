# Configuration reference

All configuration is via environment variables or a `.env` file (loaded automatically, not committed).
Copy `.env.example` to `.env` and override as needed.

All settings are read at process startup. Changes require a process restart.

## Common (all processes)

| Variable          | Default  | Secret  | Description                                                                                                     |
|-------------------|----------|---------|-----------------------------------------------------------------------------------------------------------------|
| `LOG_LEVEL`       | `INFO`   | no      | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` \| `CRITICAL`                                                         |
| `METRICS_ENABLED` | `true`   | no      | Expose `/metrics` endpoint when `true`                                                                          |
| `APP_TIMEZONE`    | `` (UTC) | no      | Optional IANA display timezone (e.g. `Europe/Berlin`). Presentation only — all storage and transmission is UTC. |
| `APP_KEY`         | ``       | **yes** | HMAC-SHA256 secret for auth token hashing. Generated automatically by `make up` if empty. Required in production. |

## API process (`strumline-api`)

| Variable            | Default   | Secret  | Description                                                  |
|--------------------|-----------|---------|--------------------------------------------------------------|
| `API_HOST`          | `0.0.0.0` | no      | Bind address                                                 |
| `API_PORT`          | `8000`    | no      | Listen port (1–65535)                                        |
| `ADMIN_API_ENABLED` | `false`   | no      | Mount admin CRUD routes at `/admin/v1` and serve Scalar docs at `/` |
| `ADMIN_API_KEY`     | ``        | **yes** | Bearer key for admin API — required when `ADMIN_API_ENABLED=true` |

When `ADMIN_API_ENABLED=true`, a non-empty `ADMIN_API_KEY` is required. Generate one:
```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

## Ingest process (`strumline-ingest`)

| Variable            | Default                        | Secret | Description                                                         |
|---------------------|--------------------------------|--------|---------------------------------------------------------------------|
| `INGEST_HOST`       | `0.0.0.0`                      | no     | Bind address                                                        |
| `INGEST_PORT`       | `8001`                         | no     | Listen port (1–65535)                                               |
| `IPC_SOCKET_PATH`   | `/var/run/strumline/ipc.sock` | no     | Unix-domain socket path shared with the processor                   |
| `API_DOCS_ENABLED`  | `false`                        | no     | Serve Scalar API docs at `/` (ingest contract — `POST /v1/logs`)  |
| `MAX_PAYLOAD_BYTES` | `1048576` (1 MiB)              | no     | Raw request limit; OTLP also limits decompressed and normalized bytes |
| `MAX_BATCH_EVENTS`  | `300`                          | no     | Maximum events per batch request                                    |
| `QUEUE_SIZE`        | `10000`                        | no     | In-process event queue capacity (must be ≥ 1); insufficient space returns retryable `503` without admitting any records |

OTLP logs use the same ingest port and token resolver. `/v1/logs` returns retryable
`503` without admitting records when a batch cannot fit the remaining queue space.
See the
[OTLP contract](api/otlp-logs.md) for batch sizing, encodings, and exporter setup.

## Processor process (`strumline-processor`)

| Variable          | Default                        | Secret | Description                                |
|-------------------|--------------------------------|---------|--------------------------------------------|
| `PROCESSOR_HOST`  | `0.0.0.0`                      | no      | Bind address                               |
| `PROCESSOR_PORT`  | `8002`                         | no      | Listen port (1–65535)                      |
| `IPC_SOCKET_PATH` | `/var/run/strumline/ipc.sock` | no      | Unix-domain socket path shared with ingest |
| `PROCESSOR_QUEUE_SIZE` | `10000`                  | no      | Bounded queue between the UDS reader and batch processor (must be ≥ 1) |
| `SINK_PROVIDER`   | `null`                         | no      | `loki` \| `null` — selects the event sink. The development `.env.example` selects `loki`. |

## Loki sink (`SINK_PROVIDER=loki`)

| Variable               | Default            | Secret | Description                                                    |
|------------------------|--------------------|--------|----------------------------------------------------------------|
| `LOKI_URL`             | `http://loki:3100` | no     | Loki push API base URL                                         |
| `LOKI_TIMEOUT_SECONDS` | `5.0`              | no     | HTTP request timeout; exceeded → retryable error               |
| `LOKI_COMPRESSION`     | `gzip`             | no     | `gzip` compresses the push body; empty string sends plain JSON |

See [`docs/sinks.md`](sinks.md) for the full sink contract, failure taxonomy, and how to add a new provider.

## Grafana (bundled observability stack)

| Variable            | Default    | Secret  | Description                     |
|---------------------|------------|---------|---------------------------------|
| `GRAFANA_USER`      | `john.doe` | no      | Grafana admin username           |
| `GRAFANA_PASSWORD`  | `changeme` | **yes** | Grafana admin password — change before exposing externally |

## Advanced configuration and fine-tuning

These variables are commented out in `.env.example`. Set them only when you need to override the defaults.

### Loki multi-tenancy

| Variable         | Default | Secret | Description                                                              |
|------------------|---------|--------|--------------------------------------------------------------------------|
| `LOKI_TENANT_ID` | `` (none) | no   | Sets `X-Scope-OrgID` on every push request. Leave empty for single-tenant Loki. |

### Processor batch tuning

| Variable                 | Default | Secret | Description                                          |
|--------------------------|---------|--------|------------------------------------------------------|
| `BATCH_MAX_SIZE`         | `500`   | no     | Flush when this many events accumulate               |
| `BATCH_MAX_WAIT_SECONDS` | `1.0`   | no     | Flush after this many seconds even if batch not full |

### Sink retry policy

| Variable                  | Default | Secret | Description                              |
|---------------------------|---------|--------|------------------------------------------|
| `SINK_MAX_RETRIES`        | `3`     | no     | Maximum retry attempts for transient errors |
| `SINK_RETRY_BASE_SECONDS` | `0.25`  | no     | Exponential backoff base delay (seconds) |
| `SINK_RETRY_MAX_SECONDS`  | `10.0`  | no     | Exponential backoff cap (seconds)        |

## Database

Two roles connect to the same PostgreSQL database. Connection URLs are assembled from parts at runtime.

| Variable             | Default             | Secret  | Used by              | Description                                                      |
|----------------------|---------------------|---------|----------------------|------------------------------------------------------------------|
| `DB_HOST`            | `postgres`          | no      | api, cli, migrations | PostgreSQL host                                                  |
| `DB_PORT`            | `5432`              | no      | api, cli, migrations | PostgreSQL port                                                  |
| `DB_NAME`            | `strumline`        | no      | api, cli, migrations | Database name                                                    |
| `DB_USER`            | `strumline`        | no      | api, cli, migrations | App role (read-write)                                            |
| `DB_PASSWORD`        | `strumline`        | **yes** | api, cli, migrations | App role password — change before deploying                      |
| `INGEST_DB_USER`     | `strumline_ingest` | no      | ingest               | Read-only role for auth token resolver                                  |
| `INGEST_DB_PASSWORD` | ``                  | **yes** | ingest               | Read-only role password — set after running the bootstrap script |

The ingest process falls back to the app role (`DB_*`) if `INGEST_DB_PASSWORD` is empty. Run the bootstrap script to
provision the read-only role:

```bash
docker compose run --rm strumline-cli python -m strumline.db.bootstrap
```
