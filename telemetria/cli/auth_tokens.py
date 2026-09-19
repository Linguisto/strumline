"""CLI: telemetria token create|revoke"""

from __future__ import annotations

import uuid

import typer
from rich.console import Console
from rich.panel import Panel

from telemetria.cli.helpers import get_app_key, get_factory, handle_error, prompt_select, run
from telemetria.cli.wizards import wizard_auth_token_create
from telemetria.control.auth_tokens import AuthTokenService
from telemetria.domain.errors import TelemetriaError

app = typer.Typer(help="Manage auth tokens.", no_args_is_help=True)


async def _fetch_app_choices() -> list[tuple[str, str]]:
    """Return [(label, app_id), ...] for all apps across all projects."""
    async with get_factory()() as session, session.begin():
        from telemetria.control.apps import AppService
        from telemetria.control.projects import ProjectService

        projects = await ProjectService(session).list_all()
        pairs = []
        for p in projects:
            apps = await AppService(session).list_all(str(p.id))
            for a in apps:
                pairs.append((f"{p.slug} / {a.slug}", str(a.id)))
        return pairs


@app.command("create")
def create(
    app_id: str = typer.Argument(None, help="App UUID."),
) -> None:
    """Create a new auth token for an app. Key is shown once — save it immediately."""
    if not app_id:
        try:
            choices = run(_fetch_app_choices())
        except Exception:
            choices = []
        app_id = wizard_auth_token_create(choices)

    async def _run() -> None:
        async with get_factory()() as session, session.begin():
            svc = AuthTokenService(session, get_app_key())
            token, raw_key = await svc.create(uuid.UUID(app_id))

        console = Console()
        console.print(
            Panel(
                f"[bold yellow]{raw_key}[/bold yellow]",
                title="Auth token key — save it now, shown only once",
                border_style="yellow",
            )
        )
        console.print(f"[dim]Token ID:[/dim]  {token.id}\n")

    try:
        run(_run())
    except TelemetriaError as e:
        handle_error(e)


@app.command("revoke")
def revoke(
    app_id: str = typer.Argument(None, help="App UUID."),
    token_id: str = typer.Argument(None, help="Token UUID to revoke."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Revoke an auth token."""
    # Resolve app
    if not app_id:
        try:
            choices = run(_fetch_app_choices())
        except Exception:
            choices = []
        if choices:
            labels = [label for label, _ in choices]
            selected = prompt_select("App", labels)
            uid: str = next(uid for label, uid in choices if label == selected)
            app_id = uid
        else:
            app_id = typer.prompt("App UUID")

    # Resolve token
    if not token_id:

        async def _fetch_tokens() -> list[tuple[str, str]]:
            async with get_factory()() as session, session.begin():
                svc = AuthTokenService(session, get_app_key())
                tokens = await svc.list_by_app(uuid.UUID(app_id))
                return [
                    (f"{str(d.id)[:8]}…  created {d.created_at.strftime('%Y-%m-%d')}", str(d.id))
                    for d in tokens
                    if d.is_active
                ]

        try:
            token_choices = run(_fetch_tokens())
        except Exception:
            token_choices = []

        if token_choices:
            labels = [label for label, _ in token_choices]
            selected = prompt_select("Token to revoke", labels)
            token_id = next(uid for label, uid in token_choices if label == selected)
        else:
            token_id = typer.prompt("Token UUID")

    if not yes:
        typer.confirm(f"Revoke token {token_id!r}?", abort=True)

    async def _run() -> None:
        async with get_factory()() as session, session.begin():
            svc = AuthTokenService(session, get_app_key())
            await svc.revoke(uuid.UUID(token_id), uuid.UUID(app_id))
            typer.echo(f"Revoked token {token_id!r}.")

    try:
        run(_run())
    except TelemetriaError as e:
        handle_error(e)
