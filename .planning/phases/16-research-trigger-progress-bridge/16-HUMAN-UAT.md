---
status: partial
phase: 16-research-trigger-progress-bridge
source: [16-VALIDATION.md, 16-05-PLAN.md]
started: 2026-07-21T14:12:00Z
updated: 2026-07-21T14:12:00Z
---

## Current Test

[awaiting human testing — operator live session per infra/DEPLOY-RUNBOOK.md § Phase 16]

## Tests

### 1. First live intake-originated seam trigger → run reaches `completed` + email arrives
prereqs: Step 16.a REBUILD + 16.b migration 0011 applied + 16.c TRIBUNAL_SERVICE_URL confirmed +
16.d NESTOR_WORKER_STALE_MINUTES=90 set + 16.e Anthropic credits topped up (all per runbook).
expected: On a DECOMPOSED smoke intake in a smoke space, click "Start research" and confirm the
AlertDialog (the 202 fires only on confirm, D-03). The intake status flips `decomposed → in_research`,
a `research_runs` row is inserted `queued`, the worker claims it, the run progresses through its
stages, reaches `completed` (~17–19 min), and the completion email arrives at your address
(`NESTOR_ADMIN_EMAIL` / the acting superadmin). This is the FIRST real intake-originated seam call —
it ALSO closes the deferred Phase-14 HTTP UAT (item 1 of 14-HUMAN-UAT.md).
how: admin intake detail → Start research → confirm → watch the panel to terminal → check inbox.
record: run id = _____, tribunal_run_id = _____, total cost (USD) = _____, duration = _____ min,
`verify_chain` result = _____ (expect OK), completion email received = yes/no.
also: after this passes, update `.planning/phases/14-auth-retirement-integration-seam/14-HUMAN-UAT.md`
item 1 result to PASS referencing this Phase-16 run id.
result: [pending]

### 2. Progress panel visual — dynamic stage list + ticking cost, intake design language
expected: While the run is in flight, the admin intake detail progress panel (`ResearchRunProgress`)
renders ONE row per mirrored `research_runs` stage via `.map` over the live `stage_detail` trace —
NO hardcoded stage count (a 10-stage run renders 10 rows; T-16-14). Each stage shows a
done/running/pending icon, and the panel shows a running cost + elapsed clock (`tabular-nums`) in the
intake design language (`border-l-4`, `bg-paperLight`, `font-mono` uppercase stage labels, `#FF2D87`
accent). On terminal it collapses to a summary card (completed timestamp / total cost / duration) or
a failure card (`error_message` + re-trigger affordance).
how: open the intake detail during the live run from step 1 and observe the panel update via SSE.
record: stages rendered dynamically = yes/no, cost ticked = yes/no, design language matches intake =
yes/no.
result: [pending]

### 3. D-08 client-isolation — client login shows NO research surface during `in_research`
expected: Log in as a CLIENT user for the smoke space while the run above is `in_research`. The
client-facing UI shows NO deep-research surface (no progress panel, no run status, no cost) — the
research experience is superadmin-only this milestone (D-08 / T-16-18). A completed run does NOT
auto-advance the client-visible status.
how: separate client login (or incognito) against the same smoke intake during the live run.
record: client sees research surface = yes/no (expect NO).
result: [pending]

### 4. Stale-window live setting — `NESTOR_WORKER_STALE_MINUTES=90` on the worker
expected: `gcloud run services describe tribunal-worker` env shows
`NESTOR_WORKER_STALE_MINUTES=90` (above the measured 17–19 min max — T-16-16, no double-dispatch),
and `NESTOR_TRIBUNAL_UNCAPPED` remains ON (D-02, left ON deliberately).
how: runbook Step 16.d verify command.
record: NESTOR_WORKER_STALE_MINUTES = _____ (expect 90), NESTOR_TRIBUNAL_UNCAPPED still ON = yes/no.
result: [pending]

## Summary

total: 4
passed: 0
issues: 0
pending: 4
skipped: 0
blocked: 0

## Gaps
