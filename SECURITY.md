# Security Policy

Strumline sits on the ingest path between application code and an observability
stack, so we take security reports seriously. This document is about **reporting
vulnerabilities**. For the security properties of a deployment (auth tokens,
database grants, payload limits, redaction, socket permissions), see
[`docs/security.md`](docs/security.md).

## Supported versions

Strumline follows semantic versioning. Security fixes are applied to the latest
`1.x` release. Before v1.0, reports against `main` are accepted on a best-effort
basis, but no pre-release tag has a supported maintenance window.

| Version | Supported |
|---|---|
| `1.x` (latest) | ✅ |
| `main` before v1.0 | Best effort |
| `< 1.0` tags | ❌ |

## Reporting a vulnerability

**Do not open a public issue for a security vulnerability.**

Report privately through GitHub's coordinated disclosure workflow:

1. Go to the repository's **Security** tab → **Report a vulnerability**
   (GitHub Private Vulnerability Reporting).
2. Describe the issue, the affected version or commit, and a reproduction if you
   have one.

If private reporting is unavailable, open a public issue containing no
vulnerability details and ask the maintainer for a private channel. Do not name
affected components, include reproduction steps, or attach evidence publicly.

Please include, where possible:

- Affected component (`ingest`, `processor`, `api`, `cli`, a sink, IPC, etc.)
- Version, tag, or commit SHA
- Reproduction steps or a proof of concept
- Impact assessment and any suggested remediation

## What to expect

- **Acknowledgement** within 5 business days.
- **Initial assessment** (severity, affected versions) within 10 business days.
- A coordinated fix and disclosure timeline agreed with you before any public
  disclosure. We aim to ship a fix within 90 days and will keep you updated.
- Credit in the release notes for the fix, unless you prefer to remain anonymous.

## Scope

In scope: the Strumline code in this repository and the published container
image — authentication and token handling, the read-only ingest role boundary,
IPC framing, payload/frame limits, decompression handling, admin API gating,
metrics exposure, and log redaction.

Reports about vulnerabilities in Strumline's shipped dependencies or container
base image are in scope when they affect the shipped product. We may coordinate
the underlying fix upstream, then publish a patched Strumline image or pin.

Out of scope: issues that require a misconfigured deployment already called out as an operator responsibility in
[`docs/security.md`](docs/security.md) (for example, exposing `/metrics` or the
admin API to an untrusted network), and best-effort delivery semantics
(accepted records may be lost on failure — this is documented behavior, not a
vulnerability).

Thank you for helping keep Strumline and its users safe.
