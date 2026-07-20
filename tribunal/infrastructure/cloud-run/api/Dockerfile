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
# Phase 13 re-home CORRECTION (13-01 SUMMARY deviation #1): the API image DOES need
# nestor_pulse/ at runtime. `nestor_pulse_sdk/tools/claude_adapter.py` does a
# MODULE-LEVEL `from nestor_pulse.tools.claude_deep_researcher import deep_research_async`,
# and that adapter is on the live engine boot path (research_division ->
# degraded_parallel -> claude_adapter). Without nestor_pulse/ the API ImportErrors at boot
# when the deep-research division loads. Only the copied leaf
# nestor_pulse/{secrets.py, tools/claude_deep_researcher.py} + namespace __init__.py files
# are present in the tree (the ADK arm was NOT copied — see tribunal/nestor_pulse/__init__.py),
# so this copy drags in no ADK modules. (The old "nestor_pulse/ is NOT copied" note reflected
# the standalone build before the re-home; it is corrected here.)

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
# Copy the SDK package + the copied nestor_pulse/ leaf (secrets.py +
# tools/claude_deep_researcher.py + namespace __init__.py files). The latter is a
# module-level boot dep of the deep-research division (see the header) — omitting it
# ImportErrors at boot. It carries NO ADK modules (they were not copied into the tree).
COPY nestor_pulse_sdk ./nestor_pulse_sdk
COPY nestor_pulse ./nestor_pulse
# Cloud Run contract: honour $PORT env var (default 8080)
ENV PYTHONUNBUFFERED=1
ENV PORT=8080
EXPOSE 8080
CMD ["sh", "-c", "uvicorn nestor_pulse_sdk.server:app --host 0.0.0.0 --port ${PORT:-8080}"]
