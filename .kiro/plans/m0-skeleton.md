# M0 — Skeleton

**Type:** Foundation  
**Depends on:** —  
**Unlocks:** M1  
**Goal:** A valid installable package, one image, three runnable containers, CI, and health endpoints.

## Deliverables

### Package and repository

```text
telemetria/
├── __init__.py
├── config.py
├── api/{__init__.py,server.py}
├── cli/{__init__.py,main.py}
├── domain/__init__.py
├── ingest/{__init__.py,server.py}
├── ipc/{__init__.py,protocol.py,envelope.py}
├── metrics/__init__.py
└── processor/{__init__.py,server.py}
tests/test_health.py
.dockerignore
.gitignore
Dockerfile
compose.yaml
Makefile
pyproject.toml
uv.lock
.env.example
```

All directories are real Python packages. The CLI entry point has a minimal `--help`/`--version` implementation so installation cannot reference a missing module.

```toml
[project.scripts]
telemetria = "telemetria.cli.main:app"
telemetria-api = "telemetria.api.server:main"
telemetria-ingest = "telemetria.ingest.server:main"
telemetria-processor = "telemetria.processor.server:main"
```

Dependencies use valid PEP 621 syntax under `[project]`, for example `dependencies = [...]`; there is no `[project.dependencies]` table. Commit `uv.lock` and install from the lock in CI and Docker.

Declare an explicit `[build-system]` and package discovery matching the flat package layout. Validate a built wheel in a clean environment, including all four console scripts and package metadata; editable imports alone are insufficient evidence of an installable package.

### Health and configuration

Each process exposes `/health`; version comes from installed package metadata rather than a hard-coded string. Processor health binds to `PROCESSOR_HOST`/`PROCESSOR_PORT` and is published to `127.0.0.1:8002` in the development Compose file.

```text
API_HOST=0.0.0.0
API_PORT=8000
INGEST_HOST=0.0.0.0
INGEST_PORT=8001
PROCESSOR_HOST=0.0.0.0
PROCESSOR_PORT=8002
IPC_SOCKET_PATH=/var/run/telemetria/ipc.sock
APP_TIMEZONE=                 # optional IANA display timezone; unset means UTC
METRICS_ENABLED=true
LOG_LEVEL=INFO
LOG_FORMAT=json
```

`APP_TIMEZONE` affects presentation only. The UTC storage invariant is established now and referenced by all later milestones.

### Image and Compose topology

- A multi-stage Dockerfile creates a non-root runtime image.
- Compose builds once with an explicit image tag such as `telemetria:${TELEMETRIA_IMAGE_TAG:-dev}`; all three services reference it and use different commands.
- The v1 topology is one host and three Telemetria containers.
- Ingest and processor mount the same named socket-directory volume.
- Image creation or an init service gives the non-root UID/GID ownership of that directory before either process starts.
- `.env` is optional, for example `env_file: { path: .env, required: false }`; `.env.example` remains the committed template.
- API, ingest, and processor define container health checks. PostgreSQL uses its own readiness health check and dependent services wait for it where needed.
- Base Compose starts no Loki, Prometheus, or Grafana services.

### Developer and CI workflow

The Makefile provides `dev-api`, `dev-ingest`, `dev-processor`, `test`, `lint`, `compose-up`, and `compose-down`. GitHub Actions runs Ruff, mypy, import-linter, and tests on pushes and pull requests. Import rules start here and expand as packages are added.

## Acceptance criteria

- [ ] `uv sync --locked` installs the package and every console script resolves.
- [ ] `docker compose config` works with no local `.env` file.
- [ ] `docker compose up` builds one tagged image and starts the three process containers plus PostgreSQL.
- [ ] `GET` requests to `:8000/health`, `:8001/health`, and `127.0.0.1:8002/health` return process name and package version.
- [ ] All service health checks become healthy.
- [ ] Ingest and processor can access the non-root shared socket directory.
- [ ] `make lint`, `make test`, and CI pass.

## Scope boundary

No database business logic, IPC framing, event ingestion, sink behavior, or Prometheus/Grafana services are implemented in M0. Stub modules define the intended package boundaries only.
