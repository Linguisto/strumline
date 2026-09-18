"""CLI: telemetria dsn create|list|revoke"""

from __future__ import annotations

import uuid
from dataclasses import asdict

import typer

from telemetria.cli.helpers import get_factory, handle_error, print_json, run
from telemetria.control.dsns import DSNService
from telemetria.domain.errors import TelemetriaError

app = typer.Typer(help="Manage DSNs.", no_args_is_help=True)


@app.command("create")
def create(
    app_id: str = typer.Argument(..., help="App UUID."),
) -> None:
    """Create a new DSN for an app. Key is shown once — save it immediately."""

    async def _run() -> None:
        async with get_factory()() as session, session.begin():
            svc = DSNService(session)
            dsn = await svc.create(uuid.UUID(app_id))
            print_json(asdict(dsn))

    try:
        run(_run())
    except TelemetriaError as e:
        handle_error(e)


@app.command("list")
def list_dsns(
    app_id: str = typer.Argument(..., help="App UUID."),
) -> None:
    """List DSNs for an app (keys are not shown in listings)."""

    async def _run() -> None:
        async with get_factory()() as session, session.begin():
            svc = DSNService(session)
            dsns = await svc.list_by_app(uuid.UUID(app_id))
            # Redact key in listings
            output = [{**asdict(d), "key": "***"} for d in dsns]
            print_json(output)

    try:
        run(_run())
    except TelemetriaError as e:
        handle_error(e)


@app.command("revoke")
def revoke(
    app_id: str = typer.Argument(..., help="App UUID."),
    dsn_id: str = typer.Argument(..., help="DSN UUID to revoke."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Revoke a DSN. Revoked DSNs are rejected immediately."""
    if not yes:
        typer.confirm(f"Revoke DSN {dsn_id!r}?", abort=True)

    async def _run() -> None:
        async with get_factory()() as session, session.begin():
            svc = DSNService(session)
            dsn = await svc.revoke(uuid.UUID(dsn_id), uuid.UUID(app_id))
            print_json({**asdict(dsn), "key": "***"})

    try:
        run(_run())
    except TelemetriaError as e:
        handle_error(e)
