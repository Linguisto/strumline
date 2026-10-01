"""CLI: strumline doctor — health checks for all services.

Checks:
- API / Ingest / Processor HTTP health endpoints
- PostgreSQL connectivity and migration state
- Loki connectivity (if SINK_PROVIDER=loki)

Non-interactive, deterministic exit codes:
  0  all required checks passed
  1  one or more required checks failed

Doctor is read-only and bounded: it never creates resources, runs migrations,
rotates keys, or submits telemetry. A green report proves processes are up and
dependencies are reachable — it does **not** prove end-to-end sink delivery.
Use the five-minute smoke test (README "Send logs") to verify delivery.
"""

from __future__ import annotations

import asyncio
from typing import Any

import typer
from rich.console import Console

from strumline.cli.helpers import OPT_JSON, OPT_PLAIN, OutputMode, mode, output

_console = Console()
_err = Console(stderr=True)

app = typer.Typer(help="Run read-only health checks for all services.", add_help_option=True)

# Check result keys used in output. ``next_step`` is additive guidance shown in
# every mode so a failing check tells the operator what to do next.
_KEYS = ["service", "status", "detail", "next_step"]

# Status constants
_OK = "ok"
_FAIL = "fail"
_SKIP = "skip"  # optional service or check intentionally not run

# Actionable next steps per required service. Kept credential-free and generic;
# doctor never echoes connection strings or exception messages.
_NEXT_STEPS: dict[str, str] = {
    "api": "start the api process (docker compose up -d strumline-api) or pass --api-url",
    "ingest": "start ingest (docker compose up -d strumline-ingest) or pass --ingest-url",
    "processor": "start the processor (docker compose up -d strumline-processor)",
    "postgres": "check DB_HOST/DB_PORT/DB_USER/DB_PASSWORD and that PostgreSQL is running",
    "migrations": "run 'strumline migrate' to apply pending migrations",
    "loki": "check LOKI_URL and Loki reachability, or set SINK_PROVIDER=null",
    "config": "fix the reported environment variables; invalid values are rejected at startup",
}


def _redact(exc: Exception) -> str:
    """Return a credential-free description of *exc*.

    Connection errors from asyncpg/SQLAlchemy commonly embed the full DSN
    (including the password) in ``str(exc)``. Doctor never surfaces that, so we
    report only the exception *type*.
    """
    return type(exc).__name__


def _check_result(service: str, status: str, detail: str = "") -> dict[str, Any]:
    next_step = _NEXT_STEPS.get(service, "") if status == _FAIL else ""
    return {"service": service, "status": status, "detail": detail, "next_step": next_step}


async def _http_get(url: str, timeout: float = 5.0) -> tuple[int, dict[str, Any]]:
    import httpx2

    async with httpx2.AsyncClient(timeout=timeout) as client:
        r = await client.get(url)
        return r.status_code, r.json()


async def _check_http(name: str, url: str, required: bool = True) -> dict[str, Any]:
    try:
        code, body = await _http_get(url)
        if code == 200 and body.get("status") == "ok":
            version = body.get("version", "")
            return _check_result(name, _OK, f"version={version}")
        return _check_result(name, _FAIL if required else _SKIP, f"HTTP {code}")
    except Exception as exc:
        return _check_result(name, _FAIL if required else _SKIP, _redact(exc))


async def _check_postgres() -> dict[str, Any]:
    try:
        from strumline.config import DatabaseSettings
        from strumline.db.session import make_session_factory

        settings = DatabaseSettings()
        factory = make_session_factory(settings.database_url)
        async with factory() as session:
            result = await session.execute(__import__("sqlalchemy").text("SELECT version()"))
            version_row = result.scalar()
            version = str(version_row or "").split(" on ")[0] if version_row else "unknown"
            return _check_result("postgres", _OK, version)
    except Exception as exc:
        return _check_result("postgres", _FAIL, _redact(exc))


async def _check_migrations() -> dict[str, Any]:
    try:
        import sqlalchemy
        from alembic.config import Config
        from alembic.runtime.migration import MigrationContext
        from alembic.script import ScriptDirectory

        from strumline.config import DatabaseSettings

        settings = DatabaseSettings()
        # Use sync engine for alembic inspection
        sync_url = settings.database_url.replace("+asyncpg", "")
        engine = sqlalchemy.create_engine(sync_url)
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            current = ctx.get_current_heads()

        cfg = Config("alembic.ini")
        script = ScriptDirectory.from_config(cfg)
        head = set(script.get_heads())

        if set(current) == head:
            return _check_result("migrations", _OK, f"head={','.join(head)}")
        return _check_result(
            "migrations",
            _FAIL,
            f"current={','.join(current) or 'none'} head={','.join(head)}",
        )
    except Exception as exc:
        return _check_result("migrations", _FAIL, _redact(exc))


async def _check_loki(loki_url: str) -> dict[str, Any]:
    """Connectivity probe only — reachability is not delivery verification."""
    try:
        import httpx2

        async with httpx2.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{loki_url.rstrip('/')}/ready")
            if r.status_code == 200:
                return _check_result("loki", _OK, "reachable (not a delivery check)")
            return _check_result("loki", _FAIL, f"HTTP {r.status_code}")
    except Exception as exc:
        return _check_result("loki", _FAIL, _redact(exc))


async def _run_checks(
    api_url_override: str | None = None,
    ingest_url_override: str | None = None,
    processor_url_override: str | None = None,
) -> list[dict[str, Any]]:
    from strumline.config import (
        APISettings,
        DatabaseSettings,
        IngestSettings,
        LokiSettings,
        ProcessorSettings,
    )

    # Invalid configuration is reported explicitly rather than being masked by
    # guessed defaults. We only fall back to model_construct() so the remaining
    # checks can still run, and we surface a failing ``config`` row.
    config_error: Exception | None = None
    try:
        api_s = APISettings()
        ingest_s = IngestSettings()
        proc_s = ProcessorSettings()
        loki_s = LokiSettings()
        db_s = DatabaseSettings()
    except Exception as exc:
        config_error = exc
        api_s = APISettings.model_construct()
        ingest_s = IngestSettings.model_construct()
        proc_s = ProcessorSettings.model_construct()
        loki_s = LokiSettings.model_construct()
        db_s = DatabaseSettings.model_construct()

    # Endpoint resolution. Explicit --*-url overrides always win. Otherwise, a
    # bind-all host (0.0.0.0/::) is not a reachable address, so we resolve it to
    # the Compose service name when a non-local DB_HOST suggests we are running
    # inside the Compose network, else to localhost. This heuristic only affects
    # the default (non-overridden) case.
    db_host = db_s.db_host
    in_compose = db_host not in ("localhost", "127.0.0.1", "")

    def _host(h: str, service_name: str) -> str:
        if h not in ("0.0.0.0", "::"):
            return h
        return service_name if in_compose else "localhost"

    api_url = api_url_override or f"http://{_host(api_s.api_host, 'api')}:{api_s.api_port}"
    ingest_url = (
        ingest_url_override
        or f"http://{_host(ingest_s.ingest_host, 'ingest')}:{ingest_s.ingest_port}"
    )
    proc_url = (
        processor_url_override
        or f"http://{_host(proc_s.processor_host, 'processor')}:{proc_s.processor_port}"
    )

    results: list[dict[str, Any]] = []
    if config_error is not None:
        results.append(_check_result("config", _FAIL, _redact(config_error)))

    tasks = [
        _check_http("api", f"{api_url}/health"),
        _check_http("ingest", f"{ingest_url}/health"),
        _check_http("processor", f"{proc_url}/health"),
        _check_postgres(),
        _check_migrations(),
    ]
    if proc_s.sink_provider == "loki":
        tasks.append(_check_loki(loki_s.loki_url))

    results.extend(await asyncio.gather(*tasks))
    return results


def _render_rich(results: list[dict[str, Any]]) -> None:
    from rich.table import Table

    table = Table(title="Doctor", show_header=True, header_style="bold cyan")
    table.add_column("SERVICE")
    table.add_column("STATUS")
    table.add_column("DETAIL")
    table.add_column("NEXT STEP")

    for row in results:
        status = row["status"]
        if status == _OK:
            status_fmt = "[green]ok[/green]"
        elif status == _FAIL:
            status_fmt = "[red]fail[/red]"
        else:
            status_fmt = "[dim]skip[/dim]"
        table.add_row(row["service"], status_fmt, row["detail"], row.get("next_step", ""))

    _console.print(table)


@app.callback(invoke_without_command=True)
def doctor(
    json: bool = OPT_JSON,
    plain: bool = OPT_PLAIN,
    api_url: str = typer.Option("", "--api-url", help="Override API base URL."),
    ingest_url: str = typer.Option("", "--ingest-url", help="Override ingest base URL."),
    processor_url: str = typer.Option("", "--processor-url", help="Override processor base URL."),
) -> None:
    """Run read-only health checks for all services.

    A green report means processes are up and dependencies are reachable; it does
    not verify sink delivery. See the README five-minute smoke test for that.
    """
    results = asyncio.run(_run_checks(api_url or None, ingest_url or None, processor_url or None))
    out = mode(json, plain)

    if out == OutputMode.JSON or out == OutputMode.PLAIN:
        output(out, results, keys=_KEYS)
    else:
        _render_rich(results)

    failed = [r for r in results if r["status"] == _FAIL]
    if failed:
        if out != OutputMode.JSON:
            _err.print(f"\n[red]{len(failed)} check(s) failed.[/red]")
        raise typer.Exit(1)

    if out != OutputMode.JSON:
        _console.print("\n[green]✓ All checks passed.[/green]")
