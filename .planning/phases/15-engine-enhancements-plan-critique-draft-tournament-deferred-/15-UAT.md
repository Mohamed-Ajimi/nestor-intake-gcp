# Phase 15 — Operator UAT: Recorded-Run Walkthrough (run-4cbb5311)

**Purpose:** prove the four Phase-15 operator surfaces (D15 agent feed, superadmin
verification report, facts-only cost, numbered clickable citations) and the `verify_chain`
gate against the **RECORDED run-4cbb5311** — the LUKOIL BeNeLux dynamic-pricing run — with
**NO live LLM run**. The Anthropic monthly cap blocks live runs until 2026-08-01; the recorded
fixture (seeded by Plan 15-01 from `docs/tribunal-run-reports/run-20260722-4cbb5311/`) supplies
all surface data, so every check below reads real recorded rows, never a fresh engine run.

**Prerequisite:** the operator has completed runbook `infra/DEPLOY-RUNBOOK.md` § Phase 15
Steps 15.a–15.d (both Tribunal images rebuilt at one `$SHA` + `tribunal-migrate` 0011 + frontend
rebuild + the Cloud Build pytest targets green + `verify_chain` re-run green on the deployed audit
data). Do NOT start this walkthrough until Steps 15.a–15.d are done.

**Visual bar:** `replit view.png` (repo root) + the D15 feed mockup in
`.planning/RESEARCH-ENGINE-DECISIONS.md` (D15). The feed must LOOK like the Replit-style activity
feed — agent cards, per-block "Worked for X · N actions · $Y" summaries, collapsible narration,
visible retries — not a status checklist.

**Baseline to read alongside:** `docs/tribunal-run-reports/run-20260722-4cbb5311/REPORT.md`
(the hand-built forensic report — the template these surfaces productize),
`.../GROUPS.md`, `.../index.json`, `.../selection-experiment/`.

**Requirement source:** ROADMAP § Phase 15 Success Criteria SC1–SC5 (the authority) +
`15-CONTEXT.md` V-02 (operator acceptance). `15-VALIDATION.md` § Manual-Only Verifications is the
registry of which behaviors are manual-only (feed/report/citation/audit visual UAT, client-role
blindness, `verify_chain` on deployed data) — it is NOT the authority for the criteria themselves.

---

## Setup

1. Log in as a **superadmin** to the deployed frontend (`nestor-frontend` run.app).
2. Navigate to the admin intake detail page for the intake carrying the recorded run-4cbb5311
   (`/admin/pulse/intakes/{id}` — the `ResearchRunProgress` anchor). The recorded run is a
   COMPLETED (terminal) run, so the feed renders frozen + clickable (D15 replay) and the D-09
   summary card's "View verification report" toggle is present.
3. Keep the baseline report `docs/tribunal-run-reports/run-20260722-4cbb5311/REPORT.md` open in a
   second window for the side-by-side V-02 sign-off.

---

## Step 1 — SC2 · The D15 agent feed + audit-body drill-down (vs `replit view.png` + D15 mockup)

**Success criterion (SC2):** the live agent-feed foundation (D15) renders agent-level activity
per the operator-agreed feed mockup — extending, not replacing, the Phase-16 dynamic-stage-list
contract; per-row cost visible.

1. On the recorded run's intake detail, confirm the research panel renders the **D15 activity
   feed** (NOT a status checklist): a chronological stream of **agent cards**, each showing the
   task it was given, with a "Show task" / "Show less" toggle expanding to the full prompt (like
   Replit's subagent blocks).
   - **Expected:** agent cards visible; each card has a task title + expandable prompt.
2. Confirm each agent card shows a **per-agent status line** mapping status → icon
   (spinner/check/retry-rotate/warning/dot) with a result line in the shape
   **`done · {N} facts · ${cost}`** — the per-row cost is visible on the card.
   - **Expected:** at least one card shows a real per-row cost (`$X`) and a facts count.
3. Confirm a **per-block summary card** renders after each work block in the shape
   **"Worked for {duration} · {N} actions · {M} items read · ${cost}"** — the professionalism signal.
   - **Expected:** at least one "Worked for …" summary card is present.
4. Confirm **retries are shown as recovery, not hidden** — if the recorded run has a retry, a card
   reads **`retry {attempt}/{max} — waiting {wait}s`** (R5); it is never suppressed.
   - **Expected:** any recorded retry is visible in the feed (if the run had none, note "no retry
     in this recorded run" — the affordance still renders when present).
5. Click an agent card's **drill-down** affordance → confirm the **redacted audit body**
   (request / response, rendered from the audit records already written per call) opens in the
   side / collapsible panel per the D12 mockup. The body is read-only, pretty-printed, GCS-sourced;
   there is **no live-URL fetch** and **no hash/prev_hash** shown.
   - **Expected:** the audit-body panel opens with request + response; NO hash field is visible.
6. **Compare against the visual bar:** hold the feed next to `replit view.png` + the D15 mockup —
   agent cards, collapsible narration, per-block summaries, visible retries. It must give
   "professionalism and confidence" (operator's bar), not a bare stage bar.
   - **Expected:** the feed visually matches the D15 activity-feed shape.

**Result:** ☐ PASS ☐ FAIL — notes: ________________________________________________

---

## Step 2 — SC1 · The superadmin verification report (funnel + verdicts + drill-down)

**Success criterion (SC1):** a superadmin-only post-run verification report renders for a
completed run from recorded data (run 4cbb5311): gate funnel numbers, per-claim verdicts,
drill-down — no client visibility (16-D-08 stands).

1. Click **"View verification report"** on the D-09 summary card. The report renders (superadmin
   only, over the Plan 15-04 proxy).
2. Confirm the **verification funnel** renders with the recorded numbers (per
   `run.verification_summary`, seeded from the recorded run): **distilled / selected (kept) /
   dropped / verify sessions / verdicts / skipped-stable + why / failed-loud**. The recorded
   funnel constants are: distilled **1,162**, kept **456**, dropped **706**, selected-verify
   **424**, skipped-stable **32**, verify-sessions **176** (see STAKEHOLDER-NOTES §2026-07-24 +
   the selection-experiment artifacts).
   - **Expected:** the funnel shows real recorded counts (not zeros / placeholders).
3. Confirm the **refuted claims** section renders each refute WITH its skeptic evidence and effect
   on the report (the report has 31 refute verdicts in the recorded extract; ≥1 carries non-null
   `evidence_refs` + reconciliation).
   - **Expected:** ≥1 refuted claim shows evidence + effect.
4. Confirm the **superseded / scoped findings** section renders temporal caveats (e.g. the KPAnG
   "pattern superseded since 1 April 2026" case — true-but-superseded claims carry the temporal
   note inline, per STAKEHOLDER-NOTES).
   - **Expected:** superseded/scoped findings render with their temporal caveat.
5. Confirm the **reconciled contradictions** section renders the chosen canonical value for
   disputed variants (e.g. the live contradictions the recorded run shipped: Aral 16% vs 21%
   share, LUKOIL NL 46 vs ~70/75 stations, the Zeeland / Gunvor / Carlyle sale disputes).
   - **Expected:** reconciled contradictions render with a canonical value.
6. Confirm the **honest UNVERIFIED list** renders — the claims that shipped without a verdict
   (the recorded run predates claim linkage, so this reports the full claim count as unverified,
   an honest signal, never a fabricated 0).
   - **Expected:** the unverified list renders an honest count (not silently "0").

**Result:** ☐ PASS ☐ FAIL — notes: ________________________________________________

---

## Step 3 — SC3 · Facts-only cost (itemized, with a pending state — never an estimate)

**Success criterion (SC3):** cost display is facts-only (C1): every countable cost class is
counted (cache writes, search fees, deep-research usageMetadata) — pending-then-backfill-exact,
never an estimate.

1. Inspect the cost display (the verification report's true-cost block + the feed's per-row cost).
   Confirm every **countable class is itemized**:
   - Anthropic **cache-WRITE** tokens are charged (the ~8.7M uncounted tokens ≈ $33 the old panel
     dropped — the run total should now reflect ~$43–45, not the old ~€5).
   - **web_search / web_fetch** server-tool fees are counted (the recorded run: 516 searches +
     216 fetches; web_search priced per-search, web_fetch billed as input tokens = $0 flat).
   - Gemini **deep-research usageMetadata** is priced when present.
   - **Expected:** the run total is the corrected (~$43–45 class) figure, not the ~€5 undercount.
2. Confirm any **un-itemizable Gemini grounding fee** shows a **"pending"** LABEL — never a
   number. Per C1 (operator, verbatim): "no estimation, only facts and correct calculations." A
   pending fee is a label until the exact billing amount is backfilled; it is NEVER a guessed
   placeholder number.
   - **Expected:** where the grounding fee is un-itemizable, the display reads "tool fees:
     pending" (a label), NOT a numeric estimate. (For the recorded run the DR `usageMetadata` is
     absent — confirmed RESEARCH Q3 — so the pending state is the expected path.)

**Result:** ☐ PASS ☐ FAIL — notes: ________________________________________________

---

## Step 4 — SC4 · Numbered clickable citations (every `[n]` resolves; dead links survive)

**Success criterion (SC4):** citations render as numbered, clickable references generated from
the existing 3-table citation model (D13); every citation number resolves.

1. In the report body, confirm each load-bearing statement carries a numbered **`[n]`** marker.
   The numbers are **generated from the claim–source database** (Plan 15-03 numbering), never
   left to the writing model (that is what produced the old run's 28 stripped markers).
2. Click **every `[n]`** marker → confirm each opens a **source panel** with: title, publication
   date, quality tier (**1 official / 2 serious press / 3 blog**), a single-source badge where
   applicable, an inline temporal caveat for verification-flagged outdated facts, AND the stored
   **snapshot** of the source text.
   - **Expected:** every `[n]` opens a panel; no number dangles.
3. Confirm a **dead link still resolves** — the panel renders the DB-stored snapshot text
   directly (it is never re-fetched from the live source URL), so a source whose live URL is now
   dead still shows its captured snapshot.
   - **Expected:** the snapshot renders from storage; the panel makes NO live-URL request.

**Result:** ☐ PASS ☐ FAIL — notes: ________________________________________________

---

## Step 5 — SC5 · `verify_chain` green on the deployed audit data

**Success criterion (SC5):** `verify_chain` stays green — new fields only ADD; no frozen audit
payload field renamed.

1. Confirm `verify_chain` was **re-run GREEN on the DEPLOYED audit data** per runbook Step 15.d
   (the 0011 migration is additive and keeps the new columns OUTSIDE the frozen hash-chain
   payload, so the chain must stay green after the migration lands — this is the T-15-17 gate).
   - **Expected:** the Step-15.d `verify_chain` proof returned GREEN. A RED chain is a STOP — do
     not sign off; investigate whether a non-additive change slipped into `_payload_for_row`.

**Result:** ☐ PASS ☐ FAIL — `verify_chain` result: ________________  notes: ______________

---

## Step 6 — Client-role blindness (16-D-08 — the client sees NOTHING)

**This is a blocking isolation check, not a success criterion per se — a client seeing any
research surface is a 16-D-08 breach.**

1. Log in as a **CLIENT** (user-role) member of the SAME space, and open the same intake.
2. Confirm **NONE** of the Phase-15 research surfaces are visible or reachable: no D15 feed, no
   verification report, no audit-body drill-down, no citation panel, no per-row cost. The
   superadmin surfaces mount ONLY under `admin.pulse.*` (route-import grep guard, enforced
   automatically) and the server proxies are superadmin-only (Plan 15-04 denial trios return
   404, existence-hidden).
   - **Expected:** the client sees NO research surface anywhere. If a client can reach ANY of it →
     STOP, this is a 16-D-08 breach — do NOT accept the phase.

**Result:** ☐ PASS ☐ FAIL — notes: ________________________________________________

---

## V-02 Sign-Off

V-02 acceptance = the hard checklist above (Steps 1–6 all PASS) **PLUS** operator sign-off after
reading the new operator surfaces next to the recorded baseline
`docs/tribunal-run-reports/run-20260722-4cbb5311/` (REPORT.md, GROUPS.md, index.json,
selection-experiment/). Both must pass.

### Hard checklist (all must be PASS)

- [ ] Step 1 — SC2: D15 agent feed renders per `replit view.png` + D15 mockup (cards, per-row
      cost, per-block summaries, visible retries) + audit-body drill-down opens (redacted, no hash)
- [ ] Step 2 — SC1: verification report renders funnel + refuted-with-evidence + superseded/scoped
      + reconciled contradictions + honest unverified list
- [ ] Step 3 — SC3: cost is facts-only — every countable class itemized (cache-write / search
      fees / DR usage), un-itemizable grounding fee shows "pending", never a number
- [ ] Step 4 — SC4: every `[n]` resolves to a source panel (title / date / tier / snapshot);
      dead links survive via the stored snapshot
- [ ] Step 5 — SC5: `verify_chain` green on the deployed audit data
- [ ] Step 6 — 16-D-08: a CLIENT login sees NONE of the research surfaces (blocking)

### Operator sign-off

Having read the new operator surfaces (feed / verification report / citations) next to the
recorded baseline `docs/tribunal-run-reports/run-20260722-4cbb5311/`, I confirm the Phase-15
operator surfaces truthfully represent the recorded run and accept the phase:

- **Recorded run walked:** run-4cbb5311 (LUKOIL BeNeLux dynamic-pricing)
- **No live LLM run:** ☐ confirmed (recorded-run-only; Anthropic cap until 2026-08-01)
- **All 6 hard-checklist items PASS:** ☐ yes ☐ no (if no, list gaps below)
- **Gaps to close (if any):** ______________________________________________________
- **Operator:** _________________________  **Date:** _______________  **Verdict:** ☐ ACCEPT ☐ REJECT

---

## Deploy Record + Deferral (2026-07-24)

**Operator decision (2026-07-24):** deploy now, DEFER the browser walkthrough + V-02 sign-off
to the combined UAT at the END of Phase 15.2 (one session covering 15 surfaces + 15.1 gates +
15.2 engine acceptance). The prerequisite deploy (Steps 15.a–15.e) and ALL automated gates ran
green on 2026-07-24:

| Step | Result |
|------|--------|
| 15.a tribunal-worker | deployed, image `20260724-214354` |
| 15.a tribunal-api | deployed, image `20260724-214354`, URL unchanged |
| 15.b migration 0011 | applied — log line `Running upgrade 0010 -> 0011` confirmed (no stale-image no-op) |
| 15.e nestor-api | rev `nestor-api-00040-8mw` (live rev predated 15-04 routes) |
| 15.c frontend | rev `nestor-frontend-00024-lwq` |
| 15.d intake suite | Cloud Build SUCCESS (denial trios + happy path incl.) |
| 15.d tribunal full suite | Cloud Build SUCCESS — 345 passed / 35 skipped (first-ever full-suite green; Phase-13 keyless-env debt resolved) |
| 15.d verify_chain critical | Cloud Build SUCCESS — chain green post-0011 (SC5 automated half) |
| 15.d seam env | `TRIBUNAL_SERVICE_URL` present, untouched |

**Fix cycle during gates (3 commits on master):** (1) recorded fixture data committed in-package
(`tests/fixtures/run_4cbb5311/recorded/`) because `gcloud builds submit tribunal` ships only the
tribunal/ subtree — repo-root `docs/` was absent in Cloud Build; (2) 15-01's
`_ConstraintEnforcingFakeWriter` accepts 15-02's additive `cache_creation_tokens` kwarg
(cross-wave integration miss caught by the gate); (3) legacy-tools D-01 guard hashes
LF-normalized bytes (Windows CRLF checkout ≠ content change; normalized hash matches the
snapshot exactly, proving the carried file untouched).

**Walkthrough status:** steps 1–5 below remain PENDING — to be run in the combined
end-of-15.2 UAT session. Client-blindness (16-D-08) is meanwhile covered automatically by the
15-04 denial trios (client/user-role → 404) which ran green in the intake suite.
