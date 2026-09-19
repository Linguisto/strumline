"""Domain errors for the Telemetria control plane.

Each error carries:
- ``exit_code``: used by the CLI
- ``http_status``: used by the admin REST API (M6b)

These are raised by control services and translated at the boundary (CLI or
HTTP handler). Control services never import typer, fastapi, or sys.exit.
"""

from __future__ import annotations


class TelemetriaError(Exception):
    """Base for all domain errors."""

    exit_code: int = 1
    http_status: int = 500


class NotFoundError(TelemetriaError):
    """Requested resource does not exist."""

    exit_code = 4
    http_status = 404

    def __init__(self, resource: str, identifier: str) -> None:
        super().__init__(f"{resource} not found: {identifier!r}")
        self.resource = resource
        self.identifier = identifier


class ConflictError(TelemetriaError):
    """Resource already exists (slug or other unique constraint)."""

    exit_code = 9
    http_status = 409

    def __init__(self, resource: str, field: str, value: str) -> None:
        super().__init__(f"{resource} with {field}={value!r} already exists")
        self.resource = resource
        self.field = field
        self.value = value


class OwnershipError(TelemetriaError):
    """Resource does not belong to the specified parent."""

    exit_code = 4  # treated as not-found to avoid leaking existence
    http_status = 404

    def __init__(self, resource: str, identifier: str, parent: str) -> None:
        super().__init__(f"{resource} {identifier!r} does not belong to {parent!r}")
        self.resource = resource
        self.identifier = identifier
        self.parent = parent


class ValidationError(TelemetriaError):
    """Input failed domain validation (e.g. invalid IANA timezone)."""

    exit_code = 2
    http_status = 422

    def __init__(self, field: str, message: str) -> None:
        super().__init__(f"Validation error on {field!r}: {message}")
        self.field = field
        self.message = message


class AlreadyRevokedError(TelemetriaError):
    """Auth token is already revoked."""

    exit_code = 9
    http_status = 409

    def __init__(self, token_id: str) -> None:
        super().__init__(f"Auth token {token_id!r} is already revoked")
        self.token_id = token_id
