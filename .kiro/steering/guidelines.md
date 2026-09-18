---
title: Project-specific guidelines
inclusion: always
---

# Project-specific guidelines

Structural patterns that are specific to this codebase. Read `conventions.md` for style rules; read this for how the layers fit together.

## Two-model split: ORM models vs. domain entities

The database layer and the domain layer use **separate types for the same data**.

- `telemetria/db/models.py` — SQLAlchemy `Mapped` classes (`ProjectModel`, `AppModel`, `DSNModel`). These are ORM-only. Nothing outside `telemetria.db` imports them.
- `telemetria/domain/entities.py` — frozen dataclasses (`Project`, `App`, `DSN`). These are the canonical representation everywhere else. No SQLAlchemy dependency, no I/O.

Repositories are the only place that converts between them via `_<entity>_from_model()` private helpers. Never expose an ORM model beyond `telemetria.db`. Never import SQLAlchemy in `domain/`, `control/`, `cli/`, `api/`, `ingest/`, `processor/`, or `ipc/`.

`TimestampMixin` adds `created_at`/`updated_at` as `DateTime(timezone=True)` to ORM models that need them. asyncpg returns these as timezone-aware but the `_ensure_utc()` helper in repositories normalizes any naive datetimes defensively before constructing domain entities.

## Repository layer (`telemetria/db/repositories.py`)

Repositories are thin adapters: SQLAlchemy queries + ORM-to-domain mapping. They:

- Accept an `AsyncSession` in `__init__` — they don't own session lifecycle
- Use `await session.flush()` (not `commit()`) — the surrounding service/transaction commits
- Raise domain errors (`NotFoundError`, `ConflictError`, `AlreadyRevokedError`) — never HTTP errors
- Map `IntegrityError` → `ConflictError` at the repository boundary

The `UNSET` sentinel (`class _Unset`) distinguishes "caller did not pass this field" from `None` (which is a meaningful value, e.g. clearing `App.timezone`). Use it for optional-update parameters that have a meaningful `None` state.

## Service layer (`telemetria/control/`)

Services own the transaction and business logic. Pattern:

```python
class ProjectService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = ProjectRepository(session)

    async def create(self, slug: str, name: str) -> Project:
        now = datetime.now(tz=UTC)
        project = Project(id=uuid.uuid4(), slug=slug, name=name, created_at=now, updated_at=now)
        return await self._repo.create(project)
```

Services construct domain entities with fresh UUIDs and UTC timestamps, then delegate persistence to repositories. They never import FastAPI, Typer, or `sys`. They never call `session.commit()` — the session context manager in the caller commits.

## Domain error taxonomy

All domain errors inherit from `TelemetriaError` and carry `exit_code` (for CLI) and `http_status` (for REST):

| Error | exit_code | http_status | When |
|---|---|---|---|
| `NotFoundError(resource, identifier)` | 4 | 404 | Row missing |
| `ConflictError(resource, field, value)` | 9 | 409 | Unique constraint violation |
| `OwnershipError(resource, id, parent)` | 4 | 404 | Wrong parent (leaks as 404) |
| `ValidationError(field, message)` | 2 | 422 | Domain rule violation |
| `AlreadyRevokedError(dsn_id)` | 9 | 409 | Revoking an already-revoked DSN |

CLI handlers catch `TelemetriaError`, print `error.args[0]`, and `raise SystemExit(error.exit_code)`.  
HTTP handlers catch `TelemetriaError` and raise `HTTPException(status_code=error.http_status, detail=str(error))`.  
Never let domain errors propagate unhandled to the framework.

## Session factory and DB access

`telemetria.db.session.make_session_factory(url)` returns an `async_sessionmaker`. Use it as an async context manager:

```python
async with session_factory() as session:
    async with session.begin():
        service = ProjectService(session)
        return await service.create(slug, name)
```

The ingest process uses a read-only session via `INGEST_DB_USER` credentials. Never give the ingest process a write-capable session.

## CLI structure (`telemetria/cli/`)

One Typer sub-app per resource (`projects.py`, `apps.py`, `dsns.py`). Each command:

1. Calls `make_session_factory` with settings from `DatabaseSettings()`
2. Runs the service method inside `async with session.begin()`
3. Catches `TelemetriaError` and exits with `error.exit_code`
4. Prints output with `typer.echo` or `rich` — no `print()`

`telemetria/cli/helpers.py` holds shared formatting helpers. Keep them small.

## Adding a new entity

Checklist:
1. Domain entity in `telemetria/domain/entities.py` (frozen dataclass, `_assert_utc` on timestamps)
2. Domain errors in `telemetria/domain/errors.py` if new error cases arise
3. ORM model in `telemetria/db/models.py` (use `TimestampMixin` if it has audit timestamps)
4. Alembic migration in `alembic/versions/`
5. Repository in `telemetria/db/repositories.py` (`_<entity>_from_model` mapper + CRUD methods)
6. Service in `telemetria/control/<entity>s.py`
7. CLI commands in `telemetria/cli/<entity>s.py`, registered in `telemetria/cli/main.py`
8. Tests: unit tests for domain logic, integration tests for repository and service
