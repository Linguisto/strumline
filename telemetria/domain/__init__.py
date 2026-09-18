"""Domain entities and errors — pure Python, no I/O dependencies."""

from telemetria.domain.entities import DSN, App, Project
from telemetria.domain.errors import (
    AlreadyRevokedError,
    ConflictError,
    NotFoundError,
    OwnershipError,
    TelemetriaError,
    ValidationError,
)
from telemetria.domain.events import Event, EventBatch

__all__ = [
    "App",
    "DSN",
    "Project",
    "AlreadyRevokedError",
    "ConflictError",
    "NotFoundError",
    "OwnershipError",
    "TelemetriaError",
    "ValidationError",
    "Event",
    "EventBatch",
]
