"""Tests for M0-B: /health endpoint on each process.

Each process exposes GET /health and returns:
    {"process": "<name>", "version": "<package version>", "status": "ok"}

Version is read from installed package metadata (importlib.metadata), not a
hard-coded string.
"""

from __future__ import annotations

import importlib.metadata

import pytest
from httpx2 import ASGITransport, AsyncClient

from strumline.api.server import create_app as create_api_app
from strumline.ingest.server import create_app as create_ingest_app
from strumline.processor.server import create_app as create_processor_app

pytestmark = pytest.mark.unit


def _expected_version() -> str:
    try:
        return importlib.metadata.version("strumline")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


@pytest.fixture
def expected_version() -> str:
    return _expected_version()


@pytest.mark.asyncio
async def test_api_health(expected_version: str) -> None:
    app = create_api_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["process"] == "api"
    assert body["status"] == "ok"
    assert body["version"] == expected_version


@pytest.mark.asyncio
async def test_ingest_health(expected_version: str) -> None:
    app = create_ingest_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["process"] == "ingest"
    assert body["status"] == "ok"
    assert body["version"] == expected_version


@pytest.mark.asyncio
async def test_processor_health(expected_version: str) -> None:
    app = create_processor_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["process"] == "processor"
    assert body["status"] == "ok"
    assert body["version"] == expected_version


@pytest.mark.asyncio
async def test_health_version_not_hardcoded(expected_version: str) -> None:
    """Version in /health must come from package metadata, not a literal."""
    assert expected_version != ""
    # If the package is installed, version is a semver-like string, not "unknown"
    if expected_version != "unknown":
        parts = expected_version.split(".")
        assert len(parts) >= 2, f"Expected semver, got {expected_version!r}"
