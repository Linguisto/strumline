"""Auth token resolver for the ingest process.

Resolves an auth token key to its associated App metadata using the read-only ingest
database role. Results are cached with a 60-second TTL to keep hot paths off
the database.

Outage policy
-------------
On a database failure during a cache miss: **fail closed** — raise
``AuthTokenResolverError`` so the request returns ``503``, rather than silently
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

from telemetria.db.models import AppModel, AuthTokenModel

if TYPE_CHECKING:
    pass

log = logging.getLogger(__name__)

# Cache TTL in seconds — revoked auth tokens remain valid for up to this period
AUTH_TOKEN_CACHE_TTL: int = 60


class AuthTokenResolverError(Exception):
    """Raised when the resolver cannot validate an auth token key."""


class AuthTokenResolverUnavailable(AuthTokenResolverError):
    """Temporary database failure, allowing exporters to retry authentication."""


@dataclass(frozen=True)
class ResolvedToken:
    """Routing metadata attached to every validated event."""

    token_id: str
    app_id: str
    app_slug: str
    project_id: str
    project_slug: str


@dataclass
class _CacheEntry:
    result: ResolvedToken | None  # None means known-invalid (revoked/unknown)
    expires_at: float


class AuthTokenResolver:
    """Thread-safe async auth token resolver with TTL cache.

    Parameters
    ----------
    factory:
        An ``async_sessionmaker`` bound to the **ingest** (read-only) DB role.
    ttl:
        Cache TTL in seconds. Defaults to ``AUTH_TOKEN_CACHE_TTL`` (60 s).
    app_key:
        Application secret for HMAC hashing. Empty = plain SHA-256 (dev only).
    """

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        ttl: int = AUTH_TOKEN_CACHE_TTL,
        app_key: str = "",
    ) -> None:
        self._factory = factory
        self._ttl = ttl
        self._app_key = app_key
        self._cache: dict[str, _CacheEntry] = {}
        self._lock = asyncio.Lock()

    async def resolve(self, key: str) -> ResolvedToken:
        """Resolve *key* to routing metadata.

        Returns a ``ResolvedToken`` on success.

        Raises
        ------
        AuthTokenResolverError
            Auth token is unknown, revoked, or the database is unavailable on a
            cache miss.
        """
        now = time.monotonic()

        # Fast path: valid cached entry
        async with self._lock:
            entry = self._cache.get(key)
            if entry is not None and entry.expires_at > now:
                if entry.result is None:
                    raise AuthTokenResolverError("Auth token is revoked or unknown (cached)")
                return entry.result

        # Slow path: query the database
        try:
            result = await self._query(key)
        except AuthTokenResolverError:
            # DB returned a definitive negative — cache it
            async with self._lock:
                self._cache[key] = _CacheEntry(
                    result=None,
                    expires_at=time.monotonic() + self._ttl,
                )
            raise
        except Exception as exc:
            # DB failure on a cache miss — fail closed
            log.warning("Auth token resolver DB error (cache miss): %s", exc)
            raise AuthTokenResolverUnavailable("Resolver unavailable — no cached result") from exc

        # Cache the positive result
        async with self._lock:
            self._cache[key] = _CacheEntry(
                result=result,
                expires_at=time.monotonic() + self._ttl,
            )
        return result

    async def _query(self, key: str) -> ResolvedToken:
        """Query the database for *key*. Raises ``AuthTokenResolverError`` if invalid."""
        from telemetria.domain.entities import hash_key as _hash_key

        key_hash = _hash_key(key, self._app_key)
        async with self._factory() as session:
            row = await session.execute(
                select(AuthTokenModel, AppModel)
                .join(AppModel, AuthTokenModel.app_id == AppModel.id)
                .where(AuthTokenModel.key_hash == key_hash)
            )
            result = row.one_or_none()

        if result is None:
            raise AuthTokenResolverError("Unknown auth token key")

        token_model, app_model = result
        if not token_model.is_active:
            raise AuthTokenResolverError("Auth token has been revoked")

        # Eagerly load project via relationship — requires joined load or
        # explicit query. Use a second query to stay within SELECT grants.
        from telemetria.db.models import ProjectModel

        async with self._factory() as session:
            project = await session.get(ProjectModel, app_model.project_id)

        if project is None:
            raise AuthTokenResolverError("Auth token app has no parent project")

        return ResolvedToken(
            token_id=str(token_model.id),
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
