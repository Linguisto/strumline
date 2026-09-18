# Telemetria

Non-blocking, lightning-fast structured telemetry collector.

## Quickstart

```bash
make install        # init.dev + build dev image + start stack + run migrations
```

Services after startup:
- API → http://localhost:8000/health
- Ingest → http://localhost:8001/health
- Processor → http://localhost:8002/health

Code changes in `telemetria/` reload automatically inside the containers.

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

One image, three containers — `telemetria-api`, `telemetria-ingest`, `telemetria-processor` — built from a multi-stage `docker/Dockerfile`:

- `builder` — installs dependencies at `/app` with `uv`
- `runtime` — minimal non-root image (`telemetria` uid 10001), no dev tools
- `dev` — extends runtime with pytest, ruff, mypy, and hot-reload

Ingest and processor share a Unix-domain socket via a named volume (`/var/run/telemetria/`). PostgreSQL stores control-plane metadata only — raw telemetry never touches the database.

Compose files:
- `docker/compose.example.yaml` → copy to `compose.yaml` (base stack)
- `docker/compose.dev.yaml` → copy to `docker-compose.override.yaml` (hot reload + dev image)

## Requirements

- Docker with Compose v2
- `make`

A local Python 3.14+ environment with `uv` is needed only for IDE tooling or `DC_EXEC=uv run` workflows.

## Docs

- [Architecture & topology](docs/architecture/decisions.md)
- [Configuration reference](docs/configuration.md)
- [Ingest HTTP contract](docs/api/ingest-contract.md)
- [IPC protocol](docs/ipc-protocol.md)
