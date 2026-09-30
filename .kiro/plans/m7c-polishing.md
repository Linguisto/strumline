# M7c — CLI, Documentation, and Developer Experience Polishing

**Type:** Optional usability milestone

**Status:** Planned

**Depends on:** M7b's corrected setup, security, and release contracts

**Goal:** Make the existing product easier to understand, script, diagnose, and
contribute to without expanding v1 capabilities.

## Scope and relationship to M7b

Read `AGENTS.md` fully before implementation. Trace the real call paths, inspect
every caller of shared helpers, and prefer existing patterns and dependencies.
Implement on a feature branch in small, focused changes.

[M7b](m7b-release-preparation.md) owns release blockers: database privileges,
credential isolation, cache safety, working startup, CI/release gates, security
reporting, community templates, production instructions, and accurate contracts.
M7c builds on that work; it does not duplicate or postpone it. Recheck all
observations below after M7b because implementation may have changed.

M7c is not an additional prerequisite for publishing v1. It may ship before or
after v1, and unfinished optional polish must not indefinitely delay release.
If implementation uncovers a security or deployment-correctness defect, track
and resolve it under the applicable release gate rather than treating it as
cosmetic work.

Keep M5 and M8 post-v1. Do not add a website, web admin UI, new TUI features,
gRPC, traces, customer metrics, new sinks, durability, or broad refactoring.
Avoid adding flags, output schemas, dependencies, or configuration keys without
checking the existing contract and documenting a concrete need.

## M7c-A — Consistent and actionable CLI failures

### Starting observations

`strumline/cli/auth_tokens.py` parses UUIDs directly with `uuid.UUID()` inside
handlers that catch only `StrumlineError`. Malformed input can escape that
translation. Some interactive choice-loading paths catch arbitrary exceptions
and substitute empty choices, hiding the difference between no resources and
a failed database connection.

### Work

- Audit project/app/token create, show, delete, and revoke paths for malformed
  UUIDs, invalid slugs, missing resources, ownership failures, conflicts,
  cancellations, and configuration/connectivity failures.
- Reuse framework validation or existing shared/domain validation as appropriate.
  Do not scatter independent parsers or blanket exception catches across commands.
- Preserve the documented `StrumlineError` exit codes. Determine non-domain
  failure behavior from existing CLI conventions before changing it; do not
  invent a parallel domain error hierarchy or silently turn operational failures
  into empty results.
- Expected user errors should identify the input/problem and offer a relevant
  next step without a traceback. Unexpected programming errors must remain
  distinguishable and diagnosable rather than being swallowed.
- Keep diagnostics on stderr and successful machine-readable output on stdout.
  Do not echo credentials, connection passwords, or raw telemetry in messages.
- Test representative failures through the actual CLI entry point, asserting
  exit status, stream placement, and useful content without brittle snapshots.

## M7c-B — Reliable noninteractive resource management

### Starting observations

`strumline/cli/helpers.py` already provides JSON/plain/Rich output helpers and
shared options. Project creation emits JSON; app/token creation currently uses
Rich panels. Resource commands also fall back to prompts when inputs are absent.

### Work

- Define and document a complete scriptable path for project creation, app
  creation with its automatically generated first token, additional token
  creation, and explicit resource lookup/revocation/deletion.
- Reuse existing output helpers and serialization, including canonical UTC
  timestamps with trailing `Z`. Inspect existing public fields and callers before
  specifying creation-result formats; document any necessary additive format.
- Fully specified commands must complete with stdin closed and no TTY. When
  required input is missing in noninteractive use, fail with clear usage guidance
  rather than waiting for a prompt or starting a wizard.
- Preserve useful interactive flows. Reuse existing confirmation options for
  destructive commands and require explicit confirmation/noninteractive intent;
  a missing TTY must not imply consent.
- Machine-readable output must parse without banners, progress text, ANSI
  escapes, or success summaries appended to stdout. Plain mode must be readable
  in redirected output and terminals without color support.
- Preserve one-time token disclosure. Emit a newly created token only in the
  explicitly requested creation result; never add raw tokens to list/show,
  diagnostics, ordinary operational logs, or retained test artifacts.
- Verify cancellation and failure do not leave partially created resources or
  falsely report success. Reuse current service transaction boundaries.
- Add focused CLI tests for closed stdin, output parsing, missing input,
  confirmation behavior, and first-token creation using existing test tooling.

## M7c-C — Improve the existing doctor command

Reuse `strumline/cli/doctor.py`, its current output modes, URL overrides, and
deterministic required-check exit status (0 success, 1 failure). Do not build a
second diagnostics interface or cross the documented CLI import boundaries.

- Add actionable next steps for missing credentials, DB connectivity failures,
  unapplied migrations, unavailable processes, and an unavailable configured
  sink, using the corrected M7b contracts as the source.
- Report invalid configuration explicitly. Review the current fallback from
  settings validation to `model_construct()`; do not quietly present guessed
  defaults as the user's working configuration.
- Review host selection: a remote `DB_HOST` alone does not establish that the
  command runs inside Compose. Respect existing explicit URL overrides and make
  endpoint resolution understandable without inventing deployment detection.
- Keep checks bounded and read-only. Do not create test resources, rotate keys,
  run migrations, submit telemetry, or repair the deployment automatically.
- Clearly distinguish process health, database/migration checks, and actual
  delivery verification. A green doctor report must not claim successful Loki
  delivery; link to the M7b smoke test for that evidence.
- Keep optional observability services optional. Reconcile command help/module
  claims with actual checks instead of adding unnecessary checks to match prose.
- Reuse JSON result fields where possible and redact sensitive exception/URL
  details across Rich, plain, and JSON output.
- Test malformed/unreachable endpoints, missing configuration, migration
  mismatch, configured Loki failure, and optional-service absence. Preserve
  useful diagnostics when an individual check fails.

## M7c-D — README and documentation navigation

- Lead with the current product: a best-effort structured logs collector over
  OTLP/HTTP. Explain in-memory admission and possible downstream loss early.
- Present supported JSON/Protobuf/gzip logs clearly and distinguish them from
  planned gRPC/traces/metrics. Keep benchmarks scoped to their actual measurement.
- Put the M7b first-event walkthrough and its Loki query where a newcomer can
  find them without navigating planning files. Improve its presentation without
  creating a second divergent set of startup commands.
- Provide concise entry paths for application developers (exporter/auth/OTLP),
  operators (deployment/configuration/security/diagnostics), contributors
  (environment/gates/workflow), and sink implementers (contract/extension guide).
  Reuse the existing README Docs section unless a separate index adds value.
- Check relative links, anchors, command examples, referenced filenames, service
  addresses, environment-variable names, and current defaults. Use the owning
  contracts and implementation; do not invent responses or example flags.
- Add a small troubleshooting guide or section mapping common symptoms to
  existing commands/docs: authentication rejection, retryable `503`, accepted
  logs absent in Loki, and migrations/configuration failures.
- Keep product and repository names consistent. Include implementation details
  only where users need them to configure, diagnose, or extend the system.

## M7c-E — Developer command and help consistency

- Audit `make help`, Makefile targets, CLI `--help`, README, CONTRIBUTING, and
  benchmark instructions for the same names and prerequisites. Prefer current
  target names instead of accumulating aliases for stale examples.
- Recheck `make benchmarks`: it executes `benchmarks/receipt_to_enqueue.py`
  inside the dev container by default, but the current Dockerfile does not copy
  that directory and Compose does not mount it. Fix the smallest relevant dev
  workflow so the advertised command works; keep tooling out of the runtime image.
- Verify benchmark result write permissions and where output is retained.
  Validation runs must use the harness's scratch/no-write mode so they do not
  unintentionally replace the published baseline.
- Check container and documented `DC_EXEC="uv run"` workflows in their intended
  environments. Explain DB prerequisites for integration tests and the extra
  requirements of benchmark/release smoke commands.
- Make help accurately describe commands and secret-disclosure behavior. Avoid
  cosmetic completion systems or new build abstractions without a demonstrated
  usability problem.

## M7c-F — Release presentation

- Use M7b's version, changelog, support, and operational contracts to prepare
  concise human-readable release notes: available capabilities, intentional
  limitations, installation/first-event links, and upgrade instructions.
- Distinguish measured performance from marketing claims and HTTP acceptance
  from sink delivery. Link technical details rather than copying entire docs.
- Review the generated changelog for understandable entries and functioning
  repository/version links. Do not add publication jobs, create a release, or
  change repo visibility as part of this polish work.
- Add a short roadmap entry marking M7c optional. Keep `M7 -> M7b -> v1.0` as
  the mandatory release path and retain the existing M8-A/B/C/D meanings.

## Validation and handoff

Use focused tests for changed behavior and manual checks for low-impact docs
and help text. Avoid snapshot suites that merely reproduce implementation.
Run `make lint` and `make test.unit`; run Docker `make test` for the final
implementation and any changed DB/service interactions.

Validate these concrete journeys with sanitized evidence:

1. A newcomer follows the README and finds the submitted event in Loki. Reuse
   M7b's five-minute smoke test, including its restricted role, real HTTP/IPC/sink
   path, elapsed-time evidence, and isolated cleanup. Do not duplicate the harness.
2. A script creates resources and captures the one-time token with stdin closed,
   consumes machine-readable output, and handles invalid input by exit code.
3. An operator diagnoses deliberately broken configuration or an unavailable
   service with doctor and receives a useful next step without a secret leak.
4. A contributor finds and executes the documented gates and benchmark command
   in the supported dev workflow without overwriting baseline results.

If polish changes the walkthrough, CLI outputs, or release artifacts before v1,
rerun the applicable M7b gates on the final candidate. M7c completion alone does
not establish release readiness. Report changed behavior, checks performed,
compatibility implications, and anything explicitly deferred.

## Acceptance criteria

- [ ] Expected CLI failures are actionable, consistently translated, and covered by meaningful tests.
- [ ] No-resource results are distinguishable from configuration/database failures.
- [ ] Fully specified resource commands work with closed stdin and no TTY.
- [ ] Missing noninteractive inputs fail promptly; destructive commands require explicit intent.
- [ ] JSON output parses cleanly, plain output contains no ANSI formatting, and diagnostics use stderr.
- [ ] Raw token disclosure remains limited to creation; list/show/log/doctor output contains no secrets.
- [ ] Doctor reports invalid configuration and useful next steps without writing or claiming delivery verification.
- [ ] README exposes supported capabilities, best-effort limitations, and the first-event walkthrough clearly.
- [ ] Developer/operator/contributor/sink-extension entry paths and local links are verified.
- [ ] Help text and documented command names/prerequisites match the actual implementation.
- [ ] The benchmark command works in the advertised dev environment and preserves published baseline results during validation.
- [ ] Release notes use M7b contracts and include capability, limitation, and upgrade links.
- [ ] All four user journeys are verified with sanitized evidence.
- [ ] `make lint`, `make test.unit`, and Docker `make test` pass on the final implementation.
- [ ] Roadmap marks M7c optional and leaves the mandatory M7b release gate and post-v1 milestones intact.
