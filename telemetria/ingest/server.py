"""Ingest process — HTTP receiver and IPC writer.

Entry point: ``telemetria-ingest``

Endpoints:
    GET  /health              → process health
    POST /v1/logs             → OTLP/HTTP logs (Protobuf or JSON)

On startup:
- Starts the IPCWriter background task connecting to the processor socket.

On shutdown (uvicorn lifespan exit):
- Cancels the writer task and closes the connection gracefully.
"""

from __future__ import annotations

import asyncio
import importlib.metadata
import logging
import signal
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress

import uvicorn
from fastapi import FastAPI

from telemetria.config import CommonSettings, DatabaseSettings, IngestSettings
from telemetria.db.session import make_session_factory
from telemetria.domain.events import Event
from telemetria.ingest.otlp import router as otlp_router
from telemetria.ingest.resolver import AuthTokenResolver
from telemetria.ingest.writer import IPCWriter
from telemetria.logging_config import configure_logging
from telemetria.metrics import (
    INGEST_QUEUE_CAPACITY,
)
from telemetria.metrics.middleware import add_metrics

log = logging.getLogger(__name__)

_PROCESS = "ingest"


def _get_version() -> str:
    try:
        return importlib.metadata.version("telemetria")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(
    settings: IngestSettings | None = None,
    db_settings: DatabaseSettings | None = None,
    common_settings: CommonSettings | None = None,
) -> FastAPI:
    """Create and configure the FastAPI ingest application."""
    if settings is None:
        settings = IngestSettings()
    if db_settings is None:
        db_settings = DatabaseSettings()
    if common_settings is None:
        common_settings = CommonSettings()

    queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=settings.queue_size)

    # Publish static capacity once at startup
    INGEST_QUEUE_CAPACITY.set(settings.queue_size)

    ingest_url = db_settings.ingest_database_url
    factory = make_session_factory(ingest_url if ingest_url else db_settings.database_url)
    resolver = AuthTokenResolver(factory, app_key=common_settings.app_key)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncGenerator[None]:
        writer = IPCWriter(queue, settings.ipc_socket_path)
        task = asyncio.create_task(writer.run(), name="ipc-writer")
        log.info("IPC writer started socket=%s", settings.ipc_socket_path)
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            await writer.close()
            log.info("IPC writer stopped")

    application = FastAPI(
        title="Telemetria Ingest",
        version=_get_version(),
        docs_url=None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.api_docs_enabled else None,
        lifespan=lifespan,
    )

    # Attach to app state so tests can inject alternatives
    application.state.queue = queue
    application.state.resolver = resolver
    application.state.settings = settings
    application.include_router(otlp_router)

    @application.get("/health", tags=["System"])
    async def health() -> dict[str, str]:
        return {"process": _PROCESS, "version": _get_version(), "status": "ok"}

    if settings.api_docs_enabled:
        from fastapi.responses import HTMLResponse
        from scalar_fastapi import get_scalar_api_reference

        @application.get("/", include_in_schema=False)
        async def scalar_docs() -> HTMLResponse:
            return get_scalar_api_reference(
                openapi_url="/openapi.json",
                title="Telemetria Ingest",
            )

    add_metrics(application, process=_PROCESS, enabled=common_settings.metrics_enabled)

    return application


app = create_app()


# ---------------------------------------------------------------------------
# Process entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Process entry point called by the ``telemetria-ingest`` console script."""
    common = CommonSettings()
    configure_logging(common, _PROCESS)

    settings = IngestSettings()
    log.info(
        "Starting process=%s host=%s port=%d ipc_socket=%s",
        _PROCESS,
        settings.ingest_host,
        settings.ingest_port,
        settings.ipc_socket_path,
    )

    def _handle_signal(sig: int, _frame: object) -> None:
        log.info("Received signal=%d, shutting down process=%s", sig, _PROCESS)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    uvicorn.run(
        "telemetria.ingest.server:app",
        host=settings.ingest_host,
        port=settings.ingest_port,
        log_config=None,
        access_log=False,
    )


if __name__ == "__main__":
    main()
