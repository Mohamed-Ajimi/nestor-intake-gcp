---
task: 260720-eh4
type: quick
subsystem: planning-docs
tags: [phase-12, uat, deploy-record, cutover]
key-files:
  modified:
    - .planning/phases/12-frontend-deploy-cutover-supabase-retirement/12-UAT.md
commit: 7731421
completed: 2026-07-20
---

# Quick Task 260720-eh4: Record rev 00010-ndr deploy + defer remaining UAT Summary

Recorded two verified facts in the phase-12 parity-UAT log (`12-UAT.md`): the 2026-07-20 live deploy of frontend rev **00010-ndr** (clearing the standing PENDING DEPLOY block) and the operator's decision to accept phase-12 parity WITH DEFERRALS, deferring the remaining unchecked checklist items until after the Tribunal milestone.

## What Changed

Three targeted, structure-preserving edits to the single tracked doc `12-UAT.md`:

1. **Resolved the pending-deploy block** — the former `⚠ PENDING DEPLOY (2026-07-16 session end)` bullet in the Live-environment section is reframed as `✓ DEPLOYED (resolves 2026-07-16 PENDING DEPLOY)`. Records: rev **00010-ndr** deployed to Cloud Run 2026-07-20 (~10:25 CEST), 100% traffic; image `frontend:20260720-102153` (Cloud Build 69381baa, 1m49s, SUCCESS); built from commit `c83fdaf` — first deployed build carrying `a710e8e` (client validation-diff fix). Smoke: `/auth/login` HTTP 200, no Supabase signature in SSR. Retest guidance retained but reframed as now-testable.

2. **Updated the "Frontend (test here):" rev history** — added a clause recording rev **00010-ndr** (`frontend:20260720-102153`, commit `c83fdaf`) as the current live build superseding 00009-4r4, with existing rev-history prose left intact.

3. **Annotated the Gate status section** — inserted a dated (2026-07-20) block above the existing PARITY GREEN paragraph recording the operator's acceptance-with-deferrals decision (explicitly NOT full PARITY GREEN); remaining unchecked items deferred until after the Tribunal milestone, still listed/unchecked, not gating phase-12 closure. Added `- Gate: [x] PARITY ACCEPTED WITH DEFERRALS (operator decision, 2026-07-20)` alongside — not replacing — the untouched `- Gate: [ ] PARITY GREEN` line.

## Verification

- `grep` confirms `00010-ndr`, `ACCEPTED WITH DEFERRALS`, and `PARITY GREEN` all present.
- Exactly 1 new checked line (`^- Gate: [x]`), 0 inherited checklist items ticked (`^- [x]` = 0).
- 21 inherited unchecked `- [ ]` boxes still present (all source-phase items + the `[ ] PARITY GREEN` line) — none flipped.

## Deviations from Plan

**1. [Rule 3 - Blocking] Staging required `git add -f`.**
- **Found during:** commit step.
- **Issue:** `.planning/` is globally gitignored; a bare `git add` of the (already-tracked) `12-UAT.md` was refused with an ignored-path error, contradicting the plan's "plain `git add` works" note.
- **Fix:** Verified the file is tracked (`git ls-files --error-unmatch` succeeds), then staged with `git add -f` on the explicit path only. Force-adding a tracked file adds no new paths and does not touch the ignored siblings — the unrelated `frontend/src/routeTree.gen.ts` (unstaged) and untracked `AGENTS.md` were left out of the index, per constraints.
- **Files modified:** none beyond the intended `12-UAT.md`.
- **Commit:** 7731421

Note: git recorded the committer identity as the machine default (`Mohamed Ajimi <ajimimo@cronos.be>`) — no repo user.name/user.email configured. Left as-is (out of task scope).

## Self-Check: PASSED

- `12-UAT.md` modified and committed — commit `7731421` present in `git log`.
- Staged diff was `12-UAT.md` only (1 file, +21/-6); no other files committed.
