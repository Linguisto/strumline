"""Loki sink provider — pushes event batches to Grafana Loki via the push API.

Entry point
-----------
Instantiated by the registry when ``SINK_PROVIDER=loki``.  Never imported
directly by ``BatchProcessor``; the processor only sees the ``EventSink`` ABC.

Loki push API
-------------
``POST <LOKI_URL>/loki/api/v1/push``

Request body is ``application/json`` (optionally gzip-compressed)::

    {
      "streams": [
        {
          "stream": {"service": "telemetria", "project": "...", "app": "...", "level": "..."},
          "values": [["<nanoseconds-string>", "<json-line>"]]
        },
        ...
      ]
    }

Timestamps
----------
- Entry timestamp = server ``received_at`` expressed as integer nanoseconds
  (decimal string, NOT a JSON number — Loki rejects numbers).
- Client ``timestamp`` is preserved as metadata inside the JSON line but never
  controls Loki storage ordering.

Grouping
--------
Events are grouped by their ``(project_slug, app_slug, level)`` label set and
sorted by entry timestamp within each group for deterministic requests.

Compression
-----------
When ``LOKI_COMPRESSION=gzip`` (default), the JSON bytes are gzip-compressed
and ``Content-Encoding: gzip`` is added.  Tests decode the request body before
inspecting it; this module does not assume the HTTP client does the compression.

Error mapping
-------------
- Network errors, timeouts, HTTP 429, HTTP 5xx  → ``RetryableSinkError``
- Other HTTP 4xx, invalid configuration          → ``PermanentSinkError``
"""

from __future__ import annotations

import gzip
import json
import logging
from typing import TYPE_CHECKING, Any

import httpx2

from telemetria.config import LokiSettings
from telemetria.sinks import EventSink, PermanentSinkError, RetryableSinkError

if TYPE_CHECKING:
    from telemetria.domain.events import Event, EventBatch

log = logging.getLogger(__name__)

_PUSH_PATH = "/loki/api/v1/push"
_SERVICE_LABEL = "telemetria"


# ---------------------------------------------------------------------------
# Timestamp helper
# ---------------------------------------------------------------------------


def _to_nanoseconds(event: Event) -> str:
    """Return ``received_at`` as a decimal nanosecond string (never a JSON number)."""
    ts = event.received_at
    # epoch seconds as integer, then add sub-second nanoseconds
    epoch_ns = int(ts.timestamp() * 1_000_000_000)
    return str(epoch_ns)


# ---------------------------------------------------------------------------
# Payload builder
# ---------------------------------------------------------------------------


def _event_line(event: Event) -> str:
    """Serialize an event to a single JSON log line."""
    return json.dumps(
        {
            "id": str(event.id),
            "received_at": event.received_at.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z",
            "timestamp": event.timestamp.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z",
            "level": event.level,
            "message": event.message,
            "payload": event.payload,
        },
        separators=(",", ":"),
    )


def _labels(event: Event) -> tuple[str, str, str]:
    """Return the (project_slug, app_slug, level) label key for grouping."""
    return (event.project_slug, event.app_slug, event.level)


def build_push_payload(batch: EventBatch) -> dict[str, Any]:
    """Build the Loki push JSON payload for *batch*.

    Events are grouped by label set and sorted by entry timestamp within each
    group so requests are deterministic and well-ordered.
    """
    groups: dict[tuple[str, str, str], list[Event]] = {}
    for event in batch:
        key = _labels(event)
        groups.setdefault(key, []).append(event)

    streams = []
    for (project, app, level), events in groups.items():
        # Sort by received_at for deterministic order within the stream
        sorted_events = sorted(events, key=lambda e: e.received_at)
        streams.append(
            {
                "stream": {
                    "service": _SERVICE_LABEL,
                    "project": project,
                    "app": app,
                    "level": level,
                },
                "values": [[_to_nanoseconds(e), _event_line(e)] for e in sorted_events],
            }
        )

    return {"streams": streams}


# ---------------------------------------------------------------------------
# LokiSink
# ---------------------------------------------------------------------------


class LokiSink(EventSink):
    """Pushes event batches to Grafana Loki.

    Parameters
    ----------
    settings:
        Loki configuration.  Defaults to ``LokiSettings()`` read from env.
    """

    name = "loki"

    def __init__(self, settings: LokiSettings | None = None) -> None:
        if settings is None:
            settings = LokiSettings()

        self._url = settings.loki_url.rstrip("/") + _PUSH_PATH
        self._tenant_id = settings.loki_tenant_id
        self._timeout = settings.loki_timeout_seconds
        self._compress = settings.loki_compression.lower() == "gzip"

        self._client = httpx2.AsyncClient(
            timeout=httpx2.Timeout(self._timeout),
        )

    async def write(self, batch: EventBatch) -> None:
        """Push *batch* to Loki.

        Raises
        ------
        RetryableSinkError
            Network error, timeout, HTTP 429, or HTTP 5xx.
        PermanentSinkError
            Other HTTP 4xx (bad request, auth failure, etc.).
        """
        payload = build_push_payload(batch)
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._compress:
            body = gzip.compress(body)
            headers["Content-Encoding"] = "gzip"
        if self._tenant_id:
            headers["X-Scope-OrgID"] = self._tenant_id

        try:
            response = await self._client.post(self._url, content=body, headers=headers)
        except httpx2.TimeoutException as exc:
            raise RetryableSinkError(f"Loki request timed out: {exc}") from exc
        except httpx2.NetworkError as exc:
            raise RetryableSinkError(f"Loki network error: {exc}") from exc
        except httpx2.HTTPError as exc:
            raise RetryableSinkError(f"Loki HTTP error: {exc}") from exc

        _handle_response(response)

        log.debug(
            "Loki push ok events=%d streams=%d status=%d",
            len(batch),
            len(payload["streams"]),
            response.status_code,
        )

    async def close(self) -> None:
        await self._client.aclose()


def _handle_response(response: httpx2.Response) -> None:
    """Map Loki HTTP response status to sink errors."""
    if response.is_success:
        return
    status = response.status_code
    if status == 429 or status >= 500:
        raise RetryableSinkError(f"Loki returned retryable status {status}: {response.text[:200]}")
    # All other 4xx
    raise PermanentSinkError(f"Loki returned permanent error {status}: {response.text[:200]}")
