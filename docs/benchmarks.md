# Benchmarks

This document is the methodology half of Strumline's performance evidence. The
executable half is `benchmarks/receipt_to_enqueue.py`. Anyone can reproduce the
baseline from this document without reading the harness source.

## What is measured

The v1 success criteria (`.kiro/steering/product.md` #5) set two hard targets:

| Target | Threshold |
|---|---|
| HTTP receipt → enqueue latency (P99) | < 5 ms |
| Sustained ingest throughput | ≥ 1,000 events/sec |

These measure the **ingest receiver** only: HTTP request parse → OTLP decode →
admission → `queue.put_nowait`. They stop at the in-process queue. IPC socket
throughput and processor decode/batch throughput are separate results (see
"Scope and exclusions"); end-to-end Loki latency is environment-dependent and
reported separately when a Loki instance is available.

## Why two phases

Latency and throughput are different questions and are measured separately:

- **Latency phase — serial (concurrency 1).** With no other request in flight,
  the client-observed round-trip time over the in-process ASGI transport equals
  the receiver's service time (there is no network and no event-loop queueing).
  This is the honest "receipt-to-enqueue" number. Measuring latency while also
  driving maximum concurrency would fold event-loop scheduling delay into the
  percentile and answer a different question ("latency under saturation"), not
  the service-time target.
- **Throughput phase — concurrent.** Many in-flight requests saturate the
  single-process event loop to measure sustained admitted events/sec.

Reporting a single "P99 under max concurrency" number conflates the two and is
the most common way this measurement is done wrong.

## Test conditions

- **Harness:** `benchmarks/receipt_to_enqueue.py`, driving the real
  `strumline.ingest.server.create_app()` FastAPI app over `httpx2`
  `ASGITransport` (in-process, no sockets, no Docker, no PostgreSQL).
- **Auth resolver:** replaced with an in-memory stub returning a fixed
  `ResolvedToken`. In production the resolver is an in-memory cache hit on the
  steady-state path, so this isolates the receiver rather than PostgreSQL.
- **Queue drain:** a background task empties `app.state.queue` continuously so
  admission never blocks on a full queue. Queue-full backpressure is a distinct
  resilience concern covered by `tests/test_resilience.py` and
  `tests/test_metrics.py`, not a throughput measurement.
- **Payload:** one OTLP/JSON `ExportLogsServiceRequest` per POST, one log record
  per request by default (`--records-per-request` to change), each record with a
  string body and two attributes plus one resource attribute — representative of
  a small structured application event.
- **Warm-up:** 2,000 unmeasured requests before either phase, to settle the
  event loop and import/codec caches.
- **Percentiles:** nearest-rank on the sorted per-request latency sample.
- **Concurrency = 1 core:** the target is stated per documented core. Python's
  GIL and the single asyncio event loop mean one ingest process is effectively
  one core for this path; the harness runs one event loop in one process.

State these in any published run: hardware/CPU, OS, Python version, payload
shape, records per request, concurrency, warm-up count, run duration, and
repetition count. The harness records host, Python version, timestamp, and all
counts into the results artifact automatically.

## Running it

The simplest path is the Make target, which runs the harness in the dev
container and writes to the untracked `benchmarks/runs/` scratch directory so
the committed baseline stays stable:

```bash
make benchmarks                 # writes benchmarks/runs/ (safe default)
make benchmarks DC_EXEC="uv run"  # run locally instead of in the container
```

Run the harness directly for custom parameters (requires a local `uv`
environment, or prefix with `docker compose run --rm strumline-cli`):

```bash
# Defaults: 5,000 serial latency requests, 20,000 concurrent throughput events,
# concurrency 32, 2,000 warm-up requests.
uv run python benchmarks/receipt_to_enqueue.py --out benchmarks/runs

# Custom run
uv run python benchmarks/receipt_to_enqueue.py \
    --latency-requests 5000 \
    --throughput-events 20000 \
    --concurrency 32 \
    --warmup 2000 \
    --records-per-request 1 \
    --out benchmarks/runs

# Print only, do not write artifacts (use this for validation runs)
uv run python benchmarks/receipt_to_enqueue.py --no-write
```

The process exits `0` only when **both** targets pass, so the harness doubles as
a smoke gate. It exits `1` when a target is missed and `2` on invalid arguments.

Only refresh the committed `benchmarks/results/` baseline deliberately, when you
intend to publish new numbers:

```bash
make benchmarks.baseline        # writes benchmarks/results/ (the committed baseline)
```

`benchmarks/runs/` is git-ignored. Only overwrite `benchmarks/results/` (the
default) when you intend to update the published baseline.

## Output artifacts

Each run writes two files to `--out` (default `benchmarks/results/`):

- `receipt_to_enqueue.json` — machine-readable full result (all counts,
  durations, percentiles, target thresholds, pass flags).
- `receipt_to_enqueue.md` — human-readable summary table with the pass/fail
  verdict per target.

The committed `benchmarks/results/` files are the published v1 baseline. Re-run
on your own hardware to reproduce; numbers scale with CPU but the harness shape
and targets are fixed. Ad-hoc runs should target `benchmarks/runs/` (ignored)
so the baseline only changes on a deliberate update.

The published 2026-09-23 baseline is one repetition on a 14-core Apple M4 Pro
(10 performance and 4 efficiency cores), 48 GB RAM, macOS 26.5.2 arm64, and
Python 3.14.6. It covers the OTLP/HTTP JSON request path only. Protobuf and gzip
have interoperability coverage in the test suite, but the published latency and
throughput numbers must not be attributed to those encodings. Run multiple
repetitions and report their spread before using the baseline for hardware or
release-to-release comparisons.

## Scope and exclusions

Measured here:

- HTTP receipt → enqueue latency (P99) — latency phase.
- Sustained ingest admission throughput — throughput phase.

Measured elsewhere / out of scope for this harness:

- **IPC write throughput** — the ingest→processor socket path. Exercised by
  `tests/test_ipc_writer.py` and `tests/test_resilience.py`.
- **Processor decode/batch throughput with NullSink** — the processor side.
  Exercised by `tests/test_processor.py`.
- **End-to-end Loki latency** — environment-dependent; measure against the
  bundled development Loki or an external instance, reported as a separate result.
- **Overload loss paths** — ingest queue full, IPC/write failure, processor
  queue full, permanent sink failure, retry exhaustion. Each has a distinct
  bounded-cardinality counter and a resilience/metrics test; see
  `docs/observability.md` and `docs/sinks.md`.
