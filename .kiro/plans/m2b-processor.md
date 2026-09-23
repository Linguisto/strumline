# M2b — Processor and Sink Contract

**Type:** Core  
**Depends on:** M2  
**Unlocks:** M3 and post-v1 M5  
**Goal:** Own the UDS server, decode frames, batch events, and dispatch through a replaceable sink contract with NullSink as the default provider.

## UDS server and reader

The processor owns `IPC_SOCKET_PATH`: it removes a stale socket only after verifying it is a socket, binds/listens, sets restrictive permissions, and accepts the single ingest writer expected in v1. Shutdown closes the server and unlinks its socket. Directory ownership is established by M0.

For each connection, the reader uses the shared `read_frame` and `decode_envelope_body` functions. It discards an incomplete frame on EOF, records malformed/oversized/unknown-version frames, and keeps the server alive. Decoded events enter the processor queue via `put_nowait`; overflow increments a processor-specific drop counter.

## Sink provider contract

```python
class EventSink(ABC):
    name: str

    @abstractmethod
    async def write(self, batch: EventBatch) -> None: ...

    async def close(self) -> None: ...

class RetryableSinkError(Exception): ...
class PermanentSinkError(Exception): ...
```

`strumline.sinks.registry` maps `SINK_PROVIDER` to a provider factory. M2b supplies `NullSink`; M3 registers `LokiSink`. Provider configuration is global for v1. `BatchProcessor` imports only `EventSink` and the generic errors, never Loki or another implementation.

```text
SINK_PROVIDER=null
BATCH_MAX_SIZE=500
BATCH_MAX_WAIT_SECONDS=1.0
SINK_MAX_RETRIES=3
SINK_RETRY_BASE_SECONDS=0.25
SINK_RETRY_MAX_SECONDS=10
```

## Batch and failure behavior

The processor flushes when batch size or wait time is reached. On `RetryableSinkError`, it retries with capped exponential backoff and jitter. On `PermanentSinkError`, or after retry exhaustion, it counts and discards the batch and continues. Shutdown stops intake, drains within a configured grace period, closes the selected sink, and then exits. Retry can duplicate already accepted sink writes; the event ID permits downstream deduplication.

## Metrics introduced with the feature

Define processor queue depth, batches, batch size/latency, sink writes/errors/retries by low-cardinality `sink` and `reason`, and `processor_events_dropped_total{reason}`. Do not reuse the ingest drop counter. M4 later assembles dashboards and sample scraping.

## Acceptance criteria

- [ ] Processor binds and listens on the UDS; ingest connects as the client.
- [ ] Stale-socket cleanup, restrictive permissions, single-writer behavior, shutdown unlink, and reconnect are tested.
- [ ] Split prefix/body reads reconstruct frames; EOF mid-frame discards only the incomplete frame.
- [ ] Unknown versions and oversized/malformed frames are counted and do not crash the process.
- [ ] Queue insertion uses `put_nowait`; overflow increments the processor drop counter.
- [ ] Size and time thresholds flush correct `EventBatch` objects to a spy or NullSink.
- [ ] Registry selection rejects unknown providers with a clear startup error.
- [ ] Retryable, permanent, exhausted-retry, shutdown-drain, and `close()` behavior are tested without provider-specific imports.
- [ ] HTTP → ingest → UDS → processor → NullSink succeeds end to end without Loki.
