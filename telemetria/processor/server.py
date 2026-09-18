"""Processor process — IPC reader, batching, and sink dispatch.

Entry point: ``telemetria-processor``

Exposes:
    GET /health  →  {"process": "processor", "version": "<package version>", "status": "ok"}

On startup:
- Binds the UDS server at IPC_SOCKET_PATH
- Starts the BatchProcessor draining the internal event queue
- Serves the health endpoint via uvicorn

On shutdown (SIGTERM/SIGINT):
- Stops accepting new UDS connections
- Drains the batch queue and closes the sink
- Exits cleanly
"""

from __future__ import annotations

import asyncio
import importlib.metadata
import logging
import signal

import uvicorn
from fastapi import FastAPI

from telemetria.config import CommonSettings, ProcessorSettings
from telemetria.domain.events import Event
from telemetria.logging_config import configure_logging
from telemetria.processor.batch import BatchProcessor
from telemetria.processor.uds_server import UDSServer
from telemetria.sinks import get_sink

log = logging.getLogger(__name__)

_PROCESS = "processor"


def _get_version() -> str:
    try:
        return importlib.metadata.version("telemetria")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def create_app() -> FastAPI:
    """Create the FastAPI health application (no UDS/batch — those run in main)."""
    application = FastAPI(
        title="Telemetria Processor",
        version=_get_version(),
        docs_url=None,
        redoc_url=None,
    )

    @application.get("/health")
    async def health() -> dict[str, str]:
        return {"process": _PROCESS, "version": _get_version(), "status": "ok"}

    return application


app = create_app()


def main() -> None:
    """Process entry point called by the ``telemetria-processor`` console script."""
    common = CommonSettings()
    configure_logging(common, _PROCESS)

    settings = ProcessorSettings()
    log.info(
        "Starting process=%s host=%s port=%d ipc_socket=%s sink=%s",
        _PROCESS,
        settings.processor_host,
        settings.processor_port,
        settings.ipc_socket_path,
        settings.sink_provider,
    )

    asyncio.run(_run(settings))


async def _run(settings: ProcessorSettings) -> None:
    # Validate sink provider early — fail fast on misconfiguration
    sink = get_sink(settings.sink_provider)
    log.info("Sink provider: %s", sink.name)

    queue: asyncio.Queue[Event] = asyncio.Queue()

    uds_server = UDSServer(settings.ipc_socket_path, queue)
    processor = BatchProcessor(
        queue,
        sink,
        batch_max_size=settings.batch_max_size,
        batch_max_wait=settings.batch_max_wait_seconds,
        max_retries=settings.sink_max_retries,
    )

    # Start UDS server and batch processor as background tasks
    await uds_server.start()
    proc_task = asyncio.create_task(processor.run(), name="batch-processor")

    # Configure uvicorn to run alongside
    config = uvicorn.Config(
        "telemetria.processor.server:app",
        host=settings.processor_host,
        port=settings.processor_port,
        log_config=None,
        access_log=False,
    )
    server = uvicorn.Server(config)

    loop = asyncio.get_running_loop()

    def _handle_signal() -> None:
        log.info("Shutdown signal received — draining processor")
        server.should_exit = True

    loop.add_signal_handler(signal.SIGTERM, _handle_signal)
    loop.add_signal_handler(signal.SIGINT, _handle_signal)

    try:
        await server.serve()
    finally:
        log.info("Stopping UDS server and draining batch queue")
        await uds_server.stop()
        await processor.stop()
        await proc_task
        log.info("Processor shutdown complete")


if __name__ == "__main__":
    main()
