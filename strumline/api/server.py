"""API process — control plane health endpoint + optional admin REST API.

Entry point: ``strumline-api``

Exposes:
    GET /health  →  {"process": "api", "version": "<package version>", "status": "ok"}

When ``ADMIN_API_ENABLED=true``:
    /admin/v1/*   →  CRUD for projects, apps, and auth tokens
    /docs         →  OpenAPI interactive docs
    /openapi.json →  OpenAPI schema
"""

from __future__ import annotations

import importlib.metadata
import logging
import signal
import sys

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from strumline.config import APISettings, CommonSettings
from strumline.logging_config import configure_logging
from strumline.metrics.middleware import add_metrics

log = logging.getLogger(__name__)

_PROCESS = "api"


def _get_version() -> str:
    try:
        return importlib.metadata.version("strumline")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def create_app(
    settings: CommonSettings | None = None,
    api_settings: APISettings | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application."""
    if settings is None:
        settings = CommonSettings()
    if api_settings is None:
        api_settings = APISettings()

    # Docs at / when API_DOCS_ENABLED=true (health+metrics) or ADMIN_API_ENABLED=true (all routes)
    show_docs = api_settings.api_docs_enabled or api_settings.admin_api_enabled
    openapi_url = "/openapi.json" if show_docs else None

    application = FastAPI(
        title="Strumline API",
        version=_get_version(),
        docs_url=None,  # replaced by Scalar at /
        redoc_url=None,
        openapi_url=openapi_url,
    )

    @application.get("/health", tags=["System"])
    async def health() -> dict[str, str]:
        return {"process": _PROCESS, "version": _get_version(), "status": "ok"}

    if show_docs:
        from scalar_fastapi import get_scalar_api_reference

        @application.get("/", include_in_schema=False)
        async def scalar_docs() -> HTMLResponse:
            return get_scalar_api_reference(
                openapi_url="/openapi.json",
                title="Strumline API",
            )

    if api_settings.admin_api_enabled:
        from strumline.api.admin import make_admin_router
        from strumline.config import DatabaseSettings
        from strumline.db.session import make_session_factory

        db = DatabaseSettings()
        factory = make_session_factory(db.database_url)
        admin_router = make_admin_router(
            session_factory=factory,
            api_key=api_settings.admin_api_key,
            app_key=settings.app_key,
        )
        application.include_router(admin_router)
        log.info("Admin API enabled at /admin/v1 — docs at /")

    add_metrics(application, process=_PROCESS, enabled=settings.metrics_enabled)
    return application


app = create_app()


def main() -> None:
    """Process entry point called by the ``strumline-api`` console script."""
    common = CommonSettings()
    configure_logging(common, _PROCESS)

    settings = APISettings()
    log.info(
        "Starting process=%s host=%s port=%d admin=%s",
        _PROCESS,
        settings.api_host,
        settings.api_port,
        settings.admin_api_enabled,
    )

    def _handle_signal(sig: int, _frame: object) -> None:
        log.info("Received signal=%d, shutting down process=%s", sig, _PROCESS)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    uvicorn.run(
        "strumline.api.server:app",
        host=settings.api_host,
        port=settings.api_port,
        log_config=None,  # use our own logging config
        access_log=False,
    )


if __name__ == "__main__":
    main()
