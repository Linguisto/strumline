"""OTLP wire contracts, limits, exporter interoperability, and sink preservation."""

from __future__ import annotations

import asyncio
import base64
import gzip
import json
import socket
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
import uvicorn
from google.protobuf.json_format import MessageToDict
from google.rpc.status_pb2 import Status
from httpx2 import ASGITransport, AsyncClient
from opentelemetry._logs import SeverityNumber
from opentelemetry.exporter.otlp.proto.http import Compression
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import (
    ExportLogsServiceRequest,
    ExportLogsServiceResponse,
)
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import SimpleLogRecordProcessor
from opentelemetry.sdk.resources import Resource

from strumline.config import IngestSettings
from strumline.domain.events import EventBatch
from strumline.ingest.resolver import (
    AuthTokenResolver,
    AuthTokenResolverError,
    AuthTokenResolverUnavailable,
    ResolvedToken,
)
from strumline.ingest.server import create_app
from strumline.ipc.codec import decode_envelope_body, encode_frame
from strumline.sinks.loki import build_push_payload

pytestmark = pytest.mark.unit
_TOKEN = {"x-strumline-token": "test-token"}
_RESOLVED = ResolvedToken(
    token_id="token",
    app_id="00000000-0000-0000-0000-000000000002",
    app_slug="app",
    project_id="00000000-0000-0000-0000-000000000001",
    project_slug="project",
)


def make_app(**settings):
    app = create_app(settings=IngestSettings(**settings))
    app.state.resolver = MagicMock(resolve=AsyncMock(return_value=_RESOLVED))
    return app


def logs_request(count=1):
    request = ExportLogsServiceRequest()
    resource = request.resource_logs.add(schema_url="https://example.org/resource/1")
    resource.resource.attributes.add(key="service.name").value.string_value = "checkout"
    scope = resource.scope_logs.add(schema_url="https://example.org/scope/1")
    scope.scope.name = "test-library"
    scope.scope.version = "1.2.3"
    for _ in range(count):
        log = scope.log_records.add(
            time_unix_nano=1726668000123456789,
            observed_time_unix_nano=1726668000987654321,
            severity_number=17,
            severity_text="ERROR",
            flags=1,
            trace_id=bytes.fromhex("aabbccddeeff00112233445566778899"),
            span_id=bytes.fromhex("1122334455667788"),
            event_name="checkout.failed",
            dropped_attributes_count=2,
        )
        log.body.string_value = "payment failed"
        log.attributes.add(key="large_integer").value.int_value = 9223372036854775807
        log.attributes.add(key="binary").value.bytes_value = b"\x00\xff"
        log.attributes.add(key="project").value.string_value = "untrusted-project"
    return request


def encode(request, media):
    if media == "application/x-protobuf":
        return request.SerializeToString()
    data = MessageToDict(request, use_integers_for_enums=True)
    for resource in data.get("resourceLogs", []):
        for scope in resource.get("scopeLogs", []):
            for record in scope.get("logRecords", []):
                for field in ("traceId", "spanId"):
                    if field in record:
                        record[field] = base64.b64decode(record[field]).hex().upper()
    return json.dumps(data).encode()


async def post(app, body, media="application/json", **headers):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post(
            "/v1/logs",
            content=body,
            headers={**_TOKEN, "content-type": media, **headers},
        )


@pytest.mark.parametrize("media", ["application/json", "application/x-protobuf"])
@pytest.mark.parametrize("compressed", [False, True])
async def test_export_preserves_record_through_ipc_and_loki(media, compressed):
    app = make_app()
    body = encode(logs_request(), media)
    response = await post(
        app,
        gzip.compress(body) if compressed else body,
        media,
        **({"content-encoding": "gzip"} if compressed else {}),
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == media
    if media == "application/json":
        assert response.json() == {}
    else:
        assert not ExportLogsServiceResponse.FromString(response.content).HasField(
            "partial_success"
        )
    event = decode_envelope_body(encode_frame(app.state.queue.get_nowait())[4:])
    assert event.project_slug == "project"
    assert event.app_slug == "app"
    assert event.timestamp.isoformat() == "2024-09-18T14:00:00.123456+00:00"
    assert event.received_at != event.timestamp
    assert event.level == "error"
    otlp = event.payload["otlp"]
    record = otlp["logRecord"]
    assert record["timeUnixNano"] == "1726668000123456789"
    assert record["observedTimeUnixNano"] == "1726668000987654321"
    assert record["traceId"] == "aabbccddeeff00112233445566778899"
    assert record["spanId"] == "1122334455667788"
    assert record["attributes"][0]["value"] == {"intValue": "9223372036854775807"}
    assert record["attributes"][1]["value"] == {"bytesValue": "AP8="}
    assert record["eventName"] == "checkout.failed"
    assert record["droppedAttributesCount"] == 2
    assert otlp["scope"]["version"] == "1.2.3"
    assert otlp["resourceSchemaUrl"] == "https://example.org/resource/1"
    stream = build_push_payload(EventBatch((event,)))["streams"][0]
    assert json.loads(stream["values"][0][1])["payload"]["otlp"] == otlp
    assert set(stream["stream"]) == {"service", "project", "app", "level"}


@pytest.mark.parametrize("media", ["application/json", "application/x-protobuf"])
async def test_empty_request(media):
    app = make_app()
    response = await post(app, encode(ExportLogsServiceRequest(), media), media)
    assert response.status_code == 200
    assert app.state.queue.empty()


@pytest.mark.parametrize(
    "body", [b"{", b"[]", b"null", b"{}{}", b'{"resourceLogs":null,"resourceLogs":[]}']
)
async def test_bad_json_is_otlp_status(body):
    app = make_app()
    response = await post(app, body)
    assert response.status_code == 400
    assert response.json() == {"message": "Invalid OTLP logs payload"}
    assert app.state.queue.empty()


async def test_bad_protobuf_is_protobuf_status():
    response = await post(make_app(), b"\xff", "application/x-protobuf")
    assert response.status_code == 400
    assert Status.FromString(response.content).message == "Invalid OTLP logs payload"


@pytest.mark.parametrize(
    "field,value", [("severityNumber", "SEVERITY_NUMBER_ERROR"), ("traceId", "not-hex")]
)
async def test_otlp_json_deviations(field, value):
    data = json.loads(encode(logs_request(), "application/json"))
    data["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0][field] = value
    response = await post(make_app(), json.dumps(data).encode())
    assert response.status_code == 400


async def test_unknown_fields_ignored():
    app = make_app()
    data = json.loads(encode(logs_request(), "application/json"))
    data["futureField"] = {"arbitrary": True}
    data["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]["futureField"] = 42
    assert (await post(app, json.dumps(data).encode())).status_code == 200
    assert "futureField" not in app.state.queue.get_nowait().payload["otlp"]["logRecord"]


@pytest.mark.parametrize("use_observed", [False, True])
async def test_timestamp_fallback_and_structured_body(use_observed):
    app = make_app()
    request = logs_request()
    record = request.resource_logs[0].scope_logs[0].log_records[0]
    record.time_unix_nano = 0
    if not use_observed:
        record.observed_time_unix_nano = 0
    record.body.kvlist_value.values.add(key="nested").value.array_value.values.add(int_value=5)
    assert (
        await post(app, request.SerializeToString(), "application/x-protobuf")
    ).status_code == 200
    event = app.state.queue.get_nowait()
    assert "kvlistValue" in event.payload["otlp"]["logRecord"]["body"]
    if use_observed:
        assert event.timestamp.microsecond == 987654
    else:
        assert event.timestamp == event.received_at


@pytest.mark.parametrize(
    "headers,status",
    [
        ({"x-strumline-token": ""}, 401),
        ({"content-type": "text/plain"}, 415),
        ({"content-encoding": "br"}, 415),
    ],
)
async def test_headers(headers, status):
    assert (await post(make_app(), b"{}", **headers)).status_code == status


@pytest.mark.parametrize(
    "error,status",
    [
        (AuthTokenResolverError("secret"), 401),
        (AuthTokenResolverUnavailable("secret"), 503),
    ],
)
async def test_auth_failure(error, status):
    app = make_app()
    app.state.resolver.resolve.side_effect = error
    response = await post(app, b"{}")
    assert response.status_code == status
    assert "secret" not in response.text


async def test_resolver_database_failure_is_retryable():
    app = make_app()
    resolver = AuthTokenResolver(MagicMock())
    resolver._query = AsyncMock(side_effect=RuntimeError("database unavailable"))
    app.state.resolver = resolver
    assert (await post(app, b"{}")).status_code == 503


@pytest.mark.parametrize("compressed", [False, True])
async def test_body_limits(compressed):
    body = b" " * 1000
    response = await post(
        make_app(max_payload_bytes=100),
        gzip.compress(body) if compressed else body,
        **({"content-encoding": "gzip"} if compressed else {}),
    )
    assert response.status_code == 413


@pytest.mark.parametrize("body", [b"not gzip", gzip.compress(b"{}")[:-2]])
async def test_invalid_gzip(body):
    assert (await post(make_app(), body, **{"content-encoding": "gzip"})).status_code == 400


async def test_record_count_limit_is_atomic():
    app = make_app(max_batch_events=1)
    response = await post(app, encode(logs_request(2), "application/json"))
    assert response.status_code == 400
    assert app.state.queue.empty()


async def test_queue_overload_is_atomic_and_retryable():
    app = make_app(queue_size=2)
    one = encode(logs_request(), "application/json")
    assert (await post(app, one)).status_code == 200
    two = encode(logs_request(2), "application/json")
    assert (await post(app, two)).status_code == 503
    assert app.state.queue.qsize() == 1
    app.state.queue.get_nowait()
    assert (await post(app, two)).status_code == 200
    assert app.state.queue.qsize() == 2


@pytest.mark.parametrize("media", ["application/json", "application/x-protobuf"])
async def test_normalized_size_partial_success(media):
    app = make_app(max_payload_bytes=4000)
    request = logs_request(2)
    request.resource_logs[0].scope_logs[0].log_records[0].body.string_value = "x" * 2200
    response = await post(app, encode(request, media), media)
    assert response.status_code == 200
    if media == "application/json":
        assert response.json()["partialSuccess"]["rejectedLogRecords"] == "1"
    else:
        assert (
            ExportLogsServiceResponse.FromString(
                response.content
            ).partial_success.rejected_log_records
            == 1
        )
    assert app.state.queue.qsize() == 1
    assert app.state.queue.get_nowait().message == "payment failed"


@asynccontextmanager
async def live_ingest(app):
    # Lifespan is disabled so the IPC writer cannot consume the asserted events.
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        server = uvicorn.Server(uvicorn.Config(app, lifespan="off", log_level="error"))
        task = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            async with asyncio.timeout(5):
                while not server.started:
                    await asyncio.sleep(0.01)
            yield f"http://127.0.0.1:{listener.getsockname()[1]}/v1/logs"
        finally:
            server.should_exit = True
            await asyncio.wait_for(task, 5)


async def test_real_sdk_http_exporter():
    app = make_app()
    async with live_ingest(app) as endpoint:

        def emit():
            provider = LoggerProvider(resource=Resource.create({"service.name": "sdk-example"}))
            exporter = OTLPLogExporter(
                endpoint=endpoint,
                headers=_TOKEN,
                compression=Compression.Gzip,  # gitleaks:allow
            )
            provider.add_log_record_processor(SimpleLogRecordProcessor(exporter))
            try:
                provider.get_logger("sdk-test").emit(
                    body="from SDK",
                    severity_number=SeverityNumber.INFO,
                    attributes={"answer": 42},
                    timestamp=1726668000123456789,
                )
            finally:
                provider.shutdown()

        await asyncio.to_thread(emit)
    event = app.state.queue.get_nowait()
    assert event.message == "from SDK"
    assert event.payload["otlp"]["logRecord"]["timeUnixNano"] == "1726668000123456789"
    assert event.payload["otlp"]["scope"]["name"] == "sdk-test"


async def test_multiple_resources_and_scopes_keep_their_context():
    app = make_app()
    request = logs_request()
    resource = request.resource_logs.add()
    resource.resource.attributes.add(key="service.name").value.string_value = "second"
    for name in ("scope-a", "scope-b"):
        scope = resource.scope_logs.add()
        scope.scope.name = name
        scope.log_records.add().body.string_value = name
    assert (
        await post(app, request.SerializeToString(), "application/x-protobuf")
    ).status_code == 200
    events = [app.state.queue.get_nowait() for _ in range(3)]
    assert [e.message for e in events] == ["payment failed", "scope-a", "scope-b"]
    assert (
        events[1].payload["otlp"]["resource"]["attributes"][0]["value"]["stringValue"] == "second"
    )
    assert events[2].payload["otlp"]["scope"]["name"] == "scope-b"


async def test_ipc_limit_applies_when_http_limit_is_larger():
    app = make_app(max_payload_bytes=4 * 1024 * 1024)
    request = logs_request(2)
    request.resource_logs[0].scope_logs[0].log_records[0].body.string_value = "x" * (600 * 1024)
    response = await post(app, request.SerializeToString(), "application/x-protobuf")
    assert response.status_code == 200
    assert (
        ExportLogsServiceResponse.FromString(response.content).partial_success.rejected_log_records
        == 1
    )
    assert app.state.queue.qsize() == 1
    assert app.state.queue.get_nowait().message == "payment failed"


async def test_normalized_batch_limit_bounds_shared_resource_expansion():
    app = make_app(max_payload_bytes=6000)
    request = logs_request(3)
    request.resource_logs[0].resource.attributes.add(key="large").value.string_value = "x" * 2000
    response = await post(app, request.SerializeToString(), "application/x-protobuf")
    assert response.status_code == 200
    assert (
        ExportLogsServiceResponse.FromString(response.content).partial_success.rejected_log_records
        == 2
    )
    assert app.state.queue.qsize() == 1


async def test_excessive_json_nesting_rejected_without_admission():
    app = make_app()
    data = json.loads(encode(logs_request(), "application/json"))
    body = {"stringValue": "secret"}
    for _ in range(80):
        body = {"arrayValue": {"values": [body]}}
    data["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]["body"] = body
    response = await post(app, json.dumps(data).encode())
    assert response.status_code == 400
    assert "secret" not in response.text
    assert app.state.queue.empty()


async def test_batch_larger_than_queue_is_not_retryable():
    app = make_app(queue_size=1)
    response = await post(app, encode(logs_request(2), "application/json"))
    assert response.status_code == 400
    assert app.state.queue.empty()


@pytest.mark.parametrize(
    "number,level",
    [
        (0, "unspecified"),
        (1, "trace"),
        (8, "debug"),
        (12, "info"),
        (16, "warn"),
        (20, "error"),
        (24, "fatal"),
        (25, "unspecified"),
    ],
)
async def test_severity_ranges(number, level):
    app = make_app()
    request = logs_request()
    request.resource_logs[0].scope_logs[0].log_records[0].severity_number = number
    response = await post(app, request.SerializeToString(), "application/x-protobuf")
    assert response.status_code == 200
    assert app.state.queue.get_nowait().level == level


async def test_zero_byte_trace_span_ids_dropped_from_payload():
    """All-zero traceId/spanId are invalid per OTLP spec and must be omitted from payload."""
    app = make_app()
    request = logs_request()
    record = request.resource_logs[0].scope_logs[0].log_records[0]
    record.trace_id = b"\x00" * 16
    record.span_id = b"\x00" * 8
    response = await post(app, request.SerializeToString(), "application/x-protobuf")
    assert response.status_code == 200
    record_data = app.state.queue.get_nowait().payload["otlp"]["logRecord"]
    assert "traceId" not in record_data
    assert "spanId" not in record_data


@pytest.mark.parametrize("compressed", [False, True])
async def test_protobuf_full_field_preservation(compressed):
    """Protobuf (with and without gzip) preserves all fields through IPC and Loki."""
    app = make_app()
    body = logs_request().SerializeToString()
    response = await post(
        app,
        gzip.compress(body) if compressed else body,
        "application/x-protobuf",
        **{"content-encoding": "gzip"} if compressed else {},
    )
    assert response.status_code == 200
    assert not ExportLogsServiceResponse.FromString(response.content).HasField("partial_success")
    event = decode_envelope_body(encode_frame(app.state.queue.get_nowait())[4:])
    otlp = event.payload["otlp"]
    record = otlp["logRecord"]
    assert record["timeUnixNano"] == "1726668000123456789"
    assert record["observedTimeUnixNano"] == "1726668000987654321"
    assert record["traceId"] == "aabbccddeeff00112233445566778899"
    assert record["spanId"] == "1122334455667788"
    assert record["attributes"][0]["value"] == {"intValue": "9223372036854775807"}
    assert record["attributes"][1]["value"] == {"bytesValue": "AP8="}
    assert record["eventName"] == "checkout.failed"
    assert record["droppedAttributesCount"] == 2
    assert otlp["scope"]["version"] == "1.2.3"
    assert otlp["resourceSchemaUrl"] == "https://example.org/resource/1"
    stream = build_push_payload(EventBatch((event,)))["streams"][0]
    assert json.loads(stream["values"][0][1])["payload"]["otlp"] == otlp


async def test_content_type_with_charset_accepted():
    """content-type: application/json; charset=utf-8 must be treated as application/json."""
    app = make_app()
    body = encode(logs_request(), "application/json")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/logs",
            content=body,
            headers={**_TOKEN, "content-type": "application/json; charset=utf-8"},
        )
    assert response.status_code == 200
    assert app.state.queue.qsize() == 1


async def test_auth_failure_response_is_valid_status_shape():
    """Error responses must be a valid google.rpc.Status with a non-empty message."""
    exception_detail = "internal-secret-reason-xyz"
    app = make_app()
    app.state.resolver.resolve.side_effect = AuthTokenResolverError(exception_detail)
    response = await post(app, b"{}")
    assert response.status_code == 401
    body = response.json()
    assert set(body.keys()) == {"message"}
    assert body["message"]
    assert exception_detail not in body["message"]  # internal exception detail must not leak
