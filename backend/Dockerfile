# syntax=docker/dockerfile:1
#
# Nestor Intake (GCP re-platform) backend image — ONE image, TWO entrypoints (D-02).
#
#   * Cloud Run SERVICE: runs the default CMD below (single Uvicorn process).
#   * Cloud Run migration JOB (Plan 03): overrides the CMD via
#       args = ["alembic", "upgrade", "head"]
#     so the SAME image runs migrations. That is why alembic.ini and
#     app/db/alembic ship inside the image.
#
# Security (D-09): there is NO DB password — auth is Cloud SQL IAM. NO secret,
# API key, or DATABASE_URL is baked into this image. Cloud Run injects only the
# non-secret env (INSTANCE_CONNECTION_NAME / DB_USER / DB_NAME / PORT).
#
# Migrations NEVER run at service startup (D-05): the default CMD is Uvicorn
# only — there is no `alembic upgrade` in CMD/ENTRYPOINT. Concurrent-migration
# races across N instances are avoided by running them solely via the Job.
#
# Concurrency (Pitfall 1): a SINGLE Uvicorn process — no multi-worker process
# manager, no extra worker flag. Each additional worker would open its own pool
# and multiply connections against the Cloud SQL tier limit as Cloud Run scales.

# ---------------------------------------------------------------------------
# Stage 1 — build: install dependencies with uv into the system interpreter.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS build

# uv: fast, lockfile-aware installer (pyproject project — no pip/requirements.txt).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

ENV PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

WORKDIR /app

# Dependency manifest first so the layer caches across source-only changes.
# `uv.lock*` is a glob: present -> frozen sync; absent -> the fallback installs
# straight from pyproject. `--no-dev` keeps pytest/testcontainers/httpx OUT of
# the runtime image.
COPY pyproject.toml uv.lock* README.md ./
RUN uv sync --frozen --no-dev --no-install-project \
    || uv pip install --system .

# Application package + migration assets. alembic.ini and app/db/alembic MUST be
# present so the migration Job (alembic upgrade head via args override) can run.
COPY app ./app
COPY alembic.ini ./alembic.ini
COPY app/db/alembic ./app/db/alembic

# Install the project itself into the system interpreter so the `app` package is
# importable from any cwd (both the Uvicorn entrypoint and the alembic Job that
# reads app/db/alembic).
RUN uv pip install --system --no-deps .

# ---------------------------------------------------------------------------
# Stage 2 — runtime: copy the installed interpreter + app, run Uvicorn.
# ---------------------------------------------------------------------------
FROM python:3.12-slim

WORKDIR /app

# Bring over the system-installed packages (uv pip install --system targets
# /usr/local) and the application + migration assets.
COPY --from=build /usr/local /usr/local
COPY --from=build /app /app

# PYTHONUNBUFFERED so Cloud Run captures logs in real time; PORT defaulted to
# 8080 but Cloud Run overrides it — the CMD binds whatever $PORT is injected.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

EXPOSE 8080

# Single Uvicorn process bound to Cloud Run's $PORT. The migration Job overrides
# this CMD with args=["alembic","upgrade","head"] (Plan 03) — do NOT bake a
# migration entrypoint here. This is the ONE app entrypoint in the image.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
