# Phase 14 — Deferred / Out-of-Scope Items (discovered during the 14-04 D-07 live session)

> RESOLUTION UPDATE (operator decision Option 1, same session):
> - **D-DEF-1 CLOSED** — the four seam-denial cases were re-homed to the Tribunal harness
>   (`tribunal/nestor_pulse_sdk/tests/test_seam_denial.py`) where `nestor_pulse_sdk` is
>   importable; they now EXECUTE (not skip). Gate: `tribunal/cloudbuild.seam-gate.yaml`.
> - **D-DEF-5 CLOSED** — the seam-gate config provisions a NON-superuser `app_user` role and
>   runs the RLS denial tests as it, so they EXECUTE (not skip). Both closed in build
>   `25b8f9eb` ("6 passed", SEAM GATE GREEN).
> - **D-DEF-4 CLOSED** — server.py import fix (commit `28dde69`), verified in build `93236469`.
> - **D-DEF-2 / D-DEF-3 REMAIN DEFERRED** — pre-existing, not Phase-14 caused; scoped to
>   Phase 20 CLOSE-02 (STATE.md: "Rerun full backend suite … 5 known mail test-harness
>   defects"). They do NOT gate Phase 14 (operator decision Option 1c).

These surfaced when the two Cloud Build CI suites (Step 14.g) ran live for the first time.
They are logged here per the executor scope boundary (only auto-fix issues DIRECTLY caused by
the current task). NONE of these are caused by the Phase-14 seam/IAM work itself.

## D-DEF-1 — Intake seam denial suite is SKIPPED (not run) under `cloudbuild.test.yaml`  [BLOCKER for the intake half of D-08]

- **Symptom:** `backend/tests/test_tribunal_seam_denial.py` collected as **1 skipped** — its four
  cases (`missing_tenant`/`wrong_sa`/`unauth`/`guc_leak`) never execute.
- **Root cause:** The file guards its imports with
  `pytest.importorskip("nestor_pulse_sdk.auth.internal_caller")` (+ `...deps`, `...orgs.api`,
  `...auth.middleware`, `...auth.provider`). The Tribunal SDK package `nestor_pulse_sdk.*` lives
  under `tribunal/` and is **only on the Python path in the Tribunal test image**, NOT in the
  intake `cloudbuild.test.yaml` image (which does `cd backend; pytest backend/tests`). So every
  seam import skips → the whole module skips.
- **Why this is architectural (Rule 4), not an auto-fix:** Making it run requires either
  vendoring/pip-installing `nestor_pulse_sdk` into the intake test image, or moving the seam
  denial suite into the Tribunal harness (where the SDK is importable), or standing up a
  combined image. That is a CI-topology decision, not a one-line fix.
- **Note:** The 14-03 SUMMARY's CI mapping table asserts this file "runs under cloudbuild.test.yaml
  (intake, -m integration)". That mapping is not achievable as configured — the file cannot import
  the SDK there. The Tribunal-side RLS half (`tribunal/.../test_seam_rls_denial.py`) is correctly
  homed and CAN run once D-DEF-3 is fixed.

## D-DEF-2 — 4 pre-existing mail-audit test failures in the intake suite  [pre-existing, unrelated to Phase 14]

- `tests/test_mail_endpoints.py::test_unset_app_base_url_refuses_send` — `assert 1 == 0`
  (WR-01: a refused send wrote a `mail.sent` audit row).
- `tests/test_mail_endpoints.py::test_invite_mail_send_failure_returns_success_false` — `assert 4 == 0`.
- `tests/test_mail_locale.py::test_mixed_locale_list_sends_correct_variant_per_recipient` — `assert 8 == 1`.
- `tests/test_mail_locale.py::test_locale_send_failure_preserves_d16` — `assert 9 == 0`.
- **Pattern:** the audit-row counts are CUMULATIVE across the run (1, 4, 8, 9…) — classic
  test-isolation bleed (mail.sent audit rows not truncated between cases in this DB-backed run),
  or an audit-on-failure regression in the mail path. Either way it lives in the mail subsystem,
  which Phase 14 did not touch. Intake build id: `6e18f9c4-e22d-4617-ba18-8b59a1372c00`
  (`4 failed, 135 passed, 1 skipped, 89 deselected`).

## D-DEF-3 — `test_legacy_tools_not_modified` fails on a missing path in the Tribunal image  [pre-existing]

- `tribunal/nestor_pulse_sdk/tests/test_graceful_degradation.py::test_legacy_tools_not_modified`
  raises `FileNotFoundError: /workspace/nestor_pulse/tools/gemini_deep_researcher.py`.
- The test reads a legacy ADK tool file by an absolute `/workspace/...` path that does not exist
  in the `tribunal/`-only Cloud Build source context. A source-layout assumption, not Phase-14 code.
  Tribunal build id: `6f71913b-969e-43dd-9950-3688a586f9cb`
  (`1 failed, 309 passed, 28 skipped, 4 errors` — the 4 errors were the D-DEF-4 server import bug, now fixed).

## D-DEF-5 — Tribunal-side `test_seam_rls_denial.py` SELF-SKIPS (superuser DSN)  [BLOCKER for the tribunal half of D-08]

- **Symptom:** the two seam RLS tests (`cross_tenant_denied`, `no_tenant_context_denied`) are
  among the 28 SKIPPED in `tribunal/cloudbuild.test.yaml`; they never assert.
- **Root cause:** `tribunal/cloudbuild.test.yaml` runs `pytest nestor_pulse_sdk/tests/ -q` against a
  **testcontainers** `postgres:15`, which connects as the `postgres` **SUPERUSER**. A Postgres
  superuser BYPASSES RLS unconditionally, so `require_non_superuser` (a `SELECT
  current_setting('is_superuser')` guard) SKIPS the test — exactly to avoid a false green. Net: the
  meaningful `tribunal.*` cross-tenant RLS denial gate does NOT run in this config.
- **Contradiction with 14-03-SUMMARY:** that SUMMARY's CI mapping says this config exercises the RLS
  test "as a non-superuser." In reality testcontainers hands a superuser DSN, so it self-skips. To
  make the gate real, the config must connect the test as a NON-superuser app role (create one +
  point the test's DSN at it), OR the intake-style fixed-DSN pattern (a dedicated non-superuser
  login role, as `cloudbuild.test.yaml` does for `app_superadmin`) must be adopted here.
- **Architectural (Rule 4):** requires a CI-config change (provision a non-superuser role in the
  testcontainers Postgres and route the RLS test's session to it). Not a code auto-fix.

## D-DEF-4 — server.py import-time KeyError  [FIXED this session — Rule 1]

- `nestor_pulse_sdk/server.py:132` did `os.environ["TRIBUNAL_SERVICE_URL"]` at module import in
  deployed mode → `KeyError` when importing `server` in the CI image (env unset), erroring the 4
  health-endpoint tests. The LIVE service is unaffected (its env vars ARE set; revision
  `tribunal-api-00004-mr6` is Ready=True). Fixed by making the deployed branch read both seam env
  vars with `.get()` and fail-CLOSED at request time (provider not installed → deps.py RuntimeError)
  instead of crashing at collection. Needs an image rebuild to land in CI (the current live image
  predates the fix).
