"""API process — control plane health endpoint.

Entry point: ``telemetria-api``

Exposes:
    GET /health  →  {"process": "api", "version": "<package version>", "status": "ok"}

Additional routes (admin REST) are deferred to M6b-A.
"""

from __future__ import annotations

import importlib.metadata
import logging
import signal
import sys

import uvicorn
from fastapi import FastAPI

from telemetria.config import APISettings, CommonSettings
from telemetria.logging_config import configure_logging

log = logging.getLogger(__name__)

_PROCESS = "api"


def _get_version() -> str:
    try:
        return importlib.metadata.version("telemetria")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    application = FastAPI(
        title="Telemetria API", version=_get_version(), docs_url=None, redoc_url=None
    )

    @application.get("/health")
    async def health() -> dict[str, str]:
        return {"process": _PROCESS, "version": _get_version(), "status": "ok"}

    return application


app = create_app()


def main() -> None:
    """Process entry point called by the ``telemetria-api`` console script."""
    common = CommonSettings()
    configure_logging(common, _PROCESS)

    settings = APISettings()
    log.info(
        "Starting process=%s host=%s port=%d",
        _PROCESS,
        settings.api_host,
        settings.api_port,
    )

    def _handle_signal(sig: int, _frame: object) -> None:
        log.info("Received signal=%d, shutting down process=%s", sig, _PROCESS)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    uvicorn.run(
        "telemetria.api.server:app",
        host=settings.api_host,
        port=settings.api_port,
        log_config=None,  # use our own logging config
        access_log=False,
    )


if __name__ == "__main__":
    main()
