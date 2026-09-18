# Configuration reference

All configuration is via environment variables (or `.env` file, optional).
Defaults are shown. No variable is required to start the base stack.
Copy `.env.example` to `.env` and override as needed; `.env` is not committed.

Restart behavior: all settings are read at process startup. Changes require a process restart.

## Common (all processes)

| Variable | Type | Default | Secret | Description |
|---|---|---|---|---|
| `LOG_LEVEL` | enum | `INFO` | no | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` \| `CRITICAL` |
| `METRICS_ENABLED` | bool | `true` | no | Expose `/metrics` endpoint when `true` (implemented in M4-A) |
| `APP_TIMEZONE` | string | `` (UTC) | no | Optional IANA display timezone (e.g. `Europe/Berlin`). Presentation only; all storage is UTC. Empty or unset means UTC. |

## API process (`telemetria-api`)

| Variable | Type | Default | Secret | Description |
|---|---|---|---|---|
| `API_HOST` | string | `0.0.0.0` | no | Bind address |
| `API_PORT` | int | `8000` | no | Listen port (1–65535) |

## Ingest process (`telemetria-ingest`)

| Variable | Type | Default | Secret | Description |
|---|---|---|---|---|
| `INGEST_HOST` | string | `0.0.0.0` | no | Bind address |
| `INGEST_PORT` | int | `8001` | no | Listen port (1–65535) |
| `IPC_SOCKET_PATH` | string | `/var/run/telemetria/ipc.sock` | no | Path to the Unix-domain socket shared with the processor |

## Processor process (`telemetria-processor`)

| Variable | Type | Default | Secret | Description |
|---|---|---|---|---|
| `PROCESSOR_HOST` | string | `0.0.0.0` | no | Bind address |
| `PROCESSOR_PORT` | int | `8002` | no | Listen port (1–65535) |
| `IPC_SOCKET_PATH` | string | `/var/run/telemetria/ipc.sock` | no | Path to the Unix-domain socket shared with ingest |

## PostgreSQL

| Variable | Type | Default | Secret | Description |
|---|---|---|---|---|
| `POSTGRES_DB` | string | `telemetria` | no | Database name |
| `POSTGRES_USER` | string | `telemetria` | no | Superuser name (for PostgreSQL container) |
| `POSTGRES_PASSWORD` | string | `telemetria` | **yes** | Superuser password — change before deploying |

## Compose image tag

| Variable | Type | Default | Description |
|---|---|---|---|
| `TELEMETRIA_IMAGE_TAG` | string | `dev` | Docker image tag used by all Compose services |

## Variables added in later milestones

| Variable | Milestone | Description |
|---|---|---|
| `SINK_PROVIDER` | M2b-B | `null` \| `loki` — selects the event sink |
| `LOKI_URL` | M3-A | Base URL of the Loki push endpoint |
| `DATABASE_URL` | M1-A | `postgresql+asyncpg://telemetria:telemetria@postgres:5432/telemetria` | Async SQLAlchemy URL for control plane |

## Test database

Pytest uses a dedicated `test_db` database on the same server as the app.
Credentials default to the `DB_*` vars; override with `TESTING_DB_*` if needed:

| Variable | Default | Description |
|---|---|---|
| `TESTING_DB_HOST` | `$DB_HOST` | Test DB host |
| `TESTING_DB_PORT` | `$DB_PORT` | Test DB port |
| `TESTING_DB_NAME` | `test_db` | Test DB name (never the same as `DB_NAME`) |
| `TESTING_DB_USER` | `$DB_USER` | Test DB user |
| `TESTING_DB_PASSWORD` | `$DB_PASSWORD` | Test DB password |
