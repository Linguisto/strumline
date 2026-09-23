"""Strumline CLI entry point.

Entry point: ``strumline``

Commands:
  list                  Tree view: projects → apps → tokens
  project create|show|delete
  app create|show|delete
  token create|revoke
  migrate
"""

from __future__ import annotations

import importlib.metadata

import typer

from strumline.cli import apps as app_cmd
from strumline.cli import auth_tokens as token_cmd
from strumline.cli import migrate as migrate_cmd
from strumline.cli import projects as project_cmd
from strumline.cli.info_cmd import app as info_app

app = typer.Typer(
    name="strumline",
    help="Strumline — best-effort structured telemetry collector.",
    add_completion=False,
    no_args_is_help=True,
)

app.add_typer(info_app, name="info")
app.add_typer(project_cmd.app, name="project")
app.add_typer(app_cmd.app, name="app")
app.add_typer(token_cmd.app, name="token")
app.command("migrate")(migrate_cmd.migrate)
app.add_typer(__import__("strumline.cli.doctor", fromlist=["app"]).app, name="doctor")
app.add_typer(__import__("strumline.cli.dashboard_cmd", fromlist=["app"]).app, name="dashboard")


def _version_callback(value: bool) -> None:
    if value:
        try:
            version = importlib.metadata.version("strumline")
        except importlib.metadata.PackageNotFoundError:
            version = "unknown"
        typer.echo(f"strumline {version}")
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
    """Strumline control-plane CLI."""


if __name__ == "__main__":
    app()
