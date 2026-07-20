# syntax=docker/dockerfile:1.7
# infrastructure/cloud-run/worker/Dockerfile
#
# Multi-stage build for the Nestor Pulse SDK worker (poll loop).
# Entrypoint: python -m nestor_pulse_sdk.runs.worker
#
# Worker has NO exposed HTTP port -- Cloud Run keeps it warm via
# --min-instances=1 --no-cpu-throttling regardless of inbound requests.
#
# Security note (T-10.5-01): NO API keys or secrets are baked into this image.
# All secrets are injected at deploy time via --set-secrets.
#
# D-01 (ADK preservation) means nestor_pulse/ must stay byte-IDENTICAL (read-only),
# NOT that it is excluded from the image. The worker DOES need it at runtime: the
# ADK engine IS nestor_pulse, and the SDK/Tribunal deep-research adapters import
# nestor_pulse.tools.*_deep_researcher. It is copied unmodified below.

FROM python:3.11-slim AS deps
WORKDIR /app
RUN pip install --no-cache-dir --upgrade pip
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.11-slim AS runtime
WORKDIR /app
# Copy installed packages from the deps stage (layer-cached)
COPY --from=deps /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin
# Copy the SDK package + the legacy nestor_pulse package (unmodified, D-01).
# The worker runs both engines: ADK (== nestor_pulse) and Tribunal (whose
# deep-research adapters import nestor_pulse.tools.*_deep_researcher).
COPY nestor_pulse_sdk ./nestor_pulse_sdk
COPY nestor_pulse ./nestor_pulse
ENV PYTHONUNBUFFERED=1
# No PORT / EXPOSE -- background worker, no HTTP server
CMD ["python", "-m", "nestor_pulse_sdk.runs.worker"]
