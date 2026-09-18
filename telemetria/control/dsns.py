"""DSN application service."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from telemetria.db.repositories import AppRepository, DSNRepository
from telemetria.domain.entities import DSN
from telemetria.domain.errors import OwnershipError


class DSNService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = DSNRepository(session)
        self._apps = AppRepository(session)

    async def create(self, app_id: uuid.UUID) -> DSN:
        """Create a new active DSN for *app_id*. Key is revealed once."""
        # Verify app exists
        await self._apps.get_by_id(app_id)
        now = datetime.now(tz=UTC)
        dsn = DSN(
            id=uuid.uuid4(),
            app_id=app_id,
            key=secrets.token_urlsafe(32),  # 256 bits of entropy, ~43 chars
            is_active=True,
            created_at=now,
            revoked_at=None,
        )
        return await self._repo.create(dsn)

    async def list_by_app(self, app_id: uuid.UUID) -> list[DSN]:
        await self._apps.get_by_id(app_id)
        return await self._repo.list_by_app(app_id)

    async def revoke(self, dsn_id: uuid.UUID, app_id: uuid.UUID) -> DSN:
        """Revoke *dsn_id*, verifying it belongs to *app_id*."""
        dsn = await self._repo.get_by_id(dsn_id)
        if dsn.app_id != app_id:
            raise OwnershipError("DSN", str(dsn_id), str(app_id))
        return await self._repo.revoke(dsn_id)
