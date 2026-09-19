"""Unit tests for telemetria doctor and config validate CLI commands."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from telemetria.cli.main import app

pytestmark = pytest.mark.unit

runner = CliRunner()

_OK = "ok"
_FAIL = "fail"
_SKIP = "skip"

_ALL_OK = [
    {"service": "api", "status": _OK, "detail": "version=0.1.0"},
    {"service": "ingest", "status": _OK, "detail": "version=0.1.0"},
    {"service": "processor", "status": _OK, "detail": "version=0.1.0"},
    {"service": "postgres", "status": _OK, "detail": "PostgreSQL 18"},
    {"service": "migrations", "status": _OK, "detail": "head=0001"},
    {"service": "loki", "status": _OK, "detail": "http://loki:3100"},
]


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------


def test_doctor_all_ok_json() -> None:
    """All checks pass → exit 0, JSON output with all 'ok'."""
    with patch("telemetria.cli.doctor._run_checks", new=AsyncMock(return_value=_ALL_OK)):
        result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    statuses = {row["service"]: row["status"] for row in data}
    assert all(s == _OK for s in statuses.values())


def test_doctor_failed_service_exits_1() -> None:
    """A failing required service → exit 1."""
    checks = [
        {"service": "api", "status": _FAIL, "detail": "connection refused"},
        {"service": "ingest", "status": _OK, "detail": "version=0.1.0"},
        {"service": "processor", "status": _OK, "detail": "version=0.1.0"},
        {"service": "postgres", "status": _OK, "detail": "ok"},
        {"service": "migrations", "status": _OK, "detail": "ok"},
    ]
    with patch("telemetria.cli.doctor._run_checks", new=AsyncMock(return_value=checks)):
        result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 1
    data = json.loads(result.output)
    statuses = {row["service"]: row["status"] for row in data}
    assert statuses["api"] == _FAIL


def test_doctor_skip_does_not_fail() -> None:
    """Optional services with status 'skip' do not cause exit 1."""
    checks = _ALL_OK + [
        {"service": "prometheus", "status": _SKIP, "detail": "not configured"},
    ]
    with patch("telemetria.cli.doctor._run_checks", new=AsyncMock(return_value=checks)):
        result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 0


def test_doctor_plain_output() -> None:
    """--plain produces text table with SERVICE/STATUS/DETAIL headers."""
    with patch("telemetria.cli.doctor._run_checks", new=AsyncMock(return_value=_ALL_OK)):
        result = runner.invoke(app, ["doctor", "--plain"])
    assert result.exit_code == 0
    assert "SERVICE" in result.output
    assert "api" in result.output
    assert "postgres" in result.output


def test_doctor_multiple_failures() -> None:
    """Multiple failing services all appear in JSON output."""
    checks = [
        {"service": "api", "status": _FAIL, "detail": "timeout"},
        {"service": "ingest", "status": _FAIL, "detail": "timeout"},
        {"service": "postgres", "status": _OK, "detail": "ok"},
        {"service": "migrations", "status": _OK, "detail": "ok"},
    ]
    with patch("telemetria.cli.doctor._run_checks", new=AsyncMock(return_value=checks)):
        result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 1
    data = json.loads(result.output)
    failed = [r for r in data if r["status"] == _FAIL]
    assert len(failed) == 2
