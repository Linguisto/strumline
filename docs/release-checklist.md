# v1 release checklist

Use this checklist after repository validation passes and before changing
visibility or publishing a tag. Repository files cannot prove GitHub settings,
contact monitoring, or package visibility, so the maintainer must verify those
items in the GitHub UI.

## Automated evidence

- `make lint`
- `make test.unit`
- `make test`
- Real OpenTelemetry Collector JSON and Protobuf interoperability tests with
  the pinned version from `.github/workflows/validate.yml`
- `docker build --target runtime --tag strumline:release-candidate -f docker/Dockerfile .`
- `SMOKE_ENV_FILE=.env scripts/release-smoke.sh`
- Full-history Gitleaks scan and Trivy filesystem/production-image scans from
  `.github/workflows/security.yml`
- Source provenance and distribution contents checked against
  `THIRD_PARTY_NOTICES.md`; the runtime image and wheel contain the project
  license and notices, while `.kiro/skills/` remains source-only.

The full-history scan has one exact-fingerprint exception in `.gitleaksignore`.
It is a false positive on the Python expression `headers=_TOKEN,
compression=Compression.Gzip` in an old test commit; `_TOKEN` contained the
literal non-secret value `test-token`. Do not broaden this exception by path,
commit, or rule.

The smoke script uses a separate Compose project and removes only its own
containers and volumes. Build and provisioning time is outside the five-minute
timer; the timer starts immediately before project and app creation. It passes
only after the exact event marker is returned by Loki.

## Maintainer-owned GitHub settings

- Enable private vulnerability reporting and submit a harmless test report.
- Confirm security notifications and Code of Conduct reports reach a monitored
  maintainer account.
- Protect `main`: require the PR validation and security checks, prevent force
  pushes and deletion, and restrict bypasses.
- Protect stable `vX.Y.Z` tags from unauthorized creation or deletion.
- Review default Actions permissions and fork pull-request behavior.
- Enable secret scanning, push protection, Dependabot alerts, and dependency
  graph support for the uv lockfile, Actions, and container images.
- Enable GitHub Discussions, or replace the Discussions support link in
  `SUPPORT.md` and the issue chooser with a working public support route.
- After the first image publish, make the GHCR package public and verify an
  unauthenticated pull by immutable digest on both amd64 and arm64.

## Publication

1. Review `CHANGELOG.md` and generated `git-cliff` notes.
2. Confirm `pyproject.toml`, `uv.lock`, CLI, health, and OpenAPI all report
   `1.0.0`.
3. Confirm every automated check above passed for the exact commit to tag.
4. Change repository visibility only after the security contacts and settings
   are verified.
5. Push `v1.0.0`. The release workflow rejects prerelease or mismatched tags,
   validates the tagged commit, publishes the multi-architecture image, and
   creates the stable GitHub release.
