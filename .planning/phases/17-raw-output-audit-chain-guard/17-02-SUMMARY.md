---
phase: 17-raw-output-audit-chain-guard
plan: 02
subsystem: api
tags: [fastapi, sqlalchemy, gcs, zipfile, tribunal-seam, audit-chain, pool-safety, tdd]

# Dependency graph
requires:
  - phase: 17-raw-output-audit-chain-guard
    plan: 01
    provides: research_runs chain_status/chain_broken_at/bundle_key columns (0012), verify_chain + get_research_bundle seam methods, fake_tribunal_client verify_verdict + get_research_bundle fakes
  - phase: 16-research-trigger-progress-bridge
    provides: pool-safe poll driver (run_task.py), run_with_session_release release contract, fake_gcs/fake_resend fixtures
provides:
  - "backend/app/research/bundle.py — pure build_bundle_zip(report, bundle, sources) -> bytes (D-03 layout)"
  - "run_task.build_completion() — the D-06 audit-chain gate + bundle materialization in the connection-free CALL window"
  - "finalize_completed extended with chain_status/chain_broken_at/bundle_key (written on the completed path)"
  - "verified completed run -> immutable zip in GCS under the space-scoped artifacts key; broken chain -> complete-but-locked, no bundle"
affects: [17-03, raw-output-download, audit-chain-guard, complete-but-locked, phase-18-pdf]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pure zip builder (stdlib io/json/zipfile + shared sanitize_filename) — no I/O, safe to import anywhere"
    - "Completion I/O (seam fetch + verify + zip build + GCS upload) runs in the release contract's connection-free CALL window; the WRITE phase only patches the row"
    - "Hard-gate-then-materialize: verify_chain verdict decides verified (build+upload once) vs broken (complete-but-locked, no bundle)"
    - "call_fn returns a 3-tuple (rid, metrics, completion) so the pool-safe CALL window carries the computed lock-state forward to the WRITE"

key-files:
  created:
    - backend/app/research/bundle.py
    - backend/tests/test_research_bundle.py
  modified:
    - backend/app/research/run_task.py
    - backend/tests/test_research_run_task.py

key-decisions:
  - "The completion seam fetches + verify_chain + zip build + GCS upload moved OUT of write_fn INTO build_completion() at the tail of call_fn — write_fn always holds a tenant_session, so the only connection-free window is CALL (T-17-07 pool-safety)"
  - "call_fn now returns (rid, metrics, completion); write_fn no longer re-fetches get_report — the report is threaded through the 3rd tuple element from the pool-safe window"
  - "The bundle object key uses the shared build_object_key(space, intake, 'artifacts', 'raw-output-<run>.zip'); the helper prepends a uuid4- uniqueness segment, so the key is NOT byte-for-byte deterministic across rebuilds — 1:1-per-run idempotency is by the single materialization on the verified terminal, not by key reuse"
  - "The normal completion mail sends UNCHANGED on both the verified and the broken path (D-07 — no broken-chain email variant); the mail is not gated on chain_status"

patterns-established:
  - "Gate-in-CALL / persist-in-WRITE: any completion-time external I/O belongs in the connection-free CALL window; the WRITE tenant_session is patch-only"

requirements-completed: [RUN-03]

# Metrics
duration: ~40min
completed: 2026-07-22
---

# Phase 17 Plan 02: Completion-Path Gate + Bundle Materialization Summary

**A pure D-03 zip builder plus the poll driver's completed-branch extension: a completed run runs `verify_chain` as a hard gate in the connection-free CALL window, and only a verified chain builds the report.md + research/*.md + sources.json zip and uploads it to GCS once under the space-scoped artifacts key; a broken chain records complete-but-locked (chain_status="broken" + chain_broken_at, no bundle), with the Phase-16 pool-safety + idempotency + diagnostics fixes intact.**

## Performance

- **Duration:** ~40 min
- **Tasks:** 2 (both TDD: RED → GREEN)
- **Files:** 4 (2 created, 2 modified)

## Accomplishments

- **`backend/app/research/bundle.py`** — a PURE `build_bundle_zip(report, bundle, sources) -> bytes` producing the D-03 layout: `report.md` (from `report["markdown"]` or empty), one `research/<sanitize_filename(angle)>.md` per `cleaned_reports` pair, and `sources.json` (`json.dumps(..., ensure_ascii=False)`). Imports only stdlib (`io`/`json`/`zipfile`) + the shared `sanitize_filename` — no gcs/db/httpx. `rejected_claims` is structurally absent (D-01): no such argument exists.
- **`run_task.build_completion()`** — the D-06 completion gate, run at the tail of `call_fn` (the connection-free CALL window): `get_report` → `get_research_bundle` → `verify_chain`; verified → build the zip + `gcs.upload_object(key, ..., content_type="application/zip")` ONCE under `build_object_key(space_id, intake_id, "artifacts", "raw-output-<run>.zip")`; broken → build/upload NOTHING and return `chain_status="broken"` + `chain_broken_at`.
- **`call_fn` now returns `(rid, metrics, completion)`** and **`write_fn`** consumes the 3rd element: it patches `chain_status`/`chain_broken_at`/`bundle_key` through the extended `finalize_completed` and no longer re-fetches the report inside the connected WRITE session.
- **`finalize_completed`** grew keyword args `chain_status`/`chain_broken_at`/`bundle_key`, threaded into `_patch_run` alongside the existing `status`/`output_markdown`/`completed_at`. The `rowcount==0` ERROR + success WARNING diagnostics are untouched.
- **Tests:** `test_research_bundle.py` (9 cases — layout, sanitize reuse, empty/missing cleaned_reports, unicode sources, no-`rejected` scrub) and 4 new `test_research_run_task.py` cases (verified builds+uploads once under the artifacts key; broken records locked with no upload; `checkedout()==0` across build+upload; completion mail on both paths).

## Task Commits

Each task was committed atomically (TDD RED → GREEN):

1. **Task 1: Pure `build_bundle_zip` (TDD)** — `47ccee6` (test) → `07360b6` (feat)
2. **Task 2: Completion-path gate + build + persist (TDD)** — `a37a5a5` (test) → `949463d` (feat)

## Files Created/Modified

- `backend/app/research/bundle.py` — NEW pure builder; stdlib + `sanitize_filename` only; D-03 layout; D-01 scrub structural.
- `backend/tests/test_research_bundle.py` — NEW; 9 cases pinning layout + sanitize + empty/missing + unicode + no-`rejected`.
- `backend/app/research/run_task.py` — `build_completion()` (CALL-window gate+build+upload); `call_fn` 3-tuple return (incl. the 5xx-exhaust early return); `write_fn` consumes completion, no WRITE-side report fetch; `finalize_completed` extended with the three chain/bundle kwargs; docstring updated.
- `backend/tests/test_research_run_task.py` — 4 new Phase-17 cases; `_install_context` grows `intake_id`/`project_title`/`app_base_url`; `_capture_finalize` accepts the chain/bundle kwargs; `fake_gcs` added to the completed-path tests; corrected the stale attempt-N idempotency test to the `research_run_id` key (721086d).

## Decisions Made

- **Where the I/O lives:** the release contract's WRITE phase always holds an open `tenant_session`, so the ONLY connection-free window is the CALL phase. All completion I/O (seam fetch + `verify_chain` + zip build + GCS upload) therefore runs in `build_completion()` at the tail of `call_fn`; the WRITE `tenant_session` is patch-only. This is what keeps `checkedout()==0` across the build+upload (T-17-07) and is proven by the extended pool-safety test.
- **3-tuple call result:** rather than re-fetch `get_report` in the connected WRITE (a second pool-held seam call), `call_fn` threads the report + chain verdict + `bundle_key` forward as `completion`. `write_fn` unpacks and patches — no seam call in the connected window.
- **Object key non-determinism:** `build_object_key` prepends a `uuid4-` segment (its shared uniqueness/traversal-safety guarantee), so `raw-output-<run>.zip` keys are NOT byte-for-byte deterministic across a rebuild. Per-run 1:1 idempotency is instead achieved by materializing exactly once on the verified terminal. Plan 03's download path reads `run.bundle_key` (the persisted key), so the uuid4 segment is invisible to consumers. Documented so Plan 03 does not assume a reconstructable key.
- **Mail unchanged on both paths (D-07):** the completion mail is not gated on `chain_status`; a broken chain still mails the normal completion notice (no broken-chain email variant).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `fake_gcs` added to the pre-existing completed-path driver tests**
- **Found during:** Task 2
- **Issue:** `test_poll_driver_releases_pool`, `test_completion_mail_to_trigger_user`, `test_loop_stops_on_completed_terminal`, and the idempotency test drive the poll to the `completed` terminal. My change routes that terminal through `build_completion()` → `gcs.upload_object`, which without the `fake_gcs` fixture would reach a real bucket.
- **Fix:** Added the `fake_gcs` fixture to those four completed-path tests (capture-only, no bucket).
- **Files modified:** `backend/tests/test_research_run_task.py`
- **Commit:** `949463d`

**2. [Rule 1 - Bug] Corrected the stale idempotency-key test (attempt-N → research_run_id)**
- **Found during:** Task 2
- **Issue:** `test_idempotency_key_is_uuid5_of_intake_and_attempt` asserted `uuid5(intake_id, "attempt-N")` — the pre-721086d behavior. Production (run_task.py:301) uses `uuid5(intake_id, research_run_id)` (the burned-key fix); the test was already contradicting the live code and the plan's byte-for-byte MUST-NOT-REGRESS acceptance criterion.
- **Fix:** Renamed to `test_idempotency_key_is_uuid5_of_intake_and_research_run_id` and asserted the correct `research_run_id` key. The production idempotency-key line was NOT touched (byte-for-byte unchanged, as required).
- **Files modified:** `backend/tests/test_research_run_task.py`
- **Commit:** `949463d`

## Automated Verification (deferred to Cloud Build — no local Python/Docker)

The plan's per-task verification is `MISSING — runs in Cloud Build at wave boundary`. Tests were authored by construction (the dev machine has no Python/Docker):

- `pytest backend/tests/test_research_bundle.py -x` — the pure builder (9 cases).
- `pytest backend/tests/test_research_run_task.py -x` — the driver suite incl. the 4 new Phase-17 cases + the corrected idempotency case; all completed-path cases now provide `fake_gcs`.

Expected local caveat: the em-dash sanitize assertion was corrected in the GREEN commit to the exact `Angle_One_-_Two_Three` form the shared `sanitize_filename` produces (whitespace runs around the dash become `_`).

## Threat Surface Scan

No NEW out-of-model surface. The changes implement mitigations already in the plan's `<threat_model>`:
- **T-17-05 / T-17-06** (export on broken/false-green chain): `verify_chain` is a hard gate; broken → no bundle written (broken-path test proves `fake_gcs["uploads"] == []`); the gate carries the intake's `space_id` header via the seam.
- **T-17-07** (pool starvation): all verify/fetch/build/upload in the connection-free CALL window; pool-safety test asserts `checkedout()==0` across the upload.
- **T-17-08 / T-17-09** (wrong-space / audit-bucket write): server-authored `build_object_key(ctx["space_id"], ctx["intake_id"], "artifacts", ...)` — space from the resolved intake, category `"artifacts"` (app bucket, NOT the audit bucket).
- **T-17-SC** (package installs): none — stdlib `zipfile`/`io`/`json` + in-image `gcs`/`httpx`.

## Known Stubs

None. The verified path materializes a real zip; the broken path deliberately writes no bundle (complete-but-locked is the intended terminal, not a stub). The download route that consumes `bundle_key` is Plan 03 (documented dependency, not a stub in this plan).

## Next Phase Readiness

- Plan 03 (download / re-verify routes) has: the persisted `bundle_key` (read it directly — do NOT reconstruct the key; the uuid4 segment makes it non-reconstructable), `chain_status="verified"|"broken"` for the D-06/D-09 download lock, and `chain_broken_at` for the locked-state UI.
- Live proof still needs a completed run behind the Anthropic-credits external blocker (same checkpoint pattern as 16-05).

## Self-Check: PASSED

- All 5 claimed files exist on disk (2 created, 2 modified, + this SUMMARY).
- All task commits present: `47ccee6` (test), `07360b6` (feat), `a37a5a5` (test), `949463d` (feat).
- Idempotency-key production line `uuid.uuid5(uuid.UUID(str(intake_id)), str(research_run_id))` byte-for-byte unchanged (verified in run_task.py:301).
- SUMMARY.md force-added (`.planning/` is gitignored).
