# Telemetria

Non-blocking, lightning-fast structured telemetry collector.

See [`docs/architecture/decisions.md`](docs/architecture/decisions.md) for accepted invariants and topology.

## Quickstart

### Development (hot reload)

```bash
make init.dev       # copy compose.yaml + .env + dev override
make build.dev      # build dev image (includes pytest, ruff, mypy)
make install        # start the stack + run migrations
```

Services:
- API → http://localhost:8000/health
- Ingest → http://localhost:8001/health
- Processor → http://localhost:8002/health (localhost only)

Code changes in `telemetria/` reload automatically inside the containers.

### Production

```bash
make init           # copy compose.yaml + .env
make build          # build production image (runtime only, no dev deps)
make install        # start the stack + run migrations
```

### Common commands

```bash
make down           # stop the stack
make migrate        # run database migrations
make lint           # ruff + mypy + import-linter
make test           # pytest
```

`lint` and `test` run inside the container via `docker compose run --rm telemetria-cli`.
Override the target with `DC_EXEC`:

```bash
make test DC_EXEC="uv run"   # run locally instead
```

## Requirements

- Docker with Compose v2
- `make`

No local Python installation required for running the stack.
A local Python 3.14+ environment with `uv` is needed only for IDE tooling or `DC_EXEC=uv run` workflows.
