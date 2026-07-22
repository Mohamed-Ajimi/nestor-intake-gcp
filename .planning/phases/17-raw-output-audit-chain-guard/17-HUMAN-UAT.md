---
status: partial
phase: 17-raw-output-audit-chain-guard
source: [17-VALIDATION.md, 17-04-PLAN.md]
started: 2026-07-22T00:00:00Z
updated: 2026-07-22T00:00:00Z
---

## Current Test

[awaiting human testing — operator live session per infra/DEPLOY-RUNBOOK.md § Phase 17]

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
record: run id = _____, tribunal_run_id = _____, `report.md` present = yes/no, number of `research/*.md`
files = _____, `sources.json` present = yes/no, any rejected-claims file/content present = yes/no
(expect NO).
result: [pending]

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
record: `chain_status` on the real run = _____ (expect `verified`), came from the completion-path gate =
yes/no, scratch-tenant tamper produced the locked card = yes/no/skipped, Re-verify lifted the lock =
yes/no/skipped.
result: [pending]

### 3. Client isolation — a client login can never see or reach the raw-output download (REPORT-02)
expected: Log in as a **CLIENT** user (user-role) for the smoke space. The client-facing UI shows NO
raw-output download, NO chain state, and NO research surface anywhere — none of it is visible or
reachable (REPORT-02 absolute rule). Reaching the download route directly as a client/user-role or
cross-space caller returns an existence-hidden **404** (never a 403, never the file) — this is proven by
the CI-gated denial suite (`test_research_cross_tenant.py`), and the live check confirms it end-to-end.
how: separate client login (or incognito) against the same smoke intake; inspect the client UI and,
optionally, attempt the download route directly.
record: client sees any raw-output/research surface = yes/no (expect NO), direct download route as
client → 404 = yes/no (if checked).
result: [pending]

## Summary

total: 3
passed: 0
issues: 0
pending: 3
skipped: 0
blocked: 0

## Gaps
