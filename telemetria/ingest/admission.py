"""Bounded HTTP body reading and auth token resolution for the ingest process.

Both helpers raise ``HTTPException`` directly so the route handler stays free
of auth/IO boilerplate.  Metrics counters are incremented here rather than in
the resolver so the accounting point is close to the HTTP boundary.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from telemetria.ingest.resolver import (
    AuthTokenResolver,
    AuthTokenResolverError,
    AuthTokenResolverUnavailable,
    ResolvedToken,
)
from telemetria.metrics import (
    INGEST_AUTH_TOKEN_CACHE_HITS_TOTAL,
    INGEST_AUTH_TOKEN_CACHE_MISSES_TOTAL,
)


async def read_body(request: Request, max_bytes: int) -> bytes:
    """Stream the request body, enforcing a hard byte cap before allocation.

    Raises ``HTTPException(413)`` as soon as the accumulated size exceeds
    *max_bytes*.  The check happens per chunk so memory usage stays bounded
    regardless of ``Content-Length`` headers.
    """
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > max_bytes:
            raise HTTPException(status_code=413, detail="Request body exceeds MAX_PAYLOAD_BYTES")
        body.extend(chunk)
    return bytes(body)


async def resolve_token(resolver: AuthTokenResolver, key: str) -> ResolvedToken:
    """Resolve *key* to routing metadata, mapping resolver errors to HTTP status.

    - Cache hit (valid) → returns ``ResolvedToken``, increments hit counter.
    - ``AuthTokenResolverUnavailable`` (DB outage on cache miss) → 503 retryable.
    - ``AuthTokenResolverError`` (unknown/revoked) → 401, increments miss counter.

    Internal exception messages are never forwarded to the caller.
    """
    try:
        result = await resolver.resolve(key)
        INGEST_AUTH_TOKEN_CACHE_HITS_TOTAL.inc()
        return result
    except AuthTokenResolverUnavailable:
        raise HTTPException(status_code=503, detail="Authentication service unavailable") from None
    except AuthTokenResolverError:
        INGEST_AUTH_TOKEN_CACHE_MISSES_TOTAL.inc()
        raise HTTPException(status_code=401, detail="Invalid or revoked auth token") from None
