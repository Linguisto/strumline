"""Ingest process — HTTP receiver and IPC writer.

Entry point: ``telemetria-ingest``

Endpoints:
    GET  /health              → process health
    POST /v1/ingest           → single event
    POST /v1/ingest/batch     → batch of events

On startup:
- Starts the IPCWriter background task connecting to the processor socket.

On shutdown (uvicorn lifespan exit):
- Cancels the writer task and closes the connection gracefully.
"""

from __future__ import annotations

import asyncio
import importlib.metadata
import json
import logging
import signal
import sys
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from typing import Any

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from telemetria.config import CommonSettings, DatabaseSettings, IngestSettings
from telemetria.db.session import make_session_factory
from telemetria.domain.events import Event
from telemetria.ingest.resolver import AuthTokenResolver, AuthTokenResolverError
from telemetria.ingest.writer import IPCWriter
from telemetria.logging_config import configure_logging
from telemetria.metrics import (
    INGEST_AUTH_TOKEN_CACHE_HITS_TOTAL,
    INGEST_AUTH_TOKEN_CACHE_MISSES_TOTAL,
    INGEST_EVENTS_ACCEPTED_TOTAL,
    INGEST_EVENTS_DROPPED_TOTAL,
    INGEST_QUEUE_CAPACITY,
    INGEST_QUEUE_DEPTH,
)
from telemetria.metrics.middleware import add_metrics

log = logging.getLogger(__name__)

_PROCESS = "ingest"
_MAX_NESTING = 10


def _get_version() -> str:
    try:
        return importlib.metadata.version("telemetria")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class EventRequest(BaseModel):
    timestamp: str | float | None = Field(
        default=None,
        description=(
            "Event timestamp. ISO 8601 with Z or UTC offset (e.g. '2026-09-18T17:00:00Z'), "
            "or Unix timestamp in seconds (e.g. 1726668000 or 1726668000.123). "
            "Missing, naive, or malformed values fall back to server receipt time."
        ),
    )
    level: str = Field(
        default="info",
        json_schema_extra={"enum": ["debug", "info", "warn", "error", "fatal"]},
    )
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)


class BatchRequest(BaseModel):
    events: list[EventRequest]


class IngestResponse(BaseModel):
    enqueued: int
    dropped: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _check_nesting(obj: Any, depth: int = 0) -> None:
    if depth > _MAX_NESTING:
        raise ValueError(f"Payload nesting exceeds limit ({_MAX_NESTING})")
    if isinstance(obj, dict):
        for v in obj.values():
            _check_nesting(v, depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            _check_nesting(v, depth + 1)


def _parse_timestamp(value: str | float | None, received_at: datetime) -> datetime:
    if value is None:
        return received_at
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=UTC)
        except ValueError, OverflowError, OSError:
            return received_at
    if not value:
        return received_at
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return received_at
        return dt.astimezone(UTC)
    except ValueError, OverflowError:
        return received_at


def _build_event(
    req: EventRequest,
    received_at: datetime,
    project_id: str,
    project_slug: str,
    app_id: str,
    app_slug: str,
) -> Event:
    _check_nesting(req.payload)
    return Event(
        id=uuid.uuid4(),
        project_id=uuid.UUID(project_id),
        project_slug=project_slug,
        app_id=uuid.UUID(app_id),
        app_slug=app_slug,
        received_at=received_at,
        timestamp=_parse_timestamp(req.timestamp, received_at),
        level=req.level.lower(),
        message=req.message,
        payload=req.payload,
    )


def _check_content_type(request: Request) -> None:
    ct = request.headers.get("content-type", "")
    if not ct.startswith("application/json"):
        raise HTTPException(status_code=415, detail="Content-Type must be application/json")


async def _read_body(request: Request, max_bytes: int) -> bytes:
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"Request body exceeds MAX_PAYLOAD_BYTES ({max_bytes})",
            )
    return body


def _parse_json(body: bytes, model: type[BaseModel]) -> Any:
    try:
        data = json.loads(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc
    try:
        return model.model_validate(data)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def _resolve_token(resolver: AuthTokenResolver, key: str) -> Any:
    try:
        result = await resolver.resolve(key)
        INGEST_AUTH_TOKEN_CACHE_HITS_TOTAL.inc()
        return result
    except AuthTokenResolverError:
        INGEST_AUTH_TOKEN_CACHE_MISSES_TOTAL.inc()
        raise HTTPException(status_code=401, detail="Invalid or revoked auth token") from None


def _enqueue(queue: asyncio.Queue[Event], event: Event) -> int:
    try:
        queue.put_nowait(event)
        INGEST_EVENTS_ACCEPTED_TOTAL.inc()
        INGEST_QUEUE_DEPTH.set(queue.qsize())
        return 0
    except asyncio.QueueFull:
        log.warning("ingest queue full — event dropped id=%s", event.id)
        INGEST_EVENTS_DROPPED_TOTAL.labels(reason="queue_full").inc()
        return 1


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

    @application.post(
        "/v1/ingest",
        status_code=202,
        tags=["Ingest"],
        summary="Ingest a single event",
        response_model=IngestResponse,
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/EventRequest"},
                        "example": {
                            "timestamp": "2026-09-18T17:00:00Z",
                            "level": "info",
                            "message": "Payment processed",
                            "payload": {"order_id": "abc123", "amount": 99.99},
                        },
                    }
                },
            }
        },
    )
    async def ingest_single(
        request: Request,
        x_telemetria_token: str = Header(..., alias="x-telemetria-token"),
    ) -> IngestResponse:
        _check_content_type(request)
        body = await _read_body(request, application.state.settings.max_payload_bytes)
        event_req = _parse_json(body, EventRequest)
        resolved = await _resolve_token(application.state.resolver, x_telemetria_token)
        received_at = datetime.now(tz=UTC)
        try:
            event = _build_event(
                event_req,
                received_at,
                resolved.project_id,
                resolved.project_slug,
                resolved.app_id,
                resolved.app_slug,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        dropped = _enqueue(application.state.queue, event)
        return IngestResponse(enqueued=1 - dropped, dropped=dropped)

    @application.post(
        "/v1/ingest/batch",
        status_code=202,
        tags=["Ingest"],
        summary="Ingest a batch of events",
        response_model=IngestResponse,
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/BatchRequest"},
                        "example": {
                            "events": [
                                {
                                    "timestamp": "2026-09-18T17:00:00Z",
                                    "level": "info",
                                    "message": "User signed in",
                                    "payload": {"user_id": 42},
                                },
                                {
                                    "timestamp": "2026-09-18T17:00:01Z",
                                    "level": "warn",
                                    "message": "Slow query detected",
                                    "payload": {"duration_ms": 1450},
                                },
                            ]
                        },
                    }
                },
            }
        },
    )
    async def ingest_batch(
        request: Request,
        x_telemetria_token: str = Header(..., alias="x-telemetria-token"),
    ) -> IngestResponse:
        _check_content_type(request)
        body = await _read_body(request, application.state.settings.max_payload_bytes)
        batch_req = _parse_json(body, BatchRequest)
        if len(batch_req.events) > application.state.settings.max_batch_events:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Batch exceeds MAX_BATCH_EVENTS"
                    f" ({application.state.settings.max_batch_events})"
                ),
            )
        resolved = await _resolve_token(application.state.resolver, x_telemetria_token)
        received_at = datetime.now(tz=UTC)
        events: list[Event] = []
        for req in batch_req.events:
            try:
                events.append(
                    _build_event(
                        req,
                        received_at,
                        resolved.project_id,
                        resolved.project_slug,
                        resolved.app_id,
                        resolved.app_slug,
                    )
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        enqueued = dropped = 0
        for event in events:
            d = _enqueue(application.state.queue, event)
            dropped += d
            enqueued += 1 - d
        return IngestResponse(enqueued=enqueued, dropped=dropped)

    add_metrics(application, process=_PROCESS, enabled=common_settings.metrics_enabled)

    # Register Pydantic models as reusable OpenAPI components so Scalar shows
    # them in the Models sidebar and links to them from route schemas.
    if settings.api_docs_enabled:
        from fastapi.openapi.utils import get_openapi

        def _custom_openapi() -> dict[str, Any]:
            if application.openapi_schema:
                return application.openapi_schema
            schema = get_openapi(
                title=application.title,
                version=application.version,
                routes=application.routes,
            )
            components = schema.setdefault("components", {})
            schemas = components.setdefault("schemas", {})

            # Register top-level models and hoist any $defs to components/schemas
            for model in (EventRequest, BatchRequest, IngestResponse):
                model_schema = model.model_json_schema()
                # Hoist nested $defs into top-level components
                for name, defn in model_schema.pop("$defs", {}).items():
                    if name not in schemas:
                        schemas[name] = defn
                # Rewrite local $defs refs to components/schemas refs
                raw = json.dumps(model_schema).replace(
                    '"#/$defs/', '"#/components/schemas/'
                )
                schemas[model.__name__] = json.loads(raw)

            application.openapi_schema = schema
            return schema

        application.openapi = _custom_openapi  # type: ignore[method-assign]

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
