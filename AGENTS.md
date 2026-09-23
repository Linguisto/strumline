# AGENTS.md

Operating guide for AI coding agents working in this repository.
Read this file fully before touching any code.

## Before writing any code

Stop at the first rung that holds:

1. Does this need to exist at all? (YAGNI)
2. Does it already exist in this codebase? Reuse the pattern that's here.
3. Does the standard library do this? Use it.
4. Does an already-installed package solve it? Use it.
5. Only then: write the minimum code that works.

Read the task, trace the real call path end to end, then decide. A small diff in the wrong place is a second bug, not a fix.

Bug fix = root cause, not symptom. Grep every caller of the function you touch. Fix the shared function once.

Do not invent response schemas, error names, configuration keys, or defaults. Check the relevant doc first.

## Environment

- Python 3.14, `uv` with a locked `uv.lock`. Never `pip install` loose packages.
- Run via `make` — targets execute inside the dev container by default. Override: `DC_EXEC="uv run"`.
- Docker + Compose v2 required for integration tests. Unit tests run without Docker.

## Quality gates — all must pass before finishing any task

1. `ruff check strumline/ tests/` — zero errors
2. `ruff format --check strumline/ tests/` — zero diff
3. `mypy strumline/` — zero errors (strict mode)
4. `lint-imports` — all import boundary contracts pass
5. `pytest` — all tests pass

Run `make lint` and `make test.unit` (or `make test` with Docker) to verify. Do not present a result as complete until both pass.

## Hard constraints

**Import boundaries** — enforced by `lint-imports`. Never cross these:

```
domain/     → nothing in strumline (pure)
ipc/        → domain/ only
ingest/     → domain/, ipc/, metrics/, db/ (read-only auth token resolver only)
processor/  → domain/, ipc/, metrics/, sinks/ (contract + factory, not loki directly)
control/    → db/, domain/
cli/        → control/, domain/
api/        → control/, domain/
```

**UTC everywhere** — every timestamp stored, transmitted, or logged must be timezone-aware UTC. PostgreSQL columns use `TIMESTAMPTZ`. JSON serializes timestamps with a trailing `Z`. Missing/naive/malformed client timestamps fall back to server `received_at`. `App.timezone` is IANA for display only — never a storage timezone.

**Ingest is read-only** — the ingest process uses a separate read-only DB role (`INGEST_DB_USER`). Never give it a write-capable session.

**No new dependencies** without a clear reason. Prefer stdlib and already-installed packages.

**No direct pushes to `main`.** Feature work goes on a branch. CI runs on push to `main`.

## Domain errors

All domain errors inherit `StrumlineError` and carry `exit_code` (CLI) and `http_status` (REST):

| Error | exit_code | http_status |
|---|---|---|
| `NotFoundError(resource, identifier)` | 4 | 404 |
| `ConflictError(resource, field, value)` | 9 | 409 |
| `OwnershipError(resource, id, parent)` | 4 | 404 |
| `ValidationError(field, message)` | 2 | 422 |
| `AlreadyRevokedError(token_id)` | 9 | 409 |

CLI handlers catch `StrumlineError`, print the message, and `raise SystemExit(error.exit_code)`.
HTTP handlers catch `StrumlineError` and raise `HTTPException(status_code=error.http_status, detail=str(error))`.

## Adding a new entity — checklist

1. Domain entity in `strumline/domain/entities.py` (frozen dataclass, `_assert_utc` on timestamps)
2. Domain errors in `strumline/domain/errors.py` if new error cases arise
3. ORM model in `strumline/db/models.py` (use `TimestampMixin` for audit timestamps)
4. Alembic migration in `alembic/versions/`
5. Repository in `strumline/db/repositories.py`
6. Service in `strumline/control/<entity>s.py`
7. CLI commands in `strumline/cli/<entity>s.py`, registered in `strumline/cli/main.py`
8. Tests: unit for domain logic, integration for repository/service

## Commit format

Conventional commits. Subject line under 72 characters, imperative mood. Breaking changes go in the commit body as `BREAKING CHANGE:`. Types `docs`, `test`, `style`, `build`, `ci`, and `chore` are skipped by the changelog generator.
