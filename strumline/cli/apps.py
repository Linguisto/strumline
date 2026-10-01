"""CLI: strumline app create|show|delete"""

from __future__ import annotations

from dataclasses import asdict

import typer

from strumline.cli.helpers import (
    confirm_destructive,
    get_app_key,
    get_factory,
    print_json,
    prompt_select,
    require_arg,
    run_command,
)
from strumline.cli.wizards import wizard_app_create
from strumline.control.apps import AppService

app = typer.Typer(help="Manage apps.", no_args_is_help=True)


async def _fetch_project_slugs() -> list[str]:
    async with get_factory()() as session, session.begin():
        from strumline.control.projects import ProjectService

        return [p.slug for p in await ProjectService(session).list_all()]


@app.command("create")
def create(
    project: str = typer.Argument(None, help="Project slug or UUID."),
    slug: str = typer.Argument(None, help="App slug (unique within project)."),
    name: str = typer.Option(None, "--name", "-n", help="Display name."),
    timezone: str | None = typer.Option(None, "--timezone", "-z", help="IANA display timezone."),
) -> None:
    """Create a new app in a project.

    Fully specified (``project``, ``slug``, ``--name``) it is non-interactive and
    scriptable. Its result — including the one-time auth token — is written as
    JSON to stdout so scripts can capture it. Missing fields trigger prompts only
    when attached to a TTY; non-interactive callers get actionable guidance.
    """

    async def _run() -> None:
        nonlocal project, slug, name, timezone
        if not project and not slug and not name:
            fields = wizard_app_create(await _fetch_project_slugs())
            project = fields["project"]
            name = fields["name"]
            slug = fields["slug"]
            timezone = timezone or (fields["timezone"] or None)
        else:
            if not project:
                slugs = await _fetch_project_slugs()
                project = (
                    prompt_select("Project", slugs)
                    if slugs
                    else require_arg(None, "project", example="app create <project> <slug>")
                )
            name = require_arg(name, "name", example="--name 'Web'")
            slug = require_arg(slug, "slug", example="app create <project> web")

        async with get_factory()() as session, session.begin():
            svc = AppService(session)
            result = await svc.create(project, slug, name, tz=timezone)

            # Automatically create the first auth token
            from strumline.control.auth_tokens import AuthTokenService

            token, raw_key = await AuthTokenService(session, get_app_key()).create(result.id)

        # Machine-readable creation result on stdout. The raw token key is only
        # ever emitted here, in the explicit creation result — never in
        # list/show/log output.
        payload = asdict(result)
        payload["token_id"] = str(token.id)
        payload["token_key"] = raw_key
        print_json(payload)

    run_command(_run())


@app.command("show")
def show(
    project: str = typer.Argument(..., help="Project slug or UUID."),
    app_id: str = typer.Argument(..., help="App slug or UUID."),
) -> None:
    """Show app details as JSON."""

    async def _run() -> None:
        async with get_factory()() as session, session.begin():
            svc = AppService(session)
            result = await svc.get(project, app_id)
            print_json(asdict(result))

    run_command(_run())


@app.command("delete")
def delete(
    project: str = typer.Argument(..., help="Project slug or UUID."),
    app_id: str = typer.Argument(..., help="App slug or UUID."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Delete an app and all its auth tokens."""

    async def _run() -> None:
        if not yes:
            confirm_destructive(f"Delete app {app_id!r} and all its auth tokens?")
        async with get_factory()() as session, session.begin():
            svc = AppService(session)
            await svc.delete(project, app_id)
            typer.echo(f"Deleted app {app_id!r}.")

    run_command(_run())
