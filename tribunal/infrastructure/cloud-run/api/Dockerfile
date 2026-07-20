# syntax=docker/dockerfile:1.7
# infrastructure/cloud-run/api/Dockerfile
#
# Multi-stage build for the Nestor Pulse SDK API server.
# Entrypoint: uvicorn nestor_pulse_sdk.server:app --host 0.0.0.0 --port ${PORT:-8080}
#
# Security note (T-10.5-01): NO API keys or secrets are baked into this image.
# All secrets are injected at deploy time via --set-secrets. Verify:
#   grep -E 'API_KEY=|SECRET=|PASSWORD=' Dockerfile  -> must return 0 lines.
#
# ADK preservation (D-01): nestor_pulse/ is NOT copied. The Cloud Run
# deployment uses only nestor_pulse_sdk/. The ADK pipeline stays local-dev only.

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
# Copy only the SDK package -- NOT nestor_pulse/ (D-01 ADK preservation)
COPY nestor_pulse_sdk ./nestor_pulse_sdk
# Cloud Run contract: honour $PORT env var (default 8080)
ENV PYTHONUNBUFFERED=1
ENV PORT=8080
EXPOSE 8080
CMD ["sh", "-c", "uvicorn nestor_pulse_sdk.server:app --host 0.0.0.0 --port ${PORT:-8080}"]
