"""IPC writer — background task that drains the ingest queue and writes
frames to the processor's Unix-domain socket.

Ownership model
---------------
One writer task owns the UDS connection.  The HTTP handlers place events into
the bounded ``asyncio.Queue`` via ``put_nowait``; they never await the writer.

Reconnect / backoff
-------------------
On any write or connection failure the writer closes the current connection and
reconnects with capped exponential backoff + ±10% jitter:

    delay = min(BASE * 2^attempt, MAX) * uniform(0.9, 1.1)

Events removed from the queue while the connection is down are lost; this is
consistent with the documented best-effort semantics.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import TYPE_CHECKING

from telemetria.ipc.codec import encode_frame

if TYPE_CHECKING:
    from telemetria.domain.events import Event

log = logging.getLogger(__name__)

_BACKOFF_BASE: float = 0.1
_BACKOFF_MAX: float = 30.0
_JITTER: float = 0.1


def _backoff(attempt: int) -> float:
    delay = min(_BACKOFF_BASE * (2**attempt), _BACKOFF_MAX)
    return float(delay * random.uniform(1 - _JITTER, 1 + _JITTER))


class IPCWriter:
    """Async IPC writer that drains *queue* to *socket_path*.

    Usage::

        writer = IPCWriter(queue, "/var/run/telemetria/ipc.sock")
        task = asyncio.create_task(writer.run())
        ...
        task.cancel()
        await writer.close()
    """

    def __init__(
        self,
        queue: asyncio.Queue[Event],
        socket_path: str,
    ) -> None:
        self._queue = queue
        self._socket_path = socket_path
        self._writer: asyncio.StreamWriter | None = None
        self._running = False

    async def run(self) -> None:
        """Run the writer loop until cancelled."""
        self._running = True
        attempt = 0
        while self._running:
            try:
                await self._connect()
                attempt = 0  # reset backoff on successful connect
                await self._drain()
            except asyncio.CancelledError:
                log.info("IPC writer cancelled")
                raise
            except Exception as exc:
                log.warning("IPC writer error (attempt=%d): %s — reconnecting", attempt, exc)
                await self._close_writer()
                delay = _backoff(attempt)
                attempt += 1
                await asyncio.sleep(delay)

    async def _connect(self) -> None:
        log.debug("IPC writer connecting to %s", self._socket_path)
        _, writer = await asyncio.open_unix_connection(self._socket_path)
        self._writer = writer
        log.info("IPC writer connected to %s", self._socket_path)

    async def _drain(self) -> None:
        """Continuously read from the queue and write frames."""
        assert self._writer is not None
        while True:
            event = await self._queue.get()
            try:
                frame = encode_frame(event)
                self._writer.write(frame)
                await self._writer.drain()
            except Exception:
                # Put the event back — best-effort retry once
                try:
                    self._queue.put_nowait(event)
                except asyncio.QueueFull:
                    log.warning("IPC writer: queue full on retry, event lost id=%s", event.id)
                raise
            finally:
                self._queue.task_done()

    async def _close_writer(self) -> None:
        if self._writer is not None:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None

    async def close(self) -> None:
        """Close the connection gracefully."""
        self._running = False
        await self._close_writer()
