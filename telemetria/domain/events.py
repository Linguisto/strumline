"""Event and EventBatch domain entities.

These are the canonical representations that cross the IPC boundary.
Both entities are pure dataclasses with no I/O dependencies.

UTC invariant
-------------
- ``received_at`` is always server-generated UTC.
- ``timestamp`` is the client timestamp normalized to UTC, or ``received_at``
  if the client value was missing, naive, malformed, or out of range.
- Neither field ever carries a non-UTC timezone or an offset string.
- Serialization always emits a trailing ``Z`` (see ``to_dict``).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID


def _assert_utc(dt: datetime, field_name: str) -> None:
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    if dt.utcoffset().total_seconds() != 0:  # type: ignore[union-attr]
        raise ValueError(f"{field_name} must be UTC, got tzinfo={dt.tzinfo!r}")


@dataclass(frozen=True)
class Event:
    """A single normalized telemetry event.

    All datetimes are timezone-aware UTC.  Project and app metadata is embedded
    so the processor never needs to query PostgreSQL.
    """

    id: UUID
    project_id: UUID
    project_slug: str
    app_id: UUID
    app_slug: str
    received_at: datetime  # server-generated UTC
    timestamp: datetime  # client time normalized to UTC, or received_at
    level: str
    message: str
    payload: dict[str, Any]

    def __post_init__(self) -> None:
        _assert_utc(self.received_at, "Event.received_at")
        _assert_utc(self.timestamp, "Event.timestamp")

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict with UTC timestamps ending in Z."""
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "project_slug": self.project_slug,
            "app_id": str(self.app_id),
            "app_slug": self.app_slug,
            "received_at": self.received_at.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z",
            "timestamp": self.timestamp.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z",
            "level": self.level,
            "message": self.message,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Event:
        """Deserialize from a dict produced by ``to_dict``."""
        return cls(
            id=UUID(d["id"]),
            project_id=UUID(d["project_id"]),
            project_slug=d["project_slug"],
            app_id=UUID(d["app_id"]),
            app_slug=d["app_slug"],
            received_at=_parse_utc(d["received_at"]),
            timestamp=_parse_utc(d["timestamp"]),
            level=d["level"],
            message=d["message"],
            payload=d["payload"],
        )


@dataclass(frozen=True)
class EventBatch:
    """An ordered sequence of events dispatched to a sink as a unit."""

    events: tuple[Event, ...]

    def __len__(self) -> int:
        return len(self.events)

    def __iter__(self) -> Iterator[Event]:
        return iter(self.events)


def _parse_utc(value: str) -> datetime:
    """Parse an ISO-8601 UTC string (trailing Z) into a timezone-aware datetime."""
    # Replace trailing Z with +00:00 for fromisoformat compatibility
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
