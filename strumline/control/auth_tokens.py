"""AuthToken application service."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from strumline.db.repositories import AppRepository, AuthTokenRepository
from strumline.domain.entities import AuthToken, hash_key
from strumline.domain.errors import OwnershipError


class AuthTokenService:
    def __init__(self, session: AsyncSession, app_key: str = "") -> None:
        self._repo = AuthTokenRepository(session)
        self._apps = AppRepository(session)
        self._app_key = app_key

    async def create(self, app_id: uuid.UUID) -> tuple[AuthToken, str]:
        """Create a new active auth token for *app_id*.

        Returns (token, raw_key). The raw key is never stored — show it once
        and discard it. The token entity carries only the HMAC-SHA256 hash.
        """
        await self._apps.get_by_id(app_id)
        raw_key = secrets.token_urlsafe(32)  # 256 bits of entropy, ~43 chars
        now = datetime.now(tz=UTC)
        token = AuthToken(
            id=uuid.uuid4(),
            app_id=app_id,
            key_hash=hash_key(raw_key, self._app_key),
            is_active=True,
            created_at=now,
            revoked_at=None,
        )
        stored = await self._repo.create(token)
        return stored, raw_key

    async def list_by_app(self, app_id: uuid.UUID) -> list[AuthToken]:
        await self._apps.get_by_id(app_id)
        return await self._repo.list_by_app(app_id)

    async def revoke(self, token_id: uuid.UUID, app_id: uuid.UUID) -> AuthToken:
        """Revoke *token_id*, verifying it belongs to *app_id*."""
        token = await self._repo.get_by_id(token_id)
        if token.app_id != app_id:
            raise OwnershipError("AuthToken", str(token_id), str(app_id))
        return await self._repo.revoke(token_id)
