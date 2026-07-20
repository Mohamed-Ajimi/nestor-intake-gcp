# Tribunal (re-homed deep-research engine)

This is the **Tribunal** deep-research engine (`nestor_pulse_sdk`), re-homed into this
repo in Phase 13 (decision **D-01**). From Phase 13 onward, all Tribunal changes, plans,
and commits happen here; the old standalone Nestor repo
(`C:\Users\ajimimo\Desktop\MOELD\Nestor\`) becomes a **frozen reference** and is no
longer edited.

This directory was populated by a **lift-and-shift** (byte-identical copy) of the working,
already-deployed engine. Integrity-critical files were carried verbatim and must NOT be
re-resolved or reformatted:

- `nestor_pulse_sdk/audit/hash_chain.py` — **FROZEN** tamper-evident audit hash-chain
  (ENGINE-04, EU AI Act Art. 12). The `_payload_for_row` field set (incl. `tenant_id`,
  `gcs_uri`) is hashed verbatim; any rename/reshape forks every chain. Do not alter.
- `requirements.txt` — pinned dependency set resolved on **Python 3.11.9**
  (`asyncpg`, `anthropic==0.104.1`, ...). Carried verbatim — do **not** bump or re-resolve.

## Separate from `backend/`

Tribunal is intentionally a **separate image and runtime** from the intake `backend/`:

| | `tribunal/` (this engine) | `backend/` (intake) |
|---|---|---|
| Python | **3.11.9** (`python:3.11-slim`) | 3.12 |
| DB driver | asyncpg (async), password-based `DATABASE_URL` over the Cloud SQL unix socket | pg8000 (sync), Cloud SQL IAM auth |
| Alembic line | its own (`0001`..`0010`), separate `version_table` + `tribunal` schema | intake `nestor` schema |

Two images / two Python minors / two DB drivers is correct and intentional — do not unify.

## What was copied

- `nestor_pulse_sdk/**` — the entire engine (server, runs, pipeline, audit, db, alembic,
  tools, citations, scripts, tests, `secrets_bootstrap.py`, `health.py`), minus the static
  `web/` UI and runtime caches (`__pycache__`, `.venv`, `.pytest_cache`).
- `nestor_pulse/secrets.py` — the **sole** cross-package dependency of the engine path
  (`secrets_bootstrap.py` imports `load_secrets_into_env` from it). The `nestor_pulse`
  package body beyond `secrets.py` (the `engine="adk"` ADK arm) was deliberately **not**
  copied; `nestor_pulse/__init__.py` here is a bare namespace so `import nestor_pulse.secrets`
  resolves without dragging in the un-copied ADK modules.
- `infrastructure/cloud-run/**` — Dockerfiles + deploy scripts, to be retargeted at the
  intake GCP project in Plan 03.
- `requirements.txt`, `pyproject.toml` (pytest config the suite needs).

## Not built here

The two NEW code changes that ride on this base — the Alembic `version_table`/`tribunal`
schema isolation in `env.py`, and the per-run advisory lock (`execute.py`) — are **Plan 02**.
Deploy retargeting is Plan 03; the live end-to-end proof run is Plan 04.
