# M6b — Admin REST API

**Type:** Enhancement  
**Depends on:** M1  
**Unlocks:** M7  
**Goal:** Expose the existing control services through an authenticated, runtime-gated REST API.

M6b depends on M1's shared control services and scriptable command semantics, not M6's terminal presentation. It can be implemented independently of the ingest and TUI milestones; API keys can be supplied through configuration before `init` exists.

## Runtime gate and authentication

The code remains in the one shared image. At process startup, `ADMIN_API_ENABLED=true` mounts the router at `/admin/v1`; false leaves it unmounted. This is a runtime configuration decision, not a Docker build variant.

```text
ADMIN_API_ENABLED=false
ADMIN_API_KEY=
```

When enabled, a non-empty `ADMIN_API_KEY` is required and every admin route uses `Authorization: Bearer <ADMIN_API_KEY>` with constant-time comparison. There is no `STRUMLINE_ADMIN_TOKEN`. Rotation updates configuration and restarts the API process.

## Architecture

Handlers are thin adapters over the `strumline/control/` services created in M1. They do not duplicate repository calls, validation, timezone rules, or auth token generation. Domain errors map centrally to stable HTTP error envelopes.

```text
GET|POST           /admin/v1/projects
GET|PATCH|DELETE   /admin/v1/projects/{project_slug}
GET|POST           /admin/v1/projects/{project_slug}/apps
GET|PATCH|DELETE   /admin/v1/projects/{project_slug}/apps/{app_slug}
GET|POST           /admin/v1/projects/{project_slug}/apps/{app_slug}/dsns
DELETE             /admin/v1/projects/{project_slug}/apps/{app_slug}/dsns/{dsn_id}
```

App create/update accepts nullable `timezone` as a validated IANA identifier. CLI and REST behavior must match because both use the same service.

## Timestamp representation

Canonical fields such as `created_at`, `updated_at`, and `revoked_at` are always UTC RFC 3339 strings ending in `Z`. The API never replaces these with localized strings. If requested through an explicit presentation option, separately named localized display fields may be added using app timezone → `APP_TIMEZONE` → UTC precedence.

## API documentation

OpenAPI JSON and interactive documentation are available only when the admin API is enabled. FastAPI's built-in docs are sufficient; if Scalar is chosen, add and pin its dependency explicitly. Docs require the same network hardening as the API.

## Acceptance criteria

- [ ] Disabled by default: `/admin/v1` and admin docs are unmounted and return `404`.
- [ ] Enabled without `ADMIN_API_KEY`: startup fails with a clear configuration error.
- [ ] Missing or incorrect bearer keys return `401`; valid keys authorize every admin route.
- [ ] CRUD and auth token operations match the CLI because handlers call shared control services.
- [ ] App timezone set/clear behavior and validation match the CLI.
- [ ] Canonical response timestamps end in `Z`; any localized fields are additional and explicitly named.
- [ ] The same built image can run with the API enabled or disabled.
- [ ] OpenAPI/docs exposure follows the runtime gate.

## Deferred

A web admin application remains a separate future milestone. This API does not add frontend assets, user accounts, sessions, or browser authentication.
