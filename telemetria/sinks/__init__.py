"""Sink contract, errors, NullSink, and registry.

``BatchProcessor`` imports only ``EventSink``, ``RetryableSinkError``, and
``PermanentSinkError`` — never a concrete provider.

``SINK_PROVIDER=null`` selects ``NullSink`` (default for v1 testing).
``SINK_PROVIDER=loki`` will be registered in M3.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from telemetria.domain.events import EventBatch

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------


class RetryableSinkError(Exception):
    """Transient failure — the batch should be retried with backoff."""


class PermanentSinkError(Exception):
    """Non-recoverable failure — discard the batch and continue."""


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class EventSink(ABC):
    """Abstract base for all event sink providers."""

    name: str = "abstract"

    @abstractmethod
    async def write(self, batch: EventBatch) -> None:
        """Write *batch* to the sink.

        Raises
        ------
        RetryableSinkError
            The write failed but may succeed on retry.
        PermanentSinkError
            The write failed and must not be retried.
        """

    async def close(self) -> None:  # noqa: B027
        """Release any resources held by this sink. Called on shutdown."""
        # Default implementation is a no-op; providers override as needed.


# ---------------------------------------------------------------------------
# NullSink
# ---------------------------------------------------------------------------


class NullSink(EventSink):
    """Discards all events. Used for testing and as the default v1 provider."""

    name = "null"

    def __init__(self) -> None:
        self._written: int = 0

    @property
    def written(self) -> int:
        return self._written

    async def write(self, batch: EventBatch) -> None:
        self._written += len(batch)
        log.debug("NullSink discarded %d events (total=%d)", len(batch), self._written)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, type[EventSink]] = {
    "null": NullSink,
}


def register_sink(name: str, cls: type[EventSink]) -> None:
    """Register a new sink provider. Called by M3+ during app startup."""
    _REGISTRY[name] = cls


def get_sink(provider: str) -> EventSink:
    """Instantiate the sink selected by *provider* name.

    Raises
    ------
    ValueError
        Unknown provider name.
    """
    cls = _REGISTRY.get(provider)
    if cls is None:
        known = ", ".join(sorted(_REGISTRY))
        raise ValueError(f"Unknown SINK_PROVIDER={provider!r}. Known providers: {known}")
    return cls()
