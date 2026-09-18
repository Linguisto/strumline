"""Telemetria CLI entry point.

Entry point: ``telemetria``

M0: --help / --version
M1: migrate, project CRUD, app CRUD, app timezone, dsn create/list/revoke
"""

from __future__ import annotations

import importlib.metadata

import typer

from telemetria.cli import apps as app_cmd
from telemetria.cli import dsns as dsn_cmd
from telemetria.cli import migrate as migrate_cmd
from telemetria.cli import projects as project_cmd

app = typer.Typer(
    name="telemetria",
    help="Telemetria — best-effort structured telemetry collector.",
    add_completion=False,
    no_args_is_help=True,
)

app.add_typer(project_cmd.app, name="project")
app.add_typer(app_cmd.app, name="app")
app.add_typer(dsn_cmd.app, name="dsn")
app.command("migrate")(migrate_cmd.migrate)


def _version_callback(value: bool) -> None:
    if value:
        try:
            version = importlib.metadata.version("telemetria")
        except importlib.metadata.PackageNotFoundError:
            version = "unknown"
        typer.echo(f"telemetria {version}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """Telemetria control-plane CLI."""


if __name__ == "__main__":
    app()
