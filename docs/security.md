# Security

This document covers the security properties of a Strumline v1 deployment,
the invariants the implementation provides, and the operator responsibilities
that fall outside the codebase.

## Admin API key

The admin REST API (`/admin/v1`) is disabled by default and gated behind a
single bearer key set in `ADMIN_API_KEY`. It is only mounted when
`ADMIN_API_ENABLED=true`.

**Generating a key:**
```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

This produces a 256-bit URL-safe random string (~43 characters).

**Rotation:** set a new `ADMIN_API_KEY` and restart the API process. There is
no grace period for the old key — it is invalid as soon as the process
restarts.

**Network exposure:** the admin API is intended for management networks only.
Never expose port 8000 to the public internet with `ADMIN_API_ENABLED=true`.
Bind the API process to an internal interface or place it behind a
network-level access control (firewall rule, security group, private subnet).

## Auth token entropy

Auth token keys are generated with `secrets.token_urlsafe(32)`: 32 bytes of
cryptographically random data, 256 bits of entropy, URL-safe base64 encoded.
The raw key is returned once at creation and never stored. Only its
HMAC-SHA256 digest (keyed with `APP_KEY`) is persisted in the database.

Set `APP_KEY` to a secret in production. Without it, SHA-256 without an HMAC
key is used — functional but provides no protection against offline dictionary
attacks on the stored hashes.

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

**Revocation cache window:** a revoked token remains valid for up to 60 seconds
(one `AUTH_TOKEN_CACHE_TTL` period). On a cache miss with a database failure,
the resolver fails closed (returns 503, admits no events).

## Database grants

Two PostgreSQL roles connect to the same database:

| Role | Variable | Grants | Used by |
|---|---|---|---|
| App role | `DB_USER` / `DB_PASSWORD` | Full read-write on all tables | API process, CLI, migrations |
| Ingest role | `INGEST_DB_USER` / `INGEST_DB_PASSWORD` | `SELECT` on `auth_tokens` and `apps` only | Ingest process (auth token resolver) |

The ingest process **never** receives write-capable credentials. If
`INGEST_DB_PASSWORD` is empty, the ingest process falls back to the app role —
this is only acceptable in development. In production, provision the read-only
role with the bootstrap script:

```bash
docker compose run --rm strumline-cli python -m strumline.db.bootstrap
```

Never grant the ingest role `INSERT`, `UPDATE`, `DELETE`, or `DDL` privileges.

## Payload and frame limits

| Limit | Default | Setting | Scope |
|---|---|---|---|
| Raw request body | 1 MiB | `MAX_PAYLOAD_BYTES` | Enforced before any parsing |
| Decompressed body | 1 MiB | `MAX_PAYLOAD_BYTES` | Enforced after gzip decompression |
| Normalized batch | 1 MiB | `MAX_PAYLOAD_BYTES` | Sum of IPC frame bodies per request |
| Records per batch | 300 | `MAX_BATCH_EVENTS` | Enforced after decoding |
| IPC frame body | 1 MiB | `IPC_MAX_FRAME_BYTES` | Hard-coded, per frame |
| JSON nesting depth | 64 | `_MAX_DEPTH` (code) | OTLP JSON only |

The raw body cap is enforced while reading the stream — no allocation beyond
the cap is made. The decompressed cap uses a read-exactly-one-byte-past-limit
check before allocating. Parser error messages are never echoed to callers.

## Metrics exposure

`/metrics` is unauthenticated. All label values are bounded low-cardinality
constants (process names, HTTP method, route template, status class, reason
codes, sink names). No token keys, project/app names, event IDs, or payload
content ever appear in metrics.

**Operator responsibility:** restrict access to `/metrics` at the network
level. Bind processes to an internal interface or apply a firewall rule before
exposing Prometheus scrape endpoints.

## Unix socket permissions

The processor creates the IPC socket (`IPC_SOCKET_PATH`) with mode `0o600`
(owner read/write only). All three containers run as uid `10001`
(`strumline` user) with no additional groups. The socket directory
(`/var/run/strumline/`) is shared via a named Docker volume accessible only
to containers that mount it.

Do not mount the IPC socket volume into untrusted containers.

## Log redaction

The ingest process never logs:
- Auth token key values (raw or hashed)
- Raw request bodies or parsed telemetry payloads
- Parser error diagnostics that could echo submitted data

Error responses from the OTLP handler use fixed strings — parser diagnostics
are caught and discarded before forming the response. The `from exc` cause is
preserved for internal tracebacks only (not sent to the caller).

Auth token cache misses are logged at `WARNING` with only the exception class
and a fixed message — no key material.

## Dependency scanning

Run `uv export --no-dev | pip-audit -` or `trivy image strumline:dev` against
the built image before each release to check for known CVEs in dependencies
and the base image.

The base image is `python:3.14-slim`. Pin the exact digest in the Dockerfile
for reproducible production builds.
