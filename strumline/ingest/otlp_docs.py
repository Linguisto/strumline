"""OpenAPI examples for the standard OTLP/HTTP logs wire contract."""

from typing import Any

_SINGLE = {
    "resourceLogs": [
        {
            "resource": {
                "attributes": [
                    {
                        "key": "service.name",
                        "value": {"stringValue": "checkout"},
                    }
                ]
            },
            "scopeLogs": [
                {
                    "scope": {"name": "checkout.runtime"},
                    "logRecords": [
                        {
                            "severityNumber": 9,
                            "severityText": "INFO",
                            "body": {"stringValue": "Application started"},
                        }
                    ],
                }
            ],
        }
    ],
}
_BATCH = {
    "resourceLogs": [
        {
            "resource": {
                "attributes": [
                    {
                        "key": "service.name",
                        "value": {"stringValue": "checkout"},
                    }
                ]
            },
            "scopeLogs": [
                {
                    "scope": {"name": "checkout.events"},
                    "logRecords": [
                        {
                            "eventName": "order.received",
                            "severityNumber": 9,
                            "body": {"stringValue": "Order received"},
                            "attributes": [
                                {"key": "order.id", "value": {"stringValue": "order-123"}}
                            ],
                        },
                        {
                            "eventName": "payment.completed",
                            "severityNumber": 9,
                            "body": {
                                "kvlistValue": {
                                    "values": [
                                        {"key": "order_id", "value": {"stringValue": "order-123"}},
                                        {"key": "amount", "value": {"doubleValue": 99.99}},
                                    ]
                                }
                            },
                        },
                    ],
                }
            ],
        }
    ],
}

# Description strings extracted so data lines stay within the 100-char line limit.
_D_ANY_VALUE = (
    "AnyValue — use stringValue, intValue, doubleValue, boolValue, arrayValue, or kvlistValue."
)
_D_INT_VALUE = "64-bit integer as a decimal string."
_D_TIME_NANO = (
    "UTC epoch nanoseconds as a decimal string. "
    "Falls back to observedTimeUnixNano, then server receipt time."
)
_D_OBS_NANO = "UTC epoch nanoseconds as a decimal string."
_D_SEVERITY = (
    "1–24 per the OTLP log model; maps to trace/debug/info/warn/error/fatal in groups of 4."
)
_D_BODY = "AnyValue — use stringValue for plain text, kvlistValue for structured data."
_D_ATTRS = "Per-record key/value attributes. Same AnyValue structure as resource attributes."
_D_TRACE_ID = "Lowercase hex string (16 bytes = 32 hex chars)."
_D_SPAN_ID = "Lowercase hex string (8 bytes = 16 hex chars)."
_D_PARTIAL = "Present only when some records were rejected. Absence means full success."
_D_REJECTED = "Number of records that were not admitted (decimal string)."
_D_ERR_MSG = "Human-readable reason. Do not retry records rejected here."
_D_PROTO_REQ = (
    "Serialized ExportLogsServiceRequest. Use an OpenTelemetry SDK or "
    "Collector exporter — binary Protobuf is not hand-editable. "
    "Set OTEL_EXPORTER_OTLP_LOGS_PROTOCOL=http/protobuf on your exporter."
)
_D_PROTO_RESP = (
    "Serialized ExportLogsServiceResponse. Returned when the request used application/x-protobuf."
)
_D_PROTO_ERR = (
    "Serialized google.rpc.Status. Returned when the request used application/x-protobuf."
)

OPENAPI: dict[str, Any] = {
    "description": (
        "Export one or many logs using ExportLogsServiceRequest. "
        "JSON uses resourceLogs → scopeLogs → logRecords; binary Protobuf uses the same schema. "
        "Optional timeUnixNano/observedTimeUnixNano are UTC epoch nanoseconds "
        "(decimal strings in JSON); missing timestamps fall back to server receipt time. "
        "The token determines project/app ownership. Content-Encoding: gzip is supported. "
        "Defaults: 300 records and 1 MiB raw/decompressed/normalized bytes per request; "
        "deployment configuration may change these limits. A 200 response acknowledges "
        "in-memory admission, not durable delivery. Do not retry partial success; "
        "retry 503 with backoff (no records were admitted)."
    ),
    "parameters": [
        {
            "name": "x-strumline-token",
            "in": "header",
            "required": True,
            "description": "App ingestion token; determines the destination project and app.",
            "schema": {"type": "string"},
        },
        {
            "name": "Content-Encoding",
            "in": "header",
            "required": False,
            "description": "Use gzip only when the request body is actually compressed.",
            "schema": {"type": "string", "enum": ["identity", "gzip"], "default": "identity"},
        },
    ],
    "requestBody": {
        "required": True,
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "title": "ExportLogsServiceRequest",
                    "properties": {
                        "resourceLogs": {
                            "type": "array",
                            "description": "One entry per resource (e.g. service instance).",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "resource": {
                                        "type": "object",
                                        "properties": {
                                            "attributes": {
                                                "type": "array",
                                                "items": {
                                                    "type": "object",
                                                    "properties": {
                                                        "key": {"type": "string"},
                                                        "value": {
                                                            "type": "object",
                                                            "description": _D_ANY_VALUE,
                                                            "properties": {
                                                                "stringValue": {"type": "string"},
                                                                "intValue": {
                                                                    "type": "string",
                                                                    "description": _D_INT_VALUE,
                                                                },
                                                                "doubleValue": {"type": "number"},
                                                                "boolValue": {"type": "boolean"},
                                                            },
                                                        },
                                                    },
                                                },
                                            },
                                        },
                                    },
                                    "schemaUrl": {"type": "string"},
                                    "scopeLogs": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "scope": {
                                                    "type": "object",
                                                    "properties": {
                                                        "name": {"type": "string"},
                                                        "version": {"type": "string"},
                                                    },
                                                },
                                                "schemaUrl": {"type": "string"},
                                                "logRecords": {
                                                    "type": "array",
                                                    "items": {
                                                        "type": "object",
                                                        "properties": {
                                                            "timeUnixNano": {
                                                                "type": "string",
                                                                "description": _D_TIME_NANO,
                                                            },
                                                            "observedTimeUnixNano": {
                                                                "type": "string",
                                                                "description": _D_OBS_NANO,
                                                            },
                                                            "severityNumber": {
                                                                "type": "integer",
                                                                "description": _D_SEVERITY,
                                                            },
                                                            "severityText": {"type": "string"},
                                                            "eventName": {"type": "string"},
                                                            "body": {
                                                                "type": "object",
                                                                "description": _D_BODY,
                                                                "properties": {
                                                                    "stringValue": {
                                                                        "type": "string"
                                                                    },
                                                                    "kvlistValue": {
                                                                        "type": "object",
                                                                        "properties": {
                                                                            "values": {
                                                                                "type": "array",
                                                                                "items": {
                                                                                    "type": "object"
                                                                                },
                                                                            }
                                                                        },
                                                                    },
                                                                },
                                                            },
                                                            "attributes": {
                                                                "type": "array",
                                                                "items": {"type": "object"},
                                                                "description": _D_ATTRS,
                                                            },
                                                            "traceId": {
                                                                "type": "string",
                                                                "description": _D_TRACE_ID,
                                                            },
                                                            "spanId": {
                                                                "type": "string",
                                                                "description": _D_SPAN_ID,
                                                            },
                                                            "flags": {"type": "integer"},
                                                            "droppedAttributesCount": {
                                                                "type": "integer"
                                                            },
                                                        },
                                                    },
                                                },
                                            },
                                        },
                                    },
                                },
                            },
                        }
                    },
                },
                "examples": {
                    "single": {"summary": "One runtime log", "value": _SINGLE},
                    "batch": {
                        "summary": "Two events, including a structured body",
                        "value": _BATCH,
                    },
                },
            },
            "application/x-protobuf": {
                "schema": {
                    "type": "string",
                    "format": "binary",
                    "description": _D_PROTO_REQ,
                },
            },
        },
    },
    "responses": {
        "200": {
            "description": "ExportLogsServiceResponse: full or partial success.",
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "title": "ExportLogsServiceResponse",
                        "properties": {
                            "partialSuccess": {
                                "type": "object",
                                "description": _D_PARTIAL,
                                "properties": {
                                    "rejectedLogRecords": {
                                        "type": "string",
                                        "description": _D_REJECTED,
                                    },
                                    "errorMessage": {
                                        "type": "string",
                                        "description": _D_ERR_MSG,
                                    },
                                },
                            }
                        },
                    },
                    "examples": {
                        "success": {"summary": "All records admitted", "value": {}},
                        "partial": {
                            "summary": "One record rejected; do not retry",
                            "value": {
                                "partialSuccess": {
                                    "rejectedLogRecords": "1",
                                    "errorMessage": (
                                        "Normalized logs exceed payload or IPC frame limits"
                                    ),
                                },
                            },
                        },
                    },
                },
                "application/x-protobuf": {
                    "schema": {
                        "type": "string",
                        "format": "binary",
                        "description": _D_PROTO_RESP,
                    },
                },
            },
        },
        **{
            str(status): {
                "description": description,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "title": "google.rpc.Status",
                            "properties": {
                                "message": {
                                    "type": "string",
                                    "description": "Human-readable error message.",
                                }
                            },
                        },
                        "example": {"message": message},
                    },
                    "application/x-protobuf": {
                        "schema": {
                            "type": "string",
                            "format": "binary",
                            "description": _D_PROTO_ERR,
                        },
                    },
                },
            }
            for status, description, message in (
                (
                    400,
                    "Invalid payload, gzip, or batch count/capacity.",
                    "Invalid OTLP logs payload",
                ),
                (401, "Missing, invalid, or revoked token.", "Missing x-strumline-token"),
                (
                    413,
                    "Raw or decompressed body exceeds the limit.",
                    "Request body exceeds MAX_PAYLOAD_BYTES",
                ),
                (415, "Unsupported media type or compression.", "Unsupported Content-Encoding"),
                (
                    503,
                    "Temporary authentication outage or full queue; retry with backoff.",
                    "Ingest queue is full; retry this batch",
                ),
            )
        },
    },
}
