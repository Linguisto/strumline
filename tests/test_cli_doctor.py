"""Unit tests for strumline doctor and config validate CLI commands."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from strumline.cli.main import app

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
    with patch("strumline.cli.doctor._run_checks", new=AsyncMock(return_value=_ALL_OK)):
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
    with patch("strumline.cli.doctor._run_checks", new=AsyncMock(return_value=checks)):
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
    with patch("strumline.cli.doctor._run_checks", new=AsyncMock(return_value=checks)):
        result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 0


def test_doctor_plain_output() -> None:
    """--plain produces text table with SERVICE/STATUS/DETAIL headers."""
    with patch("strumline.cli.doctor._run_checks", new=AsyncMock(return_value=_ALL_OK)):
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
    with patch("strumline.cli.doctor._run_checks", new=AsyncMock(return_value=checks)):
        result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 1
    data = json.loads(result.output)
    failed = [r for r in data if r["status"] == _FAIL]
    assert len(failed) == 2


# ---------------------------------------------------------------------------
# M7c-C — actionable next steps, config reporting, and redaction
# ---------------------------------------------------------------------------


def test_doctor_failed_check_includes_next_step() -> None:
    """A failing required check carries an actionable next_step field."""
    from strumline.cli.doctor import _check_result

    row = _check_result("postgres", _FAIL, "OperationalError")
    assert row["next_step"]  # non-empty guidance
    assert "PostgreSQL" in row["next_step"] or "DB_HOST" in row["next_step"]

    with patch("strumline.cli.doctor._run_checks", new=AsyncMock(return_value=[row])):
        result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data[0]["next_step"]


def test_doctor_redacts_connection_errors() -> None:
    """A DB failure surfaces the exception type only — never a DSN/password."""
    from strumline.cli.doctor import _check_postgres

    def _boom_factory(*_a: object, **_k: object) -> object:
        raise RuntimeError("connect failed: postgresql://u:sup3rsecret@db:5432/x")

    # _check_postgres imports make_session_factory from strumline.db.session.
    with patch("strumline.db.session.make_session_factory", side_effect=_boom_factory):
        import asyncio as _aio

        row = _aio.run(_check_postgres())

    assert row["status"] == _FAIL
    assert "sup3rsecret" not in row["detail"]
    assert "postgresql://" not in row["detail"]
    assert row["detail"] == "RuntimeError"


def test_doctor_reports_invalid_configuration() -> None:
    """Invalid settings produce an explicit failing 'config' row, not silent defaults."""
    import strumline.config as cfg

    def _raise(self: object, *a: object, **k: object) -> None:
        raise ValueError("API_PORT must be 1-65535, got 999999")

    with (
        patch.object(cfg.APISettings, "__init__", _raise),
        patch(
            "strumline.cli.doctor._check_http",
            new=AsyncMock(
                return_value={
                    "service": "api",
                    "status": _FAIL,
                    "detail": "x",
                    "next_step": "y",
                }
            ),
        ),
        patch(
            "strumline.cli.doctor._check_postgres",
            new=AsyncMock(
                return_value={
                    "service": "postgres",
                    "status": _FAIL,
                    "detail": "x",
                    "next_step": "y",
                }
            ),
        ),
        patch(
            "strumline.cli.doctor._check_migrations",
            new=AsyncMock(
                return_value={
                    "service": "migrations",
                    "status": _FAIL,
                    "detail": "x",
                    "next_step": "y",
                }
            ),
        ),
    ):
        import asyncio as _aio

        from strumline.cli.doctor import _run_checks

        results = _aio.run(_run_checks())

    config_rows = [r for r in results if r["service"] == "config"]
    assert len(config_rows) == 1
    assert config_rows[0]["status"] == _FAIL
    assert config_rows[0]["next_step"]
    # Exception type only — no raw config values leaked.
    assert config_rows[0]["detail"] == "ValueError"
