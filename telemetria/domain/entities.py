"""Pure domain entities for the Telemetria control plane.

All datetimes are timezone-aware UTC. No I/O, no ORM, no framework imports.
Entities are plain dataclasses — the ORM models in ``telemetria.db`` map to
these shapes but are kept separate so the domain layer has no SQLAlchemy dep.
"""

from __future__ import annotations

import zoneinfo
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


@dataclass(frozen=True)
class Project:
    id: UUID
    slug: str
    name: str
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        _assert_utc(self.created_at, "Project.created_at")
        _assert_utc(self.updated_at, "Project.updated_at")


@dataclass(frozen=True)
class App:
    id: UUID
    project_id: UUID
    slug: str
    name: str
    timezone: str | None  # validated IANA identifier; presentation only
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        _assert_utc(self.created_at, "App.created_at")
        _assert_utc(self.updated_at, "App.updated_at")
        if self.timezone is not None:
            try:
                zoneinfo.ZoneInfo(self.timezone)
            except zoneinfo.ZoneInfoNotFoundError as exc:
                raise ValueError(f"App.timezone: unknown IANA timezone {self.timezone!r}") from exc


@dataclass(frozen=True)
class DSN:
    id: UUID
    app_id: UUID
    key: str  # secrets.token_urlsafe(32) — revealed once, stored as plaintext in v1
    is_active: bool
    created_at: datetime
    revoked_at: datetime | None

    def __post_init__(self) -> None:
        _assert_utc(self.created_at, "DSN.created_at")
        if self.revoked_at is not None:
            _assert_utc(self.revoked_at, "DSN.revoked_at")


def _assert_utc(dt: datetime, field: str) -> None:
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise ValueError(f"{field} must be timezone-aware")
    offset = dt.tzinfo.utcoffset(dt)
    assert offset is not None  # guarded above
    if offset.total_seconds() != 0:
        raise ValueError(f"{field} must be UTC, got tzinfo={dt.tzinfo!r}")
