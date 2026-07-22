---
phase: 18-human-report-upload-client-delivery
plan: 01
subsystem: api
tags: [fastapi, pg8000, rls, tenant-isolation, storage, mail, report-delivery, pydantic]

# Dependency graph
requires:
  - phase: 16-research-trigger-progress-bridge
    provides: in_research status + intake status machine (the deliver verb's precondition)
  - phase: 10-notifications
    provides: results.html.j2 mail stack + _resolve_recipient_locales + _subject_for (D-06)
  - phase: 09-storage
    provides: server-authored storage keys {space}/{intake}/reports/ + signed-url seam
  - phase: 07-ai-skills
    provides: ResearchArtifactRepository + create_in_space superadmin-safe write path
provides:
  - "POST /intakes/{id}/deliver — the sole in_research -> delivered transition verb (REPORT-01)"
  - "POST /intakes/{id}/report/replace — post-delivery report repoint, status stays delivered (D-04/D-05)"
  - "GET /intakes/{id}/report — status-gated (exactly 'delivered') client report read (REPORT-02)"
  - "DeliverBody + ReportView Pydantic models (the contract 18-02/18-03 frontend mirror)"
  - "_DELIVER_TRANSITIONS allow-list; report artifact source='human-report'/type='report' literal"
affects: [18-02-admin-report-block, 18-03-client-report-page, frontend-api-seam-intakes]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "committed-before-mail: flip+link+audit in one tenant_session tx, mail LAST in its own tx"
    - "status-gated client read via exact equality (status == 'delivered'), never a >= rank"
    - "server-side PDF-only (D-10) + forged-key prefix-assert (D-08) at the write, not just input"

key-files:
  created:
    - backend/tests/test_report_delivery.py
  modified:
    - backend/app/api/intake_routes.py
    - backend/tests/test_intake_cross_tenant.py

key-decisions:
  - "Reused intakes.results_link_sent_at as the delivered-mail timestamp (no new column, no migration)"
  - "Report artifact source='human-report' literal — distinct from context-pack source so the two never collide"
  - "deliver/replace write via tenant_session (one committed tx) not injected repo — artifact create + intake patch must commit together BEFORE the mail is attempted"
  - "get_report reads the intake through a scoped IntakeRepository sharing the artifact repo's session (one scoped tx)"

patterns-established:
  - "Pattern 1: report delivery lifecycle helpers (_assert_report_key / _create_report_artifact / _send_report_mail) shared by deliver + replace"
  - "Pattern 2: cross-tenant deliver/report cases join the CI denial suite from day one (3 new -k selectors)"

requirements-completed: [REPORT-01, REPORT-02, REPORT-03]

# Metrics
duration: ~35min
completed: 2026-07-22
---

# Phase 18 Plan 01: Human-Report Delivery Backend Surface Summary

**Three backend verbs (`POST /deliver`, `POST /report/replace`, `GET /report`) owning the human-report delivery lifecycle — the sole `in_research -> delivered` transition, post-delivery replace, and the status-gated client report read — composing the existing storage/mail/transition seams with no migration, no new secret, no new package.**

## Performance

- **Duration:** ~35 min
- **Completed:** 2026-07-22
- **Tasks:** 3 (2 route tasks folded into one file, 1 test task)
- **Files modified:** 3 (1 created, 2 modified)

## Accomplishments
- `deliver_report`: links the staged report as a `research_artifacts` `report` row, flips the sole `in_research -> delivered` transition, audits in the same committed `tenant_session` tx, then sends the results-family mail LAST with a `/report` CTA — stamping `results_link_sent_at` only on a 2xx send (a mail failure leaves the intake delivered + timestamp NULL = recoverable, T-18-05).
- `replace_report`: creates a NEW artifact row and repoints `final_report_artifact_id` without changing status (D-04); optional re-notify only when recipients supplied (D-05), silent replace otherwise.
- `get_report`: 404 for every status other than exactly `delivered` (REPORT-02 invisibility, equality not `>=`); returns `ReportView` (filename/byte_size/mime_type/storage_path + `delivered_at` mirroring `results_link_sent_at`).
- Server-side PDF-only (422, D-10) + forged/cross-prefix key (404, D-08) + superadmin-safe `create_in_space` role-branch (Pitfall 4/T-18-06).
- `test_report_delivery.py` (9 cases) + 3 new cross-tenant denial cases; both files collect on the dev box via `importorskip` and run in Cloud Build.

## Task Commits

1. **Task 1+2: deliver/replace/report verbs + models** - `7cc5096` (feat) — both route tasks touch only `intake_routes.py` with shared helpers, committed together.
2. **Task 3: test_report_delivery.py + cross-tenant cases** - `ef4c779` (test)
3. **Deferred-item log (out of scope)** - `ac93166` (docs)

## Files Created/Modified
- `backend/app/api/intake_routes.py` — `_DELIVER_TRANSITIONS`, `DeliverBody`/`ReportView` models, `_report_filename`/`_assert_report_key`/`_create_report_artifact`/`_send_report_mail` helpers, and the `deliver_report`/`replace_report`/`get_report` verbs.
- `backend/tests/test_report_delivery.py` — deliver_transition, deliver_wrong_status (409), pdf_only (422), deliver_forged_key (404), deliver_mail (resolved email + stamp), deliver_mail_failure (delivered + NULL timestamp), replace, report_read_delivered, report_read_pre_delivery.
- `backend/tests/test_intake_cross_tenant.py` — `_insert_intake_status` helper, `ai_session.get_engine` patch (so the `tenant_session` write tx runs against the testcontainer), and 3 cases: deliver_cross_tenant (404 + B unchanged), report_cross_tenant (404), report_read_pre_delivery (REPORT-02 404).

## Decisions Made
- **Same-tx write via `tenant_session` (not the injected `artifact_repo`).** The plan's `<interfaces>` suggested injecting `artifact_repo=Depends(get_research_artifact_repo)` alongside `repo=Depends(get_tenant_repo)`, but those dependencies open TWO SEPARATE transactions — the artifact row would commit independently of the status flip. The plan's own behavior requirement ("audit row written on repo.session — same tx as the flip") and the flip+link atomicity both require one transaction. I used `tenant_session(identity)` (the canonical `research_routes.trigger` committed-before-schedule pattern) so the artifact create + intake patch + audit commit together, mirroring `create_running_skill_run`. See Deviations.
- **`create` vs `create_in_space` role-branch.** The plan interface named only `create_in_space`, but that method raises `RuntimeError` for a user-scoped repo (it is superadmin-only). Every create site in the codebase branches on `identity.role == "superadmin"`; I did the same in `_create_report_artifact`.
- Reused `results_link_sent_at` as the delivered timestamp (Claude's-discretion in 18-CONTEXT); no `delivered_at` column added.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Same-transaction write via `tenant_session` instead of a separately-injected `artifact_repo`**
- **Found during:** Task 1 (deliver verb)
- **Issue:** The plan's `<interfaces>` block directed injecting `artifact_repo: ResearchArtifactRepository = Depends(get_research_artifact_repo)` alongside `repo=Depends(get_tenant_repo)`. Those two dependencies each open their OWN `maker.begin()` transaction, so the report artifact row would commit in a DIFFERENT transaction from the status flip + audit — violating the plan's stated behavior ("an 'intake.status_changed' audit row written on repo.session (same tx as the flip)") and breaking flip+link atomicity (a crash between the two commits would leave a delivered intake with no linked report, or a linked report with no flip).
- **Fix:** Used `with tenant_session(identity) as txs:` for the flip+link+audit block (the canonical same-tx primitive `research_routes.trigger` uses), constructing `IntakeRepository(txs, identity)` and the artifact repo on the shared `txs` session so all three writes commit together. The mail is sent LAST in its own separate `tenant_session` (after the delivery commits), matching the A3 ordering.
- **Files modified:** backend/app/api/intake_routes.py
- **Verification:** By construction — the deliver/replace verbs open exactly one write `tenant_session` for the flip+link+audit; `test_deliver_mail_failure` asserts the flip+link persist while the timestamp stays NULL (proving the write committed before the mail).
- **Committed in:** 7cc5096

**2. [Rule 2 - Missing Critical] `create` vs `create_in_space` role-branch for the artifact write**
- **Found during:** Task 1 (deliver verb)
- **Issue:** The plan interface referenced only `artifact_repo.create_in_space(...)`. `create_in_space` raises `RuntimeError` for a USER-scoped repo (it is superadmin-only, `repository.py:167`); a plain `create` raises `RuntimeError` for a SUPERADMIN (null-space, `repository.py:146`). Using either unconditionally would 500 for one of the two caller roles.
- **Fix:** `_create_report_artifact` branches on `identity.role == "superadmin"` (→ `create_in_space(intake.space_id, ...)`) vs user (→ `create(...)`), the exact idiom every other create site uses (`storage_routes` audio row, `create_running_skill_run`, `research_routes` run row).
- **Files modified:** backend/app/api/intake_routes.py
- **Verification:** By construction; mirrors the proven role-branch in `storage_routes.py:209-215`.
- **Committed in:** 7cc5096

**3. [Rule 3 - Blocking] `ai_session.get_engine` patched in the cross-tenant test harness**
- **Found during:** Task 3 (tests)
- **Issue:** The deliver/replace write path runs through `tenant_session` (in `app.db.ai_session`), which resolves the engine via its OWN `get_engine` import — not `session_mod.get_engine`. The existing `_patch_engine_factories` only patched the `session_mod` namespace, so a cross-tenant deliver test would dial the real (unreachable) Cloud SQL engine.
- **Fix:** Extended `_patch_engine_factories` (both in `test_report_delivery.py` and `test_intake_cross_tenant.py`) to also `monkeypatch.setattr(ai_session, "get_engine", ...)`.
- **Files modified:** backend/tests/test_report_delivery.py, backend/tests/test_intake_cross_tenant.py
- **Verification:** By construction; run green in Cloud Build.
- **Committed in:** ef4c779

---

**Total deviations:** 3 auto-fixed (1 bug, 1 missing-critical, 1 blocking)
**Impact on plan:** All three are correctness requirements the plan's own behavior contract demanded (same-tx atomicity, superadmin-safe write, test-harness engine routing). No scope creep — the endpoint surface, models, and test coverage match the plan exactly.

## Issues Encountered
- **Dev machine has no Python interpreter** (per project constraint): could not run `pytest` or even `py_compile` locally. Tests were authored by-construction mirroring `test_mail_endpoints.py` / `test_intake_cross_tenant.py` fixtures and idioms verbatim. The suite runs in Cloud Build.
- **Pre-existing `ci_no_raw_db_access.sh` offender** at `app/research/run_task.py:86` (`return get_engine()`) — present at the base commit (Phase 17), NOT caused by 18-01. My `intake_routes.py` change is CLEAN under the guard (the `tenant_session` import is a seam function, not raw engine/session construction). Logged to `deferred-items.md`.

## Deferred Issues
- None caused by this plan. See `deferred-items.md` for the pre-existing `run_task.py` guard finding (out of scope).

## Threat Flags
None — no new security surface beyond the plan's `<threat_model>`. All three endpoints join the cross-tenant denial suite; PDF-only (D-10), forged-key (D-08), status-gate (REPORT-02), and superadmin-safe write (T-18-06) are all implemented and tested.

## Next Phase Readiness
- The contract (`DeliverBody`, `ReportView`, the three endpoint paths) is the source of truth the frontend plans mirror: **18-02** (admin `FinalReportBlock` repair + Deliver dialog) calls `POST /deliver` and `POST /report/replace`; **18-03** (client report page) calls `GET /report` and feeds `storage_path` back to the existing `GET /storage/signed-url`.
- Deploy: the backend needs a Cloud Run image rebuild + redeploy (no migration, no new secret) before live UAT — follow the `infra/DEPLOY-RUNBOOK.md` backend image path.
- No known blockers.

---
*Phase: 18-human-report-upload-client-delivery*
*Completed: 2026-07-22*
