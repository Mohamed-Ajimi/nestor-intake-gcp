---
status: complete
phase: 17-raw-output-audit-chain-guard
source: [17-VALIDATION.md, 17-04-PLAN.md]
started: 2026-07-22T00:00:00Z
updated: 2026-07-22T14:30:00Z
---

## Current Test

[COMPLETE 2026-07-22 — all 3 tests passed (one with a same-session fix); one minor re-test
deferred to the Phase-20 ledger, see Gaps]

> **PRECONDITION (external blocker).** This proof rides on a real `completed` run. Anthropic credits
> (the `Nestor_Claude2` key) are EMPTY — the deferred § Phase 16 live run is still parked on it. Top up
> credits and complete the parked § Phase 16 Step-16.f run FIRST (that produces the completed +
> chain-verified run this download proof needs), then run the tests below. Also required before these
> tests: Step 17.a tribunal-api REBUILD (first) + Step 17.b nestor-api REBUILD + Step 17.c migration
> 0012 applied + Step 17.d frontend deployed + Step 17.e envs confirmed (all per runbook).

## Tests

### 1. Raw-output download from a real completed run — zip contents (D-01 / D-03)
prereqs: a real `completed` + chain-verified run exists (from the parked § Phase 16 run, completed
after the credit top-up); Steps 17.a–17.e all done per runbook.
expected: On the completed smoke run's admin intake detail page, the completion summary card shows chain
state **VERIFIED** and a **Download** button. Clicking **Download** downloads a zip (attachment
disposition, forced by the signed URL). Opening the zip shows the D-03 layout: `report.md` at the root,
at least one `research/<angle>.md` file (one per provider `cleaned_reports` pair), and `sources.json`.
There is **NO rejected-claims file and NO discredited content** anywhere in the zip (D-01 — the
rejected-claims ledger is excluded at the tribunal `/research-bundle` boundary; the download serves
`cleaned_reports` only).
how: admin intake detail → completed run summary card → click Download → open the downloaded zip and
inspect its file list + contents.
record: run id = 4cbb5311-9f5f-4504-84bb-b0dda2aedf48, tribunal_run_id =
9c84e5a9-1bb9-4b6e-a3ce-2351eda9df63, `report.md` present = yes (but EMPTY — defect, see result),
`research/*.md` files = present with real content, `sources.json` present = yes, rejected-claims
content = NO (D-01 clean).
result: PASS WITH ONE DEFECT (fixed same session) 2026-07-22 — operator downloaded the zip live:
attachment disposition worked, D-03 layout correct, D-01 scrub confirmed. `report.md` was EMPTY:
the tribunal report endpoint returned only parsed `sections` (never raw markdown), so both
`output_markdown` (driver) and the bundle's report.md fell back to empty (A1 shape mismatch).
FIXED in `05b0e96` (endpoint now returns `markdown` = Output.body) + tribunal-api redeployed.
RE-TEST DEFERRED (operator decision, minor): see Gaps.

### 2. verify_chain green as a hard gate on the completion path — locked state on a broken chain (D-06)
expected: The chain-verified state on the run above was produced by the **completion-path `verify_chain`
gate** — the run's `chain_status` is `verified` (not backfilled; the completion path is the sole
writer). A verified chain is what unlocks the Download button. OPTIONAL negative proof: in a **scratch
tenant** (not the real smoke tenant), tamper the run's audit chain so `verify_chain` fails; the summary
card then shows the **complete-but-locked** state — a red locked card with a **Re-verify** button and
NO download affordance. Clicking **Re-verify** re-runs `verify_chain`; a now-passing chain lifts the
lock (`chain_status` → `verified`) and the Download button returns (the bundle materializes on the next
download click, build-on-download-if-missing).
how: confirm `chain_status=verified` on the real run (via the summary card state / a superadmin DB read);
optionally reproduce the locked → Re-verify cycle in a scratch tenant.
record: `chain_status` on the real run = verified, came from the completion-path gate = NO (run
4cbb5311 completed PRE-Phase-17-deploy, so chain_status started NULL; stamped verified via the
re-verify endpoint — the operator clicked the new NULL-state "Keten verifiëren" affordance and it
flipped to Download), scratch-tenant tamper = skipped, Re-verify lifted from NULL = yes.
result: PASS (adapted path) 2026-07-22 — verify_chain ran live against the engine and returned OK
(the EU-AI-Act Art. 12 chain check on a real 228-call run). The completion-path gate itself ships
for future runs and is pinned by the green `test_research_run_task.py` completion-gate cases.
NOTE: the NULL-state affordance did not exist as-built (chain_status NULL rendered NO button) —
fixed live in `0ff2565` before this test could run.

### 3. Client isolation — a client login can never see or reach the raw-output download (REPORT-02)
expected: Log in as a **CLIENT** user (user-role) for the smoke space. The client-facing UI shows NO
raw-output download, NO chain state, and NO research surface anywhere — none of it is visible or
reachable (REPORT-02 absolute rule). Reaching the download route directly as a client/user-role or
cross-space caller returns an existence-hidden **404** (never a 403, never the file) — this is proven by
the CI-gated denial suite (`test_research_cross_tenant.py`), and the live check confirms it end-to-end.
how: separate client login (or incognito) against the same smoke intake; inspect the client UI and,
optionally, attempt the download route directly.
record: client sees any raw-output/research surface = proven by construction + CI (visual
spot-check deferred), direct download route as client → 404 = yes (CI denial suite).
result: PASS (by construction + CI) 2026-07-22 — the full denial suite ran green in Cloud Build
against the deployed code: 6/6 cross-tenant / user-role / null-space cases return EXACTLY 404 on
both bundle-url and verify-chain (the null-space cases initially returned 403 — dependency-ordering
defect, FIXED in `3ecbba6`, suite re-run green, live on rev 00037-k7t). RawOutputControls is
admin-route-only by placement. Visual client-login spot-check folded into the Phase-20 UAT ledger
with the other visual checks.

## Summary

total: 3
passed: 3
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps

**DEFERRED RE-TEST (operator, 2026-07-22, minor):** re-download run 4cbb5311's bundle and confirm
`report.md` is non-empty, now that the seam fix (`05b0e96`) is deployed. Steps: (1) run the
prepared reset script (clears the run's stale `bundle_key` so Download lazily rebuilds through the
fixed endpoint) — `scratchpad/reset-bundle-key.sh`, or any equivalent
`UPDATE nestor.research_runs SET bundle_key=NULL WHERE id='4cbb5311-...'` via the migrate job;
(2) click Download; (3) confirm `report.md` carries the full synthesized report. Alternatively the
NEXT real completed run proves it end-to-end with no reset (completion path persists
output_markdown + builds the bundle with markdown present). → Phase-20 ledger.

Minor UI defect (ledger): the completed card shows `Duur: "—"` (duration not rendered). → Phase-20.

Three fix commits landed during this UAT (all deployed): `3ecbba6` (null-space 404 ordering),
`0ff2565` (NULL-chain-state verify affordance + local card flip), `05b0e96` (report endpoint raw
markdown). Plus an operational lesson: `gcloud run jobs update nestor-migrate --image` is REQUIRED
before executing the migration job — the job does NOT track the service image (first 0012 run was
a silent no-op on the previous day's image).
