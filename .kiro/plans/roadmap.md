# Strumline — Roadmap

## Product contract

Strumline is a best-effort telemetry collector. It accepts structured events, resolves a project and app from an auth token, buffers and batches events, and dispatches them through a replaceable sink provider. Loki is the first supported sink, not a processor dependency.

The v1 deployment is one host with three containers built from one image:

```text
strumline-api        :8000  control plane health; admin REST API when enabled
strumline-ingest     :8001  HTTP ingestion and IPC writer
strumline-processor  :8002  IPC reader, batching, sink dispatch, health/metrics
```

Ingest and processor share a Unix-domain-socket directory. PostgreSQL stores control-plane metadata only. Raw telemetry is never stored in PostgreSQL.


OTLP/HTTP log ingestion is implemented at `/v1/logs`, with Protobuf/JSON, gzip,
app-token routing, and typed resource/scope/record preservation. It uses OTLP
success, partial rejection, and retryable failure responses; success acknowledges
in-memory admission, not durable delivery. See the
[current OTLP contract](../../docs/api/otlp-logs.md). M7 covers this implementation;
[M8](m8-otlp-integration.md) extends OTLP integration after v1.

## Non-negotiable invariants

### UTC storage

- Every persisted, transmitted, logged, and sink-facing canonical timestamp is timezone-aware UTC.
- PostgreSQL timestamp columns use `TIMESTAMPTZ`; database sessions run in UTC.
- JSON APIs serialize canonical timestamps with a trailing `Z`.
- OTLP timestamps use UTC epoch nanoseconds. Preserve their exact values in the typed payload; the canonical datetime projection uses event time, then observed time, then server receipt time. `received_at` stays server-generated.
- Loki uses server `received_at` as its entry timestamp. A valid client timestamp remains event data/metadata and never controls storage ordering.
- `App.timezone` is an optional IANA timezone used only for presentation. Display precedence is app timezone, then `APP_TIMEZONE`, then UTC. CLI and REST may override the app value. Localized display fields are explicit additions and never replace canonical UTC fields.

### Sink boundary

`BatchProcessor` depends only on the sink contract and its generic errors:

```python
class EventSink(ABC):
    name: str

    @abstractmethod
    async def write(self, batch: EventBatch) -> None: ...

    async def close(self) -> None: ...

class RetryableSinkError(Exception): ...
class PermanentSinkError(Exception): ...
```

`strumline.sinks` owns a registry/factory selected by `SINK_PROVIDER=null|loki`. The provider is global in v1. Retryable failures use exponential backoff with jitter; permanent failures and retry-exhausted batches are counted and discarded. Per-app routing, fan-out, and `sink_configs` are deferred.

### First-class, deployment-independent observability

Every process exposes `/metrics` when `METRICS_ENABLED=true`, without requiring Prometheus or Grafana. The development Compose stack supplies pinned Loki, Prometheus, and Grafana services. Production deployments use the Strumline image with operator-managed infrastructure; operators may bring their own compatible services and use the shipped scrape config and dashboard JSON.

## Architecture and import boundaries

```text
HTTP client -> ingest -> bounded queue -> UDS frames -> processor queue
                                                    -> BatchProcessor
                                                    -> EventSink provider
```

- `ingest/` may import `domain/`, `ipc/`, `metrics/`, and only the read-only auth token resolver from `db/`.
- `processor/` may import `domain/`, `ipc/`, `metrics/`, and the sink contract/factory; it must not import provider implementations directly.
- `control/` contains application services shared by CLI and admin REST API.
- `cli/` and `api/` call `control/`; neither imports the data plane.
- `ipc/` may import only `domain/`.
- Import-linter enforces these boundaries from the milestone where each package appears.

## Repository shape

```text
strumline/
├── api/              # health and optional /admin/v1 routes
├── cli/              # scriptable CLI; Rich/Textual polish later
├── control/          # control-plane application services
├── db/               # models, UTC sessions, repositories, auth token resolver
├── domain/           # pure entities/errors
├── ingest/           # HTTP receiver and IPC writer
├── ipc/              # versioned framing contract
├── metrics/          # shared metric definitions
├── processor/        # IPC reader and BatchProcessor
├── sinks/            # contract, registry, NullSink, LokiSink
└── config.py
```

## Milestone dependency graph

```text
M0 -> M1 (basic CLI) -> M2 -> M2b -> M3 -> M4 -> M6 -> M7 -> M7b -> v1.0
      M1 -> M6b (admin API) -------------------------> M7
                           M2b -> M5 (post-v1 local ingest socket)
v1.0 + existing OTLP/HTTP logs -> M8 (post-v1 deeper OTLP integration)
```

M7 joins the completed data pipeline, observability, CLI/TUI, and REST tracks. Numbering identifies feature groups rather than a mandatory execution order. See [agent execution guide](agent-execution.md) for bounded work packets and checkpoints, and [planning review](planning-review.md) for unresolved contracts and proposed enrichments.

| Milestone | Goal | Depends on | v1 |
|---|---|---|---|
| [M0](m0-skeleton.md) | Installable one-image, three-container skeleton | — | yes |
| [M1](m1-core-domain.md) | UTC-safe metadata model and basic direct-DB CLI | M0 | yes |
| [M2](m2-ingest-path.md) | Validated HTTP ingestion and versioned IPC writing | M1 | yes |
| [M2b](m2b-processor.md) | UDS server, batching, sink contract and NullSink | M2 | yes |
| [M3](m3-loki-sink.md) | Loki provider behind the sink contract | M2b | yes |
| [M4](m4-observability.md) | Integrated metrics plus optional Prometheus/Grafana sample | M3 | yes |
| [M6](m6-cli-dx.md) | CLI/TUI and operator experience polish | M4 | yes |
| [M6b](m6b-admin-api.md) | Runtime-gated admin REST API | M1 | yes |
| [M7](m7-hardening.md) | Protocol docs, performance evidence, security/docs | M3, M4, M6, M6b | yes |
| [M7b](m7b-release-preparation.md) | Public OSS and release preparation | M7 | yes |
| [M7c](m7c-polishing.md) | Optional CLI/docs/developer-experience polish | M7b | no |
| [M5](m5-unix-socket.md) | Optional client-to-ingest Unix socket | M2b | no |
| [M8](m8-otlp-integration.md) | OTLP/gRPC, deeper log integration, traces and metrics | M7/v1, existing OTLP/HTTP logs | no |

M8 ships in stages: log model/correlation, gRPC logs, traces, then metrics.
Each signal requires an end-to-end path to a compatible sink before it is
advertised as supported. M8 and M5 are independent post-v1 tracks; profiles
are a later candidate rather than an M8 completion requirement.

## Deferred

- Per-app sink routing, multi-sink fan-out, and persistent sink configuration
- Sink providers beyond Loki and NullSink
- Event replay and durable/dead-letter storage
- Local Unix-socket ingestion (M5)
- OTLP/gRPC, deeper log integration, traces, and metrics (M8)
- OTLP profiles and WebSocket transport (unscheduled)
- Web admin application
- Go/Rust ingest rewrite until profiling justifies it
- msgpack until JSON framing is proven to be a bottleneck

## v1 success criteria

1. Base `docker compose up` starts PostgreSQL and the three Strumline containers from one tagged image.
2. The development Compose stack includes Loki, Prometheus, and Grafana; production BYO sink and observability deployment is documented.
3. Project, app (including presentation timezone), and auth token management works through the CLI and runtime-enabled REST API.
4. Create resources, ingest an event, and observe it through the selected sink in under five minutes.
5. Ingest sustains at least 1,000 events/sec on one documented single-core test environment; HTTP receipt-to-enqueue P99 is below 5 ms.
6. Overload and sink failure preserve service health while distinct drop/error counters explain losses.
7. UTC invariants, import boundaries, and the IPC conformance suite pass in CI.
8. M0, M1, M2, M2b, M3, M4, M6, M6b, M7, and M7b are complete. M5, M7c, and M8 are not required for v1.
9. Existing OTLP/HTTP logs pass SDK/Collector interoperability and overload/field-preservation checks as part of M7.
