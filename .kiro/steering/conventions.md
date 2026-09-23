---
title: Coding conventions
inclusion: always
---

# Coding conventions

## Module structure

Every non-trivial module opens with a module-level docstring that covers: what it does, its entry points, and any invariants callers must know about. See `strumline/ingest/server.py` or `strumline/ipc/codec.py` for the expected style.

## Settings

Use `pydantic-settings` `BaseSettings` subclasses only. One class per process. Read the relevant settings class once in `main()` or `create_app()` and pass it down — don't call `SomeSettings()` deep in helper functions. Use `@model_validator(mode="after")` for cross-field validation; use `@field_validator` for single-field transforms.

## FastAPI apps

Use the `create_app()` factory pattern (not module-level `app = FastAPI()`). Attach shared state to `application.state` so tests can inject alternatives without monkey-patching. Use the `lifespan` context manager for startup/shutdown tasks (background tasks, connections). No `@app.on_event` decorators.

`app = create_app()` at module level is only for the uvicorn entry point; tests import and call `create_app()` directly.

## Error handling

- Raise `HTTPException` from route handlers, never from business logic.
- Business logic raises domain errors (subclasses of those in `strumline.domain.errors`).
- Sink errors are `RetryableSinkError` or `PermanentSinkError` — never bare `Exception` in sink code.
- Log at `WARNING` for recoverable drops/retries, `ERROR` for permanent failures and unexpected exceptions.

## Async

- All I/O is async. No `time.sleep`, no synchronous `requests` calls, no blocking file I/O in async paths.
- Use `asyncio.wait_for` for timeouts, not `asyncio.sleep`-based polling.
- Use `asyncio.Queue` for in-process event passing. Always set `maxsize` — unbounded queues hide backpressure bugs.
- `asyncio.create_task` for fire-and-forget; store the task reference to cancel it on shutdown.

## Logging

Configure once per process via `strumline.logging_config.configure_logging(common, process_name)`. Use structured JSON in production. Use `logging.getLogger(__name__)` at module level. Log IDs and slugs as key=value pairs in format strings, not f-strings inside the log call.

```python
log.info("Event enqueued id=%s app=%s", event.id, event.app_slug)  # good
log.info(f"Event enqueued id={event.id}")  # bad
```

## Tests

Test files mirror the module they test: `tests/test_ingest.py` tests `strumline/ingest/`. Use `pytest.mark.unit` for tests with no DB dependency; use `pytest.mark.integration` for tests that need PostgreSQL.

Use `httpx2` `AsyncClient` with `transport=ASGITransport(app=create_app(...))` for route tests — never spin up a real server in tests. Inject test doubles via `app.state`.

Fixtures live in `tests/conftest.py`. Keep fixtures minimal; use `pytest.fixture(scope="session")` for expensive DB setup.

## Typing

- Strict mypy. Every function has a return type annotation. Every parameter is annotated.
- Use `from __future__ import annotations` so annotations are strings at runtime (avoids forward-reference issues).
- Use `TYPE_CHECKING` guards for imports used only in annotations.
- Prefer `X | Y` over `Optional[X]` or `Union[X, Y]`.
- `Any` is allowed only at trust boundaries (JSON decode output, external API responses). Always annotate the narrowed type immediately after validation.

## Migrations

Alembic migrations live in `alembic/versions/`. Name them `NNNN_short_description.py`. Always include both `upgrade()` and `downgrade()`. All new timestamp columns use `TIMESTAMPTZ`. All new string primary keys that look like UUIDs use `UUID` type. Run `make migrate` to apply; never run `alembic` directly in production — always through `strumline migrate`.
