"""CLI behavior tests for M7c-A (actionable failures) and M7c-B (scriptable use).

These drive the real Typer entry point with ``CliRunner`` and test doubles for
the control services, so no database is required. They assert exit codes, stream
placement, output parseability, and one-time token disclosure — not brittle
snapshots.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from strumline.cli.helpers import EXIT_UNAVAILABLE
from strumline.cli.main import app
from strumline.domain.errors import NotFoundError

pytestmark = pytest.mark.unit

# Click 8.2+ keeps stdout (machine output) and stderr (diagnostics) separate by
# default, so we can assert the M7c contract on stream placement directly.
runner = CliRunner()


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _App:
    id: uuid.UUID
    project_id: uuid.UUID
    slug: str
    name: str
    timezone: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class _Token:
    id: uuid.UUID


class _FakeSession:
    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def begin(self) -> _FakeSession:
        return self


def _fake_factory() -> object:
    """Return a callable that yields a no-op async session context manager."""

    def factory() -> _FakeSession:
        return _FakeSession()

    return factory


# ---------------------------------------------------------------------------
# M7c-A — malformed UUID is an actionable validation error, not a traceback
# ---------------------------------------------------------------------------


def test_token_create_malformed_uuid_exits_validation() -> None:
    result = runner.invoke(app, ["token", "create", "not-a-uuid"])
    assert result.exit_code == 2  # ValidationError.exit_code
    assert "not a valid UUID" in result.stderr
    assert result.stdout == ""


def test_token_revoke_malformed_app_uuid_exits_validation() -> None:
    result = runner.invoke(app, ["token", "revoke", "not-a-uuid", str(uuid.uuid4()), "--yes"])
    assert result.exit_code == 2
    assert "not a valid UUID" in result.stderr


# ---------------------------------------------------------------------------
# M7c-A — operational failure (DB unreachable) surfaces cleanly, not swallowed
# ---------------------------------------------------------------------------


def test_operational_failure_uses_unavailable_exit_code() -> None:
    def _boom() -> object:
        raise RuntimeError("connection refused to postgres://secret@host")

    with patch("strumline.cli.projects.get_factory", side_effect=_boom):
        result = runner.invoke(app, ["project", "show", "demo"])

    assert result.exit_code == EXIT_UNAVAILABLE
    # Diagnostics on stderr, actionable, and the secret-bearing message is not echoed.
    assert "Operational error" in result.stderr
    assert "secret" not in result.stderr
    assert "RuntimeError" in result.stderr
    assert result.stdout == ""


def test_domain_not_found_is_actionable_without_traceback() -> None:
    with (
        patch("strumline.cli.projects.get_factory", new=_fake_factory),
        patch(
            "strumline.control.projects.ProjectService.get",
            side_effect=NotFoundError("Project", "demo"),
        ),
    ):
        result = runner.invoke(app, ["project", "show", "demo"])

    assert result.exit_code == 4
    assert "not found" in result.stderr
    assert "Traceback" not in result.stderr


# ---------------------------------------------------------------------------
# M7c-B — scriptable app create: closed stdin, JSON on stdout, token once
# ---------------------------------------------------------------------------


def test_app_create_scriptable_emits_parseable_json_with_token() -> None:
    app_id = uuid.uuid4()
    token_id = uuid.uuid4()
    raw_key = "test-raw-token-key-value"
    now = datetime(2026, 9, 30, 12, 0, 0, tzinfo=UTC)
    created = _App(
        id=app_id,
        project_id=uuid.uuid4(),
        slug="web",
        name="Web",
        timezone=None,
        created_at=now,
        updated_at=now,
    )

    async def _create(self: object, *a: object, **k: object) -> _App:
        return created

    async def _token_create(self: object, *a: object, **k: object) -> tuple[_Token, str]:
        return _Token(id=token_id), raw_key

    with (
        patch("strumline.cli.apps.get_factory", new=_fake_factory),
        patch("strumline.control.apps.AppService.create", new=_create),
        patch("strumline.control.auth_tokens.AuthTokenService.create", new=_token_create),
    ):
        # Fully specified args + closed stdin (default for CliRunner) must not prompt.
        result = runner.invoke(app, ["app", "create", "demo", "web", "--name", "Web"])

    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)  # parses cleanly: no banners/ANSI
    assert payload["slug"] == "web"
    assert payload["token_id"] == str(token_id)
    assert payload["token_key"] == raw_key
    assert payload["created_at"].endswith("Z")


def test_app_show_never_discloses_token() -> None:
    app_id = uuid.uuid4()
    now = datetime(2026, 9, 30, 12, 0, 0, tzinfo=UTC)
    existing = _App(
        id=app_id,
        project_id=uuid.uuid4(),
        slug="web",
        name="Web",
        timezone=None,
        created_at=now,
        updated_at=now,
    )

    async def _get(self: object, *a: object, **k: object) -> _App:
        return existing

    with (
        patch("strumline.cli.apps.get_factory", new=_fake_factory),
        patch("strumline.control.apps.AppService.get", new=_get),
    ):
        result = runner.invoke(app, ["app", "show", "demo", "web"])

    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert "token_key" not in payload
    assert "token_id" not in payload


def test_token_create_emits_json_with_one_time_key() -> None:
    token_id = uuid.uuid4()
    app_id = uuid.uuid4()
    raw_key = "one-time-secret-key"

    async def _token_create(self: object, aid: uuid.UUID) -> tuple[_Token, str]:
        return _Token(id=token_id), raw_key

    with (
        patch("strumline.cli.auth_tokens.get_factory", new=_fake_factory),
        patch("strumline.control.auth_tokens.AuthTokenService.create", new=_token_create),
    ):
        result = runner.invoke(app, ["token", "create", str(app_id)])

    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["token_id"] == str(token_id)
    assert payload["token_key"] == raw_key


def test_missing_name_noninteractive_fails_fast() -> None:
    """A missing required field with closed stdin must fail, not hang or prompt."""
    result = runner.invoke(app, ["project", "create", "demo"])  # no --name, closed stdin
    assert result.exit_code == 2  # ValidationError
    assert "non-interactive" in result.stderr
    # No prompt text leaked onto stdout.
    assert "Name" not in result.stdout


def test_destructive_delete_without_yes_noninteractive_fails() -> None:
    """delete without --yes and no TTY must not be treated as consent."""
    result = runner.invoke(app, ["project", "delete", "demo"])
    assert result.exit_code == 2
    assert "--yes" in result.stderr
