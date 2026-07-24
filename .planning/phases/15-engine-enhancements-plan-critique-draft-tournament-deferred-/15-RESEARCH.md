# Phase 15: Research Engine Redesign — Operator Surfaces - Research

**Researched:** 2026-07-24
**Domain:** Backend read-surfaces over recorded audit/DB data (FastAPI + Cloud SQL) + React admin UI (TanStack + SSE), cost accounting, citation rendering
**Confidence:** HIGH (this is a UI-over-existing-data phase; nearly every claim is grounded in inspected repo code or verified provider pricing docs)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Scope & old requirements**
- **S-01:** Phase 15 officially becomes the full redesign; this sub-phase is operator surfaces only.
- **S-02:** ENGINE-05 (plan-critique) ABSORBED by the 15.2 question workshop — do NOT build a separate critique pass here.
- **S-03:** ENGINE-06 (draft tournament) DROPPED.

**Build order**
- **B-01:** Surfaces first (Phase 15), gates second (15.1), engine core last (15.2).
- **B-02:** Three separate phases, each own plans/verification/UAT.
- **B-03:** All of 15/15.1/15.2 before Phase 19; order 15 → 15.1 → 15.2 → 19 → 20.

**Failure & resume policy** (these bind the FEED's error rendering, not new engine logic this sub-phase)
- **F-01:** Parked runs resume on superadmin click only — email + "Resume" button in the feed. No auto-resume.
- **F-02:** 3-attempt rule counts full restarts only; checkpoint-resumes free/unlimited.
- **F-03:** Park/failure notifications go to the triggering superadmin; parked variant carries the Resume link.

**Hard constraints carried forward (from `<domain>`)**
- `verify_chain` stays green — frozen audit payload fields must NOT be renamed (EU AI Act Art. 12 legal gate; roadmap Phase 15 criterion 5).
- No live LLM runs before 2026-08-01 (Anthropic monthly cap) — Phase 15 must be buildable + UAT-able entirely from recorded run-4cbb5311 data.
- Tenant isolation: every new table/endpoint gets cross-tenant denial tests day one.
- Author-by-construction + Cloud Build for tests/images (no local Python/Docker).
- Phase 16 D-07 dynamic-stage-list contract: progress UI renders stages from the trace — the feed EXTENDS, not replaces, this.
- 16-D-08 client isolation: client user sees NONE of the verification report / feed / drill-down. Superadmin-only.

### Claude's Discretion
- Feed/trace data model (extend `stage_detail` items vs new rows/tables) — under the verify_chain frozen-payload constraint and the D-07 dynamic-list contract.
- Which recorded data powers which surface (audit blobs vs DB rows vs both); drill-down rendering approach (D12/D15).
- Exact checklist items for V-02 (derive from decision files during planning).
- (15.2-only discretion areas: workshop internals, retry/backoff params — OUT OF SCOPE for Phase 15.)

### Deferred Ideas (OUT OF SCOPE)
- Draft tournament (ENGINE-06) — dropped this milestone.
- Cross-provider corroboration as a further verification filter — needs semantic matching; Phase 19+.
- Embedding-based clustering for the merge step — Phase 19+.
- Auto-resume with time window for parked runs — F-01 chose click-only.
- Live A/B comparison runs (old vs new engine) — V-01 chose baseline comparison.
- **Verification GATES (materiality/error-likelihood/canonical grouping/fail-loud/superseded verdict)** — that is Phase 15.1 (ENGINE-10), NOT this phase.
- **Engine CORE (question workshop, provider fact-lists, SerpAPI stream, merge, R1–R7 reliability implementation)** — Phase 15.2 (ENGINE-11).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ENGINE-09 | Post-run operator surfaces: (a) superadmin-only verification report, (b) live agent-feed foundation (D15 mockup), (c) facts-only itemized cost (C1 — no estimates, pending-then-backfill-exact), (d) numbered clickable citations (D13) — built and UAT'd against recorded run-4cbb5311 data, no live LLM runs | (a) Verdict data lives in audit blobs + partially in claim/claim_source; needs an extraction/persist path — see §Verification Report Surface. (b) Feed extends `stage_detail` JSONB + SSE bridge + `toStageRows` — see §Feed Data Model. (c) Exact cost defects located in `cost_table.compute()` (drops cache-creation), `gemini_deep_research_raw` (drops usageMetadata), and missing tool-fee accounting — see §Cost-Truth Fixes. (d) 3-table model + `GET /api/sources/{id}` renderer already exist; numbering is generated from claim/claim_source ordering — see §Citations. |

**Requirement source of truth (plain-language operator decisions — READ before planning):**
`.planning/RESEARCH-ENGINE-DECISIONS.md` (D1–D15/R1–R7/C1) + `.planning/STAKEHOLDER-NOTES.md` §2026-07-24. The planner derives V-02 acceptance criteria from these, not from a REQUIREMENTS.md one-liner.
</phase_requirements>

---

## Summary

Phase 15 is **almost entirely UI + read-endpoints over data that already exists** — the CONTEXT.md `<code_context>` "Phase 15 is largely UI over existing data" is confirmed by code inspection. The four surfaces map onto existing infrastructure as follows:

1. **Verification report** — the source data (skeptic verdicts: support/refute/insufficient, reconciliation notes, canonical values) is produced by `group_skeptic._parse_group_verdict()` and written to per-call audit blobs in GCS, but is **NOT persisted as structured DB rows today**. The hand-built `docs/tribunal-run-reports/run-20260722-4cbb5311/` + `selection-experiment/verification-audit-EN.md` is the template to productize. The single biggest structural decision for this phase: **verdicts must be persisted to a queryable table** (extracted from the recorded audit blobs for UAT) so the report can be rendered without re-parsing 146MB of GCS blobs per view.
2. **Live agent-feed (D15)** — extends the existing `run.stage_detail` JSONB + SSE bridge + the frontend `toStageRows()` dynamic renderer (`ResearchRunProgress.tsx`). The D-07 contract already renders any stage/item the trace reports without frontend code changes. Phase 15 enriches each `items[]` entry with per-row cost + task-prompt + status, and grows the flat stage list into the Replit-style feed (agent cards, per-block summaries, drill-down).
3. **Cost-truth (C1)** — three precise defects located in code (see below). Because `run.cost_usd_total = SUM(audit_log.cost_usd)`, fixing per-call cost automatically fixes the run total. **All three fixes ADD data, never rename a hashed field** — the frozen audit payload (`_payload_for_row`) is untouched, so `verify_chain` stays green.
4. **Citations (D13)** — the 3-table model (source/claim/claim_source + snapshot_text + content_hash) and the `GET /api/sources/{id}` snapshot renderer already exist. Numbering is *generated* from claim ordering (never from the writing model). Phase 15 adds numbered `[n]` markers bound to `claim_source` ordering + a citation side-panel on the intake side.

**Primary recommendation:** Treat Phase 15 as **(A) one tribunal-side migration** adding a `cache_creation_tokens` column + a persisted verdict/verification-summary table + a per-run cost-pending flag; **(B) cost-accounting fixes** in `cost_table.py` / `audited_llm_client.py`; **(C) new tribunal read endpoints** (`/verification`, enriched `/metrics` feed, citation numbering) fronted by **(D) new intake-side seam methods + read routes** (superadmin-scoped, RLS-denial-tested); and **(E) React surfaces** anchored on the admin intake detail page. Build a recorded-run **fixture** from run-4cbb5311's audit blobs so every surface is provable in Cloud Build without a live LLM run.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Verification-verdict persistence | Tribunal (Cloud SQL `tribunal` schema) | — | Verdicts are engine artifacts; belong beside claim/source in the tribunal schema, RLS-scoped |
| Verification report rendering (data shaping) | Tribunal API (read endpoint) | Intake backend (seam pass-through) | Report is computed from tribunal tables; intake is the sole HTTP seam (SEAM-01) |
| Cost accounting (per-call + rollup) | Tribunal (`audit/`, `cost_table.py`, worker rollup) | — | Cost is derived from provider usage at call time; lives entirely in the audited client |
| Cost "pending/final" state | Tribunal (`run` row) | Intake (mirror for display) | Deep-research Gemini tool fees are not live-itemized → the run carries a pending flag |
| Feed trace enrichment | Tribunal (`stage_detail` JSONB, `set_stage`) | Intake (`get_metrics` mirror) | The trace is written by the pipeline; the D-07 contract already mirrors it to the UI |
| Feed rendering (agent cards, drill-down) | Frontend (admin route) | Intake seam (drill-down blob fetch) | Superadmin-only React over the mirrored trace + audit-blob drill-down |
| Citation numbering (generation) | Tribunal (claim/claim_source ordering) | Synthesis (marker injection) | D13: numbering GENERATED from the DB, never the writing model |
| Citation side-panel (snapshot) | Frontend | Intake seam → tribunal `GET /api/sources/{id}` | Renderer already exists tribunal-side; needs an intake-side proxy route |
| Superadmin-only gating | Intake backend (role check) + Frontend (route placement) | — | 16-D-08: client sees nothing; enforced server-side + by component placement |

---

## Standard Stack

This phase adds **no new external libraries**. It reuses the stack already in the repo. Verify no accidental new deps creep in.

### Core (already present — versions from repo)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| FastAPI | (repo pinned) | Tribunal + intake read endpoints | Existing seam + tribunal API framework [VERIFIED: repo `runs/api.py`, `audit/api.py`] |
| SQLAlchemy 2.x (async, tribunal) / pg8000 (sync, intake) | (repo pinned) | Tribunal async models; intake sync pg8000 handlers | Established split: tribunal async, intake sync-def on pg8000 threadpool [VERIFIED: repo `audited_llm_client.py`, `tribunal_client.py` docstring] |
| Alembic (tribunal's own line) | (repo pinned) | `cache_creation_tokens` column + verdict table migration | Tribunal keeps its own `alembic_version` (two-schema topology, STATE.md) [VERIFIED: repo two-schema decision] |
| React 19.2 + TanStack Router/Query | 19.2 / 1.168 / 5.83 | Admin surfaces | Existing frontend [VERIFIED: CLAUDE.md] |
| SSE (existing bridge) | — | Feed live updates | `openResearchStream` already mirrors `stage_detail` per tick [VERIFIED: repo `ResearchRunProgress.tsx`] |
| react-markdown 10.1 + remark-gfm + rehype-raw | 10.1 | Verification report + report body rendering | Already used in admin panels [CITED: CLAUDE.md] |

### Supporting (already present)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| lucide-react | 0.575 | Feed status icons (spinner/check/retry/warning) | Feed agent-card status rendering [VERIFIED: repo — already imported in `ResearchRunProgress.tsx`] |
| sonner | 2.0 | Toast on drill-down/resume errors | Return-no-throw error surfacing (CLAUDE.md) [VERIFIED: repo] |
| date-fns (nl locale) | 4.1 | Feed timestamps | Existing Dutch-locale formatting [VERIFIED: repo] |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Persisting verdicts to a new table | Re-parse audit GCS blobs on every report view | Rejected: 146MB/run of blobs, no queryable structure, slow, and couples the UI to blob layout. A persisted `verification_verdict` table (or a `run.verification_summary` JSONB) is the clean read model. |
| Enriching `stage_detail` JSONB items | New `agent_activity` table | JSONB extension is D-07-native (the UI already renders it free); a new table adds RLS surface + migration + join. Recommend JSONB for the feed backbone; reserve a table only if per-row cost history must be queried independently. |
| Numbered citations generated in the DB | Let synthesis model emit `[n]` | D13 explicitly forbids the writing-model path (it produced last run's 28 stripped markers). Numbering MUST be generated from claim/claim_source ordering. |

**Installation:** No `pip install` / `npm install` for new external packages. If the planner finds a genuinely new dependency is needed, it must run the Package Legitimacy Gate at that time.

---

## Package Legitimacy Audit

> Not required this phase — **no external packages are installed**. Every dependency is already in the repo (FastAPI, SQLAlchemy, Alembic, React/TanStack, lucide-react, sonner, date-fns, react-markdown). slopcheck was therefore not run.

If the planner introduces any new package (e.g. a charting lib for a cost breakdown), it MUST run the Package Legitimacy Gate (slopcheck + `npm view`/`pip index versions`) and gate the install behind a `checkpoint:human-verify` task.

---

## Architecture Patterns

### System Architecture Diagram

```
                        RECORDED run-4cbb5311 (no live LLM — Anthropic cap until 2026-08-01)
                        ┌─────────────────────────────────────────────────────────┐
                        │  GCS audit blobs                DB (tribunal schema)      │
                        │  gs://…-nestor-audit/runs/      run · audit_log ·         │
                        │  9c84e5a9…/  (228 per-call      claim · source ·          │
                        │  {request,response,verdict})    claim_source              │
                        └───────────────┬─────────────────────────┬────────────────┘
                                        │ (one-time extract        │
                                        │  → fixture + persist)    │
                                        ▼                          ▼
   ┌──────────────────────────────────────────────────────────────────────────────┐
   │ TRIBUNAL SIDE (Cloud Run, async SQLAlchemy, RLS by tenant_id)                  │
   │                                                                                │
   │  COST FIXES (C1)          VERIFICATION MODEL         CITATION NUMBERING (D13)  │
   │  cost_table.compute()     verification_verdict       claim/claim_source        │
   │   +cache_creation         table (or run JSONB)        ordered → [n] index      │
   │  gemini_deep_research_raw derived from verdicts +                              │
   │   record usageMetadata    gate funnel counts                                   │
   │  tool-fee accounting                                                           │
   │  run.cost_pending flag                                                         │
   │       │                        │                            │                  │
   │       ▼                        ▼                            ▼                  │
   │  GET /runs/{id}/metrics   GET /runs/{id}/verification   GET /api/sources/{id}  │
   │  (enriched stage_detail   (superadmin funnel + verdicts (snapshot renderer —    │
   │   + per-row cost)          + unverified list + cost)     already exists)        │
   └───────────────┬───────────────────┬─────────────────────────┬─────────────────┘
                   │ OIDC seam (SEAM-01: intake is the ONLY caller)                 │
                   ▼                    ▼                         ▼
   ┌──────────────────────────────────────────────────────────────────────────────┐
   │ INTAKE BACKEND (Cloud Run, sync pg8000, superadmin role-gate + space-scope)   │
   │  tribunal_client.get_metrics()   +get_verification()    +get_source()          │
   │  routes: /research/{intake}/…    (superadmin-only; RLS/denial-tested day one)  │
   └───────────────────────────────────────┬──────────────────────────────────────┘
                                            │ apiFetch (token-attaching transport)
                                            ▼
   ┌──────────────────────────────────────────────────────────────────────────────┐
   │ FRONTEND (admin.pulse.intakes.$id.tsx — SUPERADMIN-ONLY placement, D-08)      │
   │  ResearchRunProgress  →  D15 activity FEED (agent cards · per-block summary ·  │
   │                          retries visible · drill-down to audit blob)          │
   │  D-09 summary card  →  "View verification report"  →  funnel + verdicts panel  │
   │  report body  →  numbered [n] citations  →  side-panel (snapshot_text)         │
   └──────────────────────────────────────────────────────────────────────────────┘
```

### Recommended Project Structure (files this phase touches / adds)
```
tribunal/nestor_pulse_sdk/
├── audit/
│   ├── cost_table.py            # FIX: add cache_creation_tokens to compute()
│   ├── audited_llm_client.py    # FIX: record cache_creation + DR usageMetadata + tool counts
│   ├── cost_prices.json         # add web_search/web_fetch per-call fee entries (facts)
│   └── writer.py                # extend write_full_row/schema for new cost columns
├── db/models/
│   ├── audit_log.py             # ADD column cache_creation_tokens (NOT in hashed payload)
│   ├── run.py                   # ADD cost_pending flag + optional verification_summary JSONB
│   └── verification_verdict.py  # NEW (option A): persisted per-claim verdict read model
├── migrations/versions/         # tribunal Alembic line: new columns + verdict table
├── verification/                # NEW: build_verification_report() shaping from verdicts+funnel
├── runs/api.py                  # enriched /metrics feed + NEW /verification endpoint
└── tests/
    ├── fixtures/run_4cbb5311/   # NEW: recorded-run fixture (extracted from audit blobs)
    ├── test_cost_cache_write.py # NEW: cache-write + tool-fee + DR-usage cost tests
    ├── test_verification_report_endpoint.py  # NEW + RLS denial
    └── test_citation_numbering.py            # NEW

backend/app/research/
├── tribunal_client.py           # ADD get_verification() + get_source() seam methods
└── (routes)                     # ADD superadmin-only read routes + denial-suite entries

frontend/src/
├── components/intake/
│   ├── ResearchRunProgress.tsx  # grow into D15 feed (agent cards, summaries, retries)
│   ├── VerificationReport.tsx   # NEW: funnel + verdicts + unverified list (superadmin)
│   └── CitationPanel.tsx        # NEW: [n] side-panel over snapshot_text
├── lib/api/research.ts          # ADD getVerification(), citation types
└── locales/{en,fr,nl}/intake.json  # i18n keys for all new strings (i18n-audit gate)
```

### Pattern 1: ADD-only audit fields under the frozen hash chain
**What:** The hash chain payload (`hash_chain._payload_for_row`) is FROZEN — it hashes exactly `{provider, model, started_at, duration_ms, prompt_tokens, completion_tokens, cached_tokens, gcs_uri, seq, tenant_id, run_id}`. New cost data (`cache_creation_tokens`, tool-fee counts, recomputed `cost_usd`) must go in columns that are **NOT** in this set.
**When to use:** Every cost fix + every new verification field.
**Example:**
```python
# hash_chain.py:_payload_for_row — DO NOT ADD cache_creation_tokens here.
# audit_log gets a NEW cache_creation_tokens column used ONLY for cost recompute.
# cost_usd is ALSO not hashed (already nullable, recomputed freely) — see _payload_for_row.
# Result: verify_chain recomputes identical hashes → stays green (Phase 15 criterion 5).
```
[VERIFIED: repo `hash_chain.py:139-161` — `cost_usd` and any new cost column are outside the hashed set]

### Pattern 2: Cost total is a derived SUM — fix the parts, the total follows
**What:** `run.cost_usd_total = COALESCE((SELECT SUM(cost_usd) FROM audit_log WHERE run_id = :id), 0)` (worker + budget governor). Fixing per-call `cost_usd` fixes the run total with no separate rollup change.
**When to use:** All C1 token-class fixes.
[VERIFIED: repo `runs/worker.py:149-197`, `budget.py:102-138`]

### Pattern 3: D-07 dynamic-list feed — enrich `items[]`, render for free
**What:** `set_stage(run_id, tenant_id, stage_key, {"items":[{"name","status", ...}]})` merges per-stage detail into `run.stage_detail`. The frontend `toStageRows()` flattens `{stage_key:{items:[…]}}` into rows with zero hardcoded stage count. Adding fields to each item (cost, task_prompt, retries) renders without frontend structural change (the D15 feed is a richer renderer over the SAME data shape).
**When to use:** Feed agent-card enrichment.
[VERIFIED: repo `runs/stages.py:72-121`, `ResearchRunProgress.tsx:43-62`]

### Pattern 4: Existence-hidden, superadmin-scoped read seam
**What:** Intake read routes for research surfaces must (a) require superadmin, (b) be space-scoped, (c) existence-hide cross-tenant/missing as an empty/404 result — never a distinguishable 403. Mirror `sources.ts`/`contextPack.ts` client shape; mirror tribunal `GET /api/sources/{id}` 404-on-RLS-miss.
[VERIFIED: repo `renderer.py:33-40` (404 on RLS miss), `sources.ts:6-11` (existence-hidden)]

### Anti-Patterns to Avoid
- **Re-parsing GCS audit blobs on every verification-report view.** 146MB/run, unstructured. Persist a read model once.
- **Adding a field to the hashed payload.** Breaks every existing chain → `verify_chain` red → Phase 15 fails criterion 5 + violates Art. 12 gate.
- **Letting the synthesis model number citations.** D13 forbids it (28-stripped-marker failure). Generate `[n]` from claim/claim_source ordering.
- **Estimating any cost.** C1 is verbatim "no estimation, only facts". Unknown/not-yet-billed = "pending", never a placeholder number.
- **Importing the verification/feed components into any client route.** 16-D-08: superadmin-only by placement (like `ResearchRunProgress` today).
- **Removing the `google/deep-research-*` ESTIMATE prices silently.** `cost_prices.json` line 84 flags them as estimates copied from gemini-2.5-pro — under C1 these must become real recorded usage × published price, or the row shows "pending", never the estimate.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Live stage/feed transport | New websocket/polling channel | Existing SSE bridge (`openResearchStream`) + `stage_detail` mirror | D-07 contract already does this; the feed is a richer renderer, not new transport |
| Citation snapshot storage/serving | New snapshot store | 3-table model + `GET /api/sources/{id}` (`renderer.py`) | Snapshots + content_hash dedupe already exist; survive dead links |
| Cost token extraction | New usage parser | `AuditedLLMClient` already extracts `cache_creation_input_tokens` (line 309) — it's dropped downstream, not un-extracted | The extraction exists; only the cost formula + persistence drop it |
| Run cost rollup | New aggregation job | `SUM(audit_log.cost_usd)` in worker/budget | Already computed; fixing parts fixes the total |
| Cache-write pricing table | New price constants | `cost_prices.json` `cache_creation_5m` values (already present, currently unused by `compute()`) | Prices already there and match verified provider docs (1.25× base) |
| Verdict parsing | New skeptic-output parser | `group_skeptic._parse_group_verdict()` already yields `{verdict, confidence, evidence_refs, reconciliation:{disputed,relation,note,canonical}}` | Parse shape exists; it just isn't persisted/queried |

**Key insight:** This phase's engineering is *plumbing existing-but-dropped data through to a read model and a UI*, not building new engine capability. The two genuinely-new artifacts are (1) a persisted verification read model and (2) the recorded-run test fixture.

---

## Cost-Truth Fixes (C1) — exact defect locations

All prices below verified against 2026 provider docs (see Sources). `cost_prices.json` `cache_creation_5m` values already match.

| # | Defect | Location | Fix | Cost impact (run 4cbb5311) |
|---|--------|----------|-----|----------------------------|
| C1-a | `compute()` ignores cache-CREATE tokens entirely — formula has only prompt/cache-read/completion | `audit/cost_table.py:77-126` (signature has no `cache_creation_tokens` param) | Add `cache_creation_tokens` param; charge at `cache_creation_5m` rate (already in JSON). Thread the already-extracted `cache_creation_input_tokens` (audited_llm_client.py:309) into `compute()` + persist to a NEW `audit_log.cache_creation_tokens` column | 8.7M tokens × $3.75/M ≈ **$33 uncounted** [VERIFIED: REPORT.md §6 + finout.io pricing] |
| C1-b | Anthropic web_search/web_fetch tool fees never priced | `cost_table.py` (no tool-fee path) + `audited_llm_client.py` (tool counts not recorded) | Record per-call `web_search`/`web_fetch` counts (server-tool result blocks) into audit; add fee = searches × $0.01 (web_search) to the run cost | 516 searches + 216 fetches — web_search ≈ **$5.16** at $10/1000 [VERIFIED: finout.io — $10/1000 searches] |
| C1-c | Gemini deep-research `usageMetadata` dropped — DR envelope is `{status, report}` only | `audited_llm_client.py:754-839` (`gemini_deep_research_raw`) + `extract_report_from_steps` | Read `interaction.usageMetadata` (promptTokenCount, candidatesTokenCount, **thoughtsTokenCount** billed at output rate); record tokens into the DR audit row so `compute()` prices it | 6 DR calls (3 Google + 3 Claude-redundancy) — **the single most expensive stage, currently $0 in the panel** [VERIFIED: REPORT.md §6 "Not recorded" + cloudzero.com thinking-token docs] |
| C1-d | Deep-research prices are flagged ESTIMATES in the price file | `cost_prices.json:84-102` | Under C1 "facts only": once C1-c records real usage, price it at published rates; the estimate comment must be resolved (real price or the ESTIMATE removed and the row marked pending) | — |
| C1-e | No "pending vs final" state — Gemini search/grounding tool fees are not itemized live by Google | `run` model (add `cost_pending` bool / `cost_finalized_at`) | Feed row shows "tool fees: pending"; a run's cost is "final" only when nothing is pending; exact amount backfilled from GCP billing (`is_deep_research` label). NO placeholder number ever | C1 verbatim: "pending-then-backfill-exact, never an estimate" |

**Frozen-payload safety:** none of the hashed fields change. `cost_usd` is already outside `_payload_for_row`; `cache_creation_tokens` is a NEW non-hashed column; tool counts + pending flag are new columns. `verify_chain` stays green. [VERIFIED: repo `hash_chain.py:149-161`]

**Reconciliation (C1):** recorded totals checked against provider invoices (Anthropic console, GCP billing per `is_deep_research`). Any mismatch is a bug to investigate, not a rate to tune. This phase makes the numbers *countable and honest*; the live invoice reconciliation lands with the first post-cap live run (15.2+).

---

## Verification Report Surface — data-source map

**The critical structural finding:** skeptic verdicts are **produced but not persisted as queryable rows**. `_parse_group_verdict` returns per-claim `{verdict ∈ support|refute|insufficient, confidence, evidence_refs, citations, reconciliation:{disputed,relation,note,canonical}}`, but the only durable copies are (a) inside the per-call audit blob's `emit_group_verdict` tool_use in GCS, and (b) transiently in adjudication. `claim`/`claim_source` persist the *claims and their sources*, not the *verdicts*.

| Report element (from STAKEHOLDER-NOTES §2026-07-24 requirement) | Recorded data source | Action for Phase 15 |
|---|---|---|
| Verification funnel (distilled / selected / sessions / verdicts / skipped+why / failed-loud) | `docs/…/selection-experiment/*.tsv` (1,162 distilled → gate counts) + `index.json` call counts | Persist funnel counts on the run (JSONB) at pipeline end; for UAT, seed from the recorded fixture |
| Per-claim verdicts (support/refute/insufficient) + skeptic evidence | Audit blobs `emit_group_verdict` tool_use; `verification-audit-EN.md` reconstruction | **Persist a `verification_verdict` read model** (extract from blobs for the recorded run) — do NOT re-parse blobs per view |
| Superseded / scoped findings + temporal caveats | `reconciliation.note` / `reconciliation.canonical` (e.g. KPAnG "superseded since 1 April 2026") | Carry `reconciliation` into the persisted verdict; render inline caveats |
| Reconciled contradictions + chosen canonical value | `reconciliation.disputed` + `.canonical` | Same persisted verdict model |
| Honest list of claims that shipped UNVERIFIED | claims with no usable verdict (F-01 crash / cap 400 / low-stakes wave-through) | Requires distinguishing *why* unverified — REPORT.md §4.3 flags the current appendix cannot; Phase 15 surfaces the count honestly from persisted verdict-presence |
| True cost (fix P1 undercount) | C1 fixes above | Show itemized cost per class + pending state |

**Anchor:** admin intake detail page, D-09 summary card → "View verification report" link. Superadmin-only (16-D-08). [VERIFIED: repo `ResearchRunProgress.tsx` summary card at line 311+, mounted only in `admin.pulse.intakes.$id.tsx:1172`]

**Note on `verify_chain` distinction:** the "verification report" (skeptic funnel/verdicts) is DIFFERENT from `verify_chain` (audit hash-chain integrity, Phase 17). Do not conflate. Phase 15's report is the skeptic/gate story; `verify_chain` green is a *constraint* on Phase 15's DB changes, not the subject of the report.

---

## Feed Data Model — extend `stage_detail` (recommended)

**Recommendation:** Extend the `stage_detail` JSONB `items[]` shape for the D15 feed; reserve a new table only if per-agent cost history must be queried independently of the run (not required for Phase 15 surfaces).

**Current shape** (`{stage_key: {items: [{name, status}]}}`) → **D15-enriched shape**:
```jsonc
{
  "deep_research": {
    "items": [
      {
        "name": "Gemini — German 12:00 pricing rule",   // agent card title (D15)
        "status": "running|done|retry|failed|pending",  // maps to feed icons
        "task_prompt": "Research the German 12:00 …",    // expandable (Replit subagent block)
        "cost_usd": "0.42",                              // per-row live cost (C1)
        "facts": 14,                                      // "done · 14 facts · $0.12"
        "retry": {"attempt": 2, "max": 3, "wait_s": 8},  // "retry 2/3 — waiting 8s" (R5 visible)
        "audit_id": "…"                                   // drill-down key → audit blob
      }
    ],
    "summary": {"duration_s": 370, "actions": 31, "items_read": 214, "cost_usd": "2.84"}  // per-block card
  }
}
```
- **Why JSONB:** the D-07 contract (`toStageRows`) already renders any `items[]` the trace reports — new fields cost the base UI nothing; the D15 feed is a *richer renderer* over the same data. Adding fields to a JSONB item requires no migration and no chain impact (`stage_detail` is not hashed). [VERIFIED: repo `run.py:90` (stage_detail not in hashed payload), `ResearchRunProgress.tsx:53-59`]
- **Drill-down (D12):** `audit_id` per item → intake seam → tribunal audit-body fetch (blob already written per call). A new superadmin-only read route serves the recorded blob; RLS/denial-tested.
- **Frozen feed after run (D15):** `stage_detail` already survives to completed runs (merge, not overwrite — `set_stage` docstring). The feed "stays, frozen and clickable" for free.
- **Phase-15 scope caveat:** the ENGINE agents that *emit* these enriched items (workshop/researcher/skeptic per-row) are Phase 15.2. Phase 15 builds the **renderer + the enriched schema + drill-down**, proven against the RECORDED run's stage_detail (reconstruct enriched items into the fixture). Do NOT implement the emitting engine logic here.

---

## Citations (D13) — numbering generated from the DB

- **Model already exists:** `source(url, snapshot_text, content_hash)` + `claim(text, facet, position, run_id)` + `claim_source(claim_id, source_id, snippet)`. Snapshots survive dead links; content_hash dedupes per tenant. [VERIFIED: repo `extractor.py`, `db/models/source.py|claim.py|claim_source.py`]
- **Renderer already exists:** `GET /api/sources/{id}` returns `{id,url,title,provider,fetched_at,snapshot_text}`, 404 on RLS miss. [VERIFIED: repo `renderer.py`]
- **What Phase 15 adds:**
  1. **Numbering generation** — assign `[n]` from a deterministic ordering of claim/claim_source (e.g. `claim.position` / first-appearance order), NOT from the writing model (D13 hard requirement). Surface title, link, publication date, quality tier (1 official / 2 serious press / 3 blog). Single-source claims marked as such.
  2. **Intake-side seam** — the tribunal `GET /api/sources/{id}` is not yet reachable from intake; add a superadmin-scoped intake proxy route + `tribunal_client.get_source()` (mirrors `get_report` shape) + a `research.ts` client fn. (Note: the existing `frontend/src/lib/api/sources.ts` is INTAKE-UPLOAD sources — different concern; do not overload it.)
  3. **Frontend `CitationPanel.tsx`** — clicking `[n]` opens the side panel rendering `snapshot_text` directly (never re-fetch the live URL — renderer.py contract).
- **Quality tier / publication date:** `source` today has `url, title, provider, fetched_at, snapshot_text` — **quality tier and publication date are NOT stored columns**. Phase 15 must either derive tier from provider/domain heuristics or ADD columns. This is an OPEN QUESTION (see below) — confirm with operator whether tier is derived or a new stored field. [VERIFIED: repo `renderer.py:41-48` — no tier/pubdate field]

---

## Common Pitfalls

### Pitfall 1: Adding a cost field to the hashed audit payload
**What goes wrong:** Add `cache_creation_tokens` to `_payload_for_row` → every existing audit row's recomputed hash changes → `verify_chain` returns `(False, 0)` → Art. 12 legal gate red, Phase 15 criterion 5 fails.
**Why it happens:** Natural instinct to "add the field everywhere."
**How to avoid:** New cost columns live OUTSIDE `_payload_for_row`. Add a `test_hash_chain_replay`-style test asserting the recorded fixture still verifies green AFTER the migration + cost fix.
**Warning signs:** `alembic check` shows the column landed; run `verify_chain` on the fixture before/after.

### Pitfall 2: Two-schema Alembic collision
**What goes wrong:** Writing the verdict-table/column migration in the intake `nestor` Alembic line instead of tribunal's own line → revision-ID collision or wrong schema.
**Why it happens:** Two separate `alembic_version` tables (STATE.md two-schema topology).
**How to avoid:** All new tribunal columns/tables go in `tribunal/`'s Alembic line. Intake side gets NO new tables this phase (it only proxies reads).
**Warning signs:** migration references `nestor.` schema for a research artifact.

### Pitfall 3: Estimating a cost the operator forbade
**What goes wrong:** Showing the deep-research ESTIMATE price (cost_prices.json:84) as if it were real → violates C1 "facts only".
**How to avoid:** Until real Gemini DR usage is recorded (C1-c), the DR cost row is "pending", not the estimate. Once recorded, price at published rate. No placeholder numbers anywhere.
**Warning signs:** any `~` or rounded guess in a displayed cost.

### Pitfall 4: Leaking the verification report / feed to the client role
**What goes wrong:** Mounting `VerificationReport`/feed on a shared component or a client-reachable route → 16-D-08 violation (client sees research internals before delivery).
**How to avoid:** Superadmin server-side role check on every new intake read route + component placement ONLY under `admin.pulse.*`. Add a cross-role denial test (client token → 404/empty).
**Warning signs:** a new component imported outside `admin.*` route tree.

### Pitfall 5: Cross-tenant leak on new read endpoints
**What goes wrong:** A new `/verification` or drill-down endpoint that doesn't set tenant context → returns another space's verdicts.
**How to avoid:** Every new tribunal read endpoint sets `set_tenant_context`; every intake proxy is space-scoped; both join the CI-gated denial suite (`test_seam_denial.py`, `test_rls_isolation.py` patterns) DAY ONE.
**Warning signs:** endpoint without an accompanying `test_*_denial` case.

### Pitfall 6: Reconstructing the fixture wrong (mtime vs seq)
**What goes wrong:** Ordering the recorded run by `seq` — but `seq=0` on all 228 blobs of run-4cbb5311 (audit defect §4.7). Ordering breaks.
**How to avoid:** Order the fixture by GCS object mtime (REPORT.md "Ordering caveat"). Note: this seq=0 defect is a real-run artifact; NEW runs post-fix will have proper seq — but the Phase 15 fixture is the OLD run, so honor mtime.
**Warning signs:** fixture claims/verdicts out of narrative order.

---

## Code Examples

### C1-a: thread cache-creation into the cost formula (tribunal)
```python
# audit/cost_table.py — add param + charge cache-creation at the 5m rate (already in JSON)
def compute(provider, model, prompt_tokens, completion_tokens,
            cached_tokens, cache_creation_tokens: int = 0) -> Optional[Decimal]:
    ...
    cache_create_per_token = Decimal(str(entry["cache_creation_5m"])) / Decimal("1000000")
    cache_create_cost = Decimal(str(cache_creation_tokens)) * cache_create_per_token
    return prompt_cost + cache_cost + cache_create_cost + completion_cost
# audited_llm_client.py already extracts cache_creation_input_tokens (line 309) —
# pass it into compute() AND persist it to the new (non-hashed) audit column.
```
[Source: repo `cost_table.py:112-126` + `audited_llm_client.py:309` + verified 1.25× cache-write rate]

### C1-c: capture Gemini deep-research usage (tribunal)
```python
# audited_llm_client.py gemini_deep_research_raw — the interaction JSON carries usageMetadata
if status in ("completed", "done"):
    report_text = extract_report_from_steps(interaction)
    usage = interaction.get("usageMetadata", {})   # promptTokenCount, candidatesTokenCount, thoughtsTokenCount
    return {"status": "success", "report": report_text, "usage": usage}
# then record usage into the DR audit row so compute() prices it (thoughts bill at output rate).
```
[Source: repo `audited_llm_client.py:819-822` (usage currently dropped) + verified thinking-token billing]

### D-07 feed: enriched item already renders (frontend)
```tsx
// ResearchRunProgress.tsx toStageRows already maps items[]; D15 adds a richer card renderer
// over the SAME shape. New fields (cost_usd, task_prompt, retry) need no structural change to
// the flatten — only a new AgentCard component reading them.
for (const [idx, item] of items.entries()) {
  rows.push({ key: `${stageKey}:${idx}`, name: item.name, status: item.status /*, cost, retry… */ });
}
```
[Source: repo `ResearchRunProgress.tsx:53-59`]

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Cost panel shows 3 token classes (no cache-write) | Count all 4 Anthropic classes + tool fees + DR usage | Phase 15 (C1) | Panel ~€5 → ~$43–45 real; honest numbers |
| Verdicts live only in audit blobs | Persisted verification read model | Phase 15 | Verification report renderable without blob re-parse |
| Flat stage checklist | Replit-style activity feed (D15) | Phase 15 | Agent-level visibility, per-row cost, visible retries |
| Citations = model-emitted markers (28 stripped last run) | Numbered `[n]` generated from claim/source DB | Phase 15 (D13) | Every citation number resolves |

**Deprecated/outdated (do NOT touch as part of Phase 15):**
- The old engine path (adaptive_intake → distiller-as-shredder → exact-key grouping) — removed in 15.2 (V-03), not here.
- F-01 skeptic crash — already fixed in current `group_skeptic.py` (`_coerce_json` guard present); do not "re-fix" it.

---

## Runtime State Inventory

> This phase is additive (new columns/table/endpoints/UI over a RECORDED run). It is not a rename/migration of live state, but the recorded-data dependency warrants an explicit inventory.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | Recorded run lives in DB (`run`/`audit_log`/`claim`/`source`/`claim_source` for tribunal run `9c84e5a9…`) **and** GCS audit blobs (`gs://project-cb01b861-cb4a-438d-b9a-nestor-audit/runs/9c84e5a9…/`, 146MB, permanent). Verdicts are ONLY in the GCS blobs, not in queryable rows. | One-time extract of verdicts from blobs → persisted read model + test fixture. Confirm the recorded DB rows still exist in the live tribunal DB (or rebuild from `index.json`/`calls/`). |
| Live service config | None new. Feed/verification are read surfaces; no new external service. | None. |
| OS-registered state | None. | None — verified: no scheduler/pm2 changes in scope. |
| Secrets/env vars | No new secrets for Phase 15 (SERPAPI is Phase 15.2/D10). Existing GEMINI_API_KEY already read by `gemini_deep_research_raw`. Cost prices are a file, not a secret. | None. (Verify `cost_prices.json` deep-research entries; no key change.) |
| Build artifacts / installed packages | New tribunal Alembic migration must be applied to the tribunal DB (new columns/table). Cost fix requires a tribunal-worker + tribunal-api image rebuild + redeploy (recurring deploy-gap lesson, MEMORY). | Migration job + image rebuild via Cloud Build; extend `infra/DEPLOY-RUNBOOK.md`. |

**The canonical question — after every file is updated, what still has stale state?** The GCS audit blobs are immutable historical record (never rewritten); the ONLY migration is forward (new DB columns/table for the read model). The recorded run's blobs are the source of truth the fixture is built from.

---

## Common Pitfalls (cont.) — Deploy gap

Per MEMORY (recurring since Phase 6): code-complete ≠ deployed. Phase 15's cost fix + new endpoints require a **tribunal-api + tribunal-worker image rebuild** AND a **migration job run** before any live verification. Plans must include the deploy/migration runbook steps (author-by-construction; run via Cloud Build — no local Docker). The verification/feed/citation UI also needs a frontend rebuild.

---

## Validation Architecture

> `workflow.nyquist_validation` is `true` (config.json) → this section is REQUIRED.

### Test Framework
| Property | Value |
|----------|-------|
| Framework (tribunal) | pytest — `testpaths = ["nestor_pulse_sdk/tests"]` [VERIFIED: `tribunal/pyproject.toml:11-13`] |
| Framework (intake backend) | pytest (sync pg8000 harness) [VERIFIED: repo backend test history, MEMORY] |
| Framework (frontend) | vitest (`*.test.ts` present, e.g. `i18n/error-codes.test.ts`) + `tsc`/`build` gate + `i18n-audit.mjs` [VERIFIED: repo] |
| Config file (tribunal) | `tribunal/pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `pytest nestor_pulse_sdk/tests/test_cost_cache_write.py -x` (per new test file) |
| Full suite command | Cloud Build backend suite (no local Python/Docker — MEMORY "backend tests can't run locally") |

### Phase Requirements → Test Map
| Req | Behavior | Test Type | Automated Command | File Exists? |
|-----|----------|-----------|-------------------|-------------|
| ENGINE-09 (cost) | Cache-write tokens priced; DR usage recorded; tool fees counted; total = sum | unit | `pytest …/test_cost_cache_write.py -x` | ❌ Wave 0 |
| ENGINE-09 (cost) | Unknown model still → NULL, not guess (Pitfall 5 preserved) | unit | `pytest …/test_cost_cache_write.py::test_unknown_model_null -x` | ❌ Wave 0 |
| ENGINE-09 (chain) | Fixture run still `verify_chain`-green AFTER cost migration | unit | `pytest …/test_hash_chain_replay.py -x` (extend existing) | ✅ extend |
| ENGINE-09 (verification) | `/verification` returns funnel + verdicts + unverified list from fixture | integration | `pytest …/test_verification_report_endpoint.py -x` | ❌ Wave 0 |
| ENGINE-09 (verification) | Cross-tenant + client-role denied (404/empty) | integration | `pytest …/test_verification_report_endpoint.py::test_denial -x` | ❌ Wave 0 |
| ENGINE-09 (citations) | `[n]` generated deterministically; every number resolves to a source | unit | `pytest …/test_citation_numbering.py -x` | ❌ Wave 0 |
| ENGINE-09 (feed) | Enriched `stage_detail` items flatten + render (frontend) | unit | `vitest run` on a `toStageRows`/feed test | ❌ Wave 0 |
| ENGINE-09 (seam) | Intake proxy routes superadmin-only + space-scoped | integration | intake denial-suite entry | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** the relevant `pytest …::test -x` (or `vitest run <file>`) + `tsc` for frontend tasks.
- **Per wave merge:** tribunal suite subset + intake denial suite via Cloud Build.
- **Phase gate:** full Cloud Build backend suite green + `verify_chain` green on the fixture + frontend `tsc`/`build`/`i18n-audit` green before `/gsd:verify-work`. Plus V-02 operator sign-off reading the new surfaces against the recorded baseline.

### Wave 0 Gaps
- [ ] `tests/fixtures/run_4cbb5311/` — recorded-run fixture (run row + audit_log rows + claim/source/claim_source + extracted verdicts + stage_detail), ordered by mtime (Pitfall 6). The single most important Wave-0 artifact — every surface test depends on it.
- [ ] `tests/test_cost_cache_write.py` — cache-write + tool-fee + DR-usage cost, incl. NULL-on-unknown.
- [ ] `tests/test_verification_report_endpoint.py` — funnel/verdicts + RLS + role denial.
- [ ] `tests/test_citation_numbering.py` — deterministic `[n]`, all-resolve.
- [ ] Extend `tests/test_hash_chain_replay.py` — green after migration.
- [ ] Frontend feed/citation component tests (vitest) + i18n keys (en/fr/nl) for all new strings.
- [ ] Intake denial-suite entries for the new proxy routes.

*(UAT: a documented walkthrough on the admin intake detail page against the recorded run — feed replay, "View verification report", click every `[n]` — no live LLM run. This is the V-02 operator-sign-off surface.)*

---

## Security Domain

> `security_enforcement` not set to false → included.

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | Existing Identity Platform + OIDC seam (SEAM-01); new endpoints reuse it |
| V4 Access Control | **yes (primary)** | Superadmin role check + space-scoped RLS on EVERY new read endpoint; client role denied (16-D-08); existence-hidden 404/empty (never distinguishable 403) |
| V5 Input Validation | yes | `run_id`/`intake_id` as typed UUID path params (FastAPI); no free-text query into SQL |
| V6 Cryptography | yes (constraint) | Do NOT touch the SHA-256 hash chain payload; new cost columns are non-hashed. `verify_chain` stays green (Art. 12) |
| V7 Error Handling / Logging | yes | Return-no-throw (CLAUDE.md); never log tokens/secrets; audit rows already immutable |

### Known Threat Patterns for this stack
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Cross-tenant verdict/citation leak on new read endpoint | Information Disclosure | `set_tenant_context` + RLS + CI-gated denial suite day one |
| Client role viewing research internals pre-delivery | Information Disclosure | Superadmin server check + component placement under `admin.*` only (16-D-08) |
| Audit-chain tamper via cost migration | Tampering | New cost fields outside hashed payload; replay test green |
| Drill-down endpoint serving another run's audit blob | Information Disclosure | Blob fetch scoped by (tenant_id, run_id, audit_id); denial-tested |
| IDOR on `GET /api/sources/{id}` proxy | Broken Access Control | Tribunal renderer already 404s on RLS miss; intake proxy must preserve space scope |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Deep-research providers return `usageMetadata` on the Interactions `steps` response for the current Gemini DR agent (`deep-research-max-preview-04-2026`) | Cost-Truth C1-c | If DR usage is genuinely unavailable from the API, DR token cost stays "pending" (C1-e path) rather than exact — still C1-compliant, but the operator's expectation of "exact once adapter records it" (RESEARCH-ENGINE-DECISIONS C1) would need re-scoping. Verify against a recorded blob's raw response before locking the plan. |
| A2 | The recorded run's DB rows (run/audit_log/claim/source) still exist in the live tribunal Cloud SQL, OR are reconstructable from `index.json` + `calls/` | Verification Report / Fixture | If gone, the fixture must be rebuilt purely from the GCS blobs + committed extracts — more work, but still achievable (all raw material is in `docs/…/` + GCS). |
| A3 | Source quality tier (1/2/3) and publication date are DERIVED (domain/provider heuristic), not required as new stored columns | Citations (D13) | If operator wants stored authoritative tier/pubdate, a `source` table migration is added (still non-hashed, safe). Open question below. |
| A4 | Extending `stage_detail` JSONB (not a new `agent_activity` table) is sufficient for the D15 feed's Phase-15 surfaces | Feed Data Model | If per-agent cost must be queried/aggregated independently later, a table is added in 15.2; Phase 15's JSONB choice does not block that. |
| A5 | Anthropic web_search $10/1000 and cache-write 1.25× rates hold for the models used (sonnet-4-6) as of 2026-07 | Cost-Truth | Rates verified via 2026 pricing pages (secondary sources); confirm against the Anthropic console/official pricing page before locking the fee constant. cost_prices.json cache_creation_5m already encodes 1.25×, so cache-write is low-risk. |

---

## Open Questions (RESOLVED)

> All four resolved during plan revision (2026-07-24) by inspecting the committed
> `docs/tribunal-run-reports/run-20260722-4cbb5311/` extracts (`index.json` + `calls/`).

1. **Persisted verdict model: new table vs `run.verification_summary` JSONB?**
   - What we know: verdicts have a fixed shape (`verdict/confidence/evidence_refs/reconciliation`); ~176 groups/run.
   - What's unclear: whether the report needs per-claim query/filter (→ table) or just render-all (→ JSONB blob on the run).
   - **RESOLVED: TABLE chosen.** Plan 15-01 creates the `verification_verdict` RLS table (queryable, RLS-native, matches the claim/source pattern). Non-hashed and safe. `run.verification_summary` JSONB is *also* added for the run-level funnel counts (both land in migration 0011).

2. **Source quality tier + publication date — derived or stored? (A3)**
   - **RESOLVED: DERIVED heuristic.** Plan 15-03 (`citations/numbering.py`) derives quality tier (1 official / 2 serious press / 3 blog) from a provider/domain map and uses `source.fetched_at` as the publication-date proxy — no new migration. A stored authoritative-tier column remains a chain-safe *later* option if the operator wants it (explicitly out of scope this phase).

3. **Does the live Gemini DR Interactions response actually carry `usageMetadata`? (A1)**
   - **RESOLVED (confirmed by inspection): ABSENT in the recorded run.** The DR calls (e.g. `calls/006-google-deep-research-max-preview-04-2026.md`) and every DR entry in `index.json` carry `tokens_in: 0, tokens_out: 0, thoughts: 0`; the string `usageMetadata` appears in **zero** committed call extracts. Therefore Plan 15-02's C1-c path is: read `interaction.get("usageMetadata", {})` and price it **when present** (exact), but for this recorded run — and any call where `usageMetadata` is absent — the DR grounding fee is marked `cost_pending=True`, **never estimated**. The fixture (Plan 15-01) seeds the DR rows with the pending path so `test_dr_usage_recorded` asserts the absent-→-pending branch on real recorded data, and asserts the present-→-priced branch on a synthetic `usageMetadata` dict.

4. **Fixture provenance (A2)** — confirm recorded DB rows exist or plan the blob-rebuild path.
   - **RESOLVED: rebuild-from-committed-extracts is the documented fixture source.** The full per-call `emit_group_verdict` tool_use payloads — the exact `{verdict, confidence, evidence_refs, reconciliation:{disputed,relation,note,canonical}}` shape — are present in the committed skeptic-stage call extracts (`calls/047…md` onward; ~176 group_skeptic calls). Funnel counts come from `selection-experiment/*.tsv` (`claims-distilled-full.tsv` = 1,162 distilled rows; `claims-classified-full.tsv` + `keep-strict.tsv` = keep/drop buckets). Plan 15-01 rebuilds `verification_verdict` rows by parsing these committed extracts — **no GCS pull is required at test time**. If a downstream agent wants the raw blobs, they live (permanent) at `gs://project-cb01b861-cb4a-438d-b9a-nestor-audit/runs/9c84e5a9-1bb9-4b6e-a3ce-2351eda9df63/`, but the committed `calls/` extracts already carry the full verdict payload, so the loader does not depend on GCS.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Cloud Build | Backend tests + tribunal image builds (no local Python/Docker) | ✓ | — | — (MEMORY: gcloud available; local Python/Docker absent) |
| gcloud / GCS read | Fetching recorded audit blobs for the fixture | ✓ | — | Committed extracts in `docs/…/calls/` + `index.json` as partial fallback |
| Tribunal Cloud SQL (tribunal schema) | Migration + read endpoints | ✓ (live) | Postgres 15 | — |
| Anthropic live API | NOT needed this phase (recorded-run only) | ✗ (capped until 2026-08-01) | — | Recorded run-4cbb5311 fixture — this is the DESIGN, not a fallback |
| Terraform | Infra changes | ✗ (downloads blocked — MEMORY) | — | Cloud Build for images; deploy runbook for wiring |

**Missing dependencies with no fallback:** none block Phase 15 (the whole phase is designed around recorded data + Cloud Build).
**Missing dependencies with fallback:** live Anthropic (by design — recorded fixture); Terraform (deploy runbook + Cloud Build).

---

## Project Constraints (from CLAUDE.md)

- Backend language Python/FastAPI; tribunal async SQLAlchemy, intake sync pg8000 (`sync def` handlers except deliberate SSE `async def`).
- No cross-tenant access — enforced server-side at the API layer; broken-RLS class must not recur. New read endpoints join the denial suite.
- Flow ends at `decomposed`; `run-research` legacy path must never be invoked (INTAKE-05). Phase 15 touches only Tribunal's own DR path, not legacy run-research.
- Frontend: React 19 + TanStack + shadcn retained; `frontend/src/components/ui/` (shadcn) not modified directly. New surfaces are new components, not shadcn edits.
- Errors via `sonner` toast, return-no-throw (`{success, error?}`), never `alert()`.
- Imports via `@/`, never relative `../../`. Prettier: printWidth 100, double quotes, semicolons, trailing-comma all.
- i18n: every new string keyed in en/fr/nl `intake.json`; `i18n-audit.mjs` is a hard gate.
- GSD workflow enforcement: file changes go through a GSD command.

---

## Sources

### Primary (HIGH confidence — inspected repo code)
- `tribunal/nestor_pulse_sdk/audit/cost_table.py` — `compute()` omits cache-creation; `cache_creation_5m` prices unused.
- `tribunal/nestor_pulse_sdk/audit/audited_llm_client.py` — extracts `cache_creation_input_tokens` (309) but drops it in cost; `gemini_deep_research_raw` (754-839) drops `usageMetadata`.
- `tribunal/nestor_pulse_sdk/audit/hash_chain.py` — `_payload_for_row` frozen field set (149-161); `cost_usd`/new columns outside it.
- `tribunal/nestor_pulse_sdk/audit/writer.py`, `db/models/audit_log.py`, `db/models/run.py` — schema; `run.cost_usd_total`, `stage_detail` JSONB.
- `tribunal/nestor_pulse_sdk/runs/stages.py` + `runs/api.py` (metrics 786-849) + `runs/schemas.py` — feed backbone + D-07 contract.
- `tribunal/nestor_pulse_sdk/citations/extractor.py` + `renderer.py` — 3-table model + snapshot endpoint.
- `tribunal/nestor_pulse_sdk/pipeline/tribunal/group_skeptic.py` — verdict shape (F-01 already fixed via `_coerce_json`).
- `tribunal/nestor_pulse_sdk/runs/worker.py` + `budget.py` — cost rollup = SUM(audit_log.cost_usd).
- `backend/app/research/tribunal_client.py` + `run_task.py` — seam pattern for new read methods.
- `frontend/src/components/intake/ResearchRunProgress.tsx` + `lib/api/research.ts` + `lib/api/sources.ts` — feed renderer, run type, existence-hidden client pattern.
- `docs/tribunal-run-reports/run-20260722-4cbb5311/REPORT.md` (§4 defects, §6 token accounting) + `selection-experiment/*` — the productization template + gate fixtures + cost reality.
- `.planning/RESEARCH-ENGINE-DECISIONS.md` (D12/D13/D15, C1) + `.planning/STAKEHOLDER-NOTES.md` §2026-07-24 (verification-report requirement).

### Secondary (MEDIUM — verified provider pricing, 2026)
- Anthropic pricing (cache-write 1.25× 5-min TTL; web_search $10/1000): finout.io/blog/anthropic-api-pricing, docs.anthropic.com/en/docs/about-claude/pricing.
- Gemini thinking/thoughts tokens billed at output rate (`usageMetadata.thoughtsTokenCount`): cloudzero.com/blog/gemini-pricing, docs.cloud.google.com Gemini thinking.

### Tertiary (LOW — flagged for verification)
- A1/A3/A5 in Assumptions Log — confirm DR `usageMetadata` presence from a recorded blob, source-tier storage decision, and the live Anthropic fee constant against the console before locking plans.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new deps; all reused libs confirmed in repo.
- Cost defects (C1): HIGH — exact code locations inspected; magnitudes match REPORT.md §6; prices verified against 2026 provider docs.
- Verification report data source: HIGH — verdicts confirmed produced-but-not-persisted; template exists.
- Feed model: HIGH — D-07 contract + `stage_detail`/`toStageRows` inspected.
- Citations: HIGH for model/renderer existence; MEDIUM for tier/pubdate storage (open question A3).
- Frozen-payload safety: HIGH — `_payload_for_row` field set inspected; cost fields provably outside it.

**Research date:** 2026-07-24
**Valid until:** 2026-08-23 (30 days; provider prices move — re-verify fee constants before the first post-cap live run). The repo-code findings are stable until the engine is refactored in 15.2.
