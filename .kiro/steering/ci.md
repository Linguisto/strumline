---
title: CI, workflows, and release process
inclusion: always
---

# CI, workflows, and release

## Repository workflows

Five workflow files live in `.github/workflows/`.

### `lint.yml` — Pull request gates

Triggers automatically for pull requests. A concurrency group cancels an older
run when the same pull request receives another commit.

The workflow installs the locked development environment and pinned
OpenTelemetry Collector, then runs ruff, the format check, strict mypy,
import-linter, and the complete PostgreSQL-backed test suite. The dependency
review job also runs once the repository is public.

### `security.yml` — Security scans

Triggers automatically for pull requests and every Monday, and can also be run
manually. It does not repeat after a merge to `main`.

The workflow performs a full-history Gitleaks scan, a Trivy dependency/source
scan, and a Trivy production-image scan. Stale runs are cancelled only when a
pull request receives a newer commit; scheduled and manual scans run to
completion.

### `ci.yml` — Main CI and dev image

Runs manually through `workflow_dispatch`. It calls the reusable exact-commit
validation workflow. When dispatched from `main`, it also builds and publishes
the multi-architecture `ghcr.io/<owner>/<repo>:dev` image. Dispatches from other
refs validate that ref but skip publication.

Use Main CI only when a fresh mutable development image is useful. Ordinary
merges rely on the already-passed pull-request gates and do not start a duplicate
validation or image build.

### `validate.yml` — Reusable exact-commit validation

Callable by other workflows through `workflow_call`; it has no independent
automatic or manual trigger. It runs all lint and test gates with the pinned
Collector, builds and checks the production image, and completes the isolated
resource-creation-to-Loki release smoke test.

Main CI and the release workflow call this file so their validation stays
identical.

### `release.yml` — Stable release

Triggers automatically on tags matching `v*.*.*`. The workflow rejects tags
that are not stable `vX.Y.Z` versions or do not match `pyproject.toml`, validates
the exact tagged commit through `validate.yml`, generates release notes, publishes
the multi-architecture runtime image, and creates the GitHub release.

Do not add a manual publishing path. A failed tag run can be rerun from GitHub;
new release contents require a new version and tag.

## GitHub-managed automation

Dependabot checks Python, GitHub Actions, and Docker dependencies weekly.
Updates are grouped once per ecosystem to limit pull-request and workflow churn.

GitHub's dependency graph automation runs when a default-branch commit changes a
supported manifest. It is separate from the repository workflow files and should
remain enabled for dependency review and alert coverage.

## Trigger summary

| Event | Automatic work |
|---|---|
| Pull request | Full lint/test/Collector gate and security scans; dependency review when public |
| Merge to `main` | No repository-authored workflow |
| Monday schedule | Security scans and Dependabot's weekly update checks |
| Relevant manifest change on `main` | GitHub-managed dependency graph update |
| Manual Main CI dispatch | Exact-commit validation; publishes `:dev` only from `main` |
| Manual Security scans dispatch | Full-history, dependency/source, and production-image scans |
| Stable `vX.Y.Z` tag | Exact-commit validation, runtime image publication, and GitHub release |

## Local workflow

```bash
make lint              # ruff + format check + mypy + import-linter
make test              # full pytest suite
make test.unit         # unit only, no database required
make test.integration  # integration only, PostgreSQL required

# Run locally instead of in the dev container:
make lint DC_EXEC="uv run"
make test DC_EXEC="uv run"
```

`DC_EXEC` defaults to `docker compose run --rm strumline-cli`.

## Required merge checks

Require these pull-request checks on `main` once repository protections are
available:

- Lint and full test suite
- Dependency review (public repository)
- Full-history secret scan
- Dependency and source scan
- Production image scan

The release workflow validates tagged commits independently, so removing the
automatic post-merge run does not weaken the publication gate.

## Image tagging convention

| Context | Tag |
|---|---|
| Manual Main CI from `main` | `:dev` |
| Stable version tag | `:X.Y.Z`, `:X.Y`, `:sha-<short>`, `:latest` |

Registry: `ghcr.io/<owner>/<repo>` (lowercased). `STRUMLINE_IMAGE_TAG` controls
which tag Compose uses locally.
