"""BatchProcessor — drains the processor queue, batches events, dispatches to sink.

Flush triggers
--------------
- ``BATCH_MAX_SIZE`` events accumulated
- ``BATCH_MAX_WAIT_SECONDS`` elapsed since the first event in the current batch

Retry / failure policy
----------------------
- ``RetryableSinkError``: exponential backoff with jitter, up to ``SINK_MAX_RETRIES``
- ``PermanentSinkError`` or retry exhaustion: count and discard the batch
- Shutdown: stop accepting new events, drain remaining, close sink

``BatchProcessor`` imports only ``EventSink`` and the generic errors — never
a concrete provider implementation.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import TYPE_CHECKING

from telemetria.domain.events import EventBatch
from telemetria.sinks import EventSink, PermanentSinkError, RetryableSinkError

if TYPE_CHECKING:
    from telemetria.domain.events import Event

log = logging.getLogger(__name__)

_RETRY_BASE: float = 0.25
_RETRY_MAX: float = 10.0
_JITTER: float = 0.1


def _retry_delay(attempt: int, base: float = _RETRY_BASE, cap: float = _RETRY_MAX) -> float:
    delay = min(base * (2**attempt), cap)
    return float(delay * random.uniform(1 - _JITTER, 1 + _JITTER))


class BatchProcessor:
    """Consumes events from *queue* and dispatches batches to *sink*.

    Parameters
    ----------
    queue:
        Source of decoded events (written by the UDS server).
    sink:
        The selected ``EventSink`` provider.
    batch_max_size:
        Flush when this many events accumulate.
    batch_max_wait:
        Flush after this many seconds even if the batch is not full.
    max_retries:
        Maximum retry attempts for ``RetryableSinkError`` before discarding.
    """

    def __init__(
        self,
        queue: asyncio.Queue[Event],
        sink: EventSink,
        batch_max_size: int = 500,
        batch_max_wait: float = 1.0,
        max_retries: int = 3,
    ) -> None:
        self._queue = queue
        self._sink = sink
        self._batch_max_size = batch_max_size
        self._batch_max_wait = batch_max_wait
        self._max_retries = max_retries

        self._batches_sent: int = 0
        self._events_sent: int = 0
        self._events_dropped: int = 0
        self._running = False

    # ------------------------------------------------------------------
    # Public stats
    # ------------------------------------------------------------------

    @property
    def batches_sent(self) -> int:
        return self._batches_sent

    @property
    def events_sent(self) -> int:
        return self._events_sent

    @property
    def events_dropped(self) -> int:
        return self._events_dropped

    # ------------------------------------------------------------------
    # Run loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Run the processor until cancelled or ``stop()`` is called."""
        self._running = True
        pending: list[Event] = []
        deadline: float | None = None

        loop = asyncio.get_running_loop()

        while self._running or pending or not self._queue.empty():
            # How long to wait for the next event
            if deadline is not None:
                timeout = max(0.0, deadline - loop.time())
            else:
                timeout = self._batch_max_wait

            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=timeout)
                pending.append(event)
                self._queue.task_done()

                if deadline is None:
                    deadline = loop.time() + self._batch_max_wait

            except TimeoutError:
                pass  # fall through to flush check
            except asyncio.CancelledError:
                break

            # Flush if size limit reached or deadline passed
            should_flush = bool(pending) and (
                len(pending) >= self._batch_max_size
                or (deadline is not None and loop.time() >= deadline)
            )
            if should_flush:
                await self._flush(pending)
                pending = []
                deadline = None

        # Drain remaining
        if pending:
            await self._flush(pending)

        await self._sink.close()

    async def stop(self) -> None:
        """Signal the processor to drain and stop after the current batch."""
        self._running = False

    # ------------------------------------------------------------------
    # Flush with retry
    # ------------------------------------------------------------------

    async def _flush(self, events: list[Event]) -> None:
        batch = EventBatch(tuple(events))
        for attempt in range(self._max_retries + 1):
            try:
                await self._sink.write(batch)
                self._batches_sent += 1
                self._events_sent += len(batch)
                log.debug(
                    "Sink wrote %d events (batch=%d attempt=%d)",
                    len(batch),
                    self._batches_sent,
                    attempt,
                )
                return
            except RetryableSinkError as exc:
                if attempt >= self._max_retries:
                    log.error(
                        "Sink retry exhausted after %d attempts, discarding %d events: %s",
                        self._max_retries,
                        len(batch),
                        exc,
                    )
                    self._events_dropped += len(batch)
                    return
                delay = _retry_delay(attempt)
                log.warning(
                    "Sink retryable error (attempt=%d, retry in %.2fs): %s",
                    attempt,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)
            except PermanentSinkError as exc:
                log.error("Sink permanent error, discarding %d events: %s", len(batch), exc)
                self._events_dropped += len(batch)
                return
            except Exception as exc:
                log.error("Unexpected sink error, discarding %d events: %s", len(batch), exc)
                self._events_dropped += len(batch)
                return
