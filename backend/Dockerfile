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

# Dependency manifest + application source, then a single project install.
# `uv.lock*` is a glob copied for future lockfile support; the install resolves
# dependencies from `pyproject.toml`.
#
# CR-01: install the project AND its dependencies into the SYSTEM interpreter
# (/usr/local), NOT into a `uv sync` project venv (/app/.venv). The runtime stage
# carries packages via `COPY --from=build /usr/local /usr/local` only — anything
# installed into a venv would be left behind and the runtime `uvicorn`/`app`
# import would fail. `uv pip install --system .` installs project + deps in one
# pass, so this holds whether or not a `uv.lock` is ever committed (no `uv sync`
# venv branch). The hatchling backend (packages = ["app"]) needs the `app` source
# present, so it is copied before the install.
COPY pyproject.toml uv.lock* README.md ./

# Application package + migration assets. alembic.ini and app/db/alembic (shipped
# inside app/) MUST be present so the migration Job (alembic upgrade head via args
# override) can run, and so the project install can find the `app` package.
COPY app ./app
COPY alembic.ini ./alembic.ini

RUN uv pip install --system .

# CR-01 build-time smoke check: fail the build NOW if any runtime dependency is
# missing from /usr/local, rather than crash-looping on Cloud Run at startup.
# This guards against a dependency-install regression silently shipping a broken
# image (the latent failure mode CR-01 describes).
RUN python -c "import fastapi, uvicorn, sqlalchemy, alembic, pg8000, google.cloud.sql.connector, pgvector, pydantic_settings, app.main"

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
