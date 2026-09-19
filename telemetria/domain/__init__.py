"""Domain entities and errors — pure Python, no I/O dependencies."""

from telemetria.domain.entities import App, AuthToken, Project, hash_key
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
    "AuthToken",
    "Project",
    "hash_key",
    "AlreadyRevokedError",
    "ConflictError",
    "NotFoundError",
    "OwnershipError",
    "TelemetriaError",
    "ValidationError",
    "Event",
    "EventBatch",
]
