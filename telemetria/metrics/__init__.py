"""Shared Prometheus metric definitions for all Telemetria processes.

Each process imports only the families it emits. Metrics are module-level
singletons registered in the default CollectorRegistry; each process is a
separate Python process so there is no cross-process registry collision.

Naming convention
-----------------
- ``telemetria_http_requests_total``          — HTTP counters
- ``telemetria_http_request_duration_seconds`` — HTTP latency
- ``telemetria_ingest_*``                     — ingest-process metrics
- ``telemetria_processor_*``                  — processor-process metrics
- ``telemetria_ipc_*``                        — IPC framing metrics

Label cardinality rules (enforced by convention, tested in test_metrics.py)
---------------------------------------------------------------------------
Allowed labels: ``process``, ``method``, ``route``, ``status_class``,
``reason``, ``sink``.

Forbidden in labels: raw paths, auth token keys, event IDs, project/app names,
message text, payload values.

``/metrics`` is excluded from HTTP instrumentation to avoid recursion.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# ---------------------------------------------------------------------------
# HTTP instrumentation (all three processes)
# ---------------------------------------------------------------------------

HTTP_REQUESTS_TOTAL = Counter(
    "telemetria_http_requests_total",
    "Total HTTP requests handled.",
    ["process", "method", "route", "status_class"],
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "telemetria_http_request_duration_seconds",
    "HTTP request duration in seconds.",
    ["process", "method", "route"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

# ---------------------------------------------------------------------------
# Ingest process
# ---------------------------------------------------------------------------

INGEST_EVENTS_ACCEPTED_TOTAL = Counter(
    "telemetria_ingest_events_accepted_total",
    "Total events accepted and enqueued by the ingest process.",
)

INGEST_EVENTS_DROPPED_TOTAL = Counter(
    "telemetria_ingest_events_dropped_total",
    "Total events dropped by the ingest process.",
    ["reason"],
    # reason values: "queue_full", "validation_error", "auth_error"
)

INGEST_QUEUE_DEPTH = Gauge(
    "telemetria_ingest_queue_depth",
    "Current number of events waiting in the ingest queue.",
)

INGEST_QUEUE_CAPACITY = Gauge(
    "telemetria_ingest_queue_capacity",
    "Maximum capacity of the ingest queue (QUEUE_SIZE).",
)

INGEST_AUTH_TOKEN_CACHE_HITS_TOTAL = Counter(
    "telemetria_ingest_auth_token_cache_hits_total",
    "Total auth token resolver cache hits.",
)

INGEST_AUTH_TOKEN_CACHE_MISSES_TOTAL = Counter(
    "telemetria_ingest_auth_token_cache_misses_total",
    "Total auth token resolver cache misses (database queries).",
)

INGEST_IPC_RECONNECTS_TOTAL = Counter(
    "telemetria_ingest_ipc_reconnects_total",
    "Total IPC writer reconnect attempts.",
)

# ---------------------------------------------------------------------------
# Processor process
# ---------------------------------------------------------------------------

PROCESSOR_QUEUE_DEPTH = Gauge(
    "telemetria_processor_queue_depth",
    "Current number of events waiting in the processor queue.",
)

PROCESSOR_QUEUE_CAPACITY = Gauge(
    "telemetria_processor_queue_capacity",
    "Maximum capacity of the processor queue.",
)

PROCESSOR_EVENTS_DROPPED_TOTAL = Counter(
    "telemetria_processor_events_dropped_total",
    "Total events dropped by the processor (permanent failure, retry exhaustion, queue overflow).",
    ["reason"],
    # reason values: "queue_full", "sink_permanent", "sink_retries_exhausted"
)

PROCESSOR_BATCHES_TOTAL = Counter(
    "telemetria_processor_batches_total",
    "Total batches successfully written to the sink.",
    ["sink"],
)

PROCESSOR_BATCH_SIZE = Histogram(
    "telemetria_processor_batch_size",
    "Number of events per batch dispatched to the sink.",
    ["sink"],
    buckets=(1, 5, 10, 25, 50, 100, 200, 500),
)

PROCESSOR_BATCH_DURATION_SECONDS = Histogram(
    "telemetria_processor_batch_duration_seconds",
    "Time spent writing one batch to the sink, including retries.",
    ["sink"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

PROCESSOR_SINK_WRITES_TOTAL = Counter(
    "telemetria_processor_sink_writes_total",
    "Total sink write attempts (including retries).",
    ["sink", "outcome"],
    # outcome values: "success", "retryable", "permanent"
)

# ---------------------------------------------------------------------------
# IPC framing (shared between ingest writer and processor reader)
# ---------------------------------------------------------------------------

IPC_FRAMES_TOTAL = Counter(
    "telemetria_ipc_frames_total",
    "Total IPC frames processed.",
    ["direction", "outcome"],
    # direction: "sent" | "received"
    # outcome:   "ok" | "error"
)

IPC_PROTOCOL_ERRORS_TOTAL = Counter(
    "telemetria_ipc_protocol_errors_total",
    "Total IPC protocol errors (malformed, unknown version, oversized, truncated).",
    ["error_type"],
    # error_type: "malformed" | "unknown_version" | "too_large" | "truncated" | "empty"
)
