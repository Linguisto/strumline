# M6 — CLI and Developer Experience Polish

**Type:** Enhancement  
**Depends on:** M4  
**Unlocks:** M7  
**Goal:** Polish the M1 management CLI with Rich/Textual workflows, diagnostics, configuration validation, and an end-to-end quick start.

## CLI evolution

M1 already provides complete scriptable project/app/auth token management and migrations. M6 keeps those command contracts and adds presentation and operator workflows:

```text
strumline init
strumline doctor
strumline ui
strumline config validate
```

Typer handles commands, Rich handles normal terminal output, and Textual handles interactive views. Every command supports non-TTY use: stable JSON where data is returned, `--plain` for human-readable static output, deterministic exit codes, and no mandatory prompts.

Dependencies are declared through the `[project] dependencies = [...]` array or an appropriate optional-dependency group, never a `[project.dependencies]` table.

## Initialization and execution contexts

`strumline init` gathers database URLs, `APP_TIMEZONE`, `SINK_PROVIDER`, optional Loki settings, runtime admin-API settings for M6b, and optional external observability URLs. It validates IANA timezone names and writes `.env` before Compose is started. Secret files use restrictive permissions.

The quick start supports both:

- `uv run strumline ...` on the host using loopback-published PostgreSQL
- `docker compose run --rm strumline-cli ...` using the internal database hostname

It never assumes a globally installed `strumline` command.

## Doctor and TUI

`doctor` checks API/ingest/processor health, PostgreSQL connectivity/migration state, IPC visibility, selected sink connectivity, and configuration consistency. Prometheus, Grafana, Loki, and their external URLs are optional; missing optional systems produce a neutral unavailable/not-configured status rather than failing an otherwise healthy installation.

`ui` provides process health, queue/rate metrics, projects/apps, and sink status. It can scrape `/metrics` directly when Prometheus is absent. Log-tail panels require Loki and visibly degrade when it is unavailable.

## Time presentation

CLI and TUI receive canonical UTC datetimes and localize only at render time. Display precedence is app timezone, `APP_TIMEZONE`, then UTC. `--timezone <IANA>` and `--utc` are presentation overrides; JSON output remains canonical UTC with `Z` unless an explicitly named localized field is requested.

## Acceptance criteria

- [ ] Existing M1 commands retain scriptable plain/JSON contracts.
- [ ] `init` writes configuration before Compose startup and supports both host and disposable-CLI workflows.
- [ ] `doctor --plain` and JSON modes are non-interactive with meaningful exit codes.
- [ ] TUI commands fall back cleanly when no TTY is present.
- [ ] Missing optional Prometheus, Grafana, or Loki does not mark the core service unhealthy.
- [ ] UI rate panels work through Prometheus or direct metrics; log panels explain missing Loki.
- [ ] Display localization never changes canonical UTC data or JSON fields.
- [ ] README quick start creates resources, starts the development stack, sends an event, and explains production BYO infrastructure.
- [ ] CLI imports `control/` and never imports ingest, processor, or sink implementations.
