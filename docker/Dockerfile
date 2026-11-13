# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Stage 1: builder — install deps at /app so the venv path matches runtime
# ---------------------------------------------------------------------------
FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928 AS builder

# Build directly at /app so shebang paths in the venv are already correct
# when copied into the runtime stage — no relocation needed.
WORKDIR /app

RUN pip install --no-cache-dir uv==0.13.7

COPY pyproject.toml uv.lock README.md ./

# Runtime deps only — cache-friendly layer before source copy
RUN uv sync --locked --no-dev --no-install-project

COPY strumline/ ./strumline/
COPY alembic/ ./alembic/
COPY alembic.ini ./
COPY LICENSE ./
COPY THIRD_PARTY_NOTICES.md ./
RUN uv sync --locked --no-dev


# ---------------------------------------------------------------------------
# Stage 2: shared runtime base
# ---------------------------------------------------------------------------
FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928 AS runtime-base

ARG UID=10001
ARG GID=10001
RUN groupadd --gid "${GID}" strumline \
 && useradd --uid "${UID}" --gid "${GID}" --no-create-home --shell /sbin/nologin strumline

COPY --from=builder /app /app

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN mkdir -p /var/run/strumline \
 && chown "${UID}:${GID}" /var/run/strumline \
 && chown -R "${UID}:${GID}" /app

USER strumline
WORKDIR /app


# ---------------------------------------------------------------------------
# Stage 3: runtime — patched, minimal non-root production image
# ---------------------------------------------------------------------------
FROM runtime-base AS runtime

USER root

# Apply security updates not yet present in the pinned base manifest. Runtime
# dependency installation is complete, so remove pip and its vendored packages.
RUN apt-get update \
 && apt-get install --only-upgrade --yes --no-install-recommends \
      apt libapt-pkg7.0 libpcre2-8-0 libssl3t64 openssl \
 && rm -rf /var/lib/apt/lists/* \
            /usr/local/lib/python3.14/site-packages/pip \
            /usr/local/lib/python3.14/site-packages/pip-*.dist-info \
            /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.14

USER strumline


# ---------------------------------------------------------------------------
# Stage 4: dev — shared base + dev dependencies (pytest, ruff, mypy, etc.)
# ---------------------------------------------------------------------------
FROM runtime-base AS dev

USER root

COPY --from=builder /app/pyproject.toml /app/uv.lock /app/README.md /app/
COPY strumline/ /app/strumline/
COPY alembic/ /app/alembic/
COPY alembic.ini /app/
COPY tests/ /app/tests/

RUN pip install --no-cache-dir uv==0.13.7 \
    && uv sync --locked --dev \
 && pip uninstall -y uv \
 && chown -R "${UID}:${GID}" /app/.venv /app/tests

USER strumline
