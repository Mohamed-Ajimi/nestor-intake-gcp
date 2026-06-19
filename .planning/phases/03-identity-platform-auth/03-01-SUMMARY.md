---
phase: 03-identity-platform-auth
plan: 01
subsystem: backend-auth
tags: [auth, identity-platform, firebase-admin, tests, wave-0, red-scaffold]
requires:
  - "backend FastAPI skeleton + config.py (Phase 02)"
  - "backend tests harness: conftest.py engine fixture + integration marker (Phase 01/02)"
  - "ORM models: Organization, OrganizationMembership (Phase 01)"
provides:
  - "firebase-admin>=7.4,<8 declared dependency (app.auth.* imports will resolve)"
  - "Settings.firebase_project_id non-secret config field (env FIREBASE_PROJECT_ID)"
  - "RED test contract for get_current_identity (401/403 split) — plan 02 turns GREEN"
  - "RED test contract for sync_claims_from_membership — plan 03 turns GREEN"
  - "RED structural guard for bearer-route removal (AUTH-05) — plan 04 turns GREEN"
affects:
  - "backend/pyproject.toml"
  - "backend/app/core/config.py"
tech-stack:
  added:
    - "firebase-admin>=7.4,<8 (Identity Platform server SDK)"
  patterns:
    - "Wave-0 RED scaffold: tests authored before implementation; importorskip keeps collection clean"
    - "All IdP calls mocked (verify_id_token / set_custom_user_claims patched); no live IdP (D-09)"
key-files:
  created:
    - "backend/tests/test_auth_dependency.py"
    - "backend/tests/test_auth_session.py"
    - "backend/tests/test_no_bearer_routes.py"
  modified:
    - "backend/pyproject.toml"
    - "backend/app/core/config.py"
decisions:
  - "Guarded firebase_admin + app.auth.* imports with pytest.importorskip so the RED scaffolds collect cleanly on the dev box (no firebase-admin installed, no live IdP) — mirrors conftest skip-clean philosophy."
  - "No secret/credential field added to Settings (D-09): firebase_project_id is a non-secret explicit override; Admin SDK init relies on ADC (GOOGLE_CLOUD_PROJECT)."
metrics:
  duration: "3 min"
  completed: "2026-06-19"
  tasks: 3
  files: 5
---

# Phase 3 Plan 01: Wave-0 Auth Safety Net Summary

Declared the `firebase-admin` dependency, added the single non-secret `firebase_project_id` config field the Admin SDK init needs, and authored three RED test scaffolds (auth-dependency 401/403 split, login-sync membership→claim contract, and the AUTH-05 bearer-route-removal structural guard) — all mocked, no live Identity Platform, so plans 02/03/04 have a failing-test target to turn GREEN.

## What Was Built

- **Task 1 (`feat`, d5c4fe2):** Added `firebase-admin>=7.4,<8` to `[project.dependencies]` in `backend/pyproject.toml` with an inline comment matching the existing per-dep style. Added `firebase_project_id: str | None = None` to `Settings` in `backend/app/core/config.py`, documented in the class docstring's identity block (maps to env `FIREBASE_PROJECT_ID`; ADC normally supplies the project via `GOOGLE_CLOUD_PROJECT`, so the field is an explicit override only). No secret field added; `get_settings()` remains un-cached; `model_config extra="ignore"` unchanged.
- **Task 2 (`test`, 0825b68):** `test_auth_dependency.py` — a tiny FastAPI app with one route guarded by `get_current_identity`; four cases pin the contract: `test_authorized_token` (full claims → 200 + role), `test_missing_token_401_or_403` (no header → 401|403), `test_invalid_token_401` (`InvalidIdTokenError` → 401), `test_missing_role_claim_403` (no `role` claim → 403). `test_auth_session.py` — `sync_claims_from_membership` cases: `test_membership_found_writes_claim` (membership row → `set_custom_user_claims` called once with role+space_id, returns True; `@pytest.mark.integration`), `test_no_membership_no_write` (no row → False, no Admin call; `@pytest.mark.integration`), `test_already_synced_is_noop` (decoded already has `role` → False, no Admin call; no marker). All IdP calls patched.
- **Task 3 (`test`, aa6cc2c):** `test_no_bearer_routes.py` — `test_bearer_route_files_absent` asserts the 5 `*.$token.tsx` routes plus `auth.callback.tsx` are gone; `test_routetree_has_no_bearer_refs` asserts `routeTree.gen.ts` carries none of the 6 deleted route ids (skips cleanly if the gen file is absent). Repo root derived from `__file__`.

## Key Decisions

- **importorskip on `firebase_admin` and `app.auth.*`:** The plan's test bodies import names that do not exist yet (firebase-admin not installed locally; `app.auth.dependencies/identity/session` land in plans 02/03). Guarding these at module level with `pytest.importorskip` keeps the suite *collectable* on this dev box and skips (never hard-errors) until the deps/modules exist — consistent with the conftest Docker/DB skip philosophy. Once plans 02/03 land and firebase-admin is installed, the cases run RED→GREEN as intended.
- **No secret in config (D-09 / threat T-03-01):** Only the non-secret `firebase_project_id` field was added. The Admin SDK initializes via ADC, so no SA-key/password field is introduced — the acceptance criteria forbidding any `*_key`/`*_secret`/`password` field are satisfied.

## Deviations from Plan

None — plan executed exactly as written. The `importorskip` guards are an implementation detail required by the plan's own "RED until plans 02-04 land" intent (the imported modules do not exist yet) and the documented no-local-Python/no-firebase-admin environment; they do not change the asserted contract.

## Test Execution Status (Deferred-to-Live)

Per the documented environment (no local Python/Docker runtime) and D-09, the test files were **authored by construction** against the final contract and parse/collection was validated structurally (function names, patch targets, markers) via Grep. The `python -c "ast.parse(...)"` verify commands in the plan could not be executed locally because no Python interpreter is present. Running the suite (and the RED→GREEN transition) is **deferred to the live GCP / CI environment** once firebase-admin and the `app.auth.*` modules from plans 02/03 are in place. No passing output was fabricated.

Intended Wave-0 state when the suite runs after plans 02-04: the auth-dependency and login-sync cases are RED until plans 02/03 land `app.auth.*`; the bearer-route guard is RED until plan 04 deletes the routes and regenerates the tree.

## Authentication Gates

None encountered (no live IdP interaction by design).

## Self-Check: PASSED

- FOUND: backend/pyproject.toml (firebase-admin entry, grep count = 1)
- FOUND: backend/app/core/config.py (firebase_project_id field)
- FOUND: backend/tests/test_auth_dependency.py
- FOUND: backend/tests/test_auth_session.py
- FOUND: backend/tests/test_no_bearer_routes.py
- FOUND commit: d5c4fe2 (Task 1)
- FOUND commit: 0825b68 (Task 2)
- FOUND commit: aa6cc2c (Task 3)
