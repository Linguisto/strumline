# Configuration reference

All configuration is via environment variables or a `.env` file (loaded automatically, not committed).
Copy `.env.example` to `.env` and override as needed.

All settings are read at process startup. Changes require a process restart.

## Common (all processes)

| Variable          | Default  | Secret | Description                                                                                                     |
|-------------------|----------|--------|-----------------------------------------------------------------------------------------------------------------|
| `LOG_LEVEL`       | `INFO`   | no     | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` \| `CRITICAL`                                                         |
| `METRICS_ENABLED` | `true`   | no     | Expose `/metrics` endpoint when `true`                                                                          |
| `APP_TIMEZONE`    | `` (UTC) | no     | Optional IANA display timezone (e.g. `Europe/Berlin`). Presentation only — all storage and transmission is UTC. |

## API process (`telemetria-api`)

| Variable   | Default   | Secret | Description           |
|------------|-----------|--------|-----------------------|
| `API_HOST` | `0.0.0.0` | no     | Bind address          |
| `API_PORT` | `8000`    | no     | Listen port (1–65535) |

## Ingest process (`telemetria-ingest`)

| Variable            | Default                        | Secret | Description                                                         |
|---------------------|--------------------------------|--------|---------------------------------------------------------------------|
| `INGEST_HOST`       | `0.0.0.0`                      | no     | Bind address                                                        |
| `INGEST_PORT`       | `8001`                         | no     | Listen port (1–65535)                                               |
| `IPC_SOCKET_PATH`   | `/var/run/telemetria/ipc.sock` | no     | Unix-domain socket path shared with the processor                   |
| `MAX_PAYLOAD_BYTES` | `1048576` (1 MiB)              | no     | Raw request body limit — enforced before JSON parsing               |
| `MAX_BATCH_EVENTS`  | `300`                          | no     | Maximum events per batch request                                    |
| `QUEUE_SIZE`        | `10000`                        | no     | In-process event queue capacity — `QueueFull` drops events silently |

## Processor process (`telemetria-processor`)

| Variable                  | Default                        | Secret | Description                                          |
|---------------------------|--------------------------------|--------|------------------------------------------------------|
| `PROCESSOR_HOST`          | `0.0.0.0`                      | no     | Bind address                                         |
| `PROCESSOR_PORT`          | `8002`                         | no     | Listen port (1–65535)                                |
| `IPC_SOCKET_PATH`         | `/var/run/telemetria/ipc.sock` | no     | Unix-domain socket path shared with ingest           |
| `SINK_PROVIDER`           | `null`                         | no     | `null` \| `loki` — selects the event sink            |
| `BATCH_MAX_SIZE`          | `500`                          | no     | Flush batch when this many events accumulate         |
| `BATCH_MAX_WAIT_SECONDS`  | `1.0`                          | no     | Flush batch after this many seconds even if not full |
| `SINK_MAX_RETRIES`        | `3`                            | no     | Maximum retry attempts for transient sink errors     |
| `SINK_RETRY_BASE_SECONDS` | `0.25`                         | no     | Exponential backoff base delay (seconds)             |
| `SINK_RETRY_MAX_SECONDS`  | `10.0`                         | no     | Exponential backoff cap (seconds)                    |

## Database

Two roles connect to the same PostgreSQL database. Connection URLs are assembled from parts at runtime.

| Variable             | Default             | Secret  | Used by              | Description                                                      |
|----------------------|---------------------|---------|----------------------|------------------------------------------------------------------|
| `DB_HOST`            | `postgres`          | no      | api, cli, migrations | PostgreSQL host                                                  |
| `DB_PORT`            | `5432`              | no      | api, cli, migrations | PostgreSQL port                                                  |
| `DB_NAME`            | `telemetria`        | no      | api, cli, migrations | Database name                                                    |
| `DB_USER`            | `telemetria`        | no      | api, cli, migrations | App role (read-write)                                            |
| `DB_PASSWORD`        | `telemetria`        | **yes** | api, cli, migrations | App role password — change before deploying                      |
| `INGEST_DB_USER`     | `telemetria_ingest` | no      | ingest               | Read-only role for DSN resolver                                  |
| `INGEST_DB_PASSWORD` | ``                  | **yes** | ingest               | Read-only role password — set after running the bootstrap script |

The ingest process falls back to the app role (`DB_*`) if `INGEST_DB_PASSWORD` is empty. Run the bootstrap script to
provision the read-only role:

```bash
docker compose run --rm telemetria-cli python -m telemetria.db.bootstrap
```
