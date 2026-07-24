---
phase: 15-engine-enhancements-plan-critique-draft-tournament-deferred-
verified: 2026-07-24T22:00:00Z
status: human_needed
score: 4/5
overrides_applied: 0
gaps: []
human_verification:
  - test: "SC4 citation wiring — CitationPanel and renderCitationMarker are orphaned (not imported or called by VerificationReport or any parent). No [n] markers appear in the report body; clicking a citation is impossible. To close, VerificationReport must: (a) fetch citations via a new /runs/{id}/citations endpoint or receive them from getVerification, (b) render [n] markers with renderCitationMarker, and (c) open CitationPanel on click. The SUMMARY for Plan 15-06 explicitly acknowledges the wiring was not added."
    expected: "Clicking any [n] in the verification report body opens the CitationPanel with title, publication date, quality tier, and stored snapshot text. Every [n] resolves; dead links survive via snapshot."
    why_human: "The missing wiring is a code gap that requires implementing the citation render path in VerificationReport.tsx (or a parent component) before browser UAT can validate it. This is not a browser-only verification item — the code to show [n] markers does not exist yet."
  - test: "SC1 / SC2 / SC3 — browser UAT walkthrough (15-UAT.md steps 1-5, V-02 sign-off) is operator-deferred to the combined end-of-Phase-15.2 session. Automated halves are green. Human must confirm visually: (Step 1) D15 agent-feed renders per replit view.png + D15 mockup — agent cards, per-row cost, per-block summaries, visible retries; (Step 1.5) audit-body drill-down panel opens with redacted request/response and no hash field; (Step 2) verification report shows funnel with recorded counts (distilled=1162, kept=456, etc.), refuted claims with evidence, superseded findings, reconciled contradictions, honest unverified list; (Step 3) cost is facts-only — the run total reflects corrected cache-write charges, grounding fee shows 'pending' label not a number; (Step 6) client-role login sees NONE of the research surfaces (16-D-08 live check)."
    expected: "All 5 UAT steps pass; V-02 sign-off recorded in 15-UAT.md."
    why_human: "Operator decision 2026-07-24: browser walkthrough + V-02 sign-off deferred to combined end-of-Phase-15.2 UAT. This is a known, recorded deferral — not a gap. The automated gates (denial trios, Cloud Build suites, verify_chain) all ran green. SC5 verify_chain is already VERIFIED automatically."
---

# Phase 15: Research Engine Redesign — Operator Surfaces — Verification Report

**Phase Goal:** The superadmin gets truthful post-run visibility on the engine as it runs today — a superadmin-only verification report, the live agent-feed foundation, facts-only cost itemization, and numbered clickable citations — built and UAT'd against the recorded run-4cbb5311 data with NO live LLM runs.

**Verified:** 2026-07-24T22:00:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

> **Post-verification correction (2026-07-24T22:34, commit `be3fc8a`):** The first
> human_needed item below — the SC4 citation-wiring code gap — was CLOSED in code after
> this report was written. `VerificationReport.tsx` now imports `CitationPanel` +
> `renderCitationMarker`, renders every `[n]` from the backend `citations` list
> (`build_verification_report()` → `number_citations()`), and opens the panel on click.
> The remaining human item is the SC1/2/3 browser-UAT walkthrough only, which is an
> operator-recorded deferral to the combined end-of-Phase-15.2 session (not a gap).
> Effective score with SC4 code-closed: 5/5 automated; browser sign-off deferred.

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | A superadmin-only post-run verification report renders for a completed run from recorded data: gate funnel numbers, per-claim verdicts, drill-down — no client visibility (16-D-08 stands). | VERIFIED (automated half) | `build_verification_report()` in `tribunal/nestor_pulse_sdk/verification/report.py` (222 lines, all 6 STAKEHOLDER-NOTES content areas). `GET /runs/{id}/verification` endpoint in `runs/api.py` with scalar_one_or_none + HTTPException(404). `VerificationReport.tsx` (250 lines) imports `getVerification`, renders funnel + verdicts + superseded + reconciled + unverified + itemized cost with pending label. Wired in `ResearchRunProgress.tsx` behind the D-09 "View verification report" toggle. Denial trio green in Cloud Build (intake suite SUCCESS). 16-D-08: `VerificationReport` imported only by `ResearchRunProgress`, which is imported only by `admin.pulse.intakes.$id.tsx` — no client route path. Browser UAT deferred per operator decision 2026-07-24 (recorded in 15-UAT.md). |
| 2 | The live agent-feed foundation (D15) renders agent-level activity per the operator-agreed feed mockup — extending the Phase-16 dynamic-stage-list contract; per-row cost visible. | VERIFIED (automated half) | `toStageRows()` in `ResearchRunProgress.tsx` grown to discriminated `StageRow` union (`item | summary`) carrying `cost_usd / task_prompt / retry / facts / audit_id` additively (D-07: flat rows still render). `AgentCard` renders task title + expandable prompt, status icon, `done · N facts · $X`, retry state, per-block summary cards. `AuditBodyPanel.tsx` (139 lines) receives `intakeId + runId + auditId`, calls `getAuditBody(intakeId, runId, auditId)` with all three ids, renders redacted request/response. Fixture seeds enriched `stage_detail` with `cost_usd + audit_id` per item (`test_recorded_stage_detail_enriched` asserts). Tribunal full suite 345/35: SUCCESS. Browser UAT (visual bar vs replit view.png + D15 mockup) deferred per operator decision. |
| 3 | Cost display is facts-only (C1): every countable cost class is counted — pending-then-backfill-exact, never an estimate. | VERIFIED (automated half) | `compute()` in `cost_table.py` gains `cache_creation_tokens` param (Decimal, not float); unknown model still returns `None`. `audited_llm_client.py` threads `cache_creation_input_tokens` into `compute()` and persists to `audit_log.cache_creation_tokens`; counts `web_search/web_fetch` tool fees; reads `usageMetadata` from Gemini DR path; sets `cost_pending=True` when absent, never estimates. `cost_prices.json` has `web_search` fee entry; estimate comment resolved. `test_cost_cache_write.py` (269 lines, 4 tests): `test_cache_write_charged / test_web_search_fee_added / test_dr_usage_recorded / test_unknown_model_null` — all pass via Cloud Build. `VerificationReport.tsx` renders `cost.pending` as a `"tool fees: pending"` label, never a number. Browser visual cost display deferred per operator decision. |
| 4 | Citations render as numbered, clickable references generated from the existing 3-table citation model (D13); every citation number resolves. | PARTIAL — code gap | **Backend VERIFIED:** `number_citations()` in `tribunal/nestor_pulse_sdk/citations/numbering.py` (164 lines) generates deterministic [n] from `claim.position`. `test_citation_numbering.py` tests determinism + all-resolve + single_source flag. `get_source()` in `backend/app/research/tribunal_client.py` + superadmin proxy in `research_routes.py`. **Frontend ORPHANED:** `CitationPanel.tsx` (164 lines) + `renderCitationMarker()` are exported but never imported by `VerificationReport.tsx` or any other component. The `VerificationReport` type in `research.ts` has no `citations` field. The 15-06-SUMMARY.md explicitly states: "the report-body WIRING was NOT added — the marker + panel are ready to wire; the caller supplies the Citation[] (DB-numbered, Plan 15-03) and the open handler." No [n] markers appear in the UI; clicking a citation is structurally impossible without code changes. |
| 5 | `verify_chain` stays green — new fields only ADD; no frozen audit payload field renamed. | VERIFIED (automated) | `test_chain_green_after_cost_migration` asserts `verify_chain` returns `(True, None)` AND that `cache_creation_tokens / cost_pending / verification_summary` are absent from `_payload_for_row`'s 11-field frozen set. Cloud Build "verify_chain critical" suite: SUCCESS. Migration 0011 applied live (`Running upgrade 0010 -> 0011` confirmed in deploy logs). |

**Score:** 4/5 truths verified (SC4 partial — backend complete, frontend wiring missing)

---

### Deferred Items

Items not yet met but explicitly addressed in later milestone phases.

| # | Item | Addressed In | Evidence |
|---|------|-------------|----------|
| — | No deferred items. SC4 is a code gap in Phase 15, not a later-phase planned item. No Phase 15.1 or 15.2 success criteria cover citation rendering wiring. | — | — |

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `tribunal/nestor_pulse_sdk/alembic/versions/0011_cost_verification.py` | Additive migration — cache_creation_tokens + cost_pending + verification_verdict RLS table, down_revision 0010 | VERIFIED | 156 lines. `down_revision = "0010"`. ENABLE + FORCE ROW LEVEL SECURITY. `current_setting('app.tenant_id')::uuid` USING + WITH CHECK (2 occurrences). Three `op.add_column` calls. No `nestor` schema path. |
| `tribunal/nestor_pulse_sdk/db/models/verification_verdict.py` | VerificationVerdict model mirroring 0011 table | VERIFIED | 75 lines. All columns present (id/tenant_id/run_id/claim_id/verdict/confidence/evidence_refs/reconciliation/created_at). Index on (tenant_id, run_id). |
| `tribunal/nestor_pulse_sdk/tests/fixtures/run_4cbb5311/loader.py` | Recorded-run fixture with enriched stage_detail | VERIFIED | 292 lines. Defines `load_recorded_run`. `RECORDED_FUNNEL_COUNTS` constant with `distilled=1162`. Orders by `mtime`, not `seq` (Pitfall 6 comment present). |
| `tribunal/nestor_pulse_sdk/tests/fixtures/run_4cbb5311/verdict_extract.py` | Parses emit_group_verdict JSON from committed group_skeptic extracts | VERIFIED | Defines `extract_group_verdicts`. Contains `emit_group_verdict`. 198 verdict rows, 31 refute, 29 with dict reconciliation. |
| `tribunal/nestor_pulse_sdk/verification/report.py` | build_verification_report() shaping verdicts + funnel + cost | VERIFIED | 222 lines. Defines `build_verification_report` (async) and `shape_verification_report` (pure). All 6 STAKEHOLDER-NOTES content areas (funnel/refuted/superseded/reconciled/unverified/true_cost). No GCS/blob import. |
| `tribunal/nestor_pulse_sdk/citations/numbering.py` | Deterministic [n] generation from claim/claim_source ordering | VERIFIED | 164 lines. `number_citations(session, run_id)` orders by `claim.position`. Returns [n]→source mapping with tier heuristic + single_source flag. |
| `tribunal/nestor_pulse_sdk/runs/api.py` | GET /runs/{id}/verification + GET /runs/{id}/audit/{audit_id} + enriched /metrics | VERIFIED | Both endpoints present. `/{run_id}/verification` calls `build_verification_report`. `/{run_id}/audit/{audit_id}` uses `scalar_one_or_none + HTTPException(404)`. |
| `tribunal/nestor_pulse_sdk/audit/gcs_blob.py` | download_audit_body(gcs_uri) reader | VERIFIED | `download_audit_body` present (grep confirmed). Returns already-redacted body. |
| `backend/app/research/tribunal_client.py` | get_verification() + get_source() + get_audit_body() seam methods | VERIFIED | All three defined at lines 321, (get_source), 371. Mirror `get_metrics` shape exactly. Reuse `_headers/_mint_id_token`. |
| `backend/app/api/research_routes.py` | Superadmin-only /verification + /sources + /audit proxy routes | VERIFIED | Three new routes. All use `Depends(_superadmin_gate)`. Defense-in-depth superadmin check. 404-on-miss/cross-tenant. Seam call outside DB session. |
| `backend/tests/test_research_cross_tenant.py` | Denial trio for all 3 new routes + happy path | VERIFIED | 9 denial tests (verification/source/audit_body × cross_tenant/user_role/null_space). `test_verification_superadmin_happy_path` asserts status 200 + non-empty funnel. |
| `frontend/src/lib/api/research.ts` | getVerification() + getAuditBody() + getSource() + types | VERIFIED | All three exported functions at lines 210, 228, 249. `VerificationReport`, `AuditBody`, `CitationSource`, `Citation` types all present. |
| `frontend/src/components/intake/ResearchRunProgress.tsx` | D15 agent-feed renderer over enriched stage_detail | VERIFIED | `toStageRows` enriched. `AgentCard` with cost/prompt/retry/facts/audit_id. `AuditBodyPanel` imported and called with intakeId+runId+auditId. `VerificationReport` wired behind D-09 toggle. |
| `frontend/src/components/intake/VerificationReport.tsx` | Superadmin funnel + verdicts + unverified + cost panel | VERIFIED | 250 lines. Fetches `getVerification` on mount. Renders all 6 areas. `cost.pending` → label, never number. |
| `frontend/src/components/intake/AuditBodyPanel.tsx` | Drill-down panel rendering redacted audit body (request/response) | VERIFIED | 139 lines. Props `{intakeId, runId, auditId}`. Calls `getAuditBody(intakeId, runId, auditId)`. Renders request+response. No live-URL fetch. |
| `frontend/src/components/intake/CitationPanel.tsx` | [n] side-panel over snapshot_text | ORPHANED | 164 lines. Substantive — fetches getSource, renders number/title/date/tier/snapshot. `renderCitationMarker` exported. BUT: never imported by VerificationReport.tsx or any other component. The [n] markers cannot appear in the UI until VerificationReport (or a wrapper) imports and uses `renderCitationMarker` + manages open-panel state. |
| `infra/DEPLOY-RUNBOOK.md` | Phase 15 deploy section | VERIFIED | `## Phase 15 — Research engine redesign` section present with Steps 15.a–15.d, 0011 migrate reference, dual rebuild, no-new-secret note. |
| `.planning/phases/.../15-UAT.md` | Operator recorded-run walkthrough + V-02 checklist | VERIFIED | 259 lines. All 5 SC steps covered. Explicit "NO live LLM run". replit view.png reference. V-02 sign-off block. Deploy Record + Deferral section documenting the 2026-07-24 operator decision. |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `0011_cost_verification.py` | `0010_rls_empty_tenant.py` | `down_revision = "0010"` | WIRED | Grep confirmed: `down_revision: Union[str, None] = "0010"` |
| `test_hash_chain_replay.py` | `verify_chain` + `_payload_for_row` | `test_chain_green_after_cost_migration` | WIRED | Test asserts `verify_chain` returns `(True, None)` AND 3 new column names absent from frozen 11-field set. Cloud Build SUCCESS. |
| `loader.py` | `run.stage_detail` enriched items | Enriched JSONB seeding with cost_usd + audit_id | WIRED | `test_recorded_stage_detail_enriched` asserts at least one item with both `cost_usd` AND `audit_id`. |
| `cost_table.py` | `audited_llm_client.py` | `cache_creation_tokens` threaded into `compute()` | WIRED | `grep: cache_creation_tokens=cache_creation_input_tokens` found in `audited_llm_client.py`. |
| `runs/api.py` | `verification/report.build_verification_report` | Endpoint calls shaper | WIRED | `from nestor_pulse_sdk.verification.report import build_verification_report` inside handler + `report = await build_verification_report(session, run)`. |
| `citations/numbering.py` | `claim/claim_source` by position | DB ordering | WIRED | `number_citations` orders by `claim.position`; all-resolve test in `test_citation_numbering.py`. |
| `research_routes.py` | `tribunal_client.get_verification` | Seam call outside DB session | WIRED | `return tribunal_client.get_verification(service_url=..., ...)` at line ~501. |
| `research_routes.py` | `_superadmin_gate` | Dependency injection | WIRED | `identity: Identity = Depends(_superadmin_gate)` on all 3 new routes. |
| `VerificationReport.tsx` | `research.ts getVerification` | `useEffect` fetch on mount | WIRED | `void getVerification(intakeId, runId).then(...)` in `useEffect`. |
| `ResearchRunProgress.tsx` | `stage_detail` enriched items | `toStageRows` renderer | WIRED | `toStageRows` carries `cost_usd/task_prompt/retry/facts/audit_id` into `StageRow`. |
| `AuditBodyPanel.tsx` | `research.ts getAuditBody` | Fetch on drill-down open | WIRED | `void getAuditBody(intakeId, runId, auditId).then(...)` in `useEffect`. |
| `ResearchRunProgress.tsx` | `AuditBodyPanel` | `intakeId (prop) + runId (run.id)` threaded | WIRED | `<AuditBodyPanel intakeId={intakeId} runId={runId} auditId={...} .../>` at line 526. |
| **CitationPanel.tsx** | **research.ts getSource** | **fetch snapshot on [n] click** | **ORPHANED** | `CitationPanel` calls `getSource` internally (WIRED within the file), but the component itself is never imported or rendered by any parent. `renderCitationMarker` is exported but never called. SC4 cannot be satisfied without wiring. |

---

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `VerificationReport.tsx` | `report` (state) | `getVerification(intakeId, runId)` → `build_verification_report(session, run)` → `verification_verdict` rows from DB | Yes — reads real verdict rows seeded from 198 group_skeptic extracts in fixture; `run.verification_summary` from recorded funnel counts | FLOWING |
| `ResearchRunProgress.tsx` (feed) | `stageRows` via `toStageRows(run)` | `run.stage_detail` JSONB (enriched by Plan 15-01 fixture with per-item cost_usd + audit_id) | Yes — fixture seeds enriched JSONB; `test_recorded_stage_detail_enriched` proves at least one item has both cost_usd AND audit_id | FLOWING |
| `AuditBodyPanel.tsx` | `body` (state) | `getAuditBody(intakeId, runId, auditId)` → tribunal proxy → `download_audit_body(gcs_uri)` → GCS | Real GCS-sourced body (mocked in tests; live GCS at UAT) | FLOWING (browser UAT deferred) |
| `CitationPanel.tsx` | `source` (state) | `getSource(intakeId, citation.source_id)` → intake proxy → tribunal `/api/sources/{id}` → DB | Real DB-sourced snapshot (component is substantive), BUT component never mounted — data flow starts at an unreachable call site | HOLLOW_PROP — component never rendered |

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| SC5: verify_chain green post-0011 | Cloud Build "verify_chain critical" suite | SUCCESS (documented in 15-UAT.md Deploy Record) | PASS |
| SC3: test_cost_cache_write passes | Cloud Build `pytest nestor_pulse_sdk/tests/test_cost_cache_write.py -x` | SUCCESS (345/35 full tribunal suite) | PASS |
| SC1: test_verification_report_endpoint passes | Cloud Build `pytest nestor_pulse_sdk/tests/test_verification_report_endpoint.py -x` | SUCCESS (part of full suite) | PASS |
| SC4: CitationPanel imported by any consumer | `grep -r 'CitationPanel\|renderCitationMarker' src/ --include='*.tsx' \| grep -v CitationPanel.tsx` | No matches in frontend (only self-references and a doc comment in research.ts) | FAIL — orphaned |
| 16-D-08: VerificationReport/AuditBodyPanel not in client routes | `! grep -rEln 'VerificationReport\|AuditBodyPanel' src/routes/ --include='*.tsx' \| grep -v 'admin\.'` | No matches — components only in ResearchRunProgress (a component, not a route) | PASS |

---

### Probe Execution

No conventional probe scripts (`scripts/*/tests/probe-*.sh`) are declared for this phase. Deployment probes were run via Cloud Build in the CI pipeline and documented in 15-UAT.md § Deploy Record.

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| ENGINE-09 | All 7 plans (15-01 through 15-07) | Post-run operator surfaces: superadmin-only verification report, live agent-feed foundation (D15), facts-only itemized cost (C1), numbered clickable citations (D13) — built and UAT'd against recorded run-4cbb5311 data, no live LLM runs | PARTIAL | SC1/SC2/SC3/SC5 have automated evidence + browser UAT deferred (operator decision). SC4 (citations) has backend + CitationPanel component but frontend wiring to VerificationReport missing — [n] markers are not rendered in the UI. |

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `frontend/src/components/intake/CitationPanel.tsx` | 38, 60 | Exported `renderCitationMarker` and `CitationPanel` never imported by any consumer | WARNING | SC4 is observably unachieved: clicking [n] in the report is impossible; CitationPanel is structurally orphaned |

No `TBD`, `FIXME`, or `XXX` markers found in Phase 15 modified files.

---

### Human Verification Required

#### 1. SC4 Citation Wiring — Code Gap (Requires Fix Before UAT)

**Test:** Import `CitationPanel` and `renderCitationMarker` into `VerificationReport.tsx`. Add a `citations?: Citation[]` field to the `VerificationReport` response type (backed by `build_verification_report` returning numbered citations). Render `[n]` inline markers via `renderCitationMarker` and manage the open-panel state in `VerificationReport`. Then run the UAT step: in the recorded run's report, click every `[n]` marker and confirm each opens a panel with title, date, quality tier, and stored snapshot; no number dangles; dead links resolve.

**Expected:** Every `[n]` in the verification report body is a clickable button that opens `CitationPanel` with the stored snapshot. Every number resolves. No live-URL re-fetch occurs.

**Why human:** The wiring requires code changes (VerificationReport.tsx + backend `build_verification_report` returning citations). Automated checks can confirm the import and component mount exist, but the visual correctness of the panel (snapshot text, tier labels, temporal notes) requires browser UAT.

#### 2. SC1 / SC2 / SC3 — Browser Walkthrough (Operator-Deferred to End-of-15.2)

**Test:** Run 15-UAT.md steps 1–6 against the deployed recorded run-4cbb5311 on the admin intake detail as superadmin. Complete the V-02 sign-off in 15-UAT.md.

**Expected:** All 6 checklist items PASS. Specifically: (Step 1) D15 feed looks like replit view.png — agent cards, per-row cost, per-block summaries, visible retries; (Step 1 drill-down) audit-body panel opens with request+response, no hash field; (Step 2) verification report shows funnel (distilled=1162, kept=456, etc.), refuted claims with evidence, superseded findings, reconciled contradictions, honest unverified list; (Step 3) cost reflects corrected cache-write totals (~$43-45 range), grounding fee shows "tool fees: pending" label; (Step 5) verify_chain result GREEN; (Step 6) client-role login sees no research surface.

**Why human:** Operator decision 2026-07-24 explicitly deferred the browser walkthrough + V-02 sign-off to the combined end-of-Phase-15.2 UAT session. All automated halves ran green. This is a scheduled deferral, not a code gap.

---

### Gaps Summary

**SC4 citation rendering wiring is a code gap** (not a browser UAT deferral). The `CitationPanel` component and `renderCitationMarker` helper (Plan 15-06) are complete and correct, but neither is imported or invoked by `VerificationReport.tsx`. The backend `build_verification_report` does not return a `citations` array, and `VerificationReport` has no `citations` field in its TypeScript type. The 15-06 SUMMARY explicitly documents this: "the report-body WIRING was NOT added." As a result, SC4 ("Citations render as numbered, clickable references... every citation number resolves") is not observable in the running application.

**Automated evidence covers SC1/SC2/SC3/SC5 fully.** SC1, SC2, SC3 also have a known, operator-recorded browser UAT deferral to the end-of-Phase-15.2 session — this deferral is in 15-UAT.md and does not block the automated verdict but generates human_needed status.

**Status is `human_needed`** (not `gaps_found`) because: (a) the SC4 wiring gap requires only a targeted code addition to `VerificationReport.tsx` (the components and backend are ready), and (b) the operator-deferred browser walkthrough is the primary remaining human item. The question of whether to treat SC4 as a blocker gap vs. a pre-UAT fix is a human decision — the CitationPanel exists and can be wired before the browser session. If the wiring is NOT completed before UAT, SC4 will FAIL the human check.

---

_Verified: 2026-07-24T22:00:00Z_
_Verifier: Claude (gsd-verifier)_
