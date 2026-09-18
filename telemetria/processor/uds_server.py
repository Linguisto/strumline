"""UDS server for the processor process.

The processor owns ``IPC_SOCKET_PATH``:
- Removes a stale socket only after verifying it is a socket file.
- Binds with ``chmod 0o600`` (owner read/write only).
- Accepts the single ingest writer expected in v1.
- Decoded events enter the processor queue via ``put_nowait``.
- Overflow increments the processor drop counter (logged).
- On shutdown: stops accepting, closes connection, unlinks socket.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import stat
from pathlib import Path
from typing import TYPE_CHECKING

from telemetria.ipc.codec import (
    IPC_MAX_FRAME_BYTES,
    EmptyFrameError,
    FrameTooLargeError,
    IPCError,
    MalformedEnvelopeError,
    TruncatedFrameError,
    UnknownVersionError,
    decode_envelope_body,
    read_frame,
)

if TYPE_CHECKING:
    from telemetria.domain.events import Event

log = logging.getLogger(__name__)


def _remove_stale_socket(path: str) -> None:
    """Remove *path* only if it is a socket file. Raises if it is not."""
    try:
        mode = os.stat(path).st_mode
    except FileNotFoundError:
        return
    if not stat.S_ISSOCK(mode):
        raise RuntimeError(f"IPC path {path!r} exists and is not a socket — refusing to remove it")
    os.unlink(path)
    log.info("Removed stale socket %s", path)


class UDSServer:
    """Unix-domain socket server that feeds events into *queue*.

    Parameters
    ----------
    socket_path:
        Path where the socket will be created.
    queue:
        Bounded asyncio queue. Events are inserted via ``put_nowait``.
    max_frame_bytes:
        Maximum frame body size; passed to ``read_frame``.
    """

    def __init__(
        self,
        socket_path: str,
        queue: asyncio.Queue[Event],
        max_frame_bytes: int = IPC_MAX_FRAME_BYTES,
    ) -> None:
        self._path = socket_path
        self._queue = queue
        self._max_frame_bytes = max_frame_bytes
        self._server: asyncio.Server | None = None
        self._drops: int = 0

    @property
    def drops(self) -> int:
        return self._drops

    async def start(self) -> None:
        """Bind and start listening. Removes a stale socket if present."""
        _remove_stale_socket(self._path)
        # Ensure parent directory exists
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)

        self._server = await asyncio.start_unix_server(
            self._handle_connection,
            path=self._path,
        )
        # Restrict access: only the owning process can read/write
        os.chmod(self._path, 0o600)
        log.info("UDS server listening on %s", self._path)

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        peer = writer.get_extra_info("peername") or "<unknown>"
        log.info("IPC connection accepted from %s", peer)
        try:
            await self._read_loop(reader)
        except asyncio.IncompleteReadError:
            log.info("IPC connection closed (EOF) from %s", peer)
        except (FrameTooLargeError, EmptyFrameError) as exc:
            log.error("IPC frame error (closing connection): %s", exc)
        except (UnknownVersionError, MalformedEnvelopeError) as exc:
            # Non-fatal for the server — log and keep listening
            log.warning("IPC frame decode error (connection kept): %s", exc)
        except Exception as exc:
            log.error("Unexpected IPC error: %s", exc)
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    async def _read_loop(self, reader: asyncio.StreamReader) -> None:
        while True:
            try:
                body = await read_frame(reader, self._max_frame_bytes)
            except TruncatedFrameError as exc:
                log.warning("IPC truncated frame discarded: %s", exc)
                continue
            except (UnknownVersionError, MalformedEnvelopeError) as exc:
                log.warning("IPC malformed frame discarded: %s", exc)
                continue

            try:
                event = decode_envelope_body(body)
            except IPCError as exc:
                log.warning("IPC decode error: %s", exc)
                continue

            try:
                self._queue.put_nowait(event)
            except asyncio.QueueFull:
                self._drops += 1
                log.warning(
                    "Processor queue full — event dropped id=%s (total drops=%d)",
                    event.id,
                    self._drops,
                )

    async def stop(self) -> None:
        """Stop accepting connections and unlink the socket."""
        if self._server is not None:
            self._server.close()
            with contextlib.suppress(Exception):
                await self._server.wait_closed()
            self._server = None

        with contextlib.suppress(FileNotFoundError):
            os.unlink(self._path)
            log.info("UDS server socket unlinked: %s", self._path)
