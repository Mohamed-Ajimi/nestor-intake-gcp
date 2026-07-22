---
phase: 16-research-trigger-progress-bridge
plan: 05
subsystem: deploy + live UAT
tags: [runbook, uat, seam, tribunal, live-run]
requires: [16-03, 16-04]
provides:
  - "Runbook § Phase 16 (16.a–16.f: REBUILD, 0011 migrate, env confirms, stale window, live UAT)"
  - "First real intake-originated seam run proven green end-to-end (run 4cbb5311, ~48 min, completed)"
  - "Deferred Phase-14 seam HTTP UAT closed (14-HUMAN-UAT item 1 → PASS)"
affects: [17-04 live UAT (rides on this completed run), phase-20 cap/stale calibration]
key-files:
  created:
    - .planning/phases/16-research-trigger-progress-bridge/16-HUMAN-UAT.md
  modified:
    - infra/DEPLOY-RUNBOOK.md
    - .planning/phases/14-auth-retirement-integration-seam/14-HUMAN-UAT.md
key-decisions:
  - "Attempt-cap cleanup via nestor-migrate job arg-override DELETE of failed rows (user-run; classifier blocks agent)"
  - "verify_chain recording deferred to Phase-17 re-verify endpoint (seam-only access is by design)"
duration: multi-session (2026-07-21 authoring + fix cycle → 2026-07-22 green run)
completed: 2026-07-22
---

# Plan 16-05 Summary: Deploy runbook + operator live UAT (the green run)

## What was proven live (2026-07-22)

**Run 4cbb5311-9f5f-4504-84bb-b0dda2aedf48** (tribunal run 9c84e5a9-1bb9-4b6e-a3ce-2351eda9df63),
intake e08620c5, attempt 2, duration 11:16:46Z → 12:04:28Z (~48 min), terminal **completed**:

trigger click → committed trigger tx → `research driver scheduled` → `run_poll_driver START` →
seam `create_run` (engine_status=queued) → worker `run_claimed` (<1s) → TribunalPipeline →
109+ audited LLM calls (claude-sonnet-4-6 delegation, google deep-research sub-agents,
gemini-2.5-flash; 82+ MiB audit records in the run's GCS audit prefix) → driver `terminal
status=completed` → `DONE`. Driver mirrored /metrics every ~3 s throughout, all 200.

This closes the Phase-16 core loop (ENGINE-03/SEAM-03/RUN-01/RUN-02 mechanics) AND the deferred
Phase-14 seam HTTP UAT (first real intake-originated seam call — 14-HUMAN-UAT item 1 → PASS, with
the bonus negative proof that an operator identity token is rejected: "invalid internal caller token").

## The fix chain that made it possible (all deployed on nestor-api rev 00035-cqg)

- `615b6bc` — driver diagnostics (WARNING/ERROR lines; uvicorn drops app INFO) — load-bearing, do not remove
- `11e3043` — commit trigger tx BEFORE scheduling the poll driver (THE core bug: BackgroundTask ran
  before the dependency tx committed → 0-row patches, 900s lock hangs, vanished rows)
- `721086d` — idempotency key on mirror-row id (`uuid5(intake_id, research_run_id)`), not attempt
  number (attempt replay returned dead-run corpses)
- `d0032c4` (+ `ef6e941`/`f6e80ee`/`4355bc2`, quick task 260721-twy) — Tribunal intake gatekeeper →
  delegator (sonnet-4-6, multi-line research assignments, full context pack in brief, no clarify
  rubberbands)

Blocker resolution today: Anthropic credits topped up on the org behind `Nestor_Claude2`
(verified by direct minimal API call), two failed rows DELETEd via the migrate-job recipe
(executions nestor-migrate-mmzzk / -698w8), one click → green.

## Task completion

| Task | Status | Evidence |
|------|--------|----------|
| 1. Runbook § Phase 16 + 16-HUMAN-UAT.md | done (committed 2026-07-21 session) | `## Phase 16` in infra/DEPLOY-RUNBOOK.md; 16-HUMAN-UAT.md |
| 2. Operator live session (checkpoint) | done — run completed green | 16-HUMAN-UAT tests 1+4 PASS; tests 2 (panel visuals) + 3 (client isolation) pending operator confirmation, non-blocking |

## Deferred / follow-ups (carried from the fix-cycle handoff + observed in the green run)

- **Engine defect (NEW, observed live):** group skeptic systematically fails with
  `'str' object has no attribute 'get'` — skeptic arm effectively OFF; fix in nestor_pulse_sdk.
- **Anthropic org monthly usage cap** tripped mid-run (self-configured; resets 2026-08-01) —
  operator must raise it before further runs. Separate from credit balance.
- Report assembly stripped 28 unresolved `[cite:]` markers (quality note).
- Runtime calibration: delegator runs ~48 min vs old 17–19 min baseline (stale window 90 still OK).
- Frontend: apiFetch must NOT auto-retry non-idempotent POSTs on 5xx; disable Start button while pending.
- Superadmin engine pool (2+3) starvation-prone; revisit sizing or move drivers off the API process.
- Structural: move the long-lived poll driver out of BackgroundTasks (Cloud Tasks / worker).
- Trigger concurrency: partial unique index on (intake_id) WHERE status IN ('queued','running').
- 4 pre-existing mail-audit test failures (unchanged).
- Prior deferrals: AIReviewPanel/AISkillsPanel effect loops, FR/EN catalog parity, worker claim-loop
  hardening, IaC drift (incl. min-instances=1 + images 20260721-220957/20260722-001052).
- Stakeholder decisions pending in .planning/STAKEHOLDER-NOTES.md (context-pack versioning).
- CLAUDE.md "no lockfile committed" claim stale.

## Self-Check: PASSED

- Run reached `completed` live (driver terminal log 12:04:28Z) ✓
- 14-HUMAN-UAT item 1 → PASS recorded ✓
- 16-HUMAN-UAT results + gaps recorded ✓
- Runbook § Phase 16 exists ✓
