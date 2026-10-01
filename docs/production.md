# Production deployment, upgrade, and recovery

Strumline publishes one Linux `amd64`/`arm64` image to
`ghcr.io/linguisto/strumline`. Use an immutable release tag or digest in
production. The development Compose file is a local example; it includes sample
infrastructure, reload flags, anonymous Grafana access, and development defaults.

For a copyable deployment and first-log walkthrough, see [Quickstart](quickstart.md).

## Topology and startup

Run three containers from the same image:

```text
strumline-api        → strumline-api
strumline-ingest     → strumline-ingest
strumline-processor  → strumline-processor
```

API and CLI/migrations receive the read-write application database role. Ingest
receives only DB host/port/name plus `INGEST_DB_USER` and
`INGEST_DB_PASSWORD`; never inject `DB_USER` or `DB_PASSWORD` into it. Processor
does not need database credentials. Ingest and processor share a socket
directory writable by their common uid/gid (`10001` in the published image).

Start PostgreSQL, run `strumline migrate`, provision the restricted role with
`python -m strumline.db.bootstrap`, start processor, then ingest and API. The
bootstrap command is idempotent and does not change an existing password. To
rotate it, set the new secret for the bootstrap job and run
`python -m strumline.db.bootstrap --rotate`, then restart ingest with the same
secret.

Terminate TLS before public ingest traffic. Keep the admin API and unauthenticated
metrics endpoints on trusted networks. Restrict the Unix-socket volume to the
ingest and processor containers. Use operator-managed PostgreSQL and Loki with
their own access controls, backups, monitoring, and retention.

## Secrets

Provide unique database passwords, `ADMIN_API_KEY` when the admin API is
enabled, and a high-entropy `APP_KEY`. Preserve `APP_KEY` across restarts,
upgrades, restores, and failover: existing token hashes cannot be validated with
a different key. Rotate ingestion tokens deliberately after an APP_KEY loss.

## Upgrade and rollback

1. Back up the control-plane PostgreSQL database and record the running image
   digest and configuration.
2. Review release notes for schema, configuration, HTTP, IPC, and sink changes.
3. Pull by digest, run migrations once, then replace processor, ingest, and API.
4. Run `strumline doctor` and the quickstart create → ingest → Loki verification.

Alembic migrations include downgrade functions, but data-preserving rollback is
not guaranteed across every release. Restore the pre-upgrade database backup
when a release note says downgrade is unsafe. Never run old application code
against a schema it does not support.

PostgreSQL contains projects, apps, and token hashes only. Backups cannot recover
raw tokens; those are shown once. Raw telemetry is never stored there.

## Delivery and recovery limits

An OTLP `200` acknowledges admission to ingest memory. Events can be lost during
process shutdown, IPC failure, queue pressure after admission, permanent sink
failure, or retry exhaustion; retries can duplicate event IDs. There is no WAL,
replay, or dead-letter store. Database backup and container rollback cannot
recover lost telemetry. Monitor the documented drop/error metrics and validate
delivery through the configured sink after changes.
