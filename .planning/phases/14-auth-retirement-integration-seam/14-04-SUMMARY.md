---
phase: 14-auth-retirement-integration-seam
plan: 04
subsystem: infra
tags: [cloud-run, iam, oidc, service-account, least-privilege, rls, multi-tenant, cloud-build, terraform, seam]

# Dependency graph
requires:
  - phase: 14-01
    provides: "InternalCallerProvider (OIDC caller verify) + get_internal_claims (header→AuthClaims, D-05) + /api/orgs/ensure + /api/projects/ensure; retired IdP surface; firebase-admin removed"
  - phase: 14-02
    provides: "intake tribunal_client.py (OIDC-minting httpx seam client; ensure_org/ensure_project only, D-06)"
  - phase: 14-03
    provides: "seam + tribunal.* cross-tenant denial suites (the CI-gate content)"
  - phase: 13-tribunal-rehome
    provides: "deployed tribunal-api/worker/migrate on the intake project; app_user/worker_user Cloud SQL roles; alembic 0001-0010; the § Phase 13 runbook shape"
provides:
  - "Dedicated least-privilege tribunal-run@ runtime SA (WR-03/D-04b) live: Tribunal services + jobs no longer share the intake nestor-run SA"
  - "tribunal-api run.invoker bound to ONLY nestor-run (D-04 outer gate), service stays --no-allow-unauthenticated"
  - "Seam env wired live on both services (TRIBUNAL_SERVICE_URL + INTAKE_RUNTIME_SA_EMAIL on tribunal-api; TRIBUNAL_SERVICE_URL on nestor-api)"
  - "Re-homed executable seam denial gate (tribunal/cloudbuild.seam-gate.yaml + test_seam_denial.py) — the four EXACT-status cases + the two RLS cases run as a NON-superuser and cannot silently skip"
  - "D-07 live proof: one real research run to completed (chain=OK) + three negative proofs — absorbs the Phase-13 deferred queue-path proof"
affects: [phase-16-run-trigger, phase-20-close]

# Tech tracking
tech-stack:
  added: []  # no new package — IaC + CI config + a re-homed test only
  patterns:
    - "By-construction IaC (infra/main.tf) authored but NEVER applied (CR-02); live reconciliation via the gcloud § Phase 14 runbook"
    - "Dedicated callee SA + single-member run.invoker allowlist makes the IAM gate meaningful (caller nestor-run != callee tribunal-run)"
    - "Anti-false-green CI gate: a skipped denial test FAILS the build (grep requires exactly '6 passed', rejects skipped/failed/error)"
    - "Non-superuser RLS CI: provision app_user/worker_user in the ephemeral Postgres + run RLS tests as app_user so FORCE RLS actually binds (a superuser DSN is a false green)"

key-files:
  created:
    - "tribunal/nestor_pulse_sdk/tests/test_seam_denial.py"
    - "tribunal/cloudbuild.seam-gate.yaml"
    - ".gcloudignore"
    - ".planning/phases/14-auth-retirement-integration-seam/deferred-items.md"
  modified:
    - "infra/main.tf"
    - "infra/variables.tf"
    - "infra/DEPLOY-RUNBOOK.md"
    - "tribunal/infrastructure/cloud-run/deploy-api.sh"
    - "tribunal/infrastructure/cloud-run/deploy-worker.sh"
    - "tribunal/nestor_pulse_sdk/server.py"

key-decisions:
  - "tribunal-run granted cloudsql.client (project) + secretAccessor on the six Tribunal secrets + objectAdmin on the audit bucket ONLY — no identitytoolkit.admin, no intake superadmin secret, no intake uploads bucket (WR-03/T-14-14)"
  - "server.py deployed-mode now reads the two seam env vars with .get() and fails CLOSED at request time if absent, instead of KeyError at import (Rule-1 fix; live service unaffected)"
  - "Seam denial suite re-homed into the Tribunal harness (operator Option 1a) because nestor_pulse_sdk is not importable in the intake image; intake copy kept as documented contract"
  - "Phase 14 gated on the seam selectors (Option 1c): the focused seam-gate build is the D-08 gate; pre-existing mail (D-DEF-2) + legacy-tools (D-DEF-3) failures are Phase 20 CLOSE-02, not Phase-14 blockers"
  - "Live wrong-SA valid-token proof not constructible from a least-privilege box (no serviceAccountTokenCreator on any SA; Cloud Build default compute SA cannot self-mint identity tokens) — itself corroborating the SA separation; wrong-SA rejection proven by the verified invoker allowlist + app-layer 403"

patterns-established:
  - "The IAM invoker allowlist is the D-04 OUTER gate; InternalCallerProvider (app-layer 403 on wrong caller email) is the defense-in-depth INNER gate — both proven"
  - "org.id == space_id identity mapping demonstrated live by the self-provisioning smoke (tenant_id IS the org id)"

requirements-completed: [SEAM-01, SEAM-02]

# Metrics
duration: ~150min (incl. a checkpoint round-trip + a ~19min paid research run)
completed: 2026-07-20
---

# Phase 14 Plan 04: Auth-Retirement Deploy + D-07 Live Proof Summary

**Gave Tribunal its own least-privilege `tribunal-run` runtime SA and bound the `tribunal-api` invoker to ONLY the intake `nestor-run` SA (closing WR-03 so the D-04 IAM gate is meaningful), wired the two non-secret seam env vars, closed a recurring deploy-gap by rebuilding the Tribunal images with the Plan-01 auth-retirement code, and ran the D-07 live proof — one real research run to `completed` (verify_chain=OK, $1.60) plus three negative proofs — after re-homing the seam denial gate so all six cases EXECUTE as a non-superuser instead of silently skipping.**

## Performance

- **Duration:** ~150 min (spanning a checkpoint hand-back + operator Option-1 decision + a ~19-min paid run)
- **Completed:** 2026-07-20
- **Tasks:** 3 (Task 1 IaC, Task 2 runbook — both pre-committed; Task 3 live proof — this session)
- **Files created:** 4 · **Files modified:** 6

## Accomplishments

### Task 1 + 2 (pre-committed before this session)
- `5c1f6b3` — by-construction `tribunal_run` SA + least-priv bindings + `run.invoker=nestor-run` + seam env vars in `infra/main.tf`/`variables.tf`; retargeted `deploy-api.sh`/`deploy-worker.sh` (SA → tribunal-run).
- `ad91454` — `infra/DEPLOY-RUNBOOK.md` § Phase 14 steps 14.a–14.g.

### Task 3 — Live session (operator-delegated, "u do it")
Ran the runbook § Phase 14 live on project `project-cb01b861-cb4a-438d-b9a` (acct `tools@dotto.be`):

- **14.a — dedicated SA + least-priv grants.** Created `tribunal-run@project-cb01b861-cb4a-438d-b9a.iam.gserviceaccount.com`. Grants (verified): project-level `roles/cloudsql.client` ONLY; resource-scoped `roles/secretmanager.secretAccessor` on `Nestor_Claude`, `Nestor_Gemini`, `Nestor_OpenAI`, `DATABASE_URL`, `DATABASE_URL_WORKER`, `AUDIT_GCS_BUCKET`; `roles/storage.objectAdmin` on `gs://project-cb01b861-cb4a-438d-b9a-nestor-audit`. Deliberately NOT granted: `identitytoolkit.admin`, `nestor-app-superadmin-pw`, the intake uploads bucket.
- **14.b — image rebuild (deploy-gap closed).** Live `tribunal-api` was `…:20260720-fix2`, predating the Plan-01 retirement (`f13f81f`). Rebuilt both images via Cloud Build → SHA `20260720-213244` (api build `256982c2`, worker build `9eb9785c`).
- **14.c — redeploy as tribunal-run.** `tribunal-worker` + `tribunal-api` redeployed on `tribunal-run` (verified via `spec.serviceAccountName`). Captured URL `https://tribunal-api-ybkr7metoq-ew.a.run.app` (rev `tribunal-api-00004-mr6` Ready).
- **14.d — seam env live.** `tribunal-api`: `TRIBUNAL_SERVICE_URL` + `INTAKE_RUNTIME_SA_EMAIL=nestor-run@…`; `nestor-api`: `TRIBUNAL_SERVICE_URL`. Both verified present.
- **14.e — invoker gate.** `run.invoker` on tribunal-api = `serviceAccount:nestor-run@…` ONLY (verified sole binding); service stays `--no-allow-unauthenticated`; no `allUsers`.
- **14.f — retired-secret cleanup.** Both Tribunal services confirmed clean of `IDENTITY_PLATFORM_*` env. Per T-14-15 (conservative) NO Secret Manager entry deleted — the three `IDENTITY_PLATFORM_*` secrets remain (intake IdP still in use); documented later cleanup.
- **14.g — D-08 CI gate.** See "Test Gate" below.

## Task Commits

1. **Task 1: by-construction IaC + retargeted deploy scripts** — `5c1f6b3` (feat)
2. **Task 2: § Phase 14 runbook** — `ad91454` (docs)
3. **Task 3 (this session):**
   - `28dde69` (fix) — server.py deployed-mode reads seam env fail-closed, not KeyError at import
   - `3fce1f9` (docs) — deferred-items log + root `.gcloudignore`
   - `0dd46df` (test) — re-home seam denial gate to the Tribunal harness + non-superuser RLS CI config

## Test Gate (D-08) — operator Option 1c: gate on the seam selectors

| Build | Config | Result |
|-------|--------|--------|
| `25b8f9eb` | `tribunal/cloudbuild.seam-gate.yaml` (postgres:15, app_user non-superuser, alembic upgrade head) | **GREEN — "6 passed"**: the four seam cases (`missing_tenant`=400 PINNED / `wrong_sa`=403 / `unauth`=401 / `guc_leak`) + the two RLS cases (`cross_tenant_denied` / `no_tenant_context_denied`) all EXECUTED as a non-superuser. Anti-false-green: a skip would have failed the build. |
| `93236469` | `tribunal/cloudbuild.test.yaml` (full) | 1 failed / 317 passed / 28 skipped — the ONLY failure is pre-existing `test_legacy_tools_not_modified` (D-DEF-3). Phase-14 code clean (the server.py fix cleared the prior 4 health-import errors). |
| `98abf057` | `cloudbuild.test.yaml` (intake full) | 4 failed / 135 passed — the four failures are the pre-existing mail-audit defects (D-DEF-2), already scoped to Phase 20 CLOSE-02. The re-homed seam cases no longer live here. |

The **focused seam gate (`25b8f9eb`) is the D-08 gate and is GREEN.** D-DEF-2/D-DEF-3 do not gate Phase 14 (operator decision; both pre-existing, non-Phase-14).

## D-07 Live Proof

### Positive — real research run to `completed` (proof vehicle: `tribunal-smoke` job, per plan)
Execution `tribunal-smoke-phrdx` (runs in-cluster as nestor-run; self-provisions org+project+run; NESTOR_TRIBUNAL_UNCAPPED=1; image `…:20260720-161029-fix1` — the SDK pipeline/audit code is unchanged by Phase 14):

- **space_id / tenant_id (== org.id, identity mapping):** `1464b60d-0c20-4c4e-bcf0-27b0301bdba5`
- **project_id:** `9991b060-4a37-40f8-9580-793ba6ec6fbb`
- **run_id:** `b188a83e-b951-478b-98bb-423d3019eb2b`
- **status:** completed · **verify_chain:** `chain=OK` (frozen canonical_json preserved)
- **claims:** 104 · **grounded:** 88 · **recall:** 84.6% · **elapsed:** 1123s (~19 min)
- **observed cost:** **$1.6021** (sum of `audit_log.cost_usd`)
- **Note (real-world degradation, non-fatal):** one skeptic group (`supply chain planning`) hit an Anthropic HTTP 400 "credit balance too low"; the pipeline degraded gracefully and the run still reached `completed` with a verified chain. Worth topping up Anthropic credit before future paid runs.
- **D-05 acting-user attribution:** the smoke drives the pipeline in-process (no seam HTTP), so it does NOT carry seam acting-user headers. The `X-Acting-User-Id/Email → AuthClaims` threading (D-05) is proven structurally by the green seam gate (`get_internal_claims` + the `guc_leak` firewall test), NOT by this run. A live intake→tribunal acting-user HTTP call awaits the Phase-16 trigger route (see Next Phase Readiness).

### Negative 1 — unauthenticated: **PASS (live)**
`POST {tribunal-api}/api/orgs/ensure` with NO bearer → **HTTP 403** at the Cloud Run IAM edge (before the app).

### Negative 2 — wrong SA: **PASS (established, not a clean live valid-token call)**
- The invoker allowlist is `nestor-run` ONLY (verified). Any principal that is not nestor-run — including a valid token minted for a different SA — is rejected by the SAME allowlist check that gave Negative 1 its edge rejection.
- App-layer defense-in-depth: `InternalCallerProvider` returns EXACTLY **403** when the decoded caller email != the intake SA — `test_wrong_sa_caller_returns_exactly_403` EXECUTED GREEN in the seam gate (`25b8f9eb`).
- A live *valid-wrong-SA-token* call was NOT constructible: this box has no `serviceAccountTokenCreator` on any SA, and the Cloud Build default compute SA cannot self-mint identity tokens via the metadata server (attempted, build `68c8f43b`/`…` — returned a malformed token → 401 edge rejection). The inability to forge a wrong-SA token from a least-privilege posture is itself corroborating evidence that WR-03 (SA separation) holds.

### Negative 3 — cross-tenant: **PASS (live, non-superuser)**
`test_seam_project_run_cross_tenant_denied` + `test_seam_no_tenant_context_denied` + the `guc_leak` firewall EXECUTED GREEN as the non-superuser `app_user` against real Postgres with FORCE RLS (build `25b8f9eb`): tenant_a never sees tenant_b's `project`/`run` rows (both directions); an unset `app.tenant_id` returns zero rows / raises rather than leaking.

## Files Created/Modified
- `tribunal/nestor_pulse_sdk/tests/test_seam_denial.py` — NEW. Re-homed four EXACT-status seam cases (SDK natively importable here).
- `tribunal/cloudbuild.seam-gate.yaml` — NEW. Focused D-08 gate: app_user/worker_user non-superuser roles + alembic upgrade head + the six seam tests; anti-false-green skip check.
- `.gcloudignore` — NEW. Keeps the repo-root Cloud Build upload small (the intake `cloudbuild.test.yaml` does `cd backend`, so its source root must be the repo root, not `backend/`).
- `.planning/…/deferred-items.md` — NEW. D-DEF-1…5 log + resolutions.
- `tribunal/nestor_pulse_sdk/server.py` — MODIFIED. Deployed-mode fail-closed seam-env read (Rule-1 fix).
- `infra/main.tf`, `infra/variables.tf`, `infra/DEPLOY-RUNBOOK.md`, `deploy-api.sh`, `deploy-worker.sh` — Task 1/2 (pre-committed).

## Decisions Made
See frontmatter `key-decisions`. Headline: Phase 14 is gated on the **executable** seam denial gate (Option 1c); the previously-mapped homes (intake image / superuser testcontainers) silently skipped both denial suites, which the re-home + non-superuser CI config fixes.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] server.py KeyError at import in the CI/test env**
- **Found during:** Task 3, Step 14.g (tribunal full suite, build `6f71913b`).
- **Issue:** `server.py` deployed-mode did `os.environ["TRIBUNAL_SERVICE_URL"]` at module import → `KeyError` when importing `server` without the env set (4 health-endpoint test errors). Live service unaffected (env set; rev 00004-mr6 Ready).
- **Fix:** read both seam env vars with `.get()`; install `InternalCallerProvider` only when both present, else warn + leave uninstalled so authenticated routes fail CLOSED via the deps.py RuntimeError (T-14-05). Hoisted `import warnings`.
- **Verification:** build `93236469` — the 4 errors cleared (317 passed).
- **Committed in:** `28dde69`.

**2. [Rule 3 - Blocking] Seam denial suites silently SKIPPED in their mapped CI homes**
- **Found during:** Task 3, Step 14.g (builds `6e18f9c4` intake + `6f71913b` tribunal).
- **Issue:** `backend/tests/test_tribunal_seam_denial.py` importorskip-skips in the intake image (`nestor_pulse_sdk` not on path — D-DEF-1); `tribunal/…/test_seam_rls_denial.py` self-skips under testcontainers' superuser DSN (D-DEF-5). Neither denial suite actually executed → the D-08 gate was theater.
- **Fix (operator Option 1):** re-homed the four seam cases into the Tribunal harness; added `cloudbuild.seam-gate.yaml` that provisions a non-superuser app_user and runs all six seam/RLS cases with an anti-false-green skip check.
- **Verification:** build `25b8f9eb` — "6 passed", SEAM GATE GREEN.
- **Committed in:** `0dd46df`.

**3. [Rule 3 - Blocking] Runbook Step 14.g submitted the intake suite with the wrong source root**
- **Issue:** `gcloud builds submit backend --config=cloudbuild.test.yaml` fails (`cd: backend: No such file or directory`) because the config does `cd backend` and expects the repo root as source.
- **Fix:** submit `.` (repo root) with a `.gcloudignore` to keep the upload small.
- **Committed in:** `3fce1f9` (.gcloudignore).

---

**Total deviations:** 3 auto-fixed (1 bug, 2 blocking). **Impact:** all necessary to make the D-08 gate real and the images current. No scope creep — the fixes are confined to Phase-14 surface.

## Issues Encountered
- **Recurring deploy-gap** (live image predated the code): closed by the runbook's mandatory rebuild (Step 14.b).
- **Least-privilege blocked live wrong-SA-token forging:** no `tokenCreator`; Cloud Build compute SA cannot self-mint identity tokens. Resolved by proving the wrong-SA rejection via the verified allowlist + app-layer 403 (see Negative 2).
- **Anthropic credit exhaustion mid-run:** one skeptic group failed on billing; run still completed with chain=OK. Recommend topping up before further paid runs.

## Cleanup Items (documented, not blocking)
- Ephemeral smoke tenant left in the DB (clearly labelled): `DELETE FROM org WHERE id = '1464b60d-0c20-4c4e-bcf0-27b0301bdba5';` (CASCADE cleans project/run/claims). Not run here (no DB access from the dev box by design).
- Optional: remove the now-redundant Phase-13 `nestor-run` grants on the six Tribunal secrets + audit bucket (runbook 14.a note) — not required for correctness.
- Three `IDENTITY_PLATFORM_*` Secret Manager entries retained (T-14-15 conservative) — intake IdP still reads them; revisit if intake IdP is ever retired.

## Threat Flags
None beyond the plan's `<threat_model>`. The live changes implement exactly the T-14-12/13/14 mitigations (invoker allowlist, defense-in-depth caller verify, dedicated least-priv SA); T-14-15 handled conservatively (no secret deletion).

## Deferred Items (folded from deferred-items.md)
- **D-DEF-2** — 4 pre-existing intake mail-audit failures → Phase 20 CLOSE-02 (already listed in STATE.md).
- **D-DEF-3** — pre-existing `test_legacy_tools_not_modified` (missing `/workspace/nestor_pulse/tools/...` path) → Phase 20 CLOSE-02.
- **D-DEF-1, D-DEF-4, D-DEF-5** — CLOSED this session (see deferred-items.md resolution block).

## Next Phase Readiness
- **Phase-13 deferred queue-path proof: ABSORBED by D-07 — strike it from Phase 16's backlog.** The live tribunal-api runs the retirement image as tribunal-run behind the nestor-run-only invoker gate; a real run reached `completed` with a verified audit chain.
- **Phase 16 (run-trigger)** is the remaining seam consumer: it wires a nestor-api route that calls `tribunal_client.ensure_org/ensure_project` (and later run-trigger) from the nestor-run workload — the ONLY way to exercise the live intake→tribunal HTTP admit-path + D-05 acting-user header attribution end-to-end (not constructible from a dev box: no SA token minting). The IAM admit-path + acting-user threading are currently proven by-construction (verified invoker binding + green seam gate).

## Self-Check: PASSED

- Created files present: `test_seam_denial.py`, `cloudbuild.seam-gate.yaml`, `.gcloudignore`, `deferred-items.md`, `14-04-SUMMARY.md`.
- Commits present: `5c1f6b3` (Task 1), `ad91454` (Task 2), `28dde69` (server.py fix), `3fce1f9` (deferred-items), `0dd46df` (seam re-home).
- Live end-state verified: tribunal-api/worker on tribunal-run; invoker=nestor-run only; seam env on both services; SEAM GATE build `25b8f9eb` green; positive run `b188a83e` completed chain=OK.

## Fix-cycle Addendum (2026-07-20, post-review redeploy)

A code-review fix cycle landed 11 findings on master (`e93c0a8` review report → `dd6aa6d`): runbook 14.g gate corrected (6→8), `deploy-api.sh` self-heals TRIBUNAL_SERVICE_URL + fails fast if empty, OIDC verify offloaded to the threadpool, malformed `X-Nestor-Tenant-Id` → 400, `ensure_org/ensure_project` concurrency-hardened, wildcard CORS removed in deployed mode, `LOCAL_DEV_AUTH` refused under `K_SERVICE`, acting-user headers now REQUIRED (400 when absent), google-auth declared explicitly.

**Review commit range:** `e93c0a8`..`dd6aa6d` (11 fix commits) + my `dd9768e` (pin correction, below).

### Blocking regression found + fixed (Rule 3)
The review's WR-08 commit (`57dfedd`) pinned `google-auth==2.40.3` in `tribunal/requirements.txt`, but `google-adk==1.34.1` publishes `google-auth[pyopenssl]>=2.47` — so every FRESH tribunal image build (the seam-gate pip install AND the Step-14.b redeploy) failed `pip ResolutionImpossible` (build `e6e00f68`). The pre-WR-08 green image had resolved google-auth transitively to ≥2.47; the exact pin was simply below the floor. **Fix (`dd9768e`):** relaxed the pin to `google-auth>=2.47,<3`, reproducing the known-good transitive resolution while still guarding against a 3.x major bump. The live service was never at risk — its image predated the WR-08 commit.

### Seam gate rerun — GREEN "8 passed"
`gcloud builds submit tribunal --config=tribunal/cloudbuild.seam-gate.yaml` (repo root) → **build `79c095fd` SUCCESS**, log: `SEAM GATE GREEN: 8/8 executed and passed as non-superuser`. The 8 = 6 seam denial cases (now incl. `malformed_tenant`→400 [WR-03] and `missing_acting_user`→400 [WR-07]) + 2 RLS cases, all as the non-superuser `app_user`. The gate's exact-match grep (`8 passed`) rejects any skip.

### Redeploy (deploy-gap closed for the fixed code)
- **New image SHA:** `20260720-233938` (api build `0d0ccd33`, worker build `36e2651b`).
- **tribunal-api** rev `tribunal-api-20260720-233938-234912` — **Ready=True, 100% traffic**, image `…:20260720-233938`, SA `tribunal-run`.
- **tribunal-worker** redeployed on `tribunal-run`, image `…:20260720-233938`.

### Re-verified live end-state
| Check | Result |
|-------|--------|
| New tribunal-api revision Ready + traffic | `20260720-233938-234912` — True, 100% |
| Service account | `tribunal-run@…` (both api + worker) |
| Seam env present | `TRIBUNAL_SERVICE_URL=https://tribunal-api-ybkr7metoq-ew.a.run.app` + `INTAKE_RUNTIME_SA_EMAIL=nestor-run@…` |
| Invoker binding | `roles/run.invoker` = `serviceAccount:nestor-run@…` ONLY |
| Unauthenticated negative proof | `POST /api/orgs/ensure` no bearer → **403** (IAM edge) |

**Fix-cycle commit:** `dd9768e` (google-auth pin) + this addendum.

---
*Phase: 14-auth-retirement-integration-seam*
*Completed: 2026-07-20*
