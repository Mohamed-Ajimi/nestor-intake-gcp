# Quick Task 260903-fbt — The Nestor Pulse Handbook: exhaustive project documentation

**Date:** 2026-09-03
**Base commit:** `c8b8583` (asserted before any edit)
**Operator request (verbatim):** *"i want a full detailed exhaustive documentation of the project
from start to finish, i want the whole thing diagrams, schemas, reasoning behind decisions, models
used and why. go through everything, explain the structure the architecture the benefits the
difference from the market. plan it module by module very detailed and easy to comprehend,
professional, follow the best guidelines of documentation. plan it and write it down, do not miss
anything, and then push it to the repo"*

---

## 1. What is being built

A **handbook** — a versioned, multi-chapter documentation set at `docs/handbook/`, checked into the
repository and pushed to `origin/master`. It documents the whole system as it exists at `c8b8583`:
the intake platform (`backend/`, `frontend/`), the Tribunal deep-research engine (`tribunal/`), the
infrastructure (`infra/`), the legacy system it replaced (`docs/supabase-functions/`), and the
reasoning record behind every decision (`.planning/`).

**Not** being built: any code change, any deploy, any run. This task touches `docs/handbook/**`,
`README.md` (one pointer paragraph), and the GSD artefacts in `.planning/`.

## 2. Audience and reading paths

| Reader | Needs | Path |
|---|---|---|
| Stakeholder / client-side decision maker | what it is, why it is better, where it stands | 01 → 18 → 19 |
| New engineer joining the project | how it is built, how to change it safely | 00 → 03 → 04 → 05 → module chapters → 15 → 16 |
| Operator (superadmin) | how to run and read a research run, cost, incidents | 16 → 11 → 10 |
| Auditor / compliance | tenancy, audit chain, EU AI Act Art. 12, secrets | 14 → 09 → 05 |
| Whoever plans the next phase | the decision log, the open gaps, the traps | 17 → 19 → 02 |

## 3. Documentation standards adopted

- **Diátaxis-informed split**: explanation (architecture, decisions, market), reference (data model,
  endpoints, models, env knobs), how-to (operations), narrative (history). Each chapter states its
  type in its header.
- **Every chapter has the same header block**: title · audience · type · source of truth (the files
  a reader should open to verify) · last verified commit.
- **Diagrams are Mermaid** (renders natively on GitHub) — C4-style context/container diagrams,
  sequence diagrams for flows, state diagrams for the three state machines, ER diagrams for both
  schemas, flowchart for the pipeline and the workshop loop.
- **Facts cite code**: `path:symbol` or `path:line` for anything a reader could dispute. Numbers
  that come from a measured run cite the run id and the report that measured them.
- **Reasoning is explicit**: every "why" is written as *context → options considered → decision →
  consequence*, with the operator ruling date where one exists. The decision log (17) uses the ADR
  format and is the canonical register; module chapters link to it rather than restating.
- **Honesty markers**: "⛔ never executed / unobserved", "⚠ measured on n=1", "SUPERSEDED" — the
  project's own convention. The handbook must never present a projection as an observation; this is
  the single most repeated lesson in the planning record.
- **Plain language first**: each module chapter opens with a 5-line "in one paragraph" summary and a
  "how it works" narrative before any table (operator preference: explain mechanism before options).
- **No invented figures**: if a number is not in code, a report, or a measured run, it is not in the
  handbook.

## 4. Sources of truth (what the writers read)

Reasoning record: `.planning/PROJECT.md`, `ROADMAP.md`, `REQUIREMENTS.md`, `milestones/v1.0-*`,
`MILESTONES.md`, `RETROSPECTIVE.md`, `RESEARCH-ENGINE-DECISIONS.md`, `ENGINE-REDESIGN-SPEC.md`,
`STAKEHOLDER-NOTES.md`, `STATE.md`, `CONTINUE-HERE.md`, `research/FRONTIER-COMPARISON.md`,
`research/SUMMARY.md`, every `phases/*/*-CONTEXT.md` decision block, `codebase/*.md`,
`docs/BACKEND-MAP.md`, `docs/PROVENANCE.md`, `docs/tribunal-run-reports/*`.
Code: everything under `backend/`, `frontend/src`, `tribunal/`, `infra/`.
Fact sheets produced for this task (scratchpad, not committed): `backend-core.md`, `backend-api.md`,
`tribunal-pipeline.md`, `tribunal-service.md`, `frontend.md`, `infra-history.md`.

**Excluded as unsound**: `.claude/worktrees/**` (orphaned stale copy — a repo-root grep over it
reads correct deletions as incomplete).

## 5. The chapter plan — module by module

Numbering is fixed; chapter files are `docs/handbook/NN-slug.md`.

### 00 — README (index)
Purpose of the handbook, reading paths (§2), conventions, status legend, how to keep it current
(re-verify commit, which chapter owns which fact), full table of contents with one-line abstracts.

### 01 — Executive overview *(explanation)*
- What Nestor Pulse is: an agentic intake → validated research brief → adversarially verified
  deep research → human-crafted report → client delivery, for Agenic's clients.
- The two halves: the **intake platform** (pre-research, ends at `decomposed`) and the **Tribunal
  engine** (research, ends at a verified report + verification report). Where the human sits in the
  loop (operator accept/edit/reject; client validation round; operator-authored PDF).
- Who the actors are: superadmin (operator), user (client member), the engine, the providers.
- The value proposition in one page: defensible claims, auditability, tenant isolation, cost truth,
  multi-provider independence.
- Current state at `c8b8583`: v1.0 shipped 2026-07-20, v1.1 in progress; live revisions; ⛔ the
  deployed engine models have never executed a run.
- A one-screen system diagram (Mermaid C4 context).

### 02 — History and timeline *(narrative)*
- Origin: the Lovable/Supabase build, its five security flaws, how the code was pulled (Management
  API, read-only, 2026-06-18).
- The decision to re-platform (big-bang, empty DB, GCP-mandated stack), the sibling `MOELD/Nestor`
  Tribunal engine and the decision to absorb it.
- v1.0 milestone (2026-06-18 → 2026-07-20): the 12 phases in order with what each delivered and
  why the order was chosen (isolation before features), the four UAT rounds, "parity accepted with
  deferrals".
- v1.1 milestone: phases 13, 14, 16, 17, 18 (the spine), then the engine redesign 15 → 15.1 → 15.2 →
  15.3 → 15.4–15.8 (five waves), 21, 22, 23, 24 (planned). Per phase: goal, dates, key decisions,
  what it shipped, what it measured.
- The incidents that shaped the design: run `4cbb5311` (skeptic arm off, 776 cap 400s, cost
  undercount), run `d6bb3aae` (aborted; 21 of 32 inputs garbage), run `7dcf51d5` V-01 (the `<TAB>`
  bug, corroboration `both:0`), run `368ff3a0` (dispatch findings, language never set), the
  2026-07-28 worker-boot incident (claims first, sleeps last), run `fb9484dd` (the $27.79 anatomy).
- Deploy tags table and what each carried.
- Quick-task ledger summary (the 30 quick tasks) and the operator rulings they carry.
- Method: GSD phases/plans/waves, worktrees, gates — and the process lessons (retrospective).

### 03 — Architecture *(explanation)*
- C4 context, container and deployment diagrams (Mermaid).
- The four Cloud Run services and what talks to what: browser → `nestor-frontend` (SSR) →
  `nestor-api` → Cloud SQL / GCS / Identity Platform / Resend / Anthropic / OpenAI;
  `nestor-api` → `tribunal-api` (OIDC, internal) → `tribunal.run` queue → `tribunal-worker` →
  providers (Anthropic, Google, OpenAI, SerpAPI) + audit bucket.
- Two schemas, two Alembic lines, two DB drivers, two Python minors — and why (revision-id
  collision, GUC-name mismatch, frozen hash chain).
- Trust boundaries: the browser never touches the DB; the API is the only writer; Tribunal accepts
  only the intake runtime SA; tenant id travels in a header and is re-verified.
- Cross-cutting: SSE not websockets, DB-backed streams (any instance can serve), session release
  across LLM calls, signed URLs, notification-only mail.
- Sequence diagrams: (a) intake fill → submit → skill → review → validate → context pack →
  decomposed; (b) research trigger → poll → SSE → completion → bundle → deliver; (c) one LLM call
  through the audited client (audit row, hash link, GCS blob, cost).

### 04 — Domain model and lifecycles *(reference + explanation)*
- Roles and tenancy: superadmin, user, space (= organization), custom claims.
- The intake **status** machine (`draft → submitted → reviewed → validated_by_client → decomposed →
  in_research → delivered → archived`) with who/what triggers each transition (Mermaid state).
- The frontend **phase** machine (12 phases derived from status + skill run + artifacts) and the
  work-phase presentation rule — why two machines exist.
- The Tribunal **run** status machine (`queued, running, completed, completed_degraded, parked,
  failed, cancelled, needs_input, needs_report_spec`) and the four honest terminal states (R6).
- The intake-side `research_runs` mirror and the attempt / re-run counters.
- Key nouns: intake, answer, template, skill run, context pack (versioned), research question,
  proposal, run, claim, source, claim_source, verdict, group, angle, assignment, winner, bracket.

### 05 — Data model *(reference)*
- `nestor` schema: every table with columns, FKs, `space_id`, indexes; ER diagram; the RLS policy
  pattern (quoted), the `app_superadmin` bypass, FORCE RLS, roles and grants; triggers; migrations
  0001–0013 lineage table.
- `tribunal` schema: every table (org, user, project, run, run_event, claim, claim_source, source,
  output, audit_log, verification_verdict, research_gap, assignment_yield, workshop_round_yield);
  ER diagram; `app.tenant_id` GUC; `worker_user`; migrations 0001–0018 lineage table; the isolated
  `tribunal_alembic_version` mechanism.
- Storage layouts: GCS uploads bucket key scheme; audit bucket object naming and retention.
- What is deliberately empty (`findings`, `deliverables` history) and why.

### 06 — Backend: the intake API *(module reference)*
- App composition, config and secrets, health.
- Auth: token verification, claims, dependencies, admin SDK (invite/deactivate/revoke), session.
- Tenancy: engine factory, connector, pool, GUC set/reset per checkout, `TenantRepository`, the
  three CI guards (no permissive RLS, no raw DB access, no SA key), audit log.
- Endpoint inventory per router (method, path, role, effect), the `CodedError` contract, the
  transitions implemented, SSE streams, storage (signed URLs, keys, limits), mail (templates × 3
  locales, recipient/locale resolution, no-token rule).
- Tests: files by theme, conftest strategy, the Cloud Build gate.

### 07 — AI skills (pre-research) *(module reference + explanation)*
- The seven ported functions and their fates: apply-intake-skill, generate-context-pack,
  structure-answers, extract-insights, embeddings + semantic search, transcribe-audio.
- Per skill: model, prompt intent and output contract, parsing, cost estimate, DB writes, session
  release, UI review semantics (accept/edit/reject, `show_to_client`, client tick).
- The context pack: 12 sections, Dutch by ruling, versioning semantics and the three open edge cases.
- The three-language skill output (2026-08-31) and the `max_tokens` ceiling trap (SDK 21,333).
- The second cost system (`estimate_cost_usd` hardcoded rate) and why it does not reconcile.

### 08 — The research seam (intake ↔ Tribunal) *(module reference + explanation)*
- The seam contract: `tribunal_client.py` methods, OIDC minting, headers, base URL.
- Brief assembly: what the engine receives (context pack, validated questions, `[DECISION]`,
  `[REPORT]` language + size), what is excluded, why the interactive gates never fire (16 D-01).
- Trigger rules: `decomposed` only, confirm dialog, 3-attempt failure cap, re-run counter (Phase 24).
- The poll driver: cadence, mirror writes, terminal handling, mails, 401/403 retry budget.
- Completion path: `verify_chain` gate, bundle (report + scrubbed research + sources.json), GCS
  materialisation, locked state + re-verify.
- Delivery: staged upload → Deliver → `delivered`, replace, client visibility rules.

### 09 — Tribunal: service, audit chain, cost, citations *(module reference)*
- `tribunal-api` endpoint inventory; `InternalCallerProvider`; local-dev fallback.
- The worker: claim query (SKIP LOCKED), heartbeat/stale reclaim, reap, advisory lock, cancel,
  resume; "claims first, sleeps last" and the 2026-07-28 incident.
- Run events: emitter contract (`emit_safe`, thunks, PII scrub, batching), kinds vocabulary, cursor.
- The audit subsystem: what every LLM call records, the frozen `_payload_for_row`, `canonical_json`,
  the chain, `verify_chain` and its shape, GCS blob naming, 2000-char request truncation, redaction
  limits, 7-year retention; why this is the EU AI Act Art. 12 story and why fields never rename.
- Cost table: every price row (all four token classes, search/fetch fees), `compute()`, the
  null-rate trap, `cost_pending`, stale-price risk (the 4× understated Flash row).
- Citations: the 3-table model, extraction, redirect resolution, dedupe/collapse, deterministic
  numbering, snapshots.
- Secrets bootstrap (which Secret Manager name feeds which env var).

### 10 — Tribunal: the research pipeline *(module explanation + reference)*
- The stage list as executed, with a flowchart; per stage: purpose, inputs/outputs, module, model,
  what can degrade it.
- The question workshop in depth: orientation → generate (12/question) → aspect coverage →
  cluster → critique (KEEP/WEAK/KILL) → Swiss/Elo tournament with reasons → generative evolve →
  grounded admission (premise-real, `groundingChunks`) → meta-review → rejected register → exit
  criteria (coverage/quality/saturation, ≥4 rounds, cap 10) → winners (floor 5/question + 2
  cross-cutting, prefer-KEEP) → scope guard → LLM grouping (≤5) → discovery bracket rules. Diagram.
- Dispatch: streams, stakes, corroboration keys, PII scrub, fact-list contract, retry, distiller
  fallback (and why the distiller stays on 2.5 Flash), yield instrumentation.
- Merge and gates: canonical grouping, materiality, error-likelihood/stable skip, corroboration
  priority, fail-loud, the funnel vocabulary with business labels.
- Verification: the group skeptic loop, tools and caps, verdict vocabulary incl. `superseded`, the
  majority-independent survival rule, reconciliation, coverage re-entry, incidental checks.
- Synthesis: planner, Opus 5 writer, anchors → deterministic `[n]`, the deterministic sections,
  language/size directives, rejected-claims ledger, quality gate, verification report payload.
- Reliability: retry classes, breaker, checkpoints, park/resume, terminal states, budget governor
  (inert by D-07) and the caps that act as the wallet.
- Every env knob in one table.

### 11 — Models and providers: what runs where and why *(reference + explanation)*
- The full model inventory across intake + engine + deep-research adapters (provider, model, site,
  purpose, ceilings), with the history of each change (sonnet-4-5 → 4-6 → 5; 2.5-flash → 3.7-flash;
  synthesis to Opus 5; the distiller and the claude DR adapter deliberately left).
- Why each: cost share (skeptic = 79%), the measured position bias (69.9% → 58.4%), thinking-budget
  behaviour, tokenizer change, SDK non-streaming ceiling, format reliability per provider.
- Deep research providers: how each adapter works (Anthropic web tools, Gemini Deep Research agent,
  OpenAI background mode), the ≥2-of-3 degradation, `own`/SerpAPI removed from rotation.
- Price table snapshot and the rows that are introductory/tiered.
- Cost anatomy of a real run (`fb9484dd`, $27.79): the breakdown, caching is not waste (14–30%
  saved), linear ~$0.11/claim-group, the three coverage gaps.
- Perplexity assessment (resells `gpt-5.6-sol`; `[web:N]` citations) — why not a 4th stream.
- Embeddings (OpenAI 1536), Whisper, and the planned Voyage 1024 for Phase 19.

### 12 — Frontend *(module reference)*
- Stack and build (TanStack Start SSR on Cloud Run, Lovable preset, node-server).
- Route map with guards; auth flow (Identity Platform client SDK, token to API, `/auth/action`).
- The `lib/api/*` seam — the complete frontend↔backend contract table.
- Phase machine → `NextStepBanner` CTAs; the intake form (field types, batching, localised schema,
  proposal tick); admin intake detail blocks; AI review panel; context pack block + PDF export.
- Research surfaces: run page + feed renderer (kinds, settle rule, collapse), run actions, the
  verification report page (stat strip, funnel labels, verdict classes, cost), citations panel.
- Client surfaces and what is never client-visible.
- Admin management screens; i18n (namespaces, detection, audit script and its blind spot); tests;
  the D-11 bundle guard; residue (Supabase client, sales, mock-backend).

### 13 — Infrastructure, deployment and CI *(reference + how-to)*
- GCP topology as coded (Terraform resources), what is wired manually (IaC drift list), secrets.
- Images, services, sizing, timeouts, min/max instances, the always-on worker and its cost.
- Deploy discipline: derive the surface by import, digest-proof every revision, pin account and
  project, worker last after an empty-queue check, migrations proven by the literal upgrade line,
  `builds submit | tail` trap.
- The deploy tags ledger.
- Cloud Build configs (root, frontend, tribunal ×8): what each proves, `EXPECTED_FILES`.
- Local development: mock backend, Replit notes, what works without GCP.

### 14 — Security and compliance *(explanation)*
- The inherited flaws (#1–#5) and the specific mechanism that closes each.
- Defence in depth for tenancy: token claims → repository scoping → RLS GUC → CI denial suites →
  seam header re-verification → tribunal RLS; the "broken-RLS class must not recur" rule.
- Auth model, invite/deactivate/revoke, no bearer links, notification-only mail.
- Secrets handling, key rotation debts (Resend, `Nestor_Claude_Temp`, the Perplexity key), the
  audit-blob redaction limitation.
- Prompt-injection bounds in the engine (candidate truncation, `_norm_url`, findings-block
  flattening, the steering-note mitigation) and PII scrub at dispatch.
- EU AI Act Art. 12: what the chain guarantees, what it does not, retention, the frozen payload.

### 15 — Quality, testing and verification discipline *(explanation + reference)*
- Test inventory (backend, tribunal engine + gates, frontend vitest) and what each suite proves.
- Gates: the four grep guards, the Cloud Build gates, `verify_chain`, i18n audit, bundle guard.
- The project's verification method: RED-proof before fix, mutation proof, replay fixtures
  (1,162-claim fixture; 278-claim coffee blobs; 267-prompt model replay), digest proofs.
- The catalogue of gate-integrity traps learned (substring, prose-about-the-thing, vacuous
  criteria, worktree stale base, `ast`-lift name manufacture, silent skips, whole-file TBD gates).
- What is NOT covered: no `.tsx` render tests, the never-executed engine models, unobserved UI fixes.

### 16 — Operations runbook *(how-to)*
- Triggering a research run and what to watch; reading the feed; the STOP procedure; cancel/resume.
- Reading cost and itemising a run from the audit bucket without DB access (the recipe).
- Checking the audit chain and the bundle; delivering a report; replacing it.
- Incident playbook: stalled-looking runs (35-minute silences are normal), parked runs, worker
  double-run hazard, key caps, stale price rows.
- Pre-flight checklist before any paid run (account/project, digests, empty queue, worker env).
- Known operator rulings that constrain operations (uncapped budget, Dutch context pack, no cost
  figure in UI copy).

### 17 — Decision log (ADR register) *(reference)*
One entry per decision, ADR format (id · date · status · context · decision · consequences ·
source). Groups: v1.0 project decisions; v1.0 phase decisions (schema, auth, isolation, storage,
mail, i18n, cutover D-08/D-11); v1.1 milestone decisions; Phase 13/14/16/17/18 D-xx; Phase 15 S/B/V/F;
15.1 G-01…G-14 (summary); 15.2 D-01…D-17; brainstorm D1–D15, R1–R7, C1; redesign D-R1…D-R11;
15.6 D-W3-1…5; 15.7 D-W4-1…11; 15.8 D-W5-1…20 (summary of the ruled ones); 15.3 D-01…D-12;
21/22/23 rulings; D-RR-1…3a; operator rulings 2026-08-31/09-01 (uncapped, Dutch pack, no
Perplexity, model moves). Superseded decisions kept and marked.

### 18 — Market positioning and benefits *(explanation)*
- What the product is compared against: generic deep-research products (OpenAI Deep Research,
  Gemini Deep Research, Perplexity), AI-scientist systems (Google co-scientist, GPT-Rosalind,
  Claude Science), and the legacy Supabase `run-research` aggregator.
- Where Nestor Pulse leads (adversarial refutation, majority-independent survival rule,
  tamper-evident chain, multi-provider independence, cost truth, structured human gating, tenant
  isolation, honest terminal states) and where others lead (Elo ranking — adopted at question
  level; critique passes — absorbed; evolution loops — adopted in bounded form; tool ecosystems —
  irrelevant).
- The benefits to a client and to the operator, stated without invented numbers.
- What was measured versus what is projected, stated plainly.

### 19 — Known gaps, open items and roadmap *(reference)*
- What has never run (the deployed engine models), and the four things the next run must check.
- Open defects and deferred items (STATE.md ledger, review WR-*, DEF-*), the three cost gaps, the
  UI "True itemized cost" section, no `.tsx` tests, IaC drift, key rotations.
- Planned phases 19 (Q&A chat), 20 (chores/UAT), 24 (re-runs + steering note), and the open
  stakeholder decisions (RAG proposal, context-pack edge cases).

### 20 — Glossary *(reference)*
Every project term, acronym and id family (D-xx, R-x, C1, G-xx, D-W3/W4/W5, D-RR, DEF, WR/CR,
UAT-22-Fx, V-01/02/03), stage keys, funnel keys, statuses, phases.

## 6. Diagram inventory (all Mermaid)

| # | Chapter | Diagram |
|---|---|---|
| 1 | 01 | System context (actors ↔ system ↔ external providers) |
| 2 | 03 | Container diagram (4 services, DB, buckets, IdP, mail, providers) |
| 3 | 03 | Deployment topology (GCP project, region, Cloud Run, Cloud SQL, Secret Manager) |
| 4 | 03 | Sequence: intake to `decomposed` |
| 5 | 03 | Sequence: research trigger → poll → SSE → completion → bundle |
| 6 | 03 | Sequence: one audited LLM call |
| 7 | 04 | State: intake status machine |
| 8 | 04 | State: frontend phase machine |
| 9 | 04 | State: Tribunal run status machine |
| 10 | 05 | ER: `nestor` schema |
| 11 | 05 | ER: `tribunal` schema |
| 12 | 08 | Flow: brief assembly and the seam |
| 13 | 09 | Flow: audit chain linkage and verification |
| 14 | 10 | Flow: the pipeline stages end to end |
| 15 | 10 | Flow: the question workshop loop |
| 16 | 10 | Flow: dispatch — groups × providers, corroboration |
| 17 | 10 | Flow: the verification funnel (buckets) |
| 18 | 12 | Route/layout tree |
| 19 | 13 | Deploy order and gates |
| 20 | 14 | Tenancy defence-in-depth layers |

## 7. Execution plan

**Wave 0 — evidence (done before this plan was written):** six fact sheets from the code, each
citing `path:line`; the reasoning record read in full.

**Wave 1 — write (parallel):** module chapters 05, 06, 07, 08, 09, 10, 12, 13 are written by
dedicated writer agents from the fact sheets + the named planning sources; chapters 00, 01, 02, 03,
04, 11, 14, 15, 16, 17, 18, 19, 20 are written by the orchestrator, who holds the reasoning context.

**Wave 2 — verify:** a verification pass checks every `path:line` and every number in the module
chapters against the tree at `c8b8583`; cross-chapter consistency (state names, stage keys, model
ids, counts) is reconciled; Mermaid blocks are syntax-checked; internal links resolve.

**Wave 3 — publish:** `README.md` gains a pointer; `docs/handbook/` is committed in one commit with
the GSD artefacts (force-added, `.planning/` is gitignored); STATE.md quick-task row appended; push
to `origin/master`.

## 8. Acceptance criteria

1. `docs/handbook/00-README.md` … `20-glossary.md` exist, every chapter carries the standard header
   block, and the index links resolve.
2. Every module in `backend/app`, `frontend/src` (excluding `components/ui`), `tribunal/nestor_pulse_sdk`
   and `infra/` is named in at least one chapter with its responsibility.
3. Every endpoint of `nestor-api` and `tribunal-api`, every table of both schemas, every migration,
   every model id, every env knob and every Cloud Build config appears in a reference table.
4. Every decision id present in the planning record's decision blocks appears in chapter 17.
5. All 20 diagrams are present and render (Mermaid syntax validated).
6. No figure in the handbook lacks a source (code, report, or run id); projections are marked as such.
7. The verification pass found and fixed every `path:line` that did not resolve at `c8b8583`.
8. Committed and pushed; STATE.md row present.
