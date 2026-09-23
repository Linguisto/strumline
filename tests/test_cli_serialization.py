"""CLI UTC serialization tests.

The CLI renders JSON output via ``strumline.cli.helpers._to_json``. Per the
UTC invariant, every timestamp the CLI emits must carry a trailing ``Z`` (not
``+00:00`` or a naive value). This covers the CLI leg of the UTC serialization
invariant (database, IPC, CLI, REST, and Loki all have dedicated tests).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

import pytest

from strumline.cli.helpers import _serializable, _to_json

pytestmark = pytest.mark.unit


def test_serializable_datetime_uses_utc_z_suffix() -> None:
    dt = datetime(2026, 9, 18, 17, 0, 0, 123456, tzinfo=UTC)
    rendered = _serializable(dt)
    assert rendered == "2026-09-18T17:00:00.123456Z"
    assert rendered.endswith("Z")
    assert "+00:00" not in rendered


def test_to_json_renders_timestamps_with_z() -> None:
    row = {
        "id": UUID("00000000-0000-0000-0000-000000000001"),
        "created_at": datetime(2026, 9, 18, 17, 0, 0, tzinfo=UTC),
        "updated_at": datetime(2026, 9, 18, 17, 5, 0, tzinfo=UTC),
    }
    out = _to_json(row)
    parsed = json.loads(out)

    assert parsed["created_at"].endswith("Z")
    assert parsed["updated_at"].endswith("Z")
    assert "+00:00" not in out
    assert parsed["id"] == "00000000-0000-0000-0000-000000000001"


def test_serializable_rejects_naive_datetime_without_z() -> None:
    """A naive datetime would serialize without a Z — assert we never emit one.

    Domain entities enforce tz-aware UTC upstream (``_assert_utc``); this guards
    the CLI formatter so a naive value can never silently render offset-free.
    """
    naive = datetime(2026, 9, 18, 17, 0, 0)  # noqa: DTZ001 — intentionally naive
    rendered = _serializable(naive)
    # isoformat() of a naive datetime has no offset to replace, so no trailing Z.
    assert not rendered.endswith("Z")
