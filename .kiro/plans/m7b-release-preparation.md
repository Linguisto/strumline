# M7b — Release Preparation and Public OSS Readiness

**Type:** Pre-v1 release gate  
**Status:** Planned  
**Depends on:** M7 and the existing OTLP/HTTP logs implementation  
**Unlocks:** Public repository opening and v1.0 release  
**Goal:** Close the deployment, security, release-validation, and contributor
onboarding gaps found in the 2026-09-30 readiness review.

## Scope and implementation rules

Read `AGENTS.md` fully before implementation. Trace every affected call path,
reuse existing patterns and installed packages, and fix shared root causes.
Work on a feature branch. Do not introduce dependencies or configuration keys
without a concrete reason and an update to their owning documentation.

M7's checked boxes are historical milestone status, not proof that the findings
below are resolved. Reproduce each finding against the current checkout before
changing code. Record evidence before checking off an acceptance criterion.

M8 remains planned post-v1 work. Existing OTLP/HTTP JSON/Protobuf/gzip logs belong
to v1; M8-B is already reserved for OTLP/gRPC logs. This plan does not add gRPC,
traces, customer metrics, new sinks, durable storage, or replay. Preserve the
documented best-effort admission and delivery contract.

Implement repository changes and prepare concrete instructions for owner-only
settings. Do not change repository visibility, publish releases/images, rotate
live credentials, rewrite Git history, or contact external parties merely to
complete this plan. Track those actions separately for the maintainer.

## Review baseline

The readiness review found an MIT license, `CONTRIBUTING.md`, substantial
configuration/protocol/security documentation, and container release automation.
Verification on 2026-09-30:

- `make lint` with the local locked uv environment: passed ruff, format check,
  strict mypy, and the three currently configured import contracts.
- `make test.unit` locally: 163 passed, 27 deselected.
- `make test` in Docker: 188 passed, 2 skipped. Both skips were real-Collector
  interoperability tests requiring `OTELCOL_BINARY`.
- `SECURITY.md` existed locally but was untracked. Preserve and review this
  existing document rather than replacing it with a generic template.
- The running development database had no `strumline_ingest` role. This is an
  observation about that environment, not a claim about all deployments.

The review did not perform a comprehensive security audit, full-history secret
scan, dependency/image vulnerability scan, or inspect GitHub settings. Passing
tests do not establish those properties.

## M7b-A — Repair and verify the ingest database boundary

### Findings

- `strumline/db/bootstrap.py` grants reads on `auth_tokens` and `apps`, but
  `AuthTokenResolver._query()` in `strumline/ingest/resolver.py` also reads
  `projects`. A newly provisioned restricted role cannot resolve active tokens
  through that path; the failure is translated into retryable `503`.
- `strumline/ingest/server.py` falls back to `database_url` when the ingest URL
  is empty. This gives ingest a write-capable session.
- `compose.yaml` passes application DB credentials into ingest through the
  shared DB environment anchor, even when restricted credentials are present.
- Resolver integration tests use the application role, masking grant failures.
- `docs/security.md` claims ingest never receives write credentials while also
  describing a development fallback. `docs/configuration.md` documents it too.

### Work

- Align restricted SELECT grants with the resolver's real queries. Keep access
  limited to required tables; do not grant broad schema/table writes.
- Remove the write-capable fallback and fail explicitly when restricted
  credentials are absent. Use existing configuration/error conventions.
- Separate shared DB location settings from application credentials in Compose.
  Ingest must not receive application DB username/password secrets.
- Verify the bootstrap role and permission checks against all required tables,
  including `projects`, and document required provisioning privileges.
- Reconcile code, sample configuration, security docs, and architecture claims.
- Add integration coverage using an isolated restricted test role: active token
  resolution succeeds; revoked/unknown tokens fail; INSERT/UPDATE/DELETE and
  inappropriate DDL are denied. Clean up test resources without touching live
  roles. Cover missing-credential startup and absence of credential fallback.

## M7b-B — Bound authentication cache memory

### Finding

`AuthTokenResolver` retains positive and negative entries in an unbounded dict.
TTL prevents expired-entry reuse but does not evict entries. Distinct unknown
tokens can accumulate indefinitely on the unauthenticated HTTP surface.

### Work

- Use a bounded cache with eviction and expired-entry cleanup, preferring
  stdlib or an already-installed solution. Cover both positive and negative
  results and avoid retaining unnecessary raw credential material.
- Preserve the revocation window and fail-closed behavior on expired/missing
  cache entries during DB failure. Do not extend TTL through cache hits.
- Test many distinct invalid keys, capacity limits, expiry/eviction, valid-token
  resolution after eviction, and database-outage behavior. Use controlled time
  rather than long sleeps and avoid new high-cardinality metrics.
- Review resolver failure logging: `docs/security.md` promises exception-class
  logging, while the current resolver logs exception text. Make the documented
  redaction guarantee accurate and test it with sensitive exception content.

## M7b-C — Make the first-run walkthrough work

### Findings

`README.md` starts with `make up` then uses an undefined `STRUMLINE_TOKEN`.
`make up` migrates but does not bootstrap the ingest role. `.env.example` supplies
a placeholder ingest password for a role that has not yet been created.

### Work

- Define a working startup order: initialize config, start DB, migrate, provision
  restricted access, configure the generated credentials, then start ingest.
  Reuse the existing bootstrap logic; avoid a second provisioning implementation.
- Do not silently regenerate credentials on routine startup. The current
  bootstrap resets an existing role's password; make rerun/rotation behavior
  explicit and safe for the documented workflow.
- Add exact commands to create a project and app. App creation already produces
  the first token; reuse that behavior and show how to export `STRUMLINE_TOKEN`.
- Send the README sample and show a Loki/Grafana query that finds its event.
- Test the walkthrough with an isolated fresh Compose project and volumes.
  Never delete the developer's existing volumes to simulate a clean checkout.
- Verify documented startup and health checks do not imply working
  authentication or sink delivery merely because `/health` returns success.
- Bind bundled development services to loopback where external exposure is not
  needed. The current sample exposes API, ingest, Loki, Prometheus, and Grafana
  on all interfaces; Grafana also has sample credentials and anonymous viewing.
  Document deliberate exceptions and keep the dev/production distinction clear.

## M7b-D — Gate PRs and tagged releases on validation

### Findings

- `.github/workflows/lint.yml` checks PRs only; `CONTRIBUTING.md` says every
  branch and PR. Full DB tests run only after pushes to `main`.
- `.github/workflows/release.yml` publishes after changelog generation without
  checking that the tagged commit passes lint/tests.
- Its broad tag trigger can match prerelease tags, while `latest` and
  `prerelease: false` are unconditional.
- Real-Collector tests are optional and were skipped in the review run.

### Work

- Run integration tests before merging, using isolated PostgreSQL and existing
  test fixtures. Keep PR jobs safe for fork contributions and free of publishing
  credentials. Reuse workflow logic where practical without hiding checks.
- Make publishing depend on successful gates for the exact tagged commit,
  including production-image startup/smoke validation. Do not rely solely on an
  earlier green `main` build.
- Validate release tag syntax and consistency with package version. Reject
  invalid/mismatched tags before publishing.
- Define stable versus prerelease behavior. Either support prereleases correctly
  or reject them explicitly; prereleases must not overwrite stable `latest` or
  be represented as stable GitHub releases.
- Supply a pinned supported Collector binary in the release validation path so
  JSON and Protobuf interoperability tests run rather than silently skipping.
  Retain convenient optional behavior for ordinary local unit-test runs.
- Set explicit minimum workflow permissions and scope package/release writes to
  publishing jobs. Pin third-party actions to reviewed commit SHAs and pin
  production base-image/uv build-tool versions, with a documented update path.
- Validate both advertised image architectures and stage the release checks
  without pushing artifacts during this implementation task.

## M7b-E — Release identity, artifacts, and operations

### Findings

`pyproject.toml` and `uv.lock` still identify version `0.1.0`. A `v1.0.0` image tag
does not update the metadata read by CLI and health/OpenAPI version reporting.
The release workflow generates release notes, but there is no tracked changelog
or complete production deployment/upgrade/rollback runbook.

### Work

- Choose one version source using the existing packaging conventions; keep
  package metadata and lockfile synchronized and check agreement with tags.
  Prepare the v1 version change as reviewable work, without creating/pushing a
  tag. Verify CLI, health, and OpenAPI versions in the built release image.
- Document actual GHCR coordinates derived from `github.repository`, immutable
  version/digest pulls, supported architectures, and public package visibility.
- Include the project license and required notices in distributed artifacts;
  inspect the production image/build output instead of assuming root files are
  copied. Review provenance of checked-in third-party material under `.kiro/`.
- Provide a changelog/release-notes path using existing `git-cliff` configuration
  and a concise compatibility/support policy for public HTTP, IPC, CLI, schema,
  configuration, and sink behavior. Do not promise stronger delivery semantics.
- Add production instructions for three process commands, shared socket
  directory ownership, external PostgreSQL/Loki, network/TLS termination,
  protected admin/metrics endpoints, and secrets supplied by the operator.
- Cover migration ordering, backups/restoration of control-plane metadata,
  rollback constraints, upgrade compatibility, shutdown/restart loss, and the
  absence of event recovery. Explain preserving `APP_KEY` across restarts and
  recovery; changing it affects validation of existing token hashes.
- Keep package metadata links and README entry points consistent with the
  repository's actual name (`telemetria`) and product name (`Strumline`). PyPI
  publication is not required by this container-focused release plan.

## M7b-F — Complete public-repository security and community setup

- Review and include the existing root `SECURITY.md`. Confirm the latest-1.x-only
  support policy and promised 5/10-business-day responses and 90-day fix target
  are commitments the maintainer can meet. Describe pre-release support honestly.
- Provide a usable private fallback contact. Do not invent an email address or
  assume a GitHub profile has private messaging; obtain maintainer input if needed.
- Clarify dependency-vulnerability handling: upstream fixes may belong upstream,
  but reports affecting Strumline's shipped dependency/image should have a path
  to triage and patched releases. Do not blanket-reject that impact.
- Add `CODE_OF_CONDUCT.md` with an actual enforcement contact, issue templates
  for bugs/features, a PR template, and support routing. Keep them lightweight
  and link private security reporting instead of requesting public exploit details.
- Document maintenance expectations and issue/PR triage. CODEOWNERS is optional
  if it accurately reflects current maintainers; CLA/DCO, funding, and elaborate
  governance are deferred unless a concrete need emerges.
- Scan all reachable Git history for secrets, not just the current tree or
  `.env`. Record tool/version, coverage, and findings without leaking secrets.
  If credentials are found, prepare remediation; coordinate rotation and any
  history rewrite separately with the owner before public opening.
- Scan locked production dependencies and the production image/base image for
  known vulnerabilities. Add reproducible CI/release scanning with explicit
  severity/exception policy and narrow, documented exceptions. A scanner as
  external CI tooling does not automatically justify a runtime dependency.

### Maintainer-owned GitHub checklist

Repository files cannot establish these settings. Verify them using authorized
read access when available; otherwise report them as unverified owner actions.

- Enable private vulnerability reporting and test the policy's reporting path.
- Require passing PR checks on `main`; prevent force pushes and deletion, and
  restrict release-tag creation according to the maintainer's release workflow.
- Review default Actions permissions and public-fork workflow behavior.
- Enable available secret scanning/push protection and dependency alerts/update
  automation; confirm coverage of the actual uv lockfile, Actions, and images.
- Confirm GHCR package visibility permits unauthenticated pulls of public images.
- Confirm support/enforcement contacts and security notifications are monitored.
- Change repository visibility and publish v1 only after the applicable gates
  below are evidenced. Do not mark settings complete based on documentation alone.

Reference: [private vulnerability reporting](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/configure-vulnerability-reporting/configure-for-a-repository),
[protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches),
and [repository security setup](https://docs.github.com/en/code-security/getting-started/quickstart-for-securing-your-repository).

## M7b-G — Reconcile documentation, boundaries, and performance claims

- Expand import-linter enforcement to cover the boundaries in `AGENTS.md` and
  `CONTRIBUTING.md`. Current contracts only partially restrict domain/IPC and
  prohibit direct processor imports of Loki; they omit other forbidden edges.
  Trace current imports, including shared configuration/logging infrastructure,
  and document necessary exceptions explicitly rather than weakening the policy
  to make checks pass. Verify each claimed boundary is actually enforced.
- Correct architecture documentation that still describes admin REST as future,
  says queue overload produces no HTTP errors, and claims IPC write losses have
  no counter. Use current writer retry/requeue and metric behavior as the source.
- Align contributor documentation with actual CI triggers and prerequisites.
- Preserve the honest scope of performance evidence: the published baseline
  reports 0.879 ms P99 and 2,689 events/sec using in-process ASGI transport,
  stubbed authentication, and continuous queue draining. It is not network,
  restricted-DB, IPC, processor, or end-to-end Loki performance evidence.
- Record concrete CPU hardware, repetitions, and supported encoding coverage
  for reproducible published claims. Add separate measurements where launch
  claims require them; do not present correctness tests as throughput benchmarks.
- Link this milestone from the roadmap and README. Update the pre-v1 dependency
  path to `M7 -> M7b -> v1.0`; retain M5/M8 as post-v1 and do not renumber M8-B.

## Execution order and handoff

1. Reproduce and fix database grants/credential isolation and cache safety.
2. Validate fresh startup and first-event delivery with the restricted role.
3. Enforce complete boundaries and reconcile affected docs.
4. Implement PR/release validation, version consistency, scanning, and artifacts.
5. Finish operations/community docs and prepare the owner settings checklist.
6. Run all gates, then the final five-minute smoke test below, and provide
   evidence plus any remaining maintainer actions.

Separate small commits/PRs are appropriate. After every behavioral change run
the meaningful regression tests and required quality gates. Do not add tests
that merely mirror low-impact document/template edits.

## Final smoke test — create resource → ingest → observe in Loki

After the implementation and quality gates pass, execute the documented
walkthrough against the final checkout and locally built release-candidate
image. This verifies [roadmap success criterion #4](roadmap.md#v1-success-criteria):
create resources, ingest an event, and observe it through the selected sink in
under five minutes.

- Prepare an isolated stack with PostgreSQL, Loki, migrated schema, and the
  restricted ingest role. State prerequisites explicitly. Record cold image
  build/download and stack provisioning time separately from the timed
  create-resource-to-observation journey; do not conceal setup failures.
- Start the five-minute timer before creating the project and app through the
  documented CLI commands. Save the generated app token without including it
  in retained output or evidence.
- Submit the documented OTLP/HTTP sample over real HTTP with a unique harmless
  message marker. Check admission success without partial rejection, then query
  Loki until that exact marker appears under the expected project/app labels.
- Use the actual ingest resolver, IPC writer, processor, and Loki sink. No
  injected resolver, queue-only assertion, NullSink, or mocked delivery.
  A healthy process or HTTP `200` alone does not pass this smoke test.
- Require observation within five minutes of starting resource creation. Use
  bounded polling and fail explicitly on deadline or mismatched routing.
- Record commit SHA, candidate image digest, relevant service versions,
  sanitized commands, elapsed time, and the matching Loki result. Do not retain
  token keys, DB passwords, or other secrets in logs or artifacts.
- Reuse the walkthrough automation in the release gate from M7b-D where
  practical. A failed final run blocks release readiness; fix the cause and
  rerun against the final candidate. Clean up only smoke-test-owned resources.

## Acceptance criteria

### Before public repository opening

- [ ] Full-history secret scan completed and findings resolved or explicitly handed off.
- [ ] License/provenance review completed for repository and distributed material.
- [ ] SECURITY policy is included with a verified private reporting path and usable fallback.
- [ ] CoC enforcement contact, issue/PR templates, and support routing are usable.
- [ ] GitHub protections/security settings are verified or listed as outstanding owner actions.
- [ ] Public docs describe current capabilities and limitations accurately.

### Before v1.0 publication

- [ ] Restricted-role token resolution succeeds and write/DDL denials are tested.
- [ ] Ingest never receives or falls back to application write credentials.
- [ ] Authentication cache stays bounded and expiry/revocation/outage behavior is verified.
- [ ] Resolver logs meet the documented redaction guarantee.
- [ ] An isolated fresh Compose walkthrough reaches a queryable Loki event.
- [ ] Final smoke test creates resources, ingests over HTTP, and observes the correctly routed event in Loki within five minutes, with sanitized evidence.
- [ ] Integration tests run before merge and release checks validate the exact tagged commit.
- [ ] Collector JSON/Protobuf interoperability runs in release validation without skips.
- [ ] Stable/prerelease tags and version mismatch are handled before publication.
- [ ] Production image smoke tests and advertised architectures pass.
- [ ] Package, CLI, health/OpenAPI, and release versions agree.
- [ ] Dependency/image scans pass the documented policy; exceptions have rationale and owners.
- [ ] Release artifacts, changelog, deployment, upgrade, backup/restore, and rollback guidance exist.
- [ ] Documented import boundaries are enforced and performance claims match evidence.
- [ ] `make lint`, `make test.unit`, and Docker `make test` pass on the final checkout.
- [ ] README/roadmap include M7b and keep M5/M8 outside v1 requirements.
- [ ] Final handoff distinguishes verified repository work from owner settings and publishing actions.

Do not claim public-launch or v1 readiness while applicable checklist items are
unverified. Record evidence and outstanding decisions in the implementation
handoff; completion of code changes does not itself publish or open the repo.
