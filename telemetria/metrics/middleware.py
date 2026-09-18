"""HTTP instrumentation middleware and /metrics endpoint factory.

Usage in a FastAPI ``create_app``::

    from telemetria.metrics.middleware import add_metrics

    application = FastAPI(...)
    add_metrics(application, process="ingest", enabled=settings.metrics_enabled)

``add_metrics`` is a no-op when ``enabled=False`` so callers need no
conditional logic beyond reading the flag.

The ``/metrics`` route itself is excluded from HTTP instrumentation to avoid
self-referential cardinality growth.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Match, Route

from telemetria.metrics import HTTP_REQUEST_DURATION_SECONDS, HTTP_REQUESTS_TOTAL

if TYPE_CHECKING:
    from fastapi import FastAPI

_METRICS_PATH = "/metrics"


def _route_template(request: Request) -> str:
    """Return the matched route template, or '<unknown>' if unmatched.

    Uses the path template (e.g. ``/v1/ingest``) rather than the raw path so
    parameterised routes don't inflate label cardinality.
    """
    for route in request.app.routes:
        if isinstance(route, Route) and route.path != _METRICS_PATH:
            match, _ = route.matches(request.scope)
            if match == Match.FULL:
                return route.path
    return "<unknown>"


def _status_class(status_code: int) -> str:
    return f"{status_code // 100}xx"


def add_metrics(app: FastAPI, *, process: str, enabled: bool) -> None:
    """Attach the ``/metrics`` endpoint and request-instrumentation middleware.

    Parameters
    ----------
    app:
        The FastAPI application to instrument.
    process:
        Process name used as the ``process`` label value (``"api"``,
        ``"ingest"``, or ``"processor"``).
    enabled:
        When ``False`` this function is a complete no-op; ``/metrics`` is not
        mounted and no middleware is added.
    """
    if not enabled:
        return

    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
    from starlette.responses import Response as StarletteResponse

    @app.get(_METRICS_PATH, include_in_schema=False)
    async def metrics() -> StarletteResponse:
        return StarletteResponse(
            content=generate_latest(),
            media_type=CONTENT_TYPE_LATEST,
        )

    @app.middleware("http")
    async def _instrument(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Skip instrumentation for /metrics itself
        if request.url.path == _METRICS_PATH:
            return await call_next(request)

        route = _route_template(request)
        method = request.method
        start = time.perf_counter()

        response: Response = await call_next(request)

        duration = time.perf_counter() - start
        status = _status_class(response.status_code)

        HTTP_REQUESTS_TOTAL.labels(
            process=process, method=method, route=route, status_class=status
        ).inc()
        HTTP_REQUEST_DURATION_SECONDS.labels(process=process, method=method, route=route).observe(
            duration
        )

        return response
