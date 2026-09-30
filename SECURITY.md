# Security Policy

Strumline sits on the ingest path between application code and an observability
stack, so we take security reports seriously. This document is about **reporting
vulnerabilities**. For the security properties of a deployment (auth tokens,
database grants, payload limits, redaction, socket permissions), see
[`docs/security.md`](docs/security.md).

## Supported versions

Strumline follows semantic versioning. Security fixes are applied to the latest
`1.x` release. Pre-1.0 tags are not supported.

| Version | Supported |
|---|---|
| `1.x` (latest) | ✅ |
| `< 1.0` | ❌ |

## Reporting a vulnerability

**Do not open a public issue for a security vulnerability.**

Report privately through GitHub's coordinated disclosure workflow:

1. Go to the repository's **Security** tab → **Report a vulnerability**
   (GitHub Private Vulnerability Reporting).
2. Describe the issue, the affected version or commit, and a reproduction if you
   have one.

If private reporting is unavailable to you, contact the maintainer through the
GitHub profile at https://github.com/Linguisto and ask for a private channel
before sharing any details.

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

Out of scope: vulnerabilities in third-party dependencies (report those
upstream; we will bump the pin once a fix is available), issues that require a
misconfigured deployment already called out as an operator responsibility in
[`docs/security.md`](docs/security.md) (for example, exposing `/metrics` or the
admin API to an untrusted network), and best-effort delivery semantics
(accepted records may be lost on failure — this is documented behavior, not a
vulnerability).

Thank you for helping keep Strumline and its users safe.
