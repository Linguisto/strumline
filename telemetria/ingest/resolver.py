"""DSN resolver for the ingest process.

Resolves a DSN key to its associated App metadata using the read-only ingest
database role. Results are cached with a 60-second TTL to keep hot paths off
the database.

Outage policy
-------------
On a database failure during a cache miss: **fail closed** — raise
``DSNResolverError`` so the request returns ``503``, rather than silently
accepting events for an unvalidated DSN.

On a database failure with a cached (possibly stale) entry: serve the cached
value. A revoked DSN may be accepted for up to one TTL period after revocation.
This is the documented best-effort behaviour.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from telemetria.db.models import AppModel, DSNModel

if TYPE_CHECKING:
    pass

log = logging.getLogger(__name__)

# Cache TTL in seconds — revoked DSNs remain valid for up to this period
DSN_CACHE_TTL: int = 60


class DSNResolverError(Exception):
    """Raised when the resolver cannot validate a DSN key."""


@dataclass(frozen=True)
class ResolvedDSN:
    """Routing metadata attached to every validated event."""

    dsn_id: str
    app_id: str
    app_slug: str
    project_id: str
    project_slug: str


@dataclass
class _CacheEntry:
    result: ResolvedDSN | None  # None means known-invalid (revoked/unknown)
    expires_at: float


class DSNResolver:
    """Thread-safe async DSN resolver with TTL cache.

    Parameters
    ----------
    factory:
        An ``async_sessionmaker`` bound to the **ingest** (read-only) DB role.
    ttl:
        Cache TTL in seconds. Defaults to ``DSN_CACHE_TTL`` (60 s).
    """

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        ttl: int = DSN_CACHE_TTL,
    ) -> None:
        self._factory = factory
        self._ttl = ttl
        self._cache: dict[str, _CacheEntry] = {}
        self._lock = asyncio.Lock()

    async def resolve(self, key: str) -> ResolvedDSN:
        """Resolve *key* to routing metadata.

        Returns a ``ResolvedDSN`` on success.

        Raises
        ------
        DSNResolverError
            DSN is unknown, revoked, or the database is unavailable on a
            cache miss.
        """
        now = time.monotonic()

        # Fast path: valid cached entry
        async with self._lock:
            entry = self._cache.get(key)
            if entry is not None and entry.expires_at > now:
                if entry.result is None:
                    raise DSNResolverError("DSN is revoked or unknown (cached)")
                return entry.result

        # Slow path: query the database
        try:
            result = await self._query(key)
        except DSNResolverError:
            # DB returned a definitive negative — cache it
            async with self._lock:
                self._cache[key] = _CacheEntry(
                    result=None,
                    expires_at=time.monotonic() + self._ttl,
                )
            raise
        except Exception as exc:
            # DB failure on a cache miss — fail closed
            log.warning("DSN resolver DB error (cache miss): %s", exc)
            raise DSNResolverError("DSN resolver unavailable and no cached result") from exc

        # Cache the positive result
        async with self._lock:
            self._cache[key] = _CacheEntry(
                result=result,
                expires_at=time.monotonic() + self._ttl,
            )
        return result

    async def _query(self, key: str) -> ResolvedDSN:
        """Query the database for *key*. Raises ``DSNResolverError`` if invalid."""
        async with self._factory() as session:
            row = await session.execute(
                select(DSNModel, AppModel)
                .join(AppModel, DSNModel.app_id == AppModel.id)
                .where(DSNModel.key == key)
            )
            result = row.one_or_none()

        if result is None:
            raise DSNResolverError("Unknown DSN key")

        dsn_model, app_model = result
        if not dsn_model.is_active:
            raise DSNResolverError("DSN has been revoked")

        # Eagerly load project via relationship — requires joined load or
        # explicit query. Use a second query to stay within SELECT grants.
        from telemetria.db.models import ProjectModel

        async with self._factory() as session:
            project = await session.get(ProjectModel, app_model.project_id)

        if project is None:
            raise DSNResolverError("DSN app has no parent project")

        return ResolvedDSN(
            dsn_id=str(dsn_model.id),
            app_id=str(app_model.id),
            app_slug=app_model.slug,
            project_id=str(project.id),
            project_slug=project.slug,
        )

    def invalidate(self, key: str) -> None:
        """Remove *key* from the cache (e.g. after a known revocation)."""
        self._cache.pop(key, None)

    def clear(self) -> None:
        """Clear the entire cache."""
        self._cache.clear()
