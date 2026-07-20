---
phase: 14-auth-retirement-integration-seam
verified: 2026-07-20T22:00:00Z
status: human_needed
score: 3/3 must-haves verified
overrides_applied: 0
human_verification:
  - test: "Confirm the live tribunal-api service (running image SHA 20260720-233938) is actually receiving calls from the intake nestor-api service using the real IAM invoker token (nestor-run SA)"
    expected: "tribunal-api Cloud Run logs show authenticated calls from nestor-run@project-cb01b861-cb4a-438d-b9a.iam.gserviceaccount.com reaching InternalCallerProvider; no anonymous or wrong-SA calls appear in logs"
    why_human: "Cannot programmatically introspect live Cloud Run request logs or verify the deployed service's active IAM binding from the dev box. The D-07 live proof ran a smoke job (tribunal-smoke-phrdx) that self-provisions org+project+run in-process without passing through the intake->tribunal HTTP seam HTTP call. The live intake->tribunal admit path with a real SA token is by-construction, not by an observed end-to-end call from nestor-api."
  - test: "Verify the live intake nestor-api carries TRIBUNAL_SERVICE_URL and can reach tribunal-api via the seam"
    expected: "gcloud run services describe nestor-api shows TRIBUNAL_SERVICE_URL env var set; calling POST /api/orgs/ensure through nestor-api (once Phase 16 trigger route exists, or via Cloud Shell curl with the nestor-run token) returns 200 with the correct tenant_id"
    why_human: "The D-05 acting-user header attribution through the live intake->tribunal HTTP call is not proven by the Phase 14 proofs. The SUMMARY explicitly defers this to Phase 16. No automated check can verify live Cloud Run env vars or the end-to-end seam call from the dev box."
---

# Phase 14: Auth Retirement + Integration Seam Verification Report

**Phase Goal:** Tribunal's standalone auth, orgs, and UI are retired so the intake backend is the sole caller, with every run space-scoped end-to-end.
**Verified:** 2026-07-20T22:00:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #  | Truth                                                                                                      | Status     | Evidence                                                                                                                                      |
|----|------------------------------------------------------------------------------------------------------------|------------|-----------------------------------------------------------------------------------------------------------------------------------------------|
| 1  | Tribunal's own logins/orgs/UI are gone (`InternalCallerProvider` installed; `orgs/`, `account/`, `Login.jsx`, static `web/` mount removed) and only the intake backend can call the Tribunal API (IAM invoker = intake runtime SA, internal-only) | ✓ VERIFIED | `identity_platform.py`, `account/`, `demo/` absent from codebase; no `StaticFiles`, no `/app` mount, no `account_router`/`demo_router` in `server.py`; `firebase-admin` absent from `requirements.txt`; `InternalCallerProvider` installed at `set_auth_provider()` in `server.py`; `infra/main.tf` has unconditional `run.invoker` binding to nestor-run only; `deploy-api.sh`/`deploy-worker.sh` target `tribunal-run`; IDENTITY_PLATFORM absent from both deploy scripts; live proof: unauthenticated call returns 403 at IAM edge; D-07 runbook recorded as live (build `25b8f9eb` green, image `20260720-233938` deployed). |
| 2  | Every intake space maps 1:1 onto a Tribunal org/project (identity `space_id` → `tenant_id`, lazy project provisioning), so each run is space-scoped from trigger to storage | ✓ VERIFIED | `ensure_org` uses `id=tenant_uuid` (org.id == space_id, identity mapping, verified in `orgs/provision.py:116`); `ensure_project` provisions exactly one project per space using an advisory lock (WR-04 concurrency fix present); `POST /api/orgs/ensure` and `POST /api/projects/ensure` endpoints exist in `orgs/api.py`; `get_db_session` reads `user.tenant_id` (the verified header value) for RLS `SET LOCAL`; live smoke run `b188a83e` completed with `chain=OK` with space_id `1464b60d` mapping to the org. |
| 3  | The CI-gated cross-tenant denial suite is extended to cover Tribunal tables and passes (GUC-name mismatch cannot leak across the HTTP boundary) | ✓ VERIFIED | `tribunal/nestor_pulse_sdk/tests/test_seam_denial.py` exists with 6 test functions (missing_tenant→400 PINNED, malformed_tenant→400, missing_acting_user→400, wrong_sa→403, unauth→401, guc_leak firewall); `tribunal/nestor_pulse_sdk/tests/test_seam_rls_denial.py` exists with 2 async test functions (`test_seam_project_run_cross_tenant_denied`, `test_seam_no_tenant_context_denied`); `tribunal/cloudbuild.seam-gate.yaml` provisions non-superuser app_user, runs all 8 cases with anti-false-green grep (`8 passed`); recorded live result: build `79c095fd` "SEAM GATE GREEN: 8/8 executed and passed as non-superuser". |

**Score:** 3/3 truths verified

### Required Artifacts

| Artifact                                                           | Expected                                                             | Status     | Details                                                                            |
|--------------------------------------------------------------------|----------------------------------------------------------------------|------------|------------------------------------------------------------------------------------|
| `tribunal/nestor_pulse_sdk/auth/internal_caller.py`                | InternalCallerProvider (AuthProvider impl) + get_internal_claims    | ✓ VERIFIED | `class InternalCallerProvider` present; `verify_id_token` offloaded to threadpool (WR-02 fix); `get_internal_claims` requires all 3 headers; malformed UUID rejected with 400 (WR-03 fix); `SEAM_PROVIDER_MARKER = "intake-seam"` present |
| `tribunal/nestor_pulse_sdk/orgs/provision.py`                      | ensure_org / ensure_project idempotent get-or-create                | ✓ VERIFIED | Both async functions present; ON_CONFLICT_DO_NOTHING for ensure_org (WR-04); advisory lock for ensure_project (WR-04); no `_firebase_set_claims`; `owner_user_id=None` |
| `tribunal/nestor_pulse_sdk/server.py`                              | InternalCallerProvider install + dependency_overrides + stripped router mounts | ✓ VERIFIED | `set_auth_provider(InternalCallerProvider(...))` present; `dependency_overrides[get_current_user] = get_internal_claims` present; CORS gated to LOCAL_DEV_AUTH (WR-05 fix); LOCAL_DEV_AUTH refused on Cloud Run via K_SERVICE check (WR-06 fix); fail-closed env var read (D-DEF-4 fix) |
| `backend/app/research/tribunal_client.py`                          | OIDC minting + ensure_org / ensure_project HTTP client (minimal, D-06) | ✓ VERIFIED | `_mint_id_token`, `ensure_org`, `ensure_project` defined; `fetch_id_token` with service URL (no path); `X-Nestor-Tenant-Id`, `X-Acting-User-Id`, `X-Acting-User-Email` headers; `raise_for_status()` called; no trigger/poll/report methods |
| `backend/app/core/config.py`                                       | tribunal_service_url non-secret Settings field                      | ✓ VERIFIED | `tribunal_service_url: str | None = None` at line 104 with non-secret comment noting URL without path (Pitfall 4) |
| `backend/app/research/__init__.py`                                 | Package marker                                                       | ✓ VERIFIED | File exists |
| `backend/tests/test_tribunal_client.py`                            | Mocked unit test for tribunal_client                                | ✓ VERIFIED | File exists |
| `backend/tests/test_tribunal_seam_denial.py`                       | Seam-level denial suite (intake copy; skips by design D-DEF-1)     | ✓ VERIFIED | File exists; documented to skip in intake CI image since nestor_pulse_sdk not on path; not the CI gate |
| `tribunal/nestor_pulse_sdk/tests/test_seam_denial.py`             | Re-homed executing seam denial suite (6 cases)                      | ✓ VERIFIED | File exists; 6 test functions covering all required denial cases |
| `tribunal/nestor_pulse_sdk/tests/test_seam_rls_denial.py`         | tribunal.* two-tenant RLS denial (asyncpg, 2 cases)                | ✓ VERIFIED | File exists; 2 async test functions; `set_tenant_context` present; non-superuser guard present |
| `tribunal/nestor_pulse_sdk/tests/test_internal_caller.py`         | Unit tests for InternalCallerProvider                               | ✓ VERIFIED | File exists |
| `tribunal/cloudbuild.seam-gate.yaml`                              | Focused D-08 gate: non-superuser Postgres + 8-case anti-false-green | ✓ VERIFIED | File exists; provisions app_user/worker_user; runs 8 tests; `grep -E "(^| )8 passed"` exact-match; skip fails build |
| `infra/main.tf`                                                   | tribunal_run SA + least-priv bindings + run.invoker = nestor-run + seam env vars | ✓ VERIFIED | `google_service_account.tribunal_run` present; `run.invoker` binding to intake runtime SA; `TRIBUNAL_SERVICE_URL` + `INTAKE_RUNTIME_SA_EMAIL` on tribunal-api; `TRIBUNAL_SERVICE_URL` on nestor-api; no IDENTITY_PLATFORM in Tribunal blocks |
| `infra/variables.tf`                                              | tribunal_runtime_sa_id + tribunal_service_url variables             | ✓ VERIFIED | Both variables found at lines 351 and 357 |
| `infra/DEPLOY-RUNBOOK.md`                                         | § Phase 14 steps 14.a-14.g including correct seam-gate invocation   | ✓ VERIFIED | `## Phase 14` section present; Step 14.g invokes `gcloud builds submit tribunal --config=tribunal/cloudbuild.seam-gate.yaml` (CR-01 fixed by post-review commit `dd6aa6d`); all steps 14.a-14.g present including SA creation, redeploy, invoker binding |
| `tribunal/infrastructure/cloud-run/deploy-api.sh`                 | SA = tribunal-run; IDENTITY_PLATFORM absent                         | ✓ VERIFIED | `SA="tribunal-run@..."` at line 36; no IDENTITY_PLATFORM |
| `tribunal/infrastructure/cloud-run/deploy-worker.sh`              | SA = tribunal-run; IDENTITY_PLATFORM absent                         | ✓ VERIFIED | SA retargeted per SUMMARY; no IDENTITY_PLATFORM |

### Key Link Verification

| From                                                      | To                                    | Via                                       | Status     | Details                                                                             |
|-----------------------------------------------------------|---------------------------------------|-------------------------------------------|------------|-------------------------------------------------------------------------------------|
| `tribunal/nestor_pulse_sdk/server.py`                     | `set_auth_provider`                   | startup install of InternalCallerProvider | ✓ WIRED    | `set_auth_provider(InternalCallerProvider(...))` at server.py:163                  |
| `tribunal/nestor_pulse_sdk/auth/internal_caller.py`       | `google.oauth2.id_token.verify_oauth2_token` | OIDC verification via threadpool     | ✓ WIRED    | `run_in_threadpool(ga_id_token.verify_oauth2_token, token, self._transport, self._aud)` |
| `tribunal/nestor_pulse_sdk/orgs/api.py`                   | `ensure_org`                          | /api/orgs/ensure endpoint calls provisioner | ✓ WIRED | `ensure_org_endpoint` calls `ensure_org(space_id=user.tenant_id, ...)` |
| `backend/app/research/tribunal_client.py`                 | `google.oauth2.id_token.fetch_id_token` | keyless OIDC minting from ADC          | ✓ WIRED    | `ga_id_token.fetch_id_token(_TRANSPORT, service_url)` in `_mint_id_token` |
| `backend/app/research/tribunal_client.py`                 | Tribunal `/api/orgs/ensure`           | httpx.post with Bearer token + acting-user headers | ✓ WIRED | `httpx.post(f"{service_url}/api/orgs/ensure", headers=_headers(...))` |

### Data-Flow Trace (Level 4)

This phase produces backend provisioning logic and test artifacts, not UI rendering components. Data flow from the intake seam to the Tribunal DB is structural: the caller's `X-Nestor-Tenant-Id` header flows through `get_internal_claims` → `AuthClaims.tenant_id` → `get_db_session` sets `SET LOCAL app.tenant_id` → all SQL runs under that RLS context. Verified structurally by:

- `get_internal_claims` validates and extracts the tenant header (confirmed present with UUID validation in `internal_caller.py`)
- `get_db_session` sets `app.tenant_id` from `user.tenant_id` (documented as UNTOUCHED from prior phase; `orgs/api.py` uses the standard `Depends(get_db_session)` wiring)
- `ensure_org` inserts `Org(id=tenant_uuid)` where `tenant_uuid = uuid.UUID(space_id)` (org.id == space_id identity mapping proven in code)
- `ensure_project` queries `Project.tenant_id == tenant_uuid` under the tenant context (advisory-lock serialized)
- GUC-leak firewall proven by seam gate: the recording fake session captures the exact tenant set, confirming space-A header never produces space-B DB context

### Behavioral Spot-Checks

Step 7b: SKIPPED — dev box has no Python/Docker, cannot run pytest or servers locally (documented project constraint). All behavioral verification is by-construction (code structure) + recorded Cloud Build results.

### Probe Execution

| Probe | Command | Result | Status |
|-------|---------|--------|--------|
| `tribunal/cloudbuild.seam-gate.yaml` (8-case denial gate) | `gcloud builds submit tribunal --config=tribunal/cloudbuild.seam-gate.yaml` | Build `79c095fd` SUCCESS — "SEAM GATE GREEN: 8/8 executed and passed as non-superuser" (post-review fix cycle; was `25b8f9eb` for 6 cases before malformed_tenant + missing_acting_user added) | PASS (recorded) |

Note: Probe results are recorded from the live operator session in `14-04-SUMMARY.md`. The dev box has no Docker/Python; probes cannot be re-run locally. The verifier has confirmed the YAML gate file exists and matches the described behavior (8-test anti-false-green grep, non-superuser Postgres setup).

### Requirements Coverage

| Requirement | Source Plan | Description                                                                                          | Status     | Evidence                                                                                                                              |
|-------------|-------------|------------------------------------------------------------------------------------------------------|------------|---------------------------------------------------------------------------------------------------------------------------------------|
| SEAM-01     | 14-01, 14-04 | Tribunal's standalone logins/orgs/UI are retired; only the intake backend can call it (server-to-server internal auth) | ✓ SATISFIED | `InternalCallerProvider` installed; retired surfaces deleted; invoker=nestor-run ONLY; IDENTITY_PLATFORM absent from Tribunal config; live unauthenticated proof returns 403 |
| SEAM-02     | 14-01, 14-02, 14-03, 14-04 | Intake spaces map 1:1 onto Tribunal orgs; every run is space-scoped end-to-end (cross-tenant denial suite extended to Tribunal data) | ✓ SATISFIED | `ensure_org` (org.id==space_id), `ensure_project` (one per space); seam gate 8/8 PASS; live smoke run completed with chain=OK; `tribunal_client.py` provides OIDC-minted HTTP client |

No orphaned requirements: REQUIREMENTS.md maps only SEAM-01 and SEAM-02 to Phase 14, and both are accounted for.

### Anti-Patterns Found

| File                                                              | Line | Pattern                                    | Severity | Impact                                                                                                             |
|-------------------------------------------------------------------|------|--------------------------------------------|----------|--------------------------------------------------------------------------------------------------------------------|
| `backend/tests/test_tribunal_seam_denial.py`                      | 1    | All 4 original seam denial cases permanently skip in CI (D-DEF-1) | ℹ️ Info  | The executing copy is `test_seam_denial.py` in the Tribunal harness. Documented intentionally; risk is drift between the two copies (IN-02 from review). Not a blocker — the gate runs from the Tribunal harness copy. |
| `tribunal/nestor_pulse_sdk/auth/internal_caller.py`               | 126  | `except Exception` catches all exceptions including transient network errors as 401 | ℹ️ Info  | Fail-closed is correct (IN-07 from review); transient cert-fetch errors are misleading as 401 but not a security gap. Not a blocker — the review noted this as Info. |
| `backend/app/research/tribunal_client.py`                         | 47   | Module-level `ga_requests.Request()` transport shared across threadpool threads | ℹ️ Info  | `requests.Session` thread-safety is not guaranteed (IN-05 from review). Failures rare and transient. Not a blocker for the seam contract. |
| `infra/main.tf`                                                   | 1147 | Stale comment describing old allow_unauthenticated toggle (IN-01 from review) | ℹ️ Info  | Comment says invoker "gated on var.allow_unauthenticated" but the actual resource is unconditional; security intent is correct, comment is stale. |

No TBD/FIXME/XXX markers found in Phase 14 files.

**Debt-marker gate: PASSED** — no unreferenced TBD/FIXME/XXX markers in modified files.

### Human Verification Required

#### 1. Live intake→Tribunal HTTP seam call with real SA token

**Test:** From Cloud Shell, obtain a token for the nestor-run SA and call `POST https://tribunal-api-ybkr7metoq-ew.a.run.app/api/orgs/ensure` with headers `X-Nestor-Tenant-Id: <a real space_id>`, `X-Acting-User-Id: <superadmin uid>`, `X-Acting-User-Email: <superadmin email>`, `Authorization: Bearer <nestor-run id token>`.

**Expected:** HTTP 200 with `{"tenant_id": "<space_id>"}`. Cloud Run logs show the call attributed to `nestor-run@...`. The Tribunal org row exists in the DB with `id == space_id`.

**Why human:** The D-07 positive proof (smoke run `b188a83e`) ran the pipeline in-process without going through the HTTP seam from nestor-api. The live intake→tribunal HTTP call path with an actual minted nestor-run SA token has not been exercised end-to-end. The SUMMARY documents this explicitly: "A live intake→tribunal acting-user HTTP call awaits the Phase-16 trigger route." The IAM path is proven by-construction (invoker binding verified + app-layer 403 on wrong SA proven by the seam gate), but no observable server log or HTTP response confirms the full path is live.

#### 2. Confirm TRIBUNAL_SERVICE_URL on live nestor-api

**Test:** Run `gcloud run services describe nestor-api --format='value(spec.template.spec.containers[0].env)' --project=project-cb01b861-cb4a-438d-b9a --region=europe-west1` and confirm `TRIBUNAL_SERVICE_URL` is set and equals `https://tribunal-api-ybkr7metoq-ew.a.run.app` (the captured URL from Step 14.d).

**Expected:** The env var is present and correct on the live nestor-api service.

**Why human:** Cannot programmatically verify live Cloud Run service env vars from the dev box without gcloud access. The SUMMARY states Step 14.d set it, but the verifier cannot confirm the current state of the live service from a static codebase check.

### Gaps Summary

No blocking gaps were found. All three roadmap success criteria are observably met in the codebase:

1. SC1 (logins/orgs/UI retired, InternalCallerProvider installed, invoker=nestor-run only): fully implemented in code and IaC; retired surfaces deleted; live proof recorded.
2. SC2 (1:1 space→org/project mapping, space-scoped runs): `ensure_org/ensure_project` implemented with `org.id == space_id`; endpoints wired; smoke run completed with chain=OK.
3. SC3 (CI-gated cross-tenant denial suite extended to Tribunal tables, passes): 8-case seam gate exists and passed (build `79c095fd`); non-superuser RLS faithfulness enforced.

The two human verification items concern the live end-to-end intake→tribunal HTTP seam call (deferred to Phase 16 per plan's own documented D-06 scope boundary) and a live env var confirmation. These do not block the codebase goal but require operator confirmation before the seam can be claimed fully end-to-end live.

---

_Verified: 2026-07-20T22:00:00Z_
_Verifier: Claude (gsd-verifier)_
