---
gsd_state_version: 1.0
milestone: v1.1
milestone_name: Tribunal Integration
status: executing
stopped_at: Phase 15.2 context gathered (17 decisions D-01..D-17; CONTEXT.md + DISCUSSION-LOG.md)
last_updated: "2026-07-26T13:32:45.195Z"
last_activity: 2026-07-26 -- Phase 15.2 planning complete
progress:
  total_phases: 10
  completed_phases: 7
  total_plans: 63
  completed_plans: 44
  percent: 70
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-07-20)

**Core value:** A logged-in superadmin can run a full deep-research cycle on a decomposed intake — Tribunal research, human-crafted report delivery, and client Q&A over the findings — on the same GCP platform, with every client's data isolated to its own space and the legally required audit trail intact.
**Current focus:** Phase 15.1 — research-engine-redesign-verification-gates

## Current Position

Phase: 15.1 (research-engine-redesign-verification-gates) — EXECUTING
Plan: 1 of 16
Status: Ready to execute
  tribunal images 20260724-214354, migration 0011 applied, suites green — see 15-UAT.md Deploy Record).
  Browser UAT (SC1/2/3) operator-deferred to end-of-Phase-15.2 session.
  UAT STATUS (2026-07-24): Gate fix (quick 260724-vyf, rev 00025-4w8) deployed — the "View
  verification report" button + D15 feed now render on delivered/archived intakes (SURFACING proven).
  But the recorded run-4cbb5311 exists ONLY as a pytest fixture (loader.load_recorded_run seeds a
  TEST session), never seeded into the live DB, so the report body is empty on the old delivered run.
  OPERATOR DECISION 2026-07-24: WAIT for a real live run (seed option declined) — populated SC1-SC4
  browser walkthrough deferred to a live Tribunal run after the Anthropic monthly cap resets
  2026-08-01. No live-DB seeding will be done. This aligns with the existing end-of-Phase-15.2 UAT deferral.
Next: Phase 15.1 (Verification Gates) per order 15->15.1->15.2->19->20.
Last activity: 2026-07-26 -- Phase 15.2 planning complete
  (research surfaces now visible on delivered/archived, not just in_research) — found in Phase-15 UAT;
  DEPLOYED frontend rev nestor-frontend-00025-4w8 (image 20260724-231312)
  (F-01/F-02 fixes previously deployed api 00039-l69, tribunal-api 00010-9qg, worker 00009-ck8)

Progress: [██████████] 100%

## Performance Metrics

**Velocity:**

- Total plans completed: 82 (v1.0, shipped)
- Average duration: — min
- Total execution time: 0.0 hours (v1.1)

**By Phase (v1.0):**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01 | 4 | - | - |
| 02 | 3 | - | - |
| 03 | 4 | - | - |
| 04 | 4 | - | - |
| 06 | 13 | - | - |
| 08 | 3 | - | - |
| 09 | 4 | - | - |
| 07 | 11 | - | - |
| 10 | 5 | - | - |
| 11 | 9 | - | - |
| 12 | 5 | - | - |
| 13 | 4 | - | - |
| 14 | 4 | - | - |
| 18 | 4 | - | - |

**Recent Trend:**

- Last 5 plans: —
- Trend: —

*Updated after each plan completion*
| Phase 14 P04 | 150 | 3 tasks | 10 files |

## Accumulated Context

### Roadmap Evolution

- Phase 15 edited: Deferred after Phase 19 (operator decision 2026-07-21): spine 16-19 ships on engine as-is; Phase 16 dep on 15 removed (dynamic stage-list contract added); Phase 20 now also depends on 15

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work (v1.1):

- Roadmap (v1.1): Build order is re-home+audit-gate → auth-retirement+seam → engine enhancements → trigger+progress spine → raw-output+audit-guard → report delivery → Q&A chat → chores/UAT closure (research-recommended 7-phase spine + a dedicated engine-enhancements phase for the two frontier ideas).
- Roadmap (v1.1): ENGINE-04 audit-chain verification pulled EARLY into Phase 13 (re-home) — hard EU AI Act Art. 12 legal deadline 2026-08-02; a broken chain after the move must be caught before any dependent work.
- Roadmap (v1.1): ENGINE-08 concurrency advisory lock placed in Phase 13 (infra hardening) — the audit hash-chain is single-worker-safe today; the lock must precede real multi-client production use.
- Roadmap (v1.1): ENGINE-05 (plan-critique) + ENGINE-06 (draft tournament) grouped as their own Phase 15 — they touch pipeline/report-contract code; land them on the proven-green re-homed engine (after ENGINE-02) and before the Phase 16 trigger integrates against the final report/stage shape, to avoid re-wiring the audited payload after the spine is built.
- Roadmap (v1.1): Two-schema topology — Tribunal keeps its own `tribunal` schema, own Alembic line (separate `alembic_version` table), own GUC/RLS; intake backend is the sole HTTP seam (no shared DB session). Avoids Alembic revision-ID collision + GUC-name mismatch (Pitfalls 1/2).
- Project (v1.1): Human-in-the-loop report — raw engine output is superadmin-only; client sees only the hand-crafted PDF (D-report). Run `completed` does NOT auto-deliver — the PDF upload flips `in_research → delivered`.
- Project (v1.1): Voyage `voyage-3-large` (1024-dim) for Q&A chat — fidelity to legacy `ask-research`; new vendor + `VOYAGE_API_KEY` secret; dedicated `Vector(1024)` table, never mixed with the OpenAI `Vector(1536)` column.

<details>
<summary>Earlier v1.0 decisions (archived context)</summary>

- Roadmap: Build order is schema → backend/Cloud SQL → auth → isolation-proven-by-tests → CRUD+frontend seam → AI ports → SSE → storage → i18n → cutover (research-recommended).
- Roadmap: Phase 4 (tenant isolation + CI-gated cross-tenant denial suite) gates all downstream feature endpoints — isolation must be proven before features ship.
- Roadmap: Tests are phase-zero work, not cleanup (QA-01 denial suite, QA-02 `USING(true)` CI guard, QA-03 phase-machine/AI contract tests).
- Project: Big-bang cutover — Supabase paused (recoverable), retired only after parity is green for both roles.
- [Phase 1]: Plan 01-01: RLS test harness uses sync pg8000 (Q1 RESOLVED) so the test engine and Alembic env.py share one driver.
- [Phase 1]: Plan 01-02: no public.clients (Q2 RESOLVED) — org = space; space_id (= org id) is the sole isolation key; client identity is organizations.name.
- [Phase 1]: Plan 01-03: superadmin bypass via app_superadmin login role + current_user='app_superadmin' policy (Cloud SQL has no BYPASSRLS); OR'd with isolation so the app role stays space-scoped.
- [Phase 1]: Plan 01-04: 0004 ports ONLY in-scope (<= decomposed) triggers; the 3 post-decomposed Tribunal triggers are absent as objects AND as literal names (INTAKE-05).
- [Phase 2]: get_engine() mode-switch gated so explicit DSN always wins (Phase-1 regression safe, Pitfall 6); shared bounded pool on both engine modes (D-04); split /healthz + /readyz.
- [Phase 2]: one multi-stage uv Dockerfile serves both the Cloud Run service and the migration Job; no baked secrets.
- Runtime SA IAM DB user GRANTed DIRECT space-scoped privileges; RLS still applies (migration 0005).
- GCP live execution deferred to user per D-10; all artifacts authored by construction.

</details>

- [Phase 14]: Tribunal runs as dedicated least-priv tribunal-run SA; tribunal-api invoker=nestor-run ONLY (WR-03/D-04 closed live 2026-07-20)
- [Phase 14]: D-07 proven live: run b188a83e completed chain=OK cost 1.60usd; 3 negatives pass; absorbs Phase-13 queue-path proof (strike from Phase 16)

### Pending Todos

- ~~[2026-07-13] COMBINED 7+8+9 LIVE UAT RUN~~ — SUPERSEDED at v1.0 close; remaining items folded into the 12-UAT deferred ledger (see Deferred Items; revisit in Phase 20 / post-Tribunal).

### Blockers/Concerns

- [v1.1 — legal, HARD DEADLINE] EU AI Act Art. 12 audit-chain enforcement 2026-08-02: `verify_chain` must be proven green after the Tribunal re-home. Addressed in Phase 13 (ENGINE-04), guarded again in Phase 17.
- [v1.1 — cost] `NESTOR_TRIBUNAL_UNCAPPED=1` stays ON — operator explicitly deferred the cap flip-on during Phase 16 discussion (2026-07-21, 16-CONTEXT D-02): "uncapped for now". Flip off + pick cap value before real client-billed runs, Phase 20 at the latest. `STALE_RUN_MINUTES` calibration (above Phase-13 measured max run length) STAYS in Phase 16.
- [v1.1 — isolation] Every new v1.1 surface (raw-output download, deliverables writes, chat retrieval) is a fresh place the broken-RLS class of bug can recur; each read/write goes through the space-scoped session and is added to the CI-gated denial suite from day one (Phases 14/17/18/19).
- ~~[v1.1 — open decision] Auto-proceed vs surface interactive pauses~~ RESOLVED 2026-07-21 (16-CONTEXT D-01/D-01b): pause gates are OBSOLETE for seam runs — the validated intake IS the brief (engine starts at question-delegation); report spec auto-derived from intake answers. Gates must never fire.
- [v1.1 — verify before migration] Voyage `voyage-3-large` output dimension (1024) must be validated against current vendor docs before the Phase 19 column migration — column size is immutable after data exists.
- [Phase 5 follow-up — IaC DRIFT, major, carried]: the live deploy required manual steps the committed `infra/*.tf` doesn't apply (identitytoolkit.admin grant, allUsers invoker, SUPERADMIN_DB_PASSWORD_SECRET env + secretAccessor, CORS_ALLOWED_ORIGINS). Terraform state never adopted. Reconcile or maintain a deploy runbook — now applies to the two new Tribunal Cloud Run services too.
- Scope guard (INTAKE-05): legacy `run-research` (SerpAPI/SearchAPI/Apify) is superseded and must never run from new creds; deep research now flows exclusively through Tribunal.

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260629-ds9 | Add PATCH to backend CORS allow_methods | 2026-06-29 | db32754 | [260629-ds9-cors-patch-method](./quick/260629-ds9-cors-patch-method/) |
| 260629-li2 | Role-gate admin UI (claims guard + Beheer nav hide + 401-disabled redirect) | 2026-06-29 | b49bc8d | [260629-li2-role-gate-admin-ui-on-frontend-claims-ro](./quick/260629-li2-role-gate-admin-ui-on-frontend-claims-ro/) |
| 260715-fts | Apply Claude Design canvas UI consistency fixes to frontend (pre-UAT fuse) | 2026-07-15 | 8907172 | [260715-fts-apply-claude-design-canvas-ui-consistenc](./quick/260715-fts-apply-claude-design-canvas-ui-consistenc/) |
| 260715-j7f | Fuse round-2 canvas redesign of client intake form (stepper sidebar progress) | 2026-07-15 | 5b5259b | [260715-j7f-fuse-round-2-canvas-redesign-of-client-i](./quick/260715-j7f-fuse-round-2-canvas-redesign-of-client-i/) |
| 260716-e59 | Fix 4 UAT-found frontend defects (user lang switcher, nav i18n, decomposed filter, space-switch refetch) | 2026-07-16 | d358685 | [260716-e59-fix-4-uat-found-frontend-defects-user-la](./quick/260716-e59-fix-4-uat-found-frontend-defects-user-la/) |
| fast | Fix one-step-behind active-space filter (sync module accessor in setActiveSpace) | 2026-07-16 | 1d7732a | — |
| 260716-i0j | Fuse round-3 canvas redesign of admin intake detail (merged workflow panel, archive dialog, deferred-delete viz, pack preview, inline emails) | 2026-07-16 | f7297e6 | [260716-i0j-fuse-round-3-canvas-redesign-of-admin-in](./quick/260716-i0j-fuse-round-3-canvas-redesign-of-admin-in/) |
| 260716-ji9 | Intake-invite mail type (backend+frontend) + Intake-info header modal + section-heading casing | 2026-07-16 | 03603f2 | [260716-ji9-intake-mail-type-intake-info-modal-secti](./quick/260716-ji9-intake-mail-type-intake-info-modal-secti/) |
| fast | Fix phase machine consuming enrichment skill runs (fake "analysis ready" after structure-answers) | 2026-07-16 | d2f335b | — |
| fast | Restart skill-run safety poll on new dispatch (stuck 7-min timer) + toast on unusable review output | 2026-07-16 | 4eb1c6e | — |
| fast | Heranalyseer re-run button in awaiting_review banner | 2026-07-16 | acf1ba4 | — |
| 260721-twy | Convert Tribunal intake gatekeeper into a delegator (sonnet-4-6, multi-line research assignments) + full context pack in brief, clarification rubberbands removed | 2026-07-21 | d0032c4 | [260721-twy-convert-tribunal-intake-gatekeeper-into-](./quick/260721-twy-convert-tribunal-intake-gatekeeper-into-/) |
| fast | Client validation diff: patch applied refinements into research_questions + show applied text | 2026-07-16 | a710e8e | — |
| 260720-eh4 | Record rev 00010-ndr deploy (a710e8e live) + operator UAT-deferral decision in 12-UAT.md | 2026-07-20 | 7731421 | [260720-eh4-record-rev-00010-ndr-deploy-defer-remain](./quick/260720-eh4-record-rev-00010-ndr-deploy-defer-remain/) |
| 260723-ior | Merge replit-ui-changes branch (TopBar, compact lang switcher, AISkillsPanel redesign, intake-detail loop fixes + History Sheet, flag-guarded mock-auth scaffolding + mock-backend); tsc+build green | 2026-07-23 | baf9a77 | [260723-ior-merge-replit-ui-changes-branch-into-mast](./quick/260723-ior-merge-replit-ui-changes-branch-into-mast/) |
| 260723-j56 | Sweep outdated end-of-scope research messaging (scopeNote block, dead HandoffBlock + handoff ns, out-of-scope toasts, statusUnavailable rewording) + History button into header beside Intake-info + en/fr researchStarted keys | 2026-07-23 | dc10b88 | [260723-j56-sweep-outdated-end-of-scope-research-mes](./quick/260723-j56-sweep-outdated-end-of-scope-research-mes/) |
| fast | Remove vestigial superadmin Templates page (nav entry + route + i18n keys; canonical-single-template decision, parked since 2026-07-16 UAT) | 2026-07-23 | 4890b84 | — |
| fast | Restore workflow stepper card from replit right rail to full-width center position | 2026-07-23 | 39fc499 | — |
| fast | Context-pack runs merged into History sheet (real skill names) + NextStepBanner/AISkillsPanel/search in sticky right rail, stepper stays center | 2026-07-23 | 1aafe77 | — |
| 260723-kjj | Exhaustive i18n sweep (validated): AI-skills descs, History labels, TopBar bell, SKILL_LABELS→i18n, 37-key research ns backfilled en/fr, i18n-audit.mjs hard-gate script; context-pack accordion removed from center (verifier: passed, 1 browser check open) | 2026-07-23 | cd7e63a | [260723-kjj-exhaustive-i18n-hardcoded-string-sweep-h](./quick/260723-kjj-exhaustive-i18n-hardcoded-string-sweep-h/) |
| 260724-vyf | Broaden ResearchRunProgress mount gate to show Phase-15 research surfaces (D15 feed, verification report button, cost, citations) on delivered/archived intakes, not just in_research (Phase-15 UAT gap; surfacing only, not backfill; not yet deployed) | 2026-07-24 | 4398edb | [260724-vyf-broaden-researchrunprogress-mount-gate-t](./quick/260724-vyf-broaden-researchrunprogress-mount-gate-t/) |

## Deferred Items

Items acknowledged and deferred at v1.0 milestone close on 2026-07-20 (operator decision:
PARITY ACCEPTED WITH DEFERRALS). The UAT/chore items are now scoped into **Phase 20** (CLOSE-01/02/03):

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| uat | 12-UAT.md consolidated parity ledger — 21 unchecked items (AI enrichment verification, storage click-throughs, invite flow, i18n, cross-space SSE 404, two-role E2E) | scoped to Phase 20 (CLOSE-01) | 2026-07-20 |
| uat | Per-phase *-HUMAN-UAT.md partials (01, 03, 05, 06, 07, 08, 09, 10, 11) — folded into the 12-UAT ledger | scoped to Phase 20 (CLOSE-01) | 2026-07-20 |
| verification | 9 phase VERIFICATION.md files status human_needed — same human-testing debt as the UAT ledger | scoped to Phase 20 (CLOSE-01) | 2026-07-20 |
| chore | Rotate Resend API key (transited assistant chat) → version 2 of nestor-resend-api-key | scoped to Phase 20 (CLOSE-02) | 2026-07-20 |
| chore | Rerun full backend suite in Cloud Build (5 known mail test-harness defects) | scoped to Phase 20 (CLOSE-02) | 2026-07-20 |
| chore | Drop NDA PDF into frontend image + rebuild (download 404s) | scoped to Phase 20 (CLOSE-02) | 2026-07-20 |
| chore | Remove legacy VITE_SUPABASE_* from frontend/.env | scoped to Phase 20 (CLOSE-02) | 2026-07-20 |
| product | 3 open decisions: Templates page visibility, Intake-info link-row trimming, "Verzonden mails" history block | scoped to Phase 20 (CLOSE-03) | 2026-07-20 |
| tracking | 8 quick-task dirs report status "missing" — scanner artifact (all complete per Quick Tasks table) | acknowledged | 2026-07-20 |

## Session Continuity

Last session: 2026-07-26T11:00:13.988Z
Stopped at: Phase 15.2 context gathered (17 decisions D-01..D-17; CONTEXT.md + DISCUSSION-LOG.md)
  committed 54dcc1e). Standing operator direction 2026-07-24 unchanged: run ONE combined Phase-15*
  UAT once 15/15.1/15.2 are all ready (against a live run post-2026-08-01) — do NOT UAT piecemeal.
  15.1 needs NO live LLM runs: its CI proof is a deterministic replay of the recorded 1,162-claim
  fixture; the real-classifier calibration check is hand-run after the cap resets 2026-08-01.
Resume file: .planning/phases/15.2-research-engine-redesign-engine-core-inserted-2026-07-24/15.2-CONTEXT.md

## Operator Next Steps

- 2026-07-22: Phase 19 DEFERRED (operator) — stabilization/audit-fix pass first: F-01 tribunal group-skeptic JSON-string crash, F-02 CORS_ALLOWED_ORIGINS startup crash, F-03 4 mail test-harness defects, frontend/.env Supabase cleanup, Cloud Build suite rerun (closes a Phase-20 CLOSE-02 chore early).
- OPERATOR ACTION (blocking further Tribunal runs): the Anthropic org MONTHLY usage cap tripped mid-run 2026-07-22 (self-configured console limit, resets 2026-08-01) — raise/remove it in the Anthropic console before any new live run.
- After stabilization: resume with /gsd-discuss-phase 19 (Q&A chat). Remaining order stays 19 → 15 → 20.
- Phase 19 reminders: verify voyage-3-large 1024-dim against vendor docs BEFORE the column migration; provision VOYAGE_API_KEY; chat retrieval joins the denial suite day one.
