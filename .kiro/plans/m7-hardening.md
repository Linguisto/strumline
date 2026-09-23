# M7 — Hardening and Documentation

**Type:** Release gate  
**Depends on:** M3, M4, M6, M6b  
**Unlocks:** v1.0  
**Goal:** Produce repeatable performance evidence, freeze public contracts, and document secure operation and extension points.

## Protocol and contract documentation

M2 already enforces frame limits and version handling. M7 documents and tests the frozen behavior; it does not postpone safety work:

- `docs/ipc-protocol.md`: byte layout, uint32 endianness, maximum body length, JSON schema, `v` semantics, EOF/truncation, unknown-version behavior, and canonical UTC encoding.
- language-neutral conformance fixtures for minimum/maximum frames, split reads, malformed/zero/truncated bodies, and unknown versions.
- `docs/api/otlp-logs.md`: OTLP/HTTP Protobuf/JSON/gzip interoperability, typed field preservation, normalized-size limits, partial rejection, and atomic retryable queue admission. Include OTLP in performance and resilience runs for both supported encodings.
- `docs/sinks.md`: `EventSink`, registry, error taxonomy, lifecycle, retry ownership, metrics, and a provider implementation checklist.
- BYO Prometheus/Grafana instructions and optional Loki integration.
- Go/Rust ingest replacement guide based only on public HTTP/IPC contracts.

## Performance and resilience evidence

Load tests state hardware/CPU limits, software versions, payload distribution, batch sizes, concurrency, warm-up, run duration, repetitions, and percentile calculation. Results distinguish:

- HTTP receipt → enqueue latency
- ingest IPC throughput
- processor decode/batch throughput with NullSink
- end-to-end Loki latency as a separate environment-dependent result
- overload loss by ingest queue, IPC/write failure, processor queue, permanent sink failure, and retry exhaustion

The v1 target remains at least 1,000 events/sec on one documented core with receipt-to-enqueue P99 below 5 ms. CI smoke tests verify behavior; published benchmark runs establish the baseline.

Failure scenarios cover PostgreSQL/DSN-cache behavior, processor restart, stale UDS, malformed frames, queue saturation, provider outage, 429/5xx retry, permanent 4xx, and graceful shutdown deadlines.

## Security and operations

- document admin API key generation/rotation and management-network exposure
- verify 256-bit DSN key entropy and the revocation cache window
- verify least-privilege read-only ingest database grants
- document payload/frame limits, decompression policy, metrics exposure, and socket-directory permissions
- scan images/dependencies and pin sample infrastructure versions
- ensure logs redact secrets and avoid raw telemetry by default
- document UTC-only storage and presentation-time localization

## Boundary and release checks

Import-linter has run since package introduction; M7 makes the complete rule set a release gate. Processor may depend on sink abstractions/registry but not Loki directly. CLI/API may depend on control services but not the data plane.

Release artifacts include CHANGELOG, CONTRIBUTING guide, migration/rollback notes, configuration reference, Compose profile matrix, and recovery limitations caused by best-effort delivery.

## Acceptance criteria

- [x] IPC and ingest docs are sufficient to implement a compatible client/ingest process without reading Python source.
- [x] Protocol conformance fixtures pass against the Python implementation.
- [x] Sink extension documentation produces a test provider without processor changes.
- [x] Benchmark results are repeatable from the documented methodology and meet v1 targets.
- [x] Each loss path has a distinct bounded-cardinality counter and resilience test.
- [x] Security checks cover admin API, DSNs, database grants, payloads, metrics, UDS permissions, dependencies, and redaction.
- [x] BYO observability and optional Compose profiles are documented and tested.
- [x] UTC storage and API serialization invariants have database, IPC, CLI, REST, and Loki tests.
- [x] M0, M1, M2, M2b, M3, M4, M6, M6b, and M7 are complete; M5 remains post-v1.
