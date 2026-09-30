"""Pure domain entities for the Strumline control plane.

All datetimes are timezone-aware UTC. No I/O, no ORM, no framework imports.
Entities are plain dataclasses — the ORM models in ``strumline.db`` map to
these shapes but are kept separate so the domain layer has no SQLAlchemy dep.
"""

from __future__ import annotations

import hashlib
import re
import zoneinfo
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID


class _Unset:
    """Sentinel distinguishing an omitted update field from an explicit null."""


UNSET = _Unset()

# Valid slug: lowercase ASCII letters, digits, hyphens; no leading/trailing hyphens
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$")


def _assert_slug(slug: str, field: str) -> None:
    if not _SLUG_RE.match(slug):
        raise ValueError(
            f"{field} must be lowercase ASCII letters, digits, and hyphens "
            f"(no leading/trailing hyphens), got {slug!r}"
        )


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


def hash_key(raw_key: str, app_key: str = "") -> str:
    """Return a hex digest of *raw_key* suitable for storage.

    When *app_key* is set: HMAC-SHA256(app_key, raw_key) — brute-force-resistant
    even if the database leaks.

    When *app_key* is empty: plain SHA-256 (development fallback — not safe for
    production).
    """
    if app_key:
        import hmac as _hmac

        return _hmac.new(app_key.encode(), raw_key.encode(), hashlib.sha256).hexdigest()
    import logging as _logging

    _logging.getLogger(__name__).warning(
        "APP_KEY is not set — using plain SHA-256. Set APP_KEY in production."
    )
    return hashlib.sha256(raw_key.encode()).hexdigest()


@dataclass(frozen=True)
class Project:
    id: UUID
    slug: str
    name: str
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        _assert_slug(self.slug, "Project.slug")
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
        _assert_slug(self.slug, "App.slug")
        _assert_utc(self.created_at, "App.created_at")
        _assert_utc(self.updated_at, "App.updated_at")
        if self.timezone is not None:
            try:
                zoneinfo.ZoneInfo(self.timezone)
            except zoneinfo.ZoneInfoNotFoundError as exc:
                raise ValueError(f"App.timezone: unknown IANA timezone {self.timezone!r}") from exc


@dataclass(frozen=True)
class AuthToken:
    id: UUID
    app_id: UUID
    key_hash: str  # SHA-256 hex of the raw key — raw key is never stored
    is_active: bool
    created_at: datetime
    revoked_at: datetime | None

    def __post_init__(self) -> None:
        _assert_utc(self.created_at, "AuthToken.created_at")
        if self.revoked_at is not None:
            _assert_utc(self.revoked_at, "AuthToken.revoked_at")


def _assert_utc(dt: datetime, field: str) -> None:
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise ValueError(f"{field} must be timezone-aware")
    offset = dt.tzinfo.utcoffset(dt)
    assert offset is not None  # guarded above
    if offset.total_seconds() != 0:
        raise ValueError(f"{field} must be UTC, got tzinfo={dt.tzinfo!r}")
