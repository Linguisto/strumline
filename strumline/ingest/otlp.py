"""OTLP/HTTP logs adapter for the ingest process.

Entry point: ``POST /v1/logs`` (registered via ``router``).

Accepts ``ExportLogsServiceRequest`` encoded as:
- ``application/json``   — OTLP Canonical JSON with Strumline deviations
                           (see ``_protobuf_json``).
- ``application/x-protobuf`` — binary Protobuf.

Both encodings support ``Content-Encoding: gzip``.

Each log record becomes one ``Event`` whose ``payload.otlp`` preserves the
full typed resource/scope/record tree.  The processor and sinks are completely
independent of OTLP schemas: they only see ``Event``.

Invariants
----------
- Admission is atomic: either the whole admitted sub-batch enters the queue
  atomically (no ``await`` between capacity check and ``put_nowait``), or the
  entire request is rejected with a retryable 503.
- Normalized-size rejections (individual frame too large, or cumulative batch
  too large) return OTLP partial success with exact counts; they are permanent
  and must not be retried.
- Parser diagnostics are never echoed to callers; error responses use fixed
  strings to avoid leaking telemetry or internal state.
"""

from __future__ import annotations

import base64
import gzip
import io
import json
import logging
import re
import zlib
from datetime import UTC, datetime, timedelta
from typing import Any, NoReturn
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request, Response
from google.protobuf.descriptor import Descriptor, FieldDescriptor
from google.protobuf.json_format import MessageToDict, ParseDict, ParseError
from google.protobuf.message import DecodeError, Message
from google.rpc.status_pb2 import Status
from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import (
    ExportLogsServiceRequest,
    ExportLogsServiceResponse,
)
from opentelemetry.proto.logs.v1.logs_pb2 import LogRecord

from strumline.domain.events import Event
from strumline.ingest.admission import read_body, resolve_token
from strumline.ingest.otlp_docs import OPENAPI
from strumline.ingest.resolver import ResolvedToken
from strumline.ipc.codec import IPC_MAX_FRAME_BYTES, encode_frame
from strumline.metrics import (
    INGEST_EVENTS_ACCEPTED_TOTAL,
    INGEST_EVENTS_DROPPED_TOTAL,
    INGEST_QUEUE_DEPTH,
)

router = APIRouter()
log = logging.getLogger(__name__)

_JSON = "application/json"
_PROTOBUF = "application/x-protobuf"
# Maximum message nesting depth accepted in OTLP JSON. Matches ParseDict limit.
_MAX_DEPTH = 64
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
# Severity number bands → level name. Numbers 1–4 → trace, 5–8 → debug, etc.
_LEVELS = ("trace", "debug", "info", "warn", "error", "fatal")


# ---------------------------------------------------------------------------
# JSON decoding helpers
# ---------------------------------------------------------------------------


def _protobuf_json(value: Any, descriptor: Descriptor, depth: int = 0) -> dict[str, Any]:
    """Normalise an OTLP Canonical JSON dict before passing it to ``ParseDict``.

    The OTLP Canonical JSON spec deviates from standard protobuf JSON in two
    important ways that ``ParseDict`` does not handle by default:

    - **Enums must be integers** — string enum names are rejected.
    - **Trace/span IDs are hex strings** — protobuf JSON expects base64.

    Unknown fields are silently ignored (forward-compatible receiver).
    Only ``lowerCamelCase`` field names are recognised.

    Raises ``ValueError`` on invalid enum values, non-hex IDs, type mismatches,
    or nesting that exceeds ``_MAX_DEPTH``.
    """
    if depth >= _MAX_DEPTH or not isinstance(value, dict):
        raise ValueError("Invalid message or excessive nesting")
    result: dict[str, Any] = {}
    for field in descriptor.fields:
        name = field.json_name
        if name not in value:
            continue
        item = value[name]
        if item is None:
            continue
        if field.type == FieldDescriptor.TYPE_MESSAGE:
            if field.is_repeated:
                if not isinstance(item, list):
                    raise ValueError("Expected a repeated field")
                item = [_protobuf_json(v, field.message_type, depth + 1) for v in item]
            else:
                item = _protobuf_json(item, field.message_type, depth + 1)
        elif field.type == FieldDescriptor.TYPE_ENUM and type(item) is not int:
            raise ValueError("OTLP enum fields must be integers")
        elif name in ("traceId", "spanId"):
            if not isinstance(item, str) or re.fullmatch(r"(?:[0-9a-fA-F]{2})*", item) is None:
                raise ValueError("OTLP IDs must be hexadecimal")
            # ParseDict expects base64; convert from hex before handing off.
            item = base64.b64encode(bytes.fromhex(item)).decode("ascii")
        result[name] = item
    return result


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """``json.loads`` hook that rejects duplicate keys at the top level."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field")
        result[key] = value
    return result


def _invalid_constant(value: str) -> NoReturn:
    """``json.loads`` hook that rejects ``NaN``, ``Infinity``, etc."""
    raise ValueError("Invalid JSON constant")


def decode_logs(body: bytes, media_type: str) -> ExportLogsServiceRequest:
    """Decode *body* into an ``ExportLogsServiceRequest``.

    Raises ``HTTPException(400)`` on any parse error.  Parser diagnostics are
    never forwarded to the caller to avoid leaking telemetry content.
    """
    message = ExportLogsServiceRequest()
    try:
        if media_type == _PROTOBUF:
            message.ParseFromString(body)
        else:
            data = json.loads(
                body, object_pairs_hook=_unique_object, parse_constant=_invalid_constant
            )
            ParseDict(
                _protobuf_json(data, message.DESCRIPTOR), message, max_recursion_depth=_MAX_DEPTH
            )
    except (ValueError, TypeError, ParseError, DecodeError, RecursionError) as exc:
        raise HTTPException(status_code=400, detail="Invalid OTLP logs payload") from exc
    return message


# ---------------------------------------------------------------------------
# Event construction helpers
# ---------------------------------------------------------------------------


def _dict(message: Message) -> dict[str, Any]:
    """Serialise *message* to a plain dict suitable for JSON storage.

    ``use_integers_for_enums=True`` keeps enum values as numbers, matching the
    OTLP Canonical JSON spec.  Default-valued fields are omitted by the
    protobuf JSON serialiser — this is correct for a forward-compatible
    receiver.

    Caution: bytes fields (``traceId``, ``spanId``) are rendered as base64 by
    ``MessageToDict``; callers that need hex must re-encode them explicitly.
    """
    result: dict[str, Any] = MessageToDict(message, use_integers_for_enums=True)
    return result


def _event(
    record: LogRecord,
    resource: dict[str, Any],
    scope: dict[str, Any],
    resource_schema_url: str,
    scope_schema_url: str,
    resolved: ResolvedToken,
    received_at: datetime,
) -> Event:
    """Build a domain ``Event`` from one OTLP ``LogRecord`` and its context."""
    record_data = _dict(record)

    # ``_dict`` / ``MessageToDict`` renders bytes as base64.  Re-encode
    # traceId/spanId as canonical lowercase hex per the OTLP JSON convention.
    # All-zero IDs are invalid per the spec ("consumers SHOULD ignore them");
    # pop them unconditionally then re-add only when at least one byte is set.
    # ``MessageToDict`` can still emit all-zero IDs as base64, so pop first.
    for name, value in (("traceId", record.trace_id), ("spanId", record.span_id)):
        record_data.pop(name, None)
        if any(value):
            record_data[name] = value.hex()

    # Timestamp: prefer event time, fall back to observed time, then receipt.
    # Exact nanoseconds are preserved in the OTLP payload; the datetime here
    # is a microsecond-precision display projection only.
    ns = record.time_unix_nano or record.observed_time_unix_nano
    timestamp = _EPOCH + timedelta(microseconds=ns // 1000) if ns else received_at

    number = record.severity_number
    level = _LEVELS[(number - 1) // 4] if 1 <= number <= 24 else "unspecified"

    body = record_data.get("body", {})
    message = (
        record.body.string_value
        if record.body.WhichOneof("value") == "string_value"
        else (json.dumps(body, separators=(",", ":")) if body else "")
    )

    return Event(
        id=uuid4(),
        project_id=UUID(resolved.project_id),
        project_slug=resolved.project_slug,
        app_id=UUID(resolved.app_id),
        app_slug=resolved.app_slug,
        received_at=received_at,
        timestamp=timestamp,
        level=level,
        message=message,
        payload={
            "otlp": {
                "resource": resource,
                "resourceSchemaUrl": resource_schema_url,
                "scope": scope,
                "scopeSchemaUrl": scope_schema_url,
                "logRecord": record_data,
            }
        },
    )


def _response(message: Message, media_type: str, status: int = 200) -> Response:
    """Serialise *message* as JSON or Protobuf depending on *media_type*."""
    content = (
        json.dumps(_dict(message), separators=(",", ":")).encode()
        if media_type == _JSON
        else message.SerializeToString()
    )
    return Response(content, status_code=status, media_type=media_type)


# ---------------------------------------------------------------------------
# Request handler
# ---------------------------------------------------------------------------


async def _export(request: Request, media_type: str) -> Response:
    """Core export logic — validate, decode, normalise, and admit to the queue.

    Check order: content-type → encoding → auth → body read → decode →
    count limit → normalised-size loop → capacity check → enqueue.

    Content-type and encoding are validated before auth so that structurally
    invalid requests fail immediately without a database round-trip.
    """
    settings = request.app.state.settings

    if media_type not in (_JSON, _PROTOBUF):
        raise HTTPException(
            status_code=415, detail="Use application/json or application/x-protobuf"
        )
    encoding = request.headers.get("content-encoding", "identity").strip().lower()
    if encoding not in ("identity", "gzip"):
        raise HTTPException(status_code=415, detail="Unsupported Content-Encoding")

    key = request.headers.get("x-strumline-token", "")
    if not key:
        raise HTTPException(status_code=401, detail="Missing x-strumline-token")
    resolved = await resolve_token(request.app.state.resolver, key)

    body = await read_body(request, settings.max_payload_bytes)
    if encoding == "gzip":
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(body)) as compressed:
                # Read one byte past the limit to detect oversize without
                # allocating the whole buffer first.
                body = compressed.read(settings.max_payload_bytes + 1)
        except (OSError, EOFError, zlib.error) as exc:
            raise HTTPException(status_code=400, detail="Invalid gzip body") from exc
        if len(body) > settings.max_payload_bytes:
            raise HTTPException(
                status_code=413, detail="Decompressed body exceeds MAX_PAYLOAD_BYTES"
            )

    logs = decode_logs(body, media_type)
    count = sum(len(s.log_records) for r in logs.resource_logs for s in r.scope_logs)
    if count > settings.max_batch_events:
        raise HTTPException(status_code=400, detail="Batch exceeds MAX_BATCH_EVENTS")

    # Build events and apply normalised-size limits.  Flattening shared
    # resource/scope into every frame and re-encoding binary attributes can
    # expand the payload beyond its compressed wire size.  Each event must fit
    # one IPC frame; the cumulative normalised batch must also fit within
    # MAX_PAYLOAD_BYTES.  Records are considered in request order; oversized
    # records are counted as partial-success rejections while later fitting
    # records are still admitted.
    events: list[Event] = []
    rejected = 0
    normalized_bytes = 0
    received_at = datetime.now(UTC)
    for resource_logs in logs.resource_logs:
        resource = _dict(resource_logs.resource)
        for scope_logs in resource_logs.scope_logs:
            scope = _dict(scope_logs.scope)
            for record in scope_logs.log_records:
                event = _event(
                    record,
                    resource,
                    scope,
                    resource_logs.schema_url,
                    scope_logs.schema_url,
                    resolved,
                    received_at,
                )
                frame_bytes = len(encode_frame(event)) - 4  # body only, not prefix
                if (
                    frame_bytes > IPC_MAX_FRAME_BYTES
                    or normalized_bytes + frame_bytes > settings.max_payload_bytes
                ):
                    rejected += 1
                else:
                    normalized_bytes += frame_bytes
                    events.append(event)

    queue = request.app.state.queue
    # A batch that can never fit (larger than total queue) is a permanent 400.
    if queue.maxsize > 0 and len(events) > queue.maxsize:
        raise HTTPException(status_code=400, detail="Batch exceeds ingest queue capacity")
    # Insufficient current space → retryable 503; nothing is admitted.
    if queue.maxsize > 0 and len(events) > queue.maxsize - queue.qsize():
        raise HTTPException(status_code=503, detail="Ingest queue is full; retry this batch")

    # Enqueue atomically: no await between capacity check and put_nowait.
    for event in events:
        queue.put_nowait(event)
    INGEST_EVENTS_ACCEPTED_TOTAL.inc(len(events))
    INGEST_QUEUE_DEPTH.set(queue.qsize())

    if rejected:
        log.info(
            "OTLP batch partial app=%s accepted=%d rejected=%d reason=normalized_size",
            resolved.app_slug,
            len(events),
            rejected,
        )
    else:
        log.debug("OTLP batch admitted app=%s count=%d", resolved.app_slug, len(events))

    response = ExportLogsServiceResponse()
    if rejected:
        response.partial_success.rejected_log_records = rejected
        response.partial_success.error_message = (
            "Normalized logs exceed payload or IPC frame limits"
        )
        INGEST_EVENTS_DROPPED_TOTAL.labels(reason="otlp_normalized_size").inc(rejected)
    return _response(response, media_type)


@router.post(
    "/v1/logs",
    tags=["Ingest"],
    summary="Export OTLP logs over HTTP",
    response_class=Response,
    openapi_extra=OPENAPI,
)
async def export_logs(request: Request) -> Response:
    """Accept an OTLP ``ExportLogsServiceRequest`` and admit records to the queue.

    Handles both ``application/json`` and ``application/x-protobuf`` with
    optional ``Content-Encoding: gzip``.  Errors are returned as
    ``google.rpc.Status`` encoded in the same format as the request.
    """
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    try:
        return await _export(request, media_type)
    except HTTPException as exc:
        response_type = media_type if media_type in (_JSON, _PROTOBUF) else _JSON
        return _response(Status(message=str(exc.detail)), response_type, exc.status_code)
