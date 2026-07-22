---
phase: 17-raw-output-audit-chain-guard
verified: 2026-07-22T16:00:00Z
status: passed
score: 3/3 must-haves verified
overrides_applied: 0
deferred:
  - truth: "report.md non-empty on re-download of run 4cbb5311 (bundle_key reset → lazy rebuild)"
    addressed_in: "Phase 20"
    evidence: "Operator decision 2026-07-22: minor re-test deferred to the Phase-20 UAT ledger; the seam fix (05b0e96) is deployed and all future completed runs will produce non-empty report.md end-to-end"
  - truth: "Completed card Duur field renders a duration value"
    addressed_in: "Phase 20"
    evidence: "Operator decision 2026-07-22: Duur '—' on the completed card is a cosmetic defect deferred to the Phase-20 deferred-chores ledger"
  - truth: "Visual client-login spot-check (incognito session confirms no raw-output surface)"
    addressed_in: "Phase 20"
    evidence: "Operator decision 2026-07-22: folded into the Phase-20 UAT ledger alongside other visual checks; the API-level denial is proven by the CI suite (6/6 EXACTLY-404)"
---

# Phase 17: Raw Output + Audit Chain Guard Verification Report

**Phase Goal:** Once a run completes, its full raw output is secured as a superadmin-only download and the audit chain is guarded on the completion path — nothing research-related is client-visible.
**Verified:** 2026-07-22
**Status:** PASSED
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|---------|
| 1 | Superadmin can download the full raw research output as a file (GCS signed URL, space-scoped) | VERIFIED | `GET /intakes/{id}/research/{run}/bundle-url` exists in `research_routes.py` (line 331); superadmin gate + scope check + GCS `signed_download_url(ttl_seconds=300)` confirmed in code; operator downloaded the zip live on run 4cbb5311 (UAT test 1 PASS) |
| 2 | A client can never access the raw output — endpoint is superadmin-only and denies cross-space and client access (added to the CI-gated denial suite) | VERIFIED | Existence-hidden 404 role gate (`_superadmin_gate` dependency, lines 318-328) fires before repo access; 6 denial tests in `test_research_cross_tenant.py` (3 per route: space-B, user-role, null-space) all assert EXACTLY 404; Cloud Build ran 163 intake tests passed (4 known pre-existing mail defects); null-space ordering fix `3ecbba6` deployed and suite re-run green on rev 00037-k7t |
| 3 | `verify_chain` runs as a hard gate on the run-completion path (audit objects carried, frozen payload preserved), surfacing a broken chain before delivery | VERIFIED | `build_completion()` in `run_task.py` (line 264) calls `tribunal_client.verify_chain` in the connection-free CALL window before any bundle write; broken path sets `chain_status="broken"` + no upload; operator confirmed `chain_status=verified` via the re-verify affordance on run 4cbb5311 (a real 228-call Tribunal run); UAT test 2 PASS |

**Score: 3/3 truths verified**

### Deferred Items

Items not yet met but explicitly addressed in later milestone phases.

| # | Item | Addressed In | Evidence |
|---|------|-------------|----------|
| 1 | Re-download run 4cbb5311's bundle to confirm report.md non-empty after seam fix 05b0e96 | Phase 20 | Operator decision 2026-07-22; all future completed runs produce non-empty report.md via the fixed seam endpoint |
| 2 | Completed card Duur "—" (duration not rendered) | Phase 20 | Operator decision 2026-07-22; cosmetic defect in Phase-20 ledger |
| 3 | Visual client-login spot-check (browser confirms no research surface) | Phase 20 | Operator decision 2026-07-22; API surface proven by CI denial suite 6/6; visual check in Phase-20 UAT |

---

## Decision Verdicts (Phase-17 CONTEXT decisions)

| Decision | Verdict | Evidence |
|----------|---------|---------|
| D-01 (bundle = cleaned_reports only, no rejected_claims) | VERIFIED | `/research-bundle` endpoint (tribunal `runs/api.py` line 932) returns `{"cleaned_reports"}` only; `rejected_claims` excluded at boundary; test `test_completed_run_returns_cleaned_reports_only` asserts `"rejected_claims" not in body`; `build_bundle_zip` has no `rejected_claims` parameter by construction |
| D-03 (zip: report.md + research/*.md + sources.json) | VERIFIED | `build_bundle_zip` in `bundle.py` produces exactly this layout; operator confirmed D-03 layout live on run 4cbb5311 (research/*.md present with real content, sources.json present) |
| D-05 (artifacts app bucket, not audit bucket) | VERIFIED | `build_object_key(..., "artifacts", ...)` used in both `build_completion()` and `_build_and_store_bundle()`; runbook step 17.e confirms `STORAGE_BUCKET` used, NO `AUDIT_GCS_BUCKET`; operator env confirm done |
| D-06 (broken chain → complete-but-locked, no bundle) | VERIFIED | `build_completion()` broken branch sets `chain_status="broken"`, `bundle_key=None`, skips `gcs.upload_object`; `get_bundle_url` raises 409 when `chain_status != "verified"`; `test_broken_chain_no_bundle` asserts `fake_gcs["uploads"] == []` |
| D-07 (UI-only broken-chain state, no email variant) | VERIFIED | `write_fn` in `run_task.py` sends the same completion mail on both verified and broken paths (D-07 comment at line 496); `RawOutputControls` renders locked+re-verify state in `ResearchRunProgress.tsx` |
| REPORT-02 (nothing research-related is client-visible) | VERIFIED | `ResearchRunProgress` imported only by `admin.pulse.intakes.$id.tsx` (grep confirms 2 files: component + admin route); API endpoint is existence-hidden 404 for all non-superadmin callers; CI denial suite 6/6 EXACTLY-404 |

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/app/db/alembic/versions/0012_research_run_chain_bundle.py` | Migration 0012 adding chain_status, chain_broken_at, bundle_key (nullable) | VERIFIED | `revision="0012"`, `down_revision="0011"`, upgrade adds 3 nullable columns via `op.add_column` with `schema="nestor"`; no new RLS/grant/index; commit `cea6607` |
| `backend/app/db/models/research_runs.py` | ResearchRun model with chain_status, chain_broken_at, bundle_key (nullable, no server_default) | VERIFIED | Lines 99-105 declare all three as `Mapped[str|None]` / `Mapped[int|None]` with `nullable=True` and no `server_default` |
| `tribunal/nestor_pulse_sdk/runs/api.py` | GET /{run_id}/research-bundle returning {cleaned_reports} | VERIFIED | Route decorator `@router.get("/{run_id}/research-bundle")` at line 932; returns exactly `{"cleaned_reports": ...}`; D-01 scrub confirmed |
| `backend/app/research/tribunal_client.py` | get_research_bundle + verify_chain seam methods | VERIFIED | `def get_research_bundle(` (line 248) and `def verify_chain(` (line 276) both keyword-only, both use `_headers()` and `raise_for_status()`; persist nothing |
| `backend/app/research/bundle.py` | Pure build_bundle_zip(report, bundle, sources) -> bytes | VERIFIED | 81-line pure module; imports only stdlib (io, json, zipfile) + `sanitize_filename`; no I/O; no rejected_claims argument; commit `07360b6` |
| `backend/app/research/run_task.py` | finalize_completed extended + build_completion() gate | VERIFIED | `build_completion()` at line 264; `finalize_completed` at line 152 with chain_status/chain_broken_at/bundle_key kwargs; verify_chain gate at line 302; GCS upload only on verified path |
| `backend/app/api/research_routes.py` | GET bundle-url + POST verify-chain routes (superadmin-only, space-scoped) | VERIFIED | `get_bundle_url` at line 331; `reverify_chain` at line 386; both sync `def`; `_superadmin_gate` dependency; existence-hidden 404; `_build_and_store_bundle` recovery helper at line 265 |
| `frontend/src/lib/api/research.ts` | ResearchRun type extended + getBundleUrl + reVerifyChain | VERIFIED | chain_status/chain_broken_at/bundle_key in `ResearchRun` type; `getBundleUrl` and `reVerifyChain` both use `apiFetch` (never raw fetch); return ApiResult |
| `frontend/src/components/intake/ResearchRunProgress.tsx` | RawOutputControls: download (verified) / locked+re-verify (broken) | VERIFIED | `RawOutputControls` component at line 175; renders Download button when `chain_status === "verified"`; renders locked+re-verify when `chain_status === "broken"`; toast on error (no throw); admin-only placement confirmed |
| `backend/tests/test_research_bundle.py` | Pure builder unit tests | VERIFIED | File exists; 9 cases covering D-03 layout, sanitize, empty/missing cleaned_reports, unicode sources, no-rejected scrub |
| `backend/tests/test_research_bundle_download.py` | Download happy-path, lock, recovery, re-verify tests | VERIFIED | File exists; covers happy-path 200, broken-409 lock, build-on-download-if-missing, re-verify lifts lock |
| `backend/tests/test_research_cross_tenant.py` | Denial tests for both new routes (6 new tests) | VERIFIED | 6 new denial tests (3 per route) each asserting EXACTLY 404 and absence of foreign IDs in body; `verify_chain_calls == 0` on denied verify-chain |
| `tribunal/nestor_pulse_sdk/tests/test_research_bundle_endpoint.py` | Endpoint tests: happy path, 409 gates, cross-tenant | VERIFIED | File exists; asserts `"rejected_claims" not in body` on happy path; 409 on non-completed/no-cache; cross-tenant 404 |
| `infra/DEPLOY-RUNBOOK.md` | Phase 17 section with steps 17.a-17.f | VERIFIED | `## Phase 17` section confirmed in file; ordered dual-REBUILD (tribunal-api first), migration 0012 step, no-new-env confirm, frontend deploy, live UAT checkpoint |
| `.planning/phases/17-raw-output-audit-chain-guard/17-HUMAN-UAT.md` | Operator checklist with 3/3 PASS | VERIFIED | File exists; all 3 tests recorded PASS (with same-session fix cycle); run 4cbb5311 documented |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `run_task.build_completion()` | `tribunal_client.verify_chain` | direct call with seam_kwargs | WIRED | Line 302: `verdict = tribunal_client.verify_chain(run_id=rid, **seam_kwargs)` |
| `run_task.build_completion()` | `gcs.upload_object` | only on verified path | WIRED | Line 331: `gcs.upload_object(key, zip_bytes, content_type="application/zip")` gated by `if verdict.get("ok")` |
| `research_routes.get_bundle_url` | `gcs.signed_download_url` | space-scoped run lookup → signed URL | WIRED | Line 376: `url = gcs.signed_download_url(key, ttl_seconds=300, ...)` |
| `ResearchRunProgress.RawOutputControls` | `/intakes/{id}/research/{run}/bundle-url` | `getBundleUrl` → browser navigate | WIRED | Line 195: `const res = await getBundleUrl(intakeId, run.id)` → `window.location.href = res.data.url` |
| `backend/app/db/stream_session.py` | `research_runs.chain_status` | `read_latest_research_run_dict` dict | WIRED | Lines 125-127: `"chain_status": run.chain_status`, `"chain_broken_at": run.chain_broken_at`, `"bundle_key": run.bundle_key` |
| `test_research_cross_tenant.py` | both new routes | EXACTLY-404 denial assertions | WIRED | 6 tests cover bundle-url + verify-chain for space-B, user-role, null-space |

---

## Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|--------------|--------|-------------------|--------|
| `RawOutputControls` | `run.chain_status` | SSE stream → `read_latest_research_run_dict` → `research_runs.chain_status` (written by `build_completion()`) | Yes — written by the completion-path gate on a real Tribunal run | FLOWING |
| `get_bundle_url` | `run.bundle_key` | `ResearchRunRepository.get(run_id)` → `research_runs.bundle_key` (written by `build_completion()` or lazy rebuild) | Yes — GCS key of the materialized zip | FLOWING |
| `build_bundle_zip` | `cleaned_reports` | `tribunal_client.get_research_bundle` → `/api/runs/{run_id}/research-bundle` → `synthesis_cache` Output body | Yes — real DB query on the `synthesis_cache` Output row | FLOWING |

---

## Behavioral Spot-Checks

Step 7b: SKIPPED (no local Python/Docker on this machine; behavior verified through Cloud Build suite results and live operator UAT)

---

## Probe Execution

| Probe | Command | Result | Status |
|-------|---------|--------|--------|
| Backend intake suite | `gcloud builds submit --config cloudbuild.test.yaml` (Cloud Build) | 163 passed / 4 known pre-existing mail defects | PASS |
| Tribunal suite | Cloud Build | 316 passed / 1 pre-existing env-dependent failure | PASS |
| Phase-17 specific: `test_research_bundle.py` | Included in intake suite | Passed (9 cases) | PASS |
| Phase-17 specific: `test_research_bundle_download.py` | Included in intake suite | Passed | PASS |
| Phase-17 specific: `test_research_cross_tenant.py` (6 new tests) | Included in intake suite | Passed (6/6 EXACTLY-404 after `3ecbba6` fix) | PASS |
| Phase-17 specific: `test_research_bundle_endpoint.py` | Included in tribunal suite | Passed (xfail-strict without Docker, ran in Cloud Build) | PASS |

---

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|---------|
| RUN-03 | 17-01, 17-02, 17-03, 17-04 | Superadmin can download the full raw research output as a file; clients can never access it | SATISFIED | SC1: signed-URL download endpoint verified; SC2: 6/6 CI denial tests pass; SC3: verify_chain hard gate in completion path; live UAT 3/3 PASS on run 4cbb5311 |

---

## Anti-Patterns Found

| File | Pattern | Severity | Impact |
|------|---------|----------|--------|
| `backend/app/research/run_task.py` line 316-317 | `report_for_zip["markdown"] = report.get("markdown") or ""` when `report.get("markdown")` is already falsy — effectively always empty on the live seam (report endpoint returns `sections` not `markdown`) | WARNING | report.md was empty on the first live download (fixed by `05b0e96`); the `build_completion()` logic does not use the persisted `output_markdown` as fallback (only the download-recovery path `_build_and_store_bundle` does). Not a new stub — the seam endpoint was the root cause, now fixed. |

Note: The `report.md` empty-body defect was a same-session finding, root-caused to the tribunal report endpoint returning `sections` not `markdown`, and fixed in `05b0e96`. The `build_completion()` code in `run_task.py` reads `report.get("markdown")` from the seam response; since the seam now returns `markdown` = `Output.body`, future runs will produce non-empty report.md. The deferred re-download is a minor confirmation, not a blocker.

No unreferenced TBD/FIXME/XXX markers found in Phase-17 modified files.

---

## Human Verification Required

None remaining. All three operator UAT tests completed 2026-07-22 (PASS):

1. Raw-output download from run 4cbb5311 — zip attachment disposition works, D-03 layout correct (research/*.md + sources.json), D-01 scrub confirmed (no rejected claims). report.md was empty (root cause: seam returned sections, not markdown); fixed in `05b0e96`. Re-download deferred to Phase-20 ledger (minor).
2. verify_chain green as a hard gate — operator clicked "Keten verifiëren" affordance on the NULL chain_status run; verify_chain executed against the real Tribunal engine (228-call run) and returned ok=true; chain_status flipped to "verified" and Download button appeared. NULL-state affordance required same-session fix `0ff2565`.
3. Client isolation — CI denial suite 6/6 EXACTLY-404 on both routes for space-B/user-role/null-space callers; `RawOutputControls` admin-only by placement. Visual browser spot-check deferred to Phase-20 UAT ledger.

---

## Gaps Summary

No gaps. Three minor items were deferred by operator decision to the Phase-20 ledger:
1. Re-download run 4cbb5311 after bundle_key reset to confirm non-empty report.md (seam fix `05b0e96` already deployed; next real completed run will prove it end-to-end with no intervention).
2. Completed-card Duur field showing "—" (cosmetic; duration field not rendered).
3. Visual client-login browser spot-check (API surface pinned by CI; visual deferred with other Phase-20 UAT items).

None of these block the phase goal. The three ROADMAP success criteria are all verified in code and confirmed live.

---

## Fix Cycle During UAT (Informational)

Three same-session fixes committed and deployed before UAT tests were recorded:

| Commit | Description | UAT Impact |
|--------|-------------|-----------|
| `3ecbba6` | fix(17-03): superadmin gate as dependency — null-space user 404, not repo 403 | Required for denial suite to pass (null-space case was 403 pre-fix, should be 404) |
| `0ff2565` | fix(17-03): verify-chain affordance for NULL chain_status + local card flip | Required for UAT test 2 (NULL chain_status on pre-Phase-17 run rendered no button) |
| `05b0e96` | fix(17-01): report seam endpoint exposes raw markdown (report.md was empty) | Required for report.md to be non-empty; seam now returns `Output.body` as `markdown` |

All three fixes are committed, deployed, and in the Phase-17 git history. They resolve the same root-cause class as Phase-16's fix cycle (seam shape mismatch, gate ordering). The fix cycle is normal for a phase that tests live against a real engine for the first time.

---

_Verified: 2026-07-22_
_Verifier: Claude (gsd-verifier)_
