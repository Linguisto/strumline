"""M1-A: Migration tests.

Verifies the schema set up by conftest._boot_test_db:
- All three tables exist with TIMESTAMPTZ columns
- UTC session round-trip returns timezone-aware UTC datetimes
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, insert, inspect, select

import tests.conftest as conf
from telemetria.db.models import ProjectModel
from telemetria.db.session import make_session_factory

pytestmark = pytest.mark.integration


def test_migration_creates_tables() -> None:
    engine = create_engine(conf.pg_sync_url)
    tables = inspect(engine).get_table_names()
    assert "projects" in tables
    assert "apps" in tables
    assert "auth_tokens" in tables
    engine.dispose()


def test_timestamp_columns_are_timestamptz() -> None:
    engine = create_engine(conf.pg_sync_url)
    insp = inspect(engine)

    for table, col_name in [
        ("projects", "created_at"),
        ("projects", "updated_at"),
        ("apps", "created_at"),
        ("apps", "updated_at"),
        ("auth_tokens", "created_at"),
        ("auth_tokens", "revoked_at"),
    ]:
        cols = {c["name"]: c for c in insp.get_columns(table)}
        assert col_name in cols, f"{table}.{col_name} missing"
        assert getattr(cols[col_name]["type"], "timezone", False), (
            f"{table}.{col_name} must be TIMESTAMPTZ"
        )

    engine.dispose()


@pytest.mark.asyncio
async def test_utc_session_round_trip() -> None:
    factory = make_session_factory(conf.pg_url)
    now = datetime.now(tz=UTC)
    project_id = uuid.uuid4()

    async with factory() as session, session.begin():
        await session.execute(
            insert(ProjectModel).values(
                id=project_id,
                slug=f"utc-{project_id.hex[:8]}",
                name="UTC Test",
                created_at=now,
                updated_at=now,
            )
        )

    async with factory() as session, session.begin():
        result = await session.execute(select(ProjectModel).where(ProjectModel.id == project_id))
        model = result.scalar_one()

    assert model.created_at.tzinfo is not None
    assert model.created_at.utcoffset().total_seconds() == 0  # type: ignore[union-attr]
    assert abs((model.created_at - now).total_seconds()) < 0.001
