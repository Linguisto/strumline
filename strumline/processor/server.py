"""Processor process — IPC reader, batching, and sink dispatch.

Entry point: ``strumline-processor``

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

from strumline.config import CommonSettings, ProcessorSettings
from strumline.domain.events import Event
from strumline.logging_config import configure_logging
from strumline.metrics import PROCESSOR_QUEUE_CAPACITY
from strumline.metrics.middleware import add_metrics
from strumline.processor.batch import BatchProcessor
from strumline.processor.uds_server import UDSServer
from strumline.sinks import get_sink

log = logging.getLogger(__name__)

_PROCESS = "processor"


def _get_version() -> str:
    try:
        return importlib.metadata.version("strumline")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def create_app(
    settings: CommonSettings | None = None,
    proc_settings: ProcessorSettings | None = None,
) -> FastAPI:
    """Create the FastAPI health application (no UDS/batch — those run in main)."""
    if settings is None:
        settings = CommonSettings()
    if proc_settings is None:
        proc_settings = ProcessorSettings()

    application = FastAPI(
        title="Strumline Processor",
        version=_get_version(),
        docs_url=None,
        redoc_url=None,
        openapi_url="/openapi.json" if proc_settings.api_docs_enabled else None,
    )

    @application.get("/health", tags=["System"])
    async def health() -> dict[str, str]:
        return {"process": _PROCESS, "version": _get_version(), "status": "ok"}

    if proc_settings.api_docs_enabled:
        from fastapi.responses import HTMLResponse
        from scalar_fastapi import get_scalar_api_reference

        @application.get("/", include_in_schema=False)
        async def scalar_docs() -> HTMLResponse:
            return get_scalar_api_reference(
                openapi_url="/openapi.json",
                title="Strumline Processor",
            )

    add_metrics(application, process=_PROCESS, enabled=settings.metrics_enabled)
    return application


app = create_app()


def main() -> None:
    """Process entry point called by the ``strumline-processor`` console script."""
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

    queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=settings.processor_queue_size)
    PROCESSOR_QUEUE_CAPACITY.set(settings.processor_queue_size)

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
        "strumline.processor.server:app",
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
