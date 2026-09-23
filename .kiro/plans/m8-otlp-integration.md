# M8 — Deeper OpenTelemetry Integration (Post-v1)

**Type:** Staged post-v1 enhancement  
**Status:** Planned  
**Depends on:** M7/v1 and the existing OTLP/HTTP logs implementation  
**Goal:** Extend Telemetria into a receiver and forwarding pipeline for multiple
OpenTelemetry signals, with consistent transport behavior and explicit sink capabilities.

## Starting point

`POST /v1/logs` already supports OTLP/HTTP Protobuf/JSON and gzip. App tokens
determine ownership; typed resource, scope, and log-record data survive the
queue, IPC, and Loki path. This is implemented v1 scope, not deferred M8 work.
See [the current contract](../../docs/api/otlp-logs.md).

M8 expands that foundation in independently releasable stages. M5's local
Unix-socket listener is not a prerequisite. Continue to use best-effort
delivery unless a separate durability milestone changes that contract.

## M8-A — First-class log data and correlation

- Define explicit internal representations for resource, instrumentation scope,
  typed attributes, body, severity, trace/span context, schema URLs, and exact
  timestamps. Evaluate reuse of the preserved OTLP payload before adding abstractions.
- Make supported fields available to processing and sinks without ad hoc
  traversal of `payload.otlp`; retain direct OTLP JSON ingestion.
- Specify IPC versioning and upgrade behavior before changing its event schema.
- Improve sink mapping and operator log/trace correlation. Document which
  attributes are stored, indexed, or exposed as structured metadata, with
  explicit cardinality limits and backend prerequisites.
- Keep source/observed timestamps distinct from server receipt time. Record
  any deliberate precision reduction at the sink boundary.

## M8-B — OTLP/gRPC logs

- Implement the standard LogsService export RPC, reusing authentication,
  normalization, admission limits, accounting, and downstream processing.
- Define gRPC metadata authentication, message/compression limits, status and
  partial-success mapping, deadlines, cancellation, and retry behavior from
  the OTLP specification before implementation.
- Resolve listener topology, ports, TLS termination, startup/shutdown ownership,
  and deployment configuration in an architecture decision. Do not start a
  second ingestion lifecycle or duplicate writer tasks.
- Verify equivalent record preservation and overload behavior across HTTP and
  gRPC with real SDKs and a Collector.

## M8-C — Traces

- Add trace ingestion over HTTP and gRPC with a span-aware domain/IPC contract.
  Preserve resource/scope context, IDs, parentage, timing, events, links, status,
  attributes, and dropped-field counts according to the adopted OTLP schema.
- Select and implement a trace-capable sink or an OTLP forwarding provider;
  deliver a real ingest-to-backend verification before enabling the signal.
- Define per-signal routing, batching, byte budgets, retry/drop accounting,
  and behavior when no compatible sink is configured.
- Document sampling ownership and log/trace correlation. Tail sampling is a
  separate future feature, not implied by receiving spans.

## M8-D — Metrics

- Add metric ingestion over HTTP and gRPC with a metric-aware domain/IPC contract.
- Publish the supported metric-type matrix and preserve temporality,
  monotonicity, start/end timestamps, units, attributes, and exemplars for
  supported types. Specify handling of unsupported types without silent loss.
- Select a compatible metric backend or OTLP forwarding provider and test a
  complete delivery path. Do not convert metric points into log events.
- Define ownership of aggregation or temporality conversion, if required by
  the chosen backend, and test reset/restart behavior.
- Keep customer metric ingestion distinct from Telemetria's own Prometheus
  `/metrics` endpoint; receiving metrics must not register customer series in
  the process's internal monitoring registry.

## Integration and release evidence

Each stage includes SDK/Collector examples, configuration reference updates,
capability diagnostics, and independent benchmarks. Select a supported
client/version matrix and cover both direct SDK and Collector-mediated export.
Backpressure tests must show one saturated signal cannot consume all capacity
or prevent unrelated signals from progressing. Keep secrets and raw telemetry
out of operational logs by default.

Resolve concrete schemas, provider choices, configuration keys/defaults, and
deployment changes in their owning contracts before coding each stage. This
plan sets product scope; it does not preselect infrastructure or dependencies.

## Acceptance criteria

- [ ] Log metadata and correlation work through documented internal and sink interfaces.
- [ ] Existing OTLP/HTTP JSON and Protobuf logs remain covered during model/IPC changes.
- [ ] HTTP and gRPC logs interoperate with the supported SDK/Collector matrix.
- [ ] Trace ingestion reaches a compatible backend with field-preservation evidence.
- [ ] Metric ingestion reaches a compatible backend with documented type/temporality support.
- [ ] Unsupported signals/types and incompatible sink configurations fail explicitly.
- [ ] Per-signal budgets, backpressure, retries, cancellation, and shutdown have resilience tests.
- [ ] Authenticated project/app isolation holds across transports and signals.
- [ ] Diagnostics and documentation expose supported transports, signals, and backend limitations.
- [ ] Benchmarks report throughput, latency, memory, and losses per signal and under mixed load.
- [ ] M8 remains excluded from v1 completion criteria.

## Later candidates

OTLP profiles require a separate schema-maturity and backend evaluation before
scheduling. Durable buffering/replay, tail sampling, arbitrary transformations,
and a unified query API are separate product decisions and are not implied by M8.

Use the [OTLP specification](https://opentelemetry.io/docs/specs/otlp/) and the
OpenTelemetry [logs](https://opentelemetry.io/docs/specs/otel/logs/data-model/),
[traces](https://opentelemetry.io/docs/specs/otel/trace/), and
[metrics](https://opentelemetry.io/docs/specs/otel/metrics/data-model/) specifications
when freezing each stage's contracts.
