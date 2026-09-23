#!/usr/bin/env python3
"""Receipt-to-enqueue benchmark harness for the Strumline ingest receiver.

Measures the two v1 hard targets (see ``.kiro/steering/product.md`` #5):

    * HTTP receipt -> enqueue P99 latency  (target: < 5 ms)
    * sustained ingest throughput          (target: >= 1000 events/sec)

Methodology and rationale live in ``docs/benchmarks.md``. This script is the
executable half: it is deterministic in shape (fixed payload, fixed record
count, explicit warm-up and measurement phases) and self-contained (no Docker,
no PostgreSQL, no network). It exercises the *real* ingest FastAPI app via an
in-process ASGI transport, so it measures the actual receiver code path —
request parse, OTLP decode, admission, ``queue.put_nowait`` — and nothing else.

What is deliberately excluded
-----------------------------
* IPC socket write and the processor: measured separately; not part of the
  receipt-to-enqueue contract.
* The auth-token resolver database round trip: replaced with an in-memory stub
  so the measurement isolates the receiver, not PostgreSQL. Cache-hit behaviour
  in production makes this the steady-state path anyway.

A background drainer empties the queue continuously so admission never blocks
on a full queue; queue-full backpressure is a separate resilience concern with
its own test.

Two phases, two targets
-----------------------
The two v1 targets measure different things and are measured separately:

* **Latency phase** — serial requests (concurrency 1). With no in-flight
  contention, the client-observed time equals the receiver's service time:
  parse + decode + admit. This is what "receipt-to-enqueue P99" means. Running
  it under high concurrency instead would fold event-loop queueing delay into
  the number and measure something else.
* **Throughput phase** — concurrent requests. Saturates the single-process
  event loop to measure sustained admitted events/sec.

Usage
-----
    uv run python benchmarks/receipt_to_enqueue.py \
        --throughput-events 20000 --concurrency 32 \
        --latency-requests 5000 --warmup 2000 \
        --records-per-request 1 --out benchmarks/results

The default ``--out benchmarks/results`` is the committed v1 baseline. Use
``--out benchmarks/runs`` (git-ignored) for ad-hoc runs that should not touch
the baseline.

Exit code is non-zero if either v1 target is missed, so the harness doubles as
a smoke gate.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import platform
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from httpx2 import ASGITransport, AsyncClient

from strumline.config import IngestSettings
from strumline.ingest.resolver import ResolvedToken
from strumline.ingest.server import create_app

# v1 targets (product.md #5)
TARGET_P99_MS = 5.0
TARGET_THROUGHPUT_EVENTS_PER_SEC = 1000.0

_RESOLVED = ResolvedToken(
    token_id="bench-token",
    app_id="00000000-0000-0000-0000-000000000002",
    app_slug="bench-app",
    project_id="00000000-0000-0000-0000-000000000001",
    project_slug="bench-project",
)


def _otlp_payload(records: int) -> dict[str, Any]:
    """A representative OTLP/JSON logs request with *records* log records."""
    log_records = [
        {
            "severityNumber": 9,
            "severityText": "INFO",
            "body": {"stringValue": f"benchmark event {i}"},
            "attributes": [
                {"key": "http.method", "value": {"stringValue": "GET"}},
                {"key": "http.status_code", "value": {"intValue": "200"}},
            ],
        }
        for i in range(records)
    ]
    return {
        "resourceLogs": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "bench"}},
                    ]
                },
                "scopeLogs": [{"logRecords": log_records}],
            }
        ]
    }


@dataclass
class Results:
    timestamp: str
    host: str
    python: str
    records_per_request: int
    concurrency: int
    warmup_requests: int
    latency_requests: int
    latency_duration_seconds: float
    throughput_events: int
    throughput_requests: int
    throughput_duration_seconds: float
    throughput_events_per_sec: float
    throughput_requests_per_sec: float
    latency_ms_p50: float
    latency_ms_p90: float
    latency_ms_p99: float
    latency_ms_max: float
    target_p99_ms: float
    target_throughput_events_per_sec: float
    p99_pass: bool
    throughput_pass: bool

    @property
    def passed(self) -> bool:
        return self.p99_pass and self.throughput_pass


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Nearest-rank percentile. *sorted_values* must be pre-sorted."""
    if not sorted_values:
        return 0.0
    k = max(0, min(len(sorted_values) - 1, int(round(pct / 100.0 * len(sorted_values) + 0.5)) - 1))
    return sorted_values[k]


async def _drain_forever(queue: asyncio.Queue[Any], stop: asyncio.Event) -> None:
    """Continuously empty the queue so admission never hits queue-full."""
    while not stop.is_set():
        try:
            queue.get_nowait()
            queue.task_done()
        except asyncio.QueueEmpty:
            await asyncio.sleep(0.0005)


async def _run(args: argparse.Namespace) -> Results:
    # Large queue + active drainer keeps backpressure out of the measurement.
    settings = IngestSettings(queue_size=max(10_000, args.concurrency * 8))
    app = create_app(settings=settings)
    app.state.resolver = MagicMock(resolve=AsyncMock(return_value=_RESOLVED))
    queue: asyncio.Queue[Any] = app.state.queue

    payload = _otlp_payload(args.records_per_request)
    headers = {"x-strumline-token": "bench", "content-type": "application/json"}

    stop = asyncio.Event()
    drainer = asyncio.create_task(_drain_forever(queue, stop))

    latencies: list[float] = []

    # Do NOT trigger the lifespan (which would start the real IPC writer against
    # a nonexistent socket). ASGITransport without a context manager entry keeps
    # startup/shutdown events unfired; we only need the request path.
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://bench") as client:

        async def one_request(record: bool) -> None:
            t0 = time.perf_counter()
            r = await client.post("/v1/logs", json=payload, headers=headers)
            dt = time.perf_counter() - t0
            if r.status_code != 200:
                raise RuntimeError(f"unexpected status {r.status_code}: {r.text[:200]}")
            if record:
                latencies.append(dt * 1000.0)

        async def worker(count: int, record: bool) -> None:
            for _ in range(count):
                await one_request(record)

        def _split(total: int) -> list[int]:
            base, rem = divmod(total, args.concurrency)
            return [base + (1 if i < rem else 0) for i in range(args.concurrency)]

        # Warm-up (not measured): lets the event loop, codec, and JIT-ish caches settle.
        if args.warmup:
            await asyncio.gather(*(worker(n, False) for n in _split(args.warmup)))

        # ---- Latency phase: serial (concurrency 1) so client time == service time.
        async def timed_request() -> float:
            t0 = time.perf_counter()
            r = await client.post("/v1/logs", json=payload, headers=headers)
            dt = (time.perf_counter() - t0) * 1000.0
            if r.status_code != 200:
                raise RuntimeError(f"unexpected status {r.status_code}: {r.text[:200]}")
            return dt

        for _ in range(args.latency_requests):
            latencies.append(await timed_request())
        lat_duration = sum(latencies) / 1000.0

        # ---- Throughput phase: concurrent to saturate the event loop.
        thr_requests = args.throughput_events // args.records_per_request
        t_start = time.perf_counter()
        await asyncio.gather(*(worker(n, False) for n in _split(thr_requests)))
        thr_duration = time.perf_counter() - t_start

    stop.set()
    drainer.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await drainer

    latencies.sort()
    thr_events = thr_requests * args.records_per_request
    throughput_events = thr_events / thr_duration if thr_duration > 0 else 0.0

    res = Results(
        timestamp=datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
        host=platform.platform(),
        python=platform.python_version(),
        records_per_request=args.records_per_request,
        concurrency=args.concurrency,
        warmup_requests=args.warmup,
        latency_requests=len(latencies),
        latency_duration_seconds=round(lat_duration, 4),
        throughput_events=thr_events,
        throughput_requests=thr_requests,
        throughput_duration_seconds=round(thr_duration, 4),
        throughput_events_per_sec=round(throughput_events, 1),
        throughput_requests_per_sec=round(thr_requests / thr_duration if thr_duration else 0.0, 1),
        latency_ms_p50=round(_percentile(latencies, 50), 4),
        latency_ms_p90=round(_percentile(latencies, 90), 4),
        latency_ms_p99=round(_percentile(latencies, 99), 4),
        latency_ms_max=round(latencies[-1] if latencies else 0.0, 4),
        target_p99_ms=TARGET_P99_MS,
        target_throughput_events_per_sec=TARGET_THROUGHPUT_EVENTS_PER_SEC,
        p99_pass=bool(latencies) and _percentile(latencies, 99) < TARGET_P99_MS,
        throughput_pass=throughput_events >= TARGET_THROUGHPUT_EVENTS_PER_SEC,
    )
    return res


def _write_artifacts(res: Results, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "receipt_to_enqueue.json").write_text(json.dumps(asdict(res), indent=2) + "\n")

    throughput_row = (
        f"| **Throughput** | **{res.throughput_events_per_sec:,.1f} events/sec** "
        f"({res.throughput_requests_per_sec:,.1f} req/sec) |"
    )
    p99_verdict = "PASS" if res.p99_pass else "FAIL"
    thr_verdict = "PASS" if res.throughput_pass else "FAIL"
    p99_row = (
        f"| Receipt-to-enqueue P99 | < {res.target_p99_ms:.1f} ms | "
        f"{res.latency_ms_p99:.3f} ms | {p99_verdict} |"
    )
    thr_row = (
        f"| Sustained throughput | >= {res.target_throughput_events_per_sec:,.0f} events/sec | "
        f"{res.throughput_events_per_sec:,.1f} events/sec | {thr_verdict} |"
    )

    md = f"""# Receipt-to-enqueue benchmark result

_Generated by `benchmarks/receipt_to_enqueue.py`. Methodology: `docs/benchmarks.md`._

| Field | Value |
|---|---|
| Timestamp (UTC) | `{res.timestamp}` |
| Host | `{res.host}` |
| Python | {res.python} |
| Records / request | {res.records_per_request} |
| Warm-up requests | {res.warmup_requests:,} |

## Latency phase (serial, concurrency 1 — service time)

| Field | Value |
|---|---|
| Requests measured | {res.latency_requests:,} |
| Duration | {res.latency_duration_seconds:.3f} s |
| Latency P50 | {res.latency_ms_p50:.3f} ms |
| Latency P90 | {res.latency_ms_p90:.3f} ms |
| **Latency P99** | **{res.latency_ms_p99:.3f} ms** |
| Latency max | {res.latency_ms_max:.3f} ms |

## Throughput phase (concurrency {res.concurrency} — saturated)

| Field | Value |
|---|---|
| Events measured | {res.throughput_events:,} |
| Requests measured | {res.throughput_requests:,} |
| Duration | {res.throughput_duration_seconds:.3f} s |
{throughput_row}

## v1 targets

| Target | Threshold | Measured | Result |
|---|---|---|---|
{p99_row}
{thr_row}

Overall: **{"PASS" if res.passed else "FAIL"}**
"""
    (out_dir / "receipt_to_enqueue.md").write_text(md)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--throughput-events", type=int, default=20_000, help="records for the throughput phase"
    )
    p.add_argument(
        "--latency-requests", type=int, default=5_000, help="serial requests for the latency phase"
    )
    p.add_argument("--records-per-request", type=int, default=1, help="records per POST")
    p.add_argument(
        "--concurrency", type=int, default=32, help="concurrent requests in the throughput phase"
    )
    p.add_argument("--warmup", type=int, default=2_000, help="unmeasured warm-up requests")
    p.add_argument("--out", type=Path, default=Path("benchmarks/results"), help="artifact dir")
    p.add_argument("--no-write", action="store_true", help="print only, do not write artifacts")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.throughput_events < args.records_per_request:
        print("error: --throughput-events must be >= --records-per-request", file=sys.stderr)
        return 2

    res = asyncio.run(_run(args))

    print(json.dumps(asdict(res), indent=2))
    print(
        f"\nthroughput={res.throughput_events_per_sec:,.1f} ev/s "
        f"(target >= {res.target_throughput_events_per_sec:,.0f}) "
        f"{'PASS' if res.throughput_pass else 'FAIL'}",
        file=sys.stderr,
    )
    print(
        f"p99={res.latency_ms_p99:.3f} ms "
        f"(target < {res.target_p99_ms:.1f}) "
        f"{'PASS' if res.p99_pass else 'FAIL'}",
        file=sys.stderr,
    )

    if not args.no_write:
        _write_artifacts(res, args.out)
        print(f"artifacts written to {args.out}/", file=sys.stderr)

    return 0 if res.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
