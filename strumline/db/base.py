"""SQLAlchemy declarative base and shared mixins."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, MappedColumn, mapped_column


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


class TimestampMixin:
    """Adds UTC-aware ``created_at`` / ``updated_at`` columns.

    ``TIMESTAMPTZ`` stores the instant; the UTC session ensures Python
    datetimes are returned as timezone-aware UTC objects.
    """

    created_at: MappedColumn[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: MappedColumn[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
