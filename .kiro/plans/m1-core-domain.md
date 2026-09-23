# M1 — Core Domain, Database, and Basic CLI

**Type:** Foundation  
**Depends on:** M0  
**Unlocks:** M2, M6b  
**Goal:** UTC-safe project/app/auth token persistence and complete scriptable management through a direct-database CLI.

## Scope

M1 contains no management REST routes and no admin token. The admin API arrives in M6b. CLI and future REST handlers share application services in `strumline/control/`, preventing business rules from being duplicated.

## Domain and UTC rules

Pure domain entities include `Project`, `App`, and `AuthToken`. Every datetime is timezone-aware UTC.

```python
@dataclass
class App:
    id: UUID
    project_id: UUID
    slug: str
    name: str
    timezone: str | None  # validated IANA identifier; presentation only
    created_at: datetime
    updated_at: datetime
```

`App.timezone` is nullable. Display resolution is `App.timezone` → `APP_TIMEZONE` → `UTC`; no localized datetime is persisted. CLI output defaults to that display timezone and offers an explicit UTC option.

### PostgreSQL schema

- `projects`: UUID, unique slug, name, UTC `created_at`/`updated_at` as `TIMESTAMPTZ`.
- `apps`: UUID, project FK, per-project unique slug, name, nullable IANA `timezone`, UTC timestamps.
- `dsns`: UUID, app FK, unique key, active flag, UTC `created_at`/`revoked_at`.
- Do not create `sink_configs` in v1.
- Set the database/session timezone to UTC and return timezone-aware UTC Python datetimes.

Alembic owns migrations. A migration test upgrades an empty database to head.

## Control services and repositories

`strumline/control/` exposes project, app, and auth token operations used by both CLI and M6b. Repositories provide create, get, list, update, and delete/revoke methods as applicable. Domain errors map consistently to CLI exit codes now and HTTP responses later.

Auth token keys use `secrets.token_urlsafe(32)`: 32 random bytes, normally about 43 URL-safe characters. Only the key is security-sensitive; token display formatting is separate.

Create a least-privilege ingest database role/URL with grants limited to the tables and columns required for read-only auth token resolution. The Compose/bootstrap flow creates and verifies these grants rather than merely documenting a second URL.

## Basic scriptable CLI

M1 implements:

```text
strumline migrate [--dry-run]
strumline project create|list|get|update|delete
strumline app create|list|get|update|delete
strumline app timezone set|clear
strumline token create|list|revoke
```

Commands call `control/` directly and support stable plain/JSON output, non-interactive flags, useful exit codes, and destructive-operation confirmation with `--yes`. Rich/Textual presentation is deferred to M6.

Two supported execution paths are documented and tested:

- Host: `uv run strumline ...` with a host-reachable URL such as `postgresql://...@127.0.0.1:5432/strumline`; development Compose publishes PostgreSQL on loopback.
- Compose: a disposable `strumline-cli` service uses the internal `postgres` hostname and the same tagged image.

## Configuration

```text
DATABASE_URL=postgresql+asyncpg://strumline:strumline@postgres:5432/strumline
INGEST_DATABASE_URL=postgresql+asyncpg://strumline_ingest:...@postgres:5432/strumline
APP_TIMEZONE=                 # optional IANA display timezone; unset means UTC
```

## Acceptance criteria

- [ ] Migration creates projects, apps with nullable timezone, and DSNs; all timestamp columns are `TIMESTAMPTZ`.
- [ ] PostgreSQL and application sessions are verified as UTC.
- [ ] Project/app CRUD and auth token create/list/revoke work through host and Compose CLI flows.
- [ ] App timezone accepts valid IANA names, rejects invalid names, and never changes stored canonical timestamps.
- [ ] Repository update methods exist wherever the CLI exposes update.
- [ ] Auth token keys have 256 bits of entropy and are normally about 43 characters.
- [ ] The ingest database role can perform the required resolution query and cannot mutate metadata.
- [ ] No management REST routes, `STRUMLINE_ADMIN_TOKEN`, `sink_configs`, or raw telemetry tables exist.
- [ ] Domain/control/repository tests and the migration test pass.
