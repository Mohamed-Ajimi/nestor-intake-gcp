---
phase: 03-identity-platform-auth
plan: 03
subsystem: backend-auth
tags: [auth, identity-platform, login-sync, custom-claims, default-deny-router, seed, iam, wave-2]
requires:
  - "plan 02: Identity(uid,email,role,space_id) + get_current_identity + _bearer (HTTPBearer)"
  - "plan 02: init_firebase() in lifespan (Admin SDK ready before first request)"
  - "plan 01: RED contract backend/tests/test_auth_session.py (patch target app.auth.session.auth.set_custom_user_claims)"
  - "Phase 1/2: OrganizationMembership / Organization models, get_sessionmaker injection seam, FastAPI skeleton + main.py"
provides:
  - "sync_claims_from_membership(decoded, session_factory) — login-sync (membership -> server-set custom claims, AUTH-03/D-04)"
  - "POST /auth/session — anonymous-but-self-verifying login-sync handshake (verify_id_token -> sync -> {synced:true}|403)"
  - "protected_router = APIRouter(dependencies=[Depends(get_current_identity)]) — the default-deny base for all future feature routers (AUTH-01)"
  - "scripts/seed_superadmin.py — idempotent first-superadmin bootstrap (IdP user + cross-tenant claim + FK-anchored membership)"
  - "infra: runtime SA roles/identitytoolkit.admin binding + nestor-seed-superadmin Cloud Run Job"
affects:
  - "backend/app/main.py (mounts auth_router + protected_router; probes stay anonymous)"
  - "infra/main.tf, infra/variables.tf, infra/README.md (IdP IAM + seed Job + runbook)"
tech-stack:
  added: []
  patterns:
    - "Anonymous-but-self-verifying endpoint: /auth/session uses _bearer + auth.verify_id_token (NOT get_current_identity) so un-synced users can reach it (Pitfall 1)"
    - "Default-deny base router: feature routers inherit Depends(get_current_identity) via a shared protected_router (AUTH-01)"
    - "Server-set claims from the DB source of truth, never client input (D-03/D-04); claim payload kept under the 1000-byte limit"
    - "Superadmin = cross-tenant: claim space_id=None while the membership organization_id is an FK anchor only (Open Q3 / T-03-16)"
    - "Cloud Run Job alt-entrypoint for the seed (mirrors the migration Job); ADC only, password supplied at execute time (no stored credential)"
key-files:
  created:
    - "backend/app/auth/session.py"
    - "backend/app/api/__init__.py"
    - "backend/app/api/auth_routes.py"
    - "backend/scripts/seed_superadmin.py"
  modified:
    - "backend/app/main.py"
    - "infra/main.tf"
    - "infra/variables.tf"
    - "infra/README.md"
decisions:
  - "post_session distinguishes already-synced (decoded carries role) from no-membership: sync_claims_from_membership returns False for BOTH, so the handler re-checks decoded.get('role') — role present => {synced:true}, absent + False => 403 (no membership). This keeps the test contract (return False on already-synced) intact while the endpoint still returns success for an already-synced caller."
  - "Added infra/variables.tf var superadmin_email (Rule 3 — the seed Cloud Run Job's SUPERADMIN_EMAIL env needs a non-secret input); the password is NEVER an IaC var/state value — it is passed at `gcloud run jobs execute --update-env-vars` time (T-03-15)."
  - "seed UPSERT matches on (organization_id, email) and repairs provider_user_id/role in place on re-run, rather than relying on a DB ON CONFLICT — mirrors seed_dev.py's get-or-create idiom and the uq_membership_org_user intent without importing dialect-specific upsert."
metrics:
  duration: "12 min"
  completed: "2026-06-19"
  tasks: 3
  files: 8
---

# Phase 3 Plan 03: Auth Provisioning (login-sync + default-deny routing + superadmin seed) Summary

Wired the provisioning half of auth: `sync_claims_from_membership` mirrors the `organization_memberships` source-of-truth row into Identity Platform custom claims server-side (turning plan-01's `test_auth_session.py` GREEN once firebase-admin is installed), the anonymous-but-self-verifying `POST /auth/session` login-sync handshake plus the `protected_router` default-deny base every future feature router inherits (AUTH-01), the idempotent first-superadmin seed (IdP user + cross-tenant claim + FK-anchored membership, Open Q3), and the `roles/identitytoolkit.admin` IAM grant + a `nestor-seed-superadmin` Cloud Run Job + runbook the claim writes need. Nothing added creates a `run-research` path — the flow still stops at `decomposed`.

## What Was Built

- **Task 1 (`feat`, 34098b9):** `backend/app/auth/session.py` — `sync_claims_from_membership(decoded, session_factory=None) -> bool`. Short-circuits to `False` (no DB read, no Admin call) when `decoded.get("role") is not None` (already synced — idempotent, no per-request re-write). Otherwise builds a session via `maker = session_factory or get_sessionmaker()` (the seed_dev injection seam the test binds its conftest engine to) and runs `_find_membership` = `select(OrganizationMembership).where(or_(provider_user_id == uid, email == email)).scalar_one_or_none()`. No row -> `False` (D-02: never creates a user; caller 403s). Found -> `auth.set_custom_user_claims(uid, {"role": role, "space_id": None if role=="superadmin" else str(organization_id)})` exactly once, then `True`. `from firebase_admin import auth` binds the `app.auth.session.auth.set_custom_user_claims` patch target the plan-01 suite mocks. Docstring documents THE GOTCHA (client must `getIdToken(true)` after sync) and the 1000-byte claim budget.
- **Task 2 (`feat`, 5ee02b5):** `backend/app/api/__init__.py` (layer marker) + `backend/app/api/auth_routes.py` with two routers. `auth_router` (`prefix="/auth"`) carries the ANONYMOUS sync `def post_session(cred=Depends(_bearer))` — it self-verifies via `auth.verify_id_token` (Expired/Invalid -> 401), calls `sync_claims_from_membership(decoded)`, returns `{"synced": True}` on a write OR an already-synced token (`decoded.get("role") is not None`), and raises 403 when the verified user has no membership (no claim write — T-03-11). `protected_router = APIRouter(dependencies=[Depends(get_current_identity)])` is the exported default-deny base (no routes yet, Phase 4+ mounts feature routers under it). `backend/app/main.py` now `include_router`s both AFTER `app = FastAPI(...)`; no auth dependency is on the bare app so `/healthz` `/readyz` stay anonymous (Pitfall 1).
- **Task 3 (`feat`, e231ce8):** `backend/scripts/seed_superadmin.py` clones `seed_dev.py`'s shape — PowerShell-usage docstring, deterministic `SYSTEM_ORG_ID`, `seed(email, password, session_factory)`, `+`/`=` summary print, `__main__` entrypoint accepting `email`/`password` from argv or env. Flow: `firebase_admin.initialize_app()` (ADC, guarded on `_apps`); `try auth.get_user_by_email(email) except auth.UserNotFoundError: auth.create_user(email, password)` (promote-or-create); `auth.set_custom_user_claims(uid, {"role":"superadmin","space_id":None})`; then get-or-create the system "Agenic" org (`SYSTEM_ORG_ID`, satisfies the NOT NULL FK) and UPSERT the superadmin `organization_memberships` row keyed on (organization_id, email), repairing `provider_user_id`/`role` in place on re-run. `infra/main.tf` gains a third runtime-SA binding `roles/identitytoolkit.admin` (least-privilege; verification needs no role, claim writes/user-create do — Pitfall 6/T-03-14) and a `nestor-seed-superadmin` Cloud Run Job (same image, `args=["python","-m","scripts.seed_superadmin"]`, ADC, no stored password). `infra/variables.tf` adds `superadmin_email`. `infra/README.md` adds Step 4b: the IAM apply, the same-project Pitfall-5 guard (`VITE_FIREBASE_PROJECT_ID` == `GOOGLE_CLOUD_PROJECT`), the seed Job run (password via `--update-env-vars` at execute time), and the Firebase Auth emulator note.

## Contract Satisfied (plan-01 RED tests)

`backend/tests/test_auth_session.py` patches `app.auth.session.auth.set_custom_user_claims` and binds a conftest-engine `session_factory`:
- `test_membership_found_writes_claim` (`@integration`) — seeds an org + `role="user"` membership; expects `result is True`, `set_custom_user_claims` called once, `claims["role"]=="user"`, `str(claims["space_id"])==space_id`. The impl calls `set_custom_user_claims(uid, {...})` positionally so the test's `mock_set.call_args[0][-1]` reads the dict; `space_id=str(organization_id)` for a non-superadmin. ✓
- `test_no_membership_no_write` (`@integration`) — orphan decoded -> `_find_membership` None -> `False`, no Admin call. ✓
- `test_already_synced_is_noop` — decoded carries `role` -> `False` before any DB/Admin access. ✓

## Deviations from Plan

### Auto-fixed / scope-clarifying

**1. [Rule 3 - Blocking] Added `infra/variables.tf` `superadmin_email` variable**
- **Found during:** Task 3.
- **Issue:** The plan's `files_modified` lists `infra/main.tf` but the runbook directs running the seed "as a Cloud Run Job reusing the service image with an alt entrypoint, mirroring the migration Job". A declarative Job needs its `SUPERADMIN_EMAIL` from a non-secret input; hard-coding it in `main.tf` would be worse than a variable.
- **Fix:** Added a `superadmin_email` variable (default `yanick@agenic.be`) consumed by the seed Job's `SUPERADMIN_EMAIL` env. The password is deliberately NOT a variable/state value — supplied at execute time via `gcloud run jobs execute --update-env-vars SUPERADMIN_PASSWORD=...` (T-03-15).
- **Files modified:** `infra/variables.tf` (+ the seed Job + IAM block in `infra/main.tf`).
- **Commit:** e231ce8.

**2. [Clarification] `/auth/session` already-synced vs no-membership disambiguation**
- `sync_claims_from_membership` returns `False` for BOTH already-synced and no-membership (per the plan-01 test contract). To map this to the correct HTTP response, `post_session` re-checks `decoded.get("role")`: present => `{"synced": True}` (already synced, success), absent + `False` => 403 (no membership). Documented in the handler and frontmatter decisions.

Otherwise: plan executed as written.

## Threat Surface

All plan `mitigate` dispositions are realized:
- T-03-11 (claims from client input) — claims derived from the membership row matched to the verified token; no membership -> 403, no write.
- T-03-12 (forged token at /auth/session) — handler self-verifies via `auth.verify_id_token` before any claim write (Invalid/Expired -> 401).
- T-03-13 (stale claim / silent-403 loop) — `{"synced": true}` + THE GOTCHA `getIdToken(true)` documented in session.py + auth_routes.py docstrings (plan 04 implements the client handshake).
- T-03-14 (claim write fails for lack of IAM) — `roles/identitytoolkit.admin` on the runtime SA; runbook applies it before login traffic.
- T-03-15 (SA key / password leakage) — seed uses ADC (no JSON key); the superadmin password is never an IaC var/state value, only an execute-time env.
- T-03-16 (superadmin scoped to one space) — claim `space_id=None` (cross-tenant); membership `organization_id` is an FK anchor only.
- T-03-17 (anonymous feature routes) — `protected_router` default-denies via `Depends(get_current_identity)`; only probes + `/auth/session` are anonymous.

No security-relevant surface beyond the plan's threat model was introduced. No `run-research` path exists in any added file (scope ceiling honored).

## Test Execution Status (Deferred-to-Live, D-09)

This dev box has no Python/Docker/uv runtime and firebase-admin is not installed (confirmed across plans 01/02). Per the plan's own acceptance fallback and D-09, the code was **authored by construction** against the plan-01 test contract and verified **structurally** via Grep against the asserted seams: the `app.auth.session.auth.set_custom_user_claims` patch target (`from firebase_admin import auth`); the `or_(provider_user_id, email)` + `scalar_one_or_none()` lookup; the `session_factory` injection seam; superadmin `space_id=None` vs `str(organization_id)`; `/auth/session` + `get_current_identity` + `verify_id_token` present in `auth_routes.py`; the sync `def post_session` handler; `seed_superadmin.py` `get_user_by_email`/`create_user`/`set_custom_user_claims`; and `grep -c "identitytoolkit.admin" infra/main.tf` = 5 (>= 1). The `uv run pytest backend/tests/test_auth_session.py -x`, the `python -c "import ast; ast.parse(...)"` parse checks, and `terraform validate` could NOT be executed locally — running the suite (and the RED->GREEN transition once firebase-admin + a test DB are present) and `terraform validate/apply` are **deferred to the live GCP / CI environment** (the `infra/README.md` Step 4b runbook covers the live IAM apply + seed run). No passing output was fabricated.

## Authentication Gates

None encountered (no live IdP interaction by design — all Admin SDK calls are mocked in tests / ADC-deferred to live per D-09).

## Self-Check: PASSED

- FOUND: backend/app/auth/session.py (sync_claims_from_membership; or_; set_custom_user_claims; session_factory seam)
- FOUND: backend/app/api/__init__.py
- FOUND: backend/app/api/auth_routes.py (/auth/session, get_current_identity, verify_id_token, protected_router, sync def post_session)
- FOUND: backend/app/main.py (include_router(auth_router) + include_router(protected_router); probes anonymous)
- FOUND: backend/scripts/seed_superadmin.py (get_user_by_email, create_user, UserNotFoundError, set_custom_user_claims, system-org get-or-create, membership UPSERT)
- FOUND: infra/main.tf (roles/identitytoolkit.admin binding + nestor-seed-superadmin Job; grep "identitytoolkit.admin" = 5)
- FOUND: infra/variables.tf (superadmin_email)
- FOUND: infra/README.md (Step 4b: IAM apply, same-project guard, seed Job run, emulator note)
- FOUND commit: 34098b9 (Task 1)
- FOUND commit: 5ee02b5 (Task 2)
- FOUND commit: e231ce8 (Task 3)
