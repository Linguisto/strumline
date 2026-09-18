"""CLI: telemetria migrate"""

from __future__ import annotations

import typer


def migrate(
    dry_run: bool = typer.Option(False, "--dry-run", help="Print SQL without executing."),
) -> None:
    """Run database migrations to the latest revision."""
    from alembic.config import Config

    from alembic import command

    alembic_cfg = Config("alembic.ini")
    if dry_run:
        # Generate SQL script to stdout without connecting
        from io import StringIO

        buf = StringIO()
        alembic_cfg.stdout = buf
        command.upgrade(alembic_cfg, "head", sql=True)
        typer.echo(buf.getvalue())
    else:
        command.upgrade(alembic_cfg, "head")
        typer.echo("Migration complete.")
