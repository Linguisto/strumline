# Contributing to Strumline

Thanks for contributing. This guide covers the workflow, quality gates, and
conventions specific to this repository. It is the human companion to
[`AGENTS.md`](AGENTS.md) — read that too; both describe the same rules.

## Prerequisites

- **Docker** with Compose v2 and **`make`** — the primary workflow runs inside
  the dev container.
- **Python 3.14+** with [`uv`](https://docs.astral.sh/uv/) — needed only for IDE
  tooling or to run the gates locally with `DC_EXEC="uv run"`.

Dependencies are locked in `uv.lock`. Never `pip install` loose packages; use
`uv sync --locked`. New dependencies need a clear justification — prefer the
standard library and already-installed packages first.

## Getting started

```bash
make up          # create .env, build dev image, start the stack, run migrations
make down        # stop the stack (keeps volumes)
make bash        # shell in a disposable CLI container
```

After `make up` the services are:

- API → http://localhost:8000/health
- Ingest → http://localhost:8001/health
- Processor → http://localhost:8002/health

Code under `strumline/` hot-reloads inside the containers.

## Branch and PR workflow

- **Never push directly to `main`.** Feature work goes on a branch; CI runs on
  push to `main`.
- Branch from `main` and keep the change focused — a PR should do one thing.
- Open a pull request. The `lint.yml` workflow runs ruff, format check, mypy,
  import-linter, and unit tests on every branch and PR. Integration tests run
  on `main` only (they need PostgreSQL).
- Keep PR titles under ~70 characters; put detail (what changed, what was
  tested, anything deferred) in the description.

## Quality gates — all must pass before a PR is ready

Run everything with one command:

```bash
make lint        # ruff check + ruff format --check + mypy (strict) + import-linter
make test.unit   # unit tests, no Docker/DB required
make test        # full suite including integration (needs PostgreSQL)
```

Run the gates locally without the container by overriding the executor:

```bash
make lint DC_EXEC="uv run"
make test DC_EXEC="uv run"
```

The five gates, each of which must be clean:

1. `ruff check strumline/ tests/` — zero errors
2. `ruff format --check strumline/ tests/` — zero diff
3. `mypy strumline/` — zero errors (strict mode)
4. `lint-imports` — all import boundary contracts pass
5. `pytest` — all tests pass

Do not mark work complete until at least `make lint` and `make test.unit` pass.

## Non-negotiable constraints

These are enforced in CI and must never be relaxed.

### Import boundaries (`lint-imports`)

```
domain/     → nothing in strumline (pure — no I/O, no frameworks)
ipc/        → domain/ only
ingest/     → domain/, ipc/, metrics/, db/ (read-only auth token resolver only)
processor/  → domain/, ipc/, metrics/, sinks/ (contract + factory, not loki directly)
control/    → db/, domain/
cli/        → control/, domain/
api/        → control/, domain/
```

Never add a cross-boundary import. If a new provider needs plumbing, put it
behind the sink registry.

### UTC everywhere

Every timestamp that is stored, transmitted, or logged must be timezone-aware
UTC. PostgreSQL columns are `TIMESTAMPTZ`; JSON serializes with a trailing `Z`
(not `+00:00`). Missing, naive, or malformed client timestamps fall back to the
server `received_at`. `App.timezone` is an IANA key for display only — never a
storage or transmission timezone.

### Ingest is read-only

The ingest process uses a separate read-only DB role (`INGEST_DB_USER`). Never
give it a write-capable session.

### Delivery semantics

An OTLP `200` acknowledges in-memory admission, not durable delivery. Process,
IPC, or exhausted-retry failures may lose accepted records, and retries may
produce duplicate event IDs. Never document or promise stronger semantics.

## Code conventions

Full details in `.kiro/steering/conventions.md` and `.kiro/steering/guidelines.md`.
Highlights:

- `from __future__ import annotations` at the top of every module; modern syntax
  (`X | Y` unions, `match`, PEP 695 aliases).
- Strict typing: every function and parameter is annotated. `Any` only at trust
  boundaries, narrowed immediately after validation. Avoid `# type: ignore`;
  document it if unavoidable.
- All I/O is async — no `time.sleep`, no blocking `requests`, no blocking file
  I/O in async paths. Bounded `asyncio.Queue` (always set `maxsize`).
- Settings via `pydantic-settings` `BaseSettings`, one class per process, read
  once in `main()`/`create_app()` and passed down.
- FastAPI apps use the `create_app()` factory and `lifespan` — no module-level
  `app = FastAPI()` (except the uvicorn entry point) and no `@app.on_event`.
- Line length 100. Docstrings on public modules, classes, and functions.
- **Two-model split:** ORM models (`db/models.py`) never leave `strumline.db`;
  domain entities (`domain/entities.py`) are the canonical type everywhere else.
  Repositories are the only place that converts between them.
- **Domain errors** subclass `StrumlineError` and carry `exit_code` (CLI) and
  `http_status` (REST). Business logic raises domain errors; route handlers
  translate them to `HTTPException`. Never raise `HTTPException` from business
  logic.

### Adding a new entity

Follow the checklist in `AGENTS.md`: domain entity → domain errors → ORM model →
Alembic migration → repository → service → CLI commands → tests (unit for domain
logic, integration for repository/service).

## Tests

- Test files mirror the module they test (`tests/test_ingest.py` →
  `strumline/ingest/`).
- Mark every test `@pytest.mark.unit` (fast, no DB) or `@pytest.mark.integration`
  (needs PostgreSQL).
- Use `httpx2` `AsyncClient` with `ASGITransport(app=create_app(...))` for route
  tests — never spin up a real server. Inject test doubles via `app.state`.
- Shared fixtures live in `tests/conftest.py`; keep them minimal.
- New features and bug fixes need tests. A bug fix should cover the root cause,
  not just the reported symptom.

## Commits

Use [Conventional Commits](https://www.conventionalcommits.org/). Subject line
under 72 characters, imperative mood. Breaking changes go in the body as
`BREAKING CHANGE:`. Commit messages feed the changelog via `git-cliff`, so write
them for a reader. The types `docs`, `test`, `style`, `build`, `ci`, and `chore`
are skipped by the changelog generator.

## Migrations

Alembic migrations live in `alembic/versions/`, named `NNNN_short_description.py`,
with both `upgrade()` and `downgrade()`. New timestamp columns use `TIMESTAMPTZ`;
UUID-shaped primary keys use the `UUID` type. Apply with `make migrate` — never
run `alembic` directly in production.

## Documentation

Update the relevant docs under `docs/` when behavior or configuration changes,
and keep the module docstring accurate — it should describe what the module
does, its entry points, and any invariants callers rely on.

## License

By contributing, you agree that your contributions are licensed under the
[MIT License](LICENSE).
