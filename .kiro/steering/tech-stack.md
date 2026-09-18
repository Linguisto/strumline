---
title: Tech stack and tooling
inclusion: always
---

# Tech stack

## Language and runtime

- Python 3.14 (minimum). Use modern syntax: `|` union types, `match`, PEP 695 type aliases where appropriate.
- `from __future__ import annotations` at the top of every module.
- All async I/O. Synchronous blocking calls are banned in async contexts.

## Core dependencies

| Package | Role |
|---|---|
| `fastapi` + `uvicorn[standard]` | HTTP server for api, ingest, processor health |
| `pydantic` v2 | Request validation, settings |
| `pydantic-settings` | `BaseSettings` with `.env` file support |
| `sqlalchemy[asyncio]` + `asyncpg` | Async ORM / PostgreSQL |
| `alembic` | Database migrations |
| `python-json-logger` | Structured JSON logging |
| `typer` | CLI |

## Dev dependencies

| Package | Role |
|---|---|
| `pytest` + `pytest-asyncio` | Test suite (`asyncio_mode = "auto"`) |
| `httpx2` | Async HTTP test client |
| `ruff` | Linting + formatting (`line-length = 100`) |
| `mypy` (strict) | Type checking |
| `import-linter` | Boundary enforcement |
| `psycopg2-binary` | Sync DB access in test fixtures |

## Package manager

`uv` with a locked `uv.lock`. Always `uv sync --locked`. Never `pip install` loose packages. Build backend is `hatchling`.

## Build system

Multi-stage Dockerfile (`docker/Dockerfile`):
- `builder` — installs deps at `/app` so shebang paths survive copy
- `runtime` — minimal non-root (`telemetria` uid 10001) production image
- `dev` — extends runtime with dev deps, test sources, hot-reload

Compose files:
- `docker/compose.example.yaml` → copied to `compose.yaml` (not committed)
- `docker/compose.dev.yaml` → copied to `docker-compose.override.yaml` (not committed)

`TELEMETRIA_IMAGE_TAG` env var selects which image tag compose uses. `TELEMETRIA_TARGET` selects the Dockerfile build stage.

## Configuration

All settings via environment variables or `.env` (never hard-coded). Classes:

- `CommonSettings` — log level, metrics flag, display timezone
- `DatabaseSettings` — two DB roles: app (read-write) and ingest (read-only DSN resolver)
- `APISettings`, `IngestSettings`, `ProcessorSettings`

Each process imports only its own settings group. Invalid or missing required vars raise `ValidationError` at import time.

## Test markers

- `unit` — fast, no DB
- `integration` — requires running PostgreSQL

Run targets: `make test`, `make test.unit`, `make test.integration`.  
Override executor: `make test DC_EXEC="uv run"`.

## Code style

- `ruff` select: `E, F, I, UP, B, SIM`
- `mypy` strict, `ignore_missing_imports = true`
- Line length 100
- Docstrings on public modules, classes, and functions
- No `# type: ignore` unless absolutely unavoidable; document why if used
