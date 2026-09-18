# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Stage 1: builder — install deps at /app so the venv path matches runtime
# ---------------------------------------------------------------------------
FROM python:3.14-slim AS builder

# Build directly at /app so shebang paths in the venv are already correct
# when copied into the runtime stage — no relocation needed.
WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock README.md ./

# Runtime deps only — cache-friendly layer before source copy
RUN uv sync --locked --no-dev --no-install-project

COPY telemetria/ ./telemetria/
COPY alembic/ ./alembic/
COPY alembic.ini ./
RUN uv sync --locked --no-dev


# ---------------------------------------------------------------------------
# Stage 2: runtime — minimal non-root production image
# ---------------------------------------------------------------------------
FROM python:3.14-slim AS runtime

ARG UID=10001
ARG GID=10001
RUN groupadd --gid "${GID}" telemetria \
 && useradd --uid "${UID}" --gid "${GID}" --no-create-home --shell /sbin/nologin telemetria

COPY --from=builder /app /app

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN mkdir -p /var/run/telemetria \
 && chown "${UID}:${GID}" /var/run/telemetria \
 && chown -R "${UID}:${GID}" /app

USER telemetria
WORKDIR /app


# ---------------------------------------------------------------------------
# Stage 3: dev — runtime + dev dependencies (pytest, ruff, mypy, etc.)
# ---------------------------------------------------------------------------
FROM runtime AS dev

USER root

COPY --from=builder /app/pyproject.toml /app/uv.lock /app/README.md /app/
COPY telemetria/ /app/telemetria/
COPY alembic/ /app/alembic/
COPY alembic.ini /app/
COPY tests/ /app/tests/

RUN pip install --no-cache-dir uv \
 && uv sync --locked --dev \
 && pip uninstall -y uv \
 && chown -R "${UID}:${GID}" /app/.venv /app/tests

USER telemetria
