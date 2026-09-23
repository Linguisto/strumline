# Coding-agent execution guide

## Authority and work units

The roadmap owns product scope; milestone documents own feature acceptance criteria. This guide divides those milestones into bounded implementation packets. It does not expand v1 scope or adopt the unresolved behavioral proposals in [planning-review.md](planning-review.md).

Resolve each packet's relevant contract decisions before coding it. Record decisions in the owning contract and update references. Do not let each agent invent response schemas, defaults, error names, or configuration semantics independently.

Keep current milestone IDs for traceability. A packet is a reviewable change with a usable output and focused validation, not necessarily one chat turn. Finish its tests and documentation before marking it complete. Advance to the next ready packet without asking for permission for routine authorized work.

## Contracts before consumers

Introduce these alongside their first owner, not as a late M7 documentation exercise:

| Artifact | Owner | Required contents |
|---|---|---|
| `docs/architecture/decisions.md` | M0-A, expanded per feature | Accepted invariants, topology, ownership, deferred scope |
| `docs/configuration.md` | M0-B, expanded per feature | Variable type/default, consumer, required-when, precedence, secret status, restart behavior |
| `docs/api/control-contract.md` | M1-B | CRUD/auth token rules, timezone configuration, pagination, domain errors |
| `docs/api/otlp-logs.md` | M2-A | OTLP single/batch requests, responses, UTC rules, limits, best-effort semantics |
| `docs/ipc-protocol.md` | M2-A | Frame/schema/version/error behavior and golden fixtures |
| `docs/sinks.md` | M2b-B | EventBatch, ABC, lifecycle, failure taxonomy, retries, success semantics |
| `docs/metrics.md` | M2-C, expanded per feature | Metric names/types/units/labels, admission/drop meanings, known observability limits |

M7 audits these contracts and compatibility evidence; it does not first discover their contents.

## Implementation packets

| Packet | Needs | Deliverable | Evidence to close |
|---|---|---|---|
| M0-A Packaging | — | Explicit backend, Python target, lockfile, importable packages, four scripts | Build wheel; install in clean environment; script help/version and package metadata resolve |
| M0-B Process skeleton | M0-A | Shared config primitives, per-process settings, process factories, health, logging | Each process starts/stops independently; metadata version and UTC logs; invalid relevant settings fail clearly |
| M0-C Container/CI | M0-B | One tagged image, non-root volume ownership, Compose, Makefile, CI | Fresh build without `.env`; healthy containers; same image IDs; writable shared directory; lint/test jobs |
| M1-A Persistence | M0-C | Entities, migrations, UTC sessions, repositories, bootstrap and least-privilege roles | Fresh/existing DB migration checks; UTC round trip; forbidden writes denied for ingest role |
| M1-B Control services | M1-A | Transactional CRUD, auth token lifecycle, scope checks, timezone validation | Service-level success/conflict/not-found/ownership tests with real PostgreSQL constraints |
| M1-C Basic CLI | M1-B | Scriptable commands, stable JSON/exit codes, disposable CLI service | Host and Compose workflows create/read/update/delete metadata and revoke an auth token |
| M2-A Event/IPC contracts | M1-C | Event and EventBatch schema decisions, HTTP examples, frame codec, golden fixtures | UTC/offset/fallback fixtures; UTF-8 byte boundaries; version/length/truncation cases |
| M2-B Resolver | M2-A | Read-only auth token lookup, bounded TTL cache, outage policy | Active/revoked/expired cache, cache capacity, DB failure, and routing metadata tests |
| M2-C HTTP admission | M2-B | Body limits, whole-batch validation, bounded queue admission, feature metrics | Invalid batch enqueues zero; queue pressure rejects atomically with retryable status; memory/admission limits enforced |
| M2-D IPC writer | M2-C | One writer task, reconnect/deadlines, failure and shutdown policy | Fake Unix server observes golden frames; stalled/failed writes obey bounded memory/time rules |
| M2b-A IPC receiver | M2-D | Owned Unix listener, reader lifecycle, processor queue | Live-owner collision rejected; fragmented reads; malformed/oversized frames; EOF and reconnect |
| M2b-B Batcher/provider contract | M2b-A | EventSink/errors/registry, NullSink, bounded batching/retry/shutdown | Spy provider sees size/time/byte flushes; fake clock tests retries; close/cancellation; HTTP-to-spy integration |
| M3-A Loki provider | M2b-B | Wire encoding, response classification, selected-provider settings | Captured gzip request has decimal-string epoch nanoseconds; retries/permanent errors match contract |
| M3-B Loki deployment | M3-A | Pinned development service and explicit production provider configuration; external connection docs | Real Loki ingest/query round trip; NullSink works without Loki |
| M4-A Metric integration | M2b-B | Shared registry conventions, metric endpoint behavior, metrics-only dashboard | All processes scrape; disabled endpoint behavior; bounded label families; no Loki required |
| M4-B Observability infrastructure | M3-B, M4-A | Bundled development Prometheus/Grafana and reusable BYO artifacts | Development stack and external production services |
| M6-A Operator commands | M1-C, M2b-B | init/config/doctor, host/container contexts, explicit degradation | Offline initialization, invalid config, missing optional service versus failed selected provider |
| M6-B Terminal presentation | M6-A, M4-B | Rich/Textual polish, rate views, optional Loki read adapter, timezone rendering | Non-TTY fallback; canonical JSON stays UTC; unavailable panels and DB-free optional views behave as specified |
| M6b-A REST management | M1-C | Runtime-gated routes over existing services; API key auth; canonical UTC | CRUD parity and nested ownership; disabled/enabled/missing-key matrix; docs gate |
| M7-A Release integration | M3-B, M4-B, M6-B, M6b-A | Repeatable walkthrough, failure suite, full boundary audit | End-to-end development quick start; production deployment guidance; graceful shutdown; documented crash-loss limits |
| M7-B Release evidence | M7-A | Reproducible benchmark, docs audit, compatibility fixtures, release notes | Target-load run with stable queues and no observed drops; latency methodology; protocol and extension docs |

M5 stays post-v1, after the working M2b pipeline. Split it into listener lifecycle and HTTP parity/cleanup packets when scheduled.

[M8](m8-otlp-integration.md) is a separate post-v1 track building on existing
OTLP/HTTP logs. Schedule M8-A log integration, M8-B gRPC logs, M8-C traces, and
M8-D metrics as separate vertical slices. Freeze each stage's contracts first;
new signals require a compatible sink and end-to-end evidence before closure.

M4-A and M6-A are partial milestones and can start before their full milestone prerequisites complete. M4-B and M6-B retain the full integration gates. This permits early diagnostics without marking the full milestone done prematurely.

## Recommended sequence for one agent

1. M0-A/B/C: produce an installable, runnable foundation.
2. M1-A/B/C: produce a working metadata/CLI slice.
3. M2-A/B/C/D and M2b-A/B: produce the first testable end-to-end telemetry slice using a spy/NullSink.
4. M4-A and M6-A: make the pipeline inspectable before adding infrastructure.
5. M3-A/B and M4-B: verify real storage and optional observability.
6. M6b-A: expose shared control services; it may be scheduled any time after M1-C.
7. M6-B: finish terminal presentation against stable metrics and services.
8. M7-A/B: publish integration and performance evidence; finalize v1.

The dependency graph permits independent work; it is not authorization to spawn agents. Any parallel execution must use the session's collaboration policy and avoid simultaneous edits to shared contracts/configuration.

## Packet handoff template

Each implementation task should contain:

```text
Packet ID and observable outcome:
Prerequisites and already completed evidence:
Owning contracts to read:
Allowed modules and expected outputs:
Inputs/outputs and failure behavior:
Acceptance cases (including one relevant failure path):
Exact verification commands once the toolchain exists:
Non-goals and unresolved decisions:
Completion evidence and follow-up packet:
```

Resolve concrete file ownership from the milestone package structure. Avoid broad instructions such as “implement production-ready ingestion” without naming its contract, failure cases, and stopping point.

## Verification and progress discipline

- Use the configured project interpreter and lockfile. M0 establishes exact commands; later tasks reuse them instead of inventing alternate runners.
- Test public behavior and meaningful failure boundaries. Do not duplicate implementation logic in assertions or add tests for wording-only edits.
- Use a real PostgreSQL instance for migration/constraint/role checks, a fake provider for retry tests, a Unix server for framing tests, and real Loki only for the provider integration packet.
- Use injected clocks/sleep/jitter for deterministic batch/retry/TTL tests; avoid multi-second sleeps where a fake clock establishes the behavior.
- Grow import checks with real packages. Allow provider construction in the composition root/registry while preventing `BatchProcessor` from depending on provider implementations; do not accidentally prohibit the intended factory's transitive imports.
- Keep status as pending/in-progress/blocked/done per packet, with commands/results or a concrete blocker. Checkboxes are not evidence by themselves.
- Run a checkpoint after each complete vertical slice. Broaden testing only when changes or unresolved risks justify it.
- M0 closure must include the missing packaging/configuration decisions from the review. Later packet closure must not conceal unresolved behavior behind “may,” “if useful,” or “choose at implementation time.”
