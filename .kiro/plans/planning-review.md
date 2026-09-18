# Planning review

## Verdict and scope

The intended system is coherent: one host, three Telemetria processes, direct-database CLI/control services, an isolated ingestion process, versioned UDS IPC, and a replaceable write-only sink. UTC-only canonical timestamps and optional first-class Prometheus/Grafana support remain requirements.

The workspace currently contains plans and minimal project metadata, with no application implementation. Acceptance criteria below describe future evidence, not verified runtime behavior. Architecture is sufficiently defined to begin M0; contracts below should be settled before their owning implementation packets.

This review separates factual corrections already applied from proposed behavioral decisions. The recommendations below are not silently adopted requirements. Once settled, move each decision into its owning contract and milestone; do not maintain competing specifications.

## Corrections applied

- M0 now explicitly requires a build backend, package discovery, and wheel/console-script verification. `uv sync` does not install a project without a build system ([uv documentation](https://docs.astral.sh/uv/concepts/projects/sync/)).
- M2 no longer suggests automatically retaining a non-UTC original timestamp in metadata.
- M3 now specifies nanoseconds as a decimal string in Loki JSON, not a JSON number. The push endpoint rejects numeric timestamps ([Loki API](https://grafana.com/docs/loki/latest/reference/loki-http-api/)).
- M6b now depends on M1 rather than TUI polish; M7 explicitly joins the completed feature tracks.

## High-priority gaps

### 1. Bounded queues are not a complete memory budget

Evidence: M2 limits HTTP bytes and queue items; M2b limits batch item count. Neither specifies queue byte budgets, concurrent request-body memory, outstanding sink tasks, or batch bytes.

Consequence: several individually valid batches can exhaust process memory. A batch of 500 large events can also exceed a sink's request limit.

Proposal: specify maximum request bytes, normalized event bytes, queue items and bytes, batch items and bytes, active requests, and one in-flight sink batch initially. Account for JSON decoding/encoding copies and Python object overhead; serialized-byte accounting is a budget proxy, not exact RSS. Define defaults together and test sustained overload under a process memory limit.

Owner: M2-A/M2-C, M2b-B. Add an explicit `EventBatch` definition, absent from the current domain contract.

### 2. HTTP acceptance is intentionally best-effort but underspecified

Evidence: M2 says responses “may include” accepted/dropped counts; error codes are grouped rather than mapped. The acceptance checklist asks for batch-count enforcement before parsing without specifying a streaming parser.

Proposal: retain the approved `202` behavior even if every valid event is locally dropped. Freeze a response such as `{ "validated": 10, "enqueued": 7, "dropped": 3 }`; define `enqueued` strictly as local ingest admission. Document the same shape for single events. Whole-batch validation is atomic; queue admission need not be.

Enforce the byte cap while reading, then parse the bounded body, then count/validate its events before enqueue. Recommend rejecting compressed HTTP input in v1 unless streaming decompression limits are explicitly implemented. Keep outbound Loki gzip support.

Specify exact JSON envelopes, unknown fields, non-finite numbers, nesting limits, level normalization, and status mappings. Invalid DSNs are 401; an unavailable resolver on a cache miss should be a service failure, not a false authentication rejection.

Owner: M2-A/M2-B/M2-C.

### 3. IPC recovery and socket ownership need a state machine

Evidence: M2b checks only that a stale path is a socket before unlinking it. It does not distinguish another live processor's socket. Invalid-frame handling records errors without specifying when to close the connection.

Proposal: single processor owner, single Uvicorn worker per process, explicit ownership protection, and rejection of a second live owner. Unlink only a demonstrably stale socket owned by this service. Never remove a regular file or symlink target.

Close the connection on oversized length, incomplete frame timeout, or truncation; continue past an unknown version or malformed envelope only when its entire bounded body has been consumed. Specify prefix/body read deadlines, reconnect/backoff, extra-writer handling, and shutdown cleanup.

Validate normalized event size including the envelope before enqueue so a public request cannot create an impossible-to-send frame. Define whether an ambiguous failed write is discarded or retried; best-effort permits either, but implementations need one rule.

Owner: M2-A/M2-D/M2b-A.

### 4. Successful writes, losses, and duplicates need precise limits

Evidence: M7 requires a distinct counter for each loss path. A hard kill cannot emit counters for lost memory, and `write`/`drain` provides no processor acknowledgment.

Proposal: distinguish observed drops, uncertain delivery after transport failure, and unobservable loss after process termination. Do not promise exact loss accounting across crashes. Preserve event IDs on sink retries; document that retrying HTTP currently generates new IDs, so these are not general idempotency keys.

Define sink `write` success, partial-acceptance uncertainty, retry count versus total attempts, maximum elapsed retry time, cancellation, unexpected exceptions, and `close` deadline. NullSink should report intentional discards explicitly rather than implying durable delivery. The five-minute “find an event” success criterion should name the Loki walkthrough, not NullSink.

Owner: M2-A/M2b-B/M7.

### 5. Optional software versus broken configured dependencies

Evidence: M6 says missing Loki does not make the installation unhealthy even though Loki may be the selected provider. M0 specifies health but later plans never define a full readiness contract.

Proposal: `/health` reports a responsive process and critical-task liveness; `/ready` reports ability to perform the configured role, with explicit dependency/degraded status. A missing unconfigured optional service is neutral. Failure of configured Loki must be visible to `doctor` and delivery status even when liveness remains 200. Do not make event processing depend on Prometheus/Grafana health.

Define database/cache behavior, background-task supervision, startup order, migration readiness, and bounded shutdown: stop HTTP intake, drain ingest, finish processor intake, drain batches, close sink. Keep the shutdown deadline below the container stop grace period.

Owner: M0-B/M1-A/M2-D/M2b-B/M6-A.

### 6. Metadata updates affect routing and authorization

Evidence: M1 exposes updates/deletes but does not define slug mutability, FK deletion policy, transaction boundaries, pagination, or DSN secret exposure. M2 caches DSNs with no capacity or unavailable-database policy.

Proposal: make slugs immutable in v1; changing display names is safe and avoids stale cached routing labels. Specify cascade/restrict deletion, revocation semantics, cache capacity and TTL, and no stale authorization beyond expiry. Enforce nested project/app/DSN ownership in shared services, especially DSN revocation by ID.

Choose a DSN secret policy before migrations. Recommended: reveal generated secrets once, store a digest, and return redacted listings. This changes the current plaintext-key sketch and remains a proposal. Define CLI/API pagination and exact error/exit mappings. Migration privileges belong to bootstrap/migration execution; routine control-plane privileges should be narrower.

Owner: M1-A/M1-B/M1-C/M6b.

### 7. Loki support needs a complete wire and deployment contract

Evidence: M3 maps timeouts/429/5xx and other 4xx, but omits redirects and Loki's ingestion-blocking status. Authentication/TLS for external Loki is also absent.

Loki documents a configurable blocked-ingestion status, default 260. Treating every 2xx as success can lose events invisibly ([Loki validation documentation](https://grafana.com/docs/loki/latest/operations/request-validation-rate-limits/)). Specify supported success responses, 260 handling, redirect policy, Retry-After handling within the retry budget, external authentication, TLS verification, and secret redaction.

Project/app/level labels are not intrinsically low-cardinality: bound slug/level domains and document a stream budget. Sorting one batch and using UTC `received_at` cannot guarantee ordering across concurrent requests or clock adjustments. Add skew, old-event, and retry-order fixtures.

Owner: M3-A/M3-B.

### 8. Configuration and Compose setup have hidden dependencies

Evidence: M0 shares one settings concept across processes; M1 offers host and container URLs; M6 writes `.env` before startup using a disposable container. No exact precedence, bind mount, service profile, or CLI entrypoint is specified.

Proposal: typed settings per process plus shared primitives, one precedence table, empty-string handling, and startup-only settings unless explicitly documented otherwise. Require Loki secrets only when Loki is selected; require the admin key only in the enabled API process. Ingest must never receive write-capable DB credentials merely because every service consumes the same file.

Give the disposable CLI an explicit profile, entrypoint, working-directory bind mount for generated configuration, and offline `init` mode. Describe the first-image-build step. Test both empty and existing database volumes, migrations, role creation/grants, and upgrades. Pin the tested Python 3.14 patch, uv, build backend, and container versions without inventing compatibility claims.

Compose profiles start services; the plan still needs an explicit mechanism selecting `SINK_PROVIDER=loki` and generating optional Grafana provisioning. Support external Loki even when the bundled Loki profile is disabled ([Compose profiles](https://docs.docker.com/compose/how-tos/profiles/)).

Owner: M0-C/M1-A/M3-B/M4-B/M6-A.

## Product clarifications and enrichments

- Keep Telemetria's v1 contract focused on collection and forwarding. Sink replacement guarantees writes, not a portable log-query API. Loki-specific TUI log browsing should use an optional read adapter outside `EventSink`; another write provider need not implement queries.
- Define project/app isolation as routing/authentication scope, not separate storage tenants. State whether v1 is a trusted single-operator installation; the single admin key does not implement per-project admin authorization.
- Specify the timestamp boundary: Telemetria-owned fields are UTC; arbitrary payload strings cannot reliably be recognized as dates. Recommended: treat payload as opaque JSON and never duplicate original non-UTC client timestamp fields automatically. `TIMESTAMPTZ` stores an instant, not the original zone; UTC sessions control output ([PostgreSQL documentation](https://www.postgresql.org/docs/current/datatype-datetime.html)).
- Give presentation precedence in one place: explicit display override → stored app timezone → `APP_TIMEZONE` → UTC. Distinguish persistent app configuration from one-command/request display options. Add `tzdata` availability to slim-image checks.
- Clarify `APP_TIMEZONE` as an operator default for presentation, not a process-wide `TZ` change. Metadata JSON and sink records remain UTC under every display setting.
- Make the five-minute quick start one reproducible script with a concrete event fixture. Base/NullSink validates plumbing; the optional Loki walkthrough proves storage/querying.
- Keep performance goals as targets until measured. Define loss-free steady-state duration, queue stability, event size, CPU allocation, warm cache, and timestamp instrumentation; throughput should not pass merely because all requests return 202 while dropping events.
- Add a small architecture decision record for best-effort delivery, one host/worker topology, UTC normalization, global provider choice, and direct-DB CLI. Avoid introducing a durable broker, generic plugin framework, or query abstraction before evidence requires one.

## Validation limits

This is a document and source-reference review. No service, integration test, or benchmark exists to establish runtime guarantees yet. The earlier claim that a keyword scan established full consistency was too strong: it caught stale wording, not the semantic gaps above.
