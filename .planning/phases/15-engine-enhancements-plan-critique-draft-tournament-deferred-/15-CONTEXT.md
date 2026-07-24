# Phase 15: Research Engine Redesign (was: Engine Enhancements) - Context

**Gathered:** 2026-07-24
**Status:** Ready for planning

<domain>
## Phase Boundary

**Phase 15 IS the full research-engine redesign** decided by the operator on 2026-07-24 —
it replaces the original "plan-critique + draft tournament" scope. The redesign is fully
specified in two operator-agreed decision files (see canonical refs): the engine decisions
D1–D15, reliability decisions R1–R7, cost decision C1 (`.planning/RESEARCH-ENGINE-DECISIONS.md`)
and the verification-stage package + superadmin verification report
(`.planning/STAKEHOLDER-NOTES.md` §2026-07-24). Downstream agents treat those files as the
requirement source — they are written in plain language, one decision per bullet, all locked.

**Structure (operator decision):** split into THREE phases, executed in this order, all
before Phase 19:

1. **Phase 15 — Operator surfaces**: post-run verification report (superadmin-only),
   live agent-feed foundation (D15), cost-truth fixes (C1), numbered/clickable citations
   surface (D13). Built and UAT'd against the RECORDED run-4cbb5311 data + today's engine.
   Needs NO live LLM runs — can start immediately.
2. **Phase 15.1 — Verification gates**: materiality gate + error-likelihood gate +
   canonical grouping + corroboration prioritization + fail-loud + "superseded" verdict
   (STAKEHOLDER-NOTES package + D9/D11). Proven by replaying the recorded 1,162-claim
   fixture through the gates in tests.
3. **Phase 15.2 — Engine core**: question workshop with pairwise tournament (D2–D7),
   structured provider fact-lists + per-provider safety-net distiller (D8), SerpAPI-fueled
   own researcher stream (D10), cross-provider merge with LLM-based clustering (D9, see
   decisions below), language tagging (D7), reliability R1–R7, report changes (D13/D14).

**New execution order (operator, 2026-07-24 — SUPERSEDES the 2026-07-22 "engine work after
19" hold): 15 → 15.1 → 15.2 → 19 → 20.** Rationale: Phase 19's Q&A chat then indexes the
NEW engine's output from day one instead of a data model about to be replaced.

**Out of scope:** draft tournament (ENGINE-06 — DROPPED, see decisions), embedding
infrastructure (stays in Phase 19), cost-cap flip-on (stays Phase 20 per 16-CONTEXT D-02),
client-visible research surfaces (D-08 client isolation stands), Supabase/legacy paths.

**Hard constraints carried forward:**
- `verify_chain` stays green — frozen audit payload fields must not be renamed (legal gate,
  EU AI Act Art. 12; roadmap Phase 15 criterion 3 still applies to every sub-phase).
- No live LLM runs before 2026-08-01 (Anthropic monthly cap) — 15 and 15.1 are deliberately
  buildable without any; 15.2's live validation lands after reset.
- Tenant isolation: every new table/endpoint gets cross-tenant denial tests day one.
- Author-by-construction + Cloud Build for tests/images (no local Python/Docker).
- Phase 16 D-07 dynamic-stage-list contract: progress UI renders stages from the trace —
  new stages must appear without frontend code changes (the feed extends, not replaces, this).

</domain>

<decisions>
## Implementation Decisions

### Scope & old requirements
- **S-01:** Phase 15 officially becomes the full redesign. Roadmap: rename phase, rewrite
  goal + success criteria from the decision files; insert phases 15.1 and 15.2.
- **S-02:** ENGINE-05 (plan-critique) is ABSORBED by the question workshop (D2 — orientation
  + critique + pairwise tournament IS the plan-critique pass, evolved). Map the requirement
  accordingly, don't build a separate critique pass.
- **S-03:** ENGINE-06 (draft tournament) is DROPPED (operator, 2026-07-24). Single synthesis
  + operator shaping step stays (D14). Tournament exists at question level only. Remove the
  requirement; note in REQUIREMENTS.md changelog.

### Build order
- **B-01:** Surfaces first (Phase 15), gates second (15.1), engine core last (15.2).
- **B-02:** Three separate phases, each with own plans/verification/UAT — not one phase
  with waves.
- **B-03:** All of 15/15.1/15.2 before Phase 19; Phase 19 last before 20 (order confirmed
  explicitly; supersedes 2026-07-22 sequencing).

### 15.2 clustering mechanism (D9 merge)
- **B-04:** Same-fact claim clustering across providers is **LLM-based** — an LLM groups
  the structured fact lists directly ("group lines stating the same fact"). NO embedding
  machinery in 15.2 (operator chose simplicity; ~1,000 facts/run is within LLM-grouping
  scale). Phase 19 builds embeddings later for chat, unchanged.

### Validation & cutover (15.2)
- **V-01:** Validation = new engine runs live on a test intake and is compared against the
  RECORDED old-engine baseline (run 4cbb5311: report, verification audit, cost, duration —
  all in docs/tribunal-run-reports/). No side-by-side A/B double-run (operator chose the
  cheaper path; the comparison harness stays available but unused here).
- **V-02:** Acceptance = hard checklist derived from the decision files (workshop questions
  chosen & visible in feed; per-provider fact lists present; gate funnel numbers recorded;
  contradictory variants collide in one skeptic session; every citation number resolves;
  verify_chain green; cost fully itemized per C1 with nothing silently missing; feed
  complete with per-row cost) **PLUS operator sign-off** after reading the new report next
  to the recorded baseline. Both must pass.
- **V-03:** On acceptance the OLD engine path (adaptive_intake one-call → distiller-as-
  shredder → exact-key grouping → 953-group verification) is **removed immediately** — no
  fallback flag period (consistent with the project's big-bang cutover philosophy). The
  first live run also validates the deployed F-01 skeptic fix by construction.

### Failure & resume policy (resolves R4 open sub-decision + carries Phase 16 rules)
- **F-01:** Parked runs resume on **superadmin click only** — email + "Resume" button in
  the feed. No auto-resume (spend never restarts without a human; consistent with 16-D-03
  confirm-before-trigger).
- **F-02:** The 3-attempt rule (16-D-04) counts **full restarts only**. Checkpoint-resumes
  (parked → resumed, retry-from-failure continuing at checkpoint) are free and unlimited.
  After 3 full restarts: "needs investigation" state, as today.
- **F-03:** Park/failure notifications go to the triggering superadmin (16-D-10 unchanged),
  same short-body mail style + link (16-D-11); parked variant carries the Resume link.

### Claude's Discretion
- Feed/trace data model (extend `stage_detail` items vs new rows/tables) — under the
  verify_chain frozen-payload constraint and the D-07 dynamic-list contract.
- Which recorded data powers which surface in Phase 15 (audit blobs vs DB rows vs both);
  drill-down rendering approach (D12/D15).
- Exact checklist items for V-02 (derive from decision files during planning).
- Workshop internals: candidate counts, tournament pairing scheme, evolve step mechanics —
  within D2's plain-language description (30–50 candidates → 10–15 winners as the target
  shape, adjustable by evidence).
- Which test intake the 15.2 validation run uses (smoke space exists; smoke tenant
  1464b60d noted for cleanup — check it's suitable or create fresh).
- Retry/backoff parameters, breaker thresholds (R1/R2), checkpoint granularity (R3) —
  follow the best-practice sources cited in RESEARCH-ENGINE-DECISIONS.md Area 9.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### The requirement source (operator-agreed decision files — read FIRST)
- `.planning/RESEARCH-ENGINE-DECISIONS.md` — D1–D15 (engine + views, incl. the agreed feed
  mockup), R1–R7 (reliability), C1 (cost facts-only). Plain language, all locked.
- `.planning/STAKEHOLDER-NOTES.md` §"2026-07-24 — Verification redesign" — the verification
  gates package, selection-experiment numbers, and the superadmin verification-report
  requirement. Also §"2026-07-22 — OPERATOR HOLD" for the defect list the redesign answers.
- `replit view.png` (repo root) — the visual reference for the live feed (D15).

### Evidence base (the "why" + test fixtures)
- `docs/tribunal-run-reports/run-20260722-4cbb5311/REPORT.md` — full forensic audit of the
  baseline run (stage narrative, defects P0–P3, cost reality §4).
- `docs/tribunal-run-reports/run-20260722-4cbb5311/GROUPS.md` + `calls/` + `index.json` —
  per-call extracts; the raw material for Phase 15's surfaces UAT.
- `docs/tribunal-run-reports/run-20260722-4cbb5311/selection-experiment/` — the 1,162-claim
  fixture + blind classifications (`claims-distilled-full.tsv`, `claims-classified-full.tsv`,
  `keep-strict.tsv`, `kept-claims-EN.md`, `verification-audit-EN.md`) — 15.1's gate tests
  replay THESE and should reproduce the recorded keep/drop numbers.
- Raw audit blobs (permanent): `gs://project-cb01b861-cb4a-438d-b9a-nestor-audit/runs/9c84e5a9-1bb9-4b6e-a3ce-2351eda9df63/`

### Prior phase decisions that bind this phase
- `.planning/phases/16-research-trigger-progress-bridge/16-CONTEXT.md` — D-01/D-01b (no
  pause gates), D-02 (uncapped until Phase 20), D-04 (3-attempt rule, amended by F-02 here),
  D-07 (dynamic stage list — the contract the feed extends), D-08 (client sees nothing),
  D-09/D-10/D-11 (summary card, email rules).
- `.planning/ROADMAP.md` § Phase 15 + § Progress (execution order line — needs updating to
  15 → 15.1 → 15.2 → 19 → 20 per B-03).
- `.planning/REQUIREMENTS.md` — ENGINE-05 (absorbed per S-02), ENGINE-06 (dropped per S-03).

### Engine code this redesign touches (map from the 2026-07-24 exploration)
- `tribunal/nestor_pulse_sdk/pipeline/tribunal/pipeline.py` — the orchestration loop
  (intake → division → research → distill → group → verify → adjudicate → coverage →
  conflict → scrub → synthesize) the redesign restructures.
- `tribunal/nestor_pulse_sdk/pipeline/tribunal/intake.py` — `adaptive_intake` (the one-call
  step the question workshop replaces).
- `tribunal/nestor_pulse_sdk/pipeline/tribunal/group_skeptic.py` + `skeptic.py` — the
  hand-written audited tool-use loop; the TEMPLATE for workshop/researcher agents (15.2)
  and the stage 15.1's gates feed.
- `tribunal/nestor_pulse_sdk/pipeline/tribunal/research_division.py` — stakes-based provider
  delegation (D6 deliberate distribution lands here).
- `tribunal/nestor_pulse_sdk/citations/extractor.py` — 3-table claim/source model +
  `persist_tribunal_claims`; D13's citation numbering is GENERATED from these tables.
- `tribunal/nestor_pulse_sdk/pipeline/synthesis/steps.py` — synthesis + deterministic
  Sources section (D13/D14 land here); report_planner.py — report_spec shaping (kept).
- `tribunal/nestor_pulse_sdk/runs/stages.py` — ENGINE_STAGES + stage_detail JSONB merge
  (the feed's data backbone); `runs/worker.py` — claim/park/resume states (R3/R4).
- `tribunal/nestor_pulse_sdk/audit/` — AuditedLLMClient + cost_table (C1 fixes: cache-write
  counting, search fees, deep-research usageMetadata recording).
- `frontend/src/components/intake/ResearchRunProgress.tsx` — the panel the feed (D15)
  grows out of; keep SSE bridge + dynamic-stage contract.
- `backend/app/research/` — seam client + research_runs bridge (park state + resume
  endpoint land intake-side here).
- `infra/DEPLOY-RUNBOOK.md` — extend per sub-phase (new env: SERPAPI key for D10, etc.).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **Skeptic tool-use loop** (`group_skeptic.py`): audited, server-side web_search/web_fetch,
  client-tool termination, prompt caching — the ready-made template for workshop agents and
  the SerpAPI researcher (15.2 clones it, doesn't invent).
- **Audit records** (146MB for the baseline run alone): already contain per-call request/
  response/model/cost — the feed drill-down (D12) and verification report render THESE;
  Phase 15 is largely UI over existing data.
- **3-table citation model** (source/claim/claim_source + snapshot_text + content_hash):
  D13's clickable citations need no new storage — snapshots already survive dead links.
- **`stage_detail` JSONB + SSE bridge + dynamic stage rendering**: the feed foundation;
  extend with agent-level items (D-07 contract says UI absorbs new stages for free).
- **Comparison harness** (`run.comparison_id`): exists; NOT used for validation (V-01) but
  available if the baseline comparison proves insufficient.
- **Budget governor + advisory locks + worker claim/stale logic**: R1–R6 build on these,
  not from scratch.

### Established Patterns
- Hand-written async loops over agent SDKs (Tribunal convention — keep for new agents).
- Frozen audit payload + hash chain: any new stage/agent rows must ADD fields, never rename
  (verify_chain green is a phase success criterion).
- Plain-language operator decisions in .planning/*.md are the requirement source of truth
  for this phase — unusual but deliberate; planner derives acceptance criteria from them.
- Intake-side: sync `def` handlers on pg8000 except deliberate SSE `async def`.

### Integration Points
- Feed/verification report render on the admin intake detail page (ResearchRunProgress
  anchor + D-09 summary card → "View verification report").
- Park state: worker (tribunal side) ↔ research_runs bridge (intake side) ↔ email (Phase 10
  mail stack) ↔ Resume button → seam client call.
- Workshop consumes the context pack via the existing brief-assembly path (16-D-01 entry
  point); it must NOT alter client-validated questions (D4).

</code_context>

<specifics>
## Specific Ideas

- The Replit screenshot (`replit view.png`) is the explicit visual bar for the feed: agent
  cards appearing on spin-up, per-block "Worked for X · N actions · $Y" summaries,
  collapsible narration, visible retries. "It gives professionalism and confidence."
- The feed mockup embedded in RESEARCH-ENGINE-DECISIONS.md D15 was explicitly agreed with
  the operator — treat it as the wireframe.
- Google co-scientist's tournament (pairwise debates, Elo-style ranking) is the reference
  for the question workshop's ranking step — scaled down to 30–50 candidates.
- Cost display: "no estimation, only facts and correct calculations" (operator, verbatim) —
  pending-then-backfill-exact, never a guessed number (C1).
- Baseline for "did we actually improve": the LUKOIL BeNeLux dynamic-pricing run
  (4cbb5311) — same intake domain should be re-runnable for the V-01 validation.

</specifics>

<deferred>
## Deferred Ideas

- **Draft tournament (ENGINE-06)** — dropped this milestone; first candidate to revisit if
  report quality disappoints after the redesign ships (operator note from S-03 discussion).
- **Cross-provider corroboration as a further verification filter** — needs semantic
  matching; revisit after Phase 19's embeddings exist (recorded in STAKEHOLDER-NOTES).
- **Embedding-based clustering for the merge step** — B-04 chose LLM-based; embeddings
  remain a Phase 19+ upgrade path if LLM grouping proves weak.
- **Auto-resume with time window for parked runs** — F-01 chose click-only; revisit if
  parked runs pile up in practice.
- **Live A/B comparison runs (old vs new engine)** — V-01 chose baseline comparison; the
  comparison_id harness stays available if ever needed.

</deferred>

---

*Phase: 15-Research Engine Redesign*
*Context gathered: 2026-07-24*
