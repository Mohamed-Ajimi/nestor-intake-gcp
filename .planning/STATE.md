---
gsd_state_version: 1.0
milestone: v1.1
milestone_name: Tribunal Integration
status: executing
stopped_at: Phase 15.2 context gathered (17 decisions D-01..D-17; CONTEXT.md + DISCUSSION-LOG.md)
last_updated: "2026-07-31T09:19:15.562Z"
last_activity: 2026-07-31 -- Phase 15.7 planning complete
progress:
  total_phases: 16
  completed_phases: 10
  total_plans: 109
  completed_plans: 97
  percent: 63
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-07-20)

**Core value:** A logged-in superadmin can run a full deep-research cycle on a decomposed intake — Tribunal research, human-crafted report delivery, and client Q&A over the findings — on the same GCP platform, with every client's data isolated to its own space and the legally required audit trail intact.
**Current focus:** Phase 15.7 — research engine redesign creative workshop loop wave 4

## Current Position

Phase: 15.7 (research-engine-redesign-creative-workshop-loop-wave-4) — NOT STARTED
  ⚠ READ FIRST before planning 15.7: `.planning/phases/15.7-*/15.7-OPEN-ITEMS.md` — three rulings that
  ENGINE-REDESIGN-SPEC § 5 does not read like on its face (the tournament STAYS; the loop must DISCOVER,
  not only sharpen; Elo carries with median seeding for newcomers), plus four open items needing an
  operator ruling — chief among them an exit rule that as written fires NEVER, making the 10-round cap
  the normal cost rather than the ceiling.

Gates (15.6, current — these SUPERSEDE the 15.5 numbers a previous entry carried here):
  Engine `cloudbuild.test-engine.yaml` build **dfdcae3d** = **1293 passed / 0 failed / 13 skipped**,
  `collecting: 35 of 35 expected files`. Gates `cloudbuild.test-gates.yaml` build **2eae97e6** =
  **187 passed**, 2 deselected.
  The engine count rose 1118 → 1293 (+175: +165 from the seven plans, +10 from the critical-fix pass)
  and EXPECTED_FILES 33 → 35, so the new tests RAN rather than being silently skipped.
  The gates count did NOT rise and that is CORRECT, not a skip: that config runs a fixed set of 13
  files, none of which 15.6 touched. NOTE it has **no `EXPECTED_FILES` assertion at all** — a mistyped
  path there is a silent skip with no red build. Same defect class the engine config was hardened
  against, still live one file over. Worth closing in 15.8.
  Statuses were read from `gcloud builds describe`, never a shell exit code (`builds submit | tail`
  returns the PIPE's status, so a FAILED build reports exit 0).

Phase 15.6 (Wave 3) COMPLETE, GATE-VERIFIED, NOT DEPLOYED — 7/7 plans, verification 42/42 must-haves,
  44 commits, base 34bf790 → 8c2f3e9. Research is dispatched BY TOPIC: ≤5 LLM-decided groups, each to
  all three providers; `corroboration_key` populates on EVERY angle (was NULL for ~12 of 15 after Wave
  2 — the specific thing this wave existed to fix); `_D6_TOP_K` and `NESTOR_TRIBUNAL_D6_TOP_K` deleted;
  `own` left the rotation only (its runner, timeout and report label survive, so reinstatement is one
  line). The discovery bracket may raise questions the client did not ask — max 5 global slots,
  per-parent cap 3, no fetched http(s) source means no slot, unused slots roll back to the mandate, and
  each dispatched question is traceable in the report to the quote and URL that provoked it, in all
  four languages.

  CODE REVIEW FOUND 2 CRITICALS THAT 42/42 VERIFICATION AND 1283 GREEN TESTS BOTH MISSED — because each
  plan's must_haves were individually satisfied and the defects lived in the SEAMS between them:
    CR-02 (fixed, efc01a4) — `discovery_bracket.discovery_question_text` bounded `assumption` and
      `world_says` with `_norm()` but took the model-authored `source_url` through `_text()` only:
      no whitespace collapse, no length cap, guarded only by `startswith(("http://","https://"))`. A
      URL carrying `\n\n=== Disregard the assignment above` reached three PAID providers verbatim.
      Wave 3 is what put that field on a provider prompt; before it, it only rendered into the report.
      Fix: `_norm_url` — collapse, refuse if a space survives, keep the scheme gate, cap at a new
      `_DISCOVERY_URL_CHARS = 300`.
    CR-01 (fixed, 18065fa) — `_normalise_winners` collapses winner text; `_bound_groups_to_winners`
      compared RAW `member.get("text")` against that collapsed set, and `build_groups` copies member
      text verbatim while `_verbatim_winner` truncates without collapsing. So a client question typed
      with an interior newline or double space — ordinary in a form textarea — was injected by the D4
      coverage guard as a repair group and then SILENTLY DROPPED by dispatch, with the warning blaming
      "not among the strongest winners". Fix: a `_text_key` join applied to BOTH sides at the
      comparison site, so every producer is fixed at once.
  Regression re-gated after the fixes: 1293 passed, 0 failed. 10 new tests, 8 failing on pre-fix source.

  STILL OPEN from that review, deferred to 15.8 (full detail in `15.6-REVIEW.md` § Resolution):

    - The SAME normalisation hazard exists twice more in `workshop_rank.py` (`_restamp_groups`'
      `rank_by_text`, `_stamp_discovery_ranks`' `numbered`). A miss there does not drop a question — it
      silently leaves a STALE `rank`, and rank drives stakes. Fix it with CR-01's class.

    - WR-01: `room = ceiling - len(work)` is measured before the merge pass, so a model returning 5
      groups — exactly what the grouping prompt asks for — makes mandate-strict a NO-OP.

    - WR-06: `_uniform_dispatch` counts distinct corroboration keys, not copies, so a trim shedding 2 of
      3 still prints "went to all 3 research streams"; the comment at `pipeline.py:2049` claims otherwise.

    - WR-05: `NESTOR_TRIBUNAL_D6_MAX_GROUPS=1` + a cross-cutting question → `max_groups=0` →
      `max(1, int(0 or 1))` → 2 groups, 6 paid calls at a dial set to 3.

    - WR-04: `_bound_groups_to_winners(17, …)` still raises on `list(groups or [])`.
    - Test-file code review was never run (production files only). 6 test files unreviewed.

Status: Ready to execute
  built — operator ruling 2026-07-29. 15.4-11 deploy plan stays PARKED and must be RE-SCOPED from
  "Wave 1 alone" to the whole redesign before it ever runs.
  OWED AT 15.8, still unpaid: the two Alembic proofs — the literal lines `Running upgrade 0015 -> 0016`
  and `Running upgrade 0016 -> 0017`, never an exit code. Phase 15.6 added NO third migration (asserted:
  the alembic diff against the phase base is empty).
  A green engine gate is not a green engine: 1293 passing tests say nothing about what three real
  providers return, what the grouping LLM actually emits, or whether `corroboration_key` finally
  populates on a real run.

  Phase 15.5 decisions taken in session (recorded in 15.5-CONTEXT.md), all three closing gaps the
  spec left open:
    D-W2-1  as_of is parsed in Python from EVIDENCE; the distiller prompt contract is NOT touched
            (it is what Wave 1 just proved: 141/137/43/143 against the real audit blobs).
    D-W2-2  record the dispatch corroboration_key as-is. Only the top-3 winners have one; the
            remainder is dealt round-robin with "". NULL for ~12 of 15 winners is CORRECT here and
            fills in Wave 3. The key is read for dispatch at research_division.py:684/:714/:1313
            and pipeline.py:3920, so it must not be populated.
    D-W2-3  _dedupe_claims merges sub_question/corroboration_key first-wins. Verified to need ZERO
            production code — the function already keeps the first occurrence whole.
    D-W2-4  (taken after wave 1 landed) month precision keeps its month: `maart 2021` and `2021-03`
            both resolve to 2021-03-01, not 2021-01-01/None. As built, the bare-year convention was
            overwriting March with January, which collapses `maart 2021` and `december 2021` onto one
            instant — the exact D-V01-4 rollout-vs-contradiction failure as_of exists to prevent.

  THE CROSS-PLAN REGRESSION THE GATE CAUGHT (fix 9064e76) — the lesson of this phase:
    Three green verifications missed it. The plan-checker passed, the phase verifier passed 7/7, and
    all three executors reported success. Only EXECUTING the merged tree found it.
    15.5-01 wrote `test_the_extractor_module_stays_stdlib_pure` as an exact allowlist of the four
    modules `claim_attribution.py` imported at the time. 15.5-02 (cc5088c) then added
    parent_index/resolved_facet to that same module with type annotations, bringing in `typing` and —
    under `if TYPE_CHECKING:`, so never at runtime — `collections.abc`. Neither plan could have
    caught it: they ran in isolated worktrees and neither could execute the other's tests.
    THE MODULE WAS NEVER BROKEN. Both names are stdlib, collections.abc is not imported at runtime,
    and the merged module still lifts and runs under the bundled interpreter (verified before any
    edit). The test was measuring a proxy, too narrowly. So it was TIGHTENED, not loosened: the
    allowlist widened to the stdlib names in real use, PLUS the two things its docstring actually
    promises are now asserted directly — no SDK import, and liftability proved by DOING it with
    runpy. The second cannot rot whatever the allowlist says.
    GENERALISED: parallel executors in isolated worktrees cannot see each other's assertions. Any
    test that pins an EXACT set over a file a sibling plan also edits is a scheduled failure.

  ALSO: `gcloud builds submit ... | tail` returns the PIPE's exit code, so a FAILED build reports
  exit 0 to the shell. Read the build text or `gcloud builds list`, never the shell status. Same
  class as the `ls || true` trap.

  OWED AT 15.8 — carried forward from every plan in this phase, never claimed here:

    - `Running upgrade 0016 -> 0017` (alembic 0017 has NEVER run), alongside 0016's still-unpaid
      `Running upgrade 0015 -> 0016`. Proof is the literal line, never exit code 0.

    - The pytest runs. BOTH builds: `cloudbuild.test-engine.yaml` (reconcile `collecting: 33 of 33`)
      and `cloudbuild.test-gates.yaml`. Baselines to beat: engine 1030 passed / 33 files, gates 182
      passed — both counts must RISE (~23 new test functions from 15.5-02 alone), and EXPECTED_FILES
      must stay 33 (only 15.5-01 added a file).

  Two corrections to ENGINE-REDESIGN-SPEC.md § 3, both verified against source:

    - the new alembic revision is 0017 on top of 0016, not "on top of 0015" (the spec predates
      Wave 1 landing 0016_source_resolved_url.py).

    - only the top-3 winners carry a corroboration_key at all, which the spec does not mention.

  Known, accepted sparseness of the new columns: the distiller-fallback path cannot carry attribution
  at all — claim_distiller builds units as (provider_name, chunk_text) at steps.py:1624-1630, so the
  angle is gone before distillation. Those claims are permanently NULL. Recorded in three places.
  20-26 close them. Phase verification deliberately NOT run; phase NOT marked complete.
  Next: /gsd:execute-phase 15.2 --gaps-only  (waves 1/2/3/4; 22 and 26 are non-autonomous)

  CAP RESET IS NO LONGER THE BLOCKER — the burner key works. The blockers are now the 12 defects.
  Do NOT start another live run before wave 1 (D-E) lands: a stalled or killed run currently
  re-executes itself every 60 min at full cost, held back only by a TEMPORARY env hack
  (NESTOR_WORKER_STALE_MINUTES=525600 on tribunal-worker) that plan 15.2-20 reverts.

DEPLOYED LIVE 2026-07-27 at shared SHA 20260727-085533 (full record: 15.2-UAT.md § Deploy Record):
  tribunal-worker-20260727-085533-090959 · tribunal-api-20260727-085533-091105 ·
  nestor-api-00041-9xp · nestor-frontend-00027-zcr — all 100% traffic.
  Tribunal alembic 0012 -> 0013 applied, proven by the literal log line (not exit 0).
  Audit-chain gate re-run POST-migration: 34 passed / 0 skipped (EU AI Act Art. 12, due 2026-08-02).
  ANTHROPIC repointed Nestor_Claude -> Nestor_Claude2 on ALL THREE services and PINNED in the
  committed deploy scripts (operator decision 2026-07-27); SERPAPI bound from the pre-existing
  Nestor_SERP on both Tribunal services. Two missing IAM grants applied and read back.

CAP NO LONGER BLOCKS V-01 (2026-07-27). Nestor_Claude2 is NOT topped up, so both Tribunal
  services were repointed to a TEMPORARY burner key in its own secret Nestor_Claude_Temp, via the
  TRIBUNAL_ANTHROPIC_SECRET override (nothing committed changed). Validated live: 1-token
  POST /v1/messages returned HTTP 200, so the key works AND is not capped.
  => Tasks 4-6 can run NOW; 2026-08-01 is now only when Nestor_Claude2 is expected back.
  THREE DEBTS: (a) the burner key transited assistant chat -> rotate after testing, same class as
  the Resend key in Phase 20 CLOSE-02; (b) revert to Nestor_Claude2 when topped up by redeploying
  with NO override; (c) nestor-api was NOT swapped (blocked mid-session) and still holds
  Nestor_Claude2, so intake AI skills fail until swapped — Tribunal runs are unaffected.
  Command in 15.2-UAT.md (use --update-secrets, never --set-secrets).

WHAT REMAINS (plan 18 Tasks 4-6):
  Task 4 V-01 — ONE live run on a fresh test intake vs the recorded 4cbb5311 baseline
  Task 5 V-02 — the 16-item checklist + dated operator sign-off
  Task 6 V-03 — a SEPARATE cleanup commit after sign-off (never claim_distiller, D-15)

BEFORE V-01, verify by hand:

  - that Nestor_Claude2 actually holds credit (untestable while capped; a wrong key fails the
    ~$45 run only AFTER it has spent SerpApi/Gemini/OpenAI budget)

  - the audit-blob redaction check — the SerpApi key rides in a QUERY PARAMETER, so an
    unredacted body freezes a live credential into the audit bucket under 7-year retention.
    Blocking, not advisory.
  Standing operator direction 2026-07-24 holds: ONE combined Phase-15* browser UAT against a
  live run, not piecemeal.
Next: /gsd-plan-phase for Wave 2 (claim attribution, D-R3) off .planning/ENGINE-REDESIGN-SPEC.md § 3. Then Wave 3 (dispatch + discovery bracket), Wave 4 (creative loop), Wave 5 (yield). ONE deploy + ONE run at the end. Rotate Nestor_Claude_Temp before that run.
Last activity: 2026-07-31 -- Phase 15.7 planning complete

Progress: [██████████] 100%

## Performance Metrics

**Velocity:**

- Total plans completed: 90 (v1.0, shipped)
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
| 15.6 | 8 | - | - |

**Recent Trend:**

- Last 5 plans: —
- Trend: —

*Updated after each plan completion*
| Phase 14 P04 | 150 | 3 tasks | 10 files |

## Accumulated Context

### Roadmap Evolution

- Phase 15 edited: Deferred after Phase 19 (operator decision 2026-07-21): spine 16-19 ships on engine as-is; Phase 16 dep on 15 removed (dynamic stage-list contract added); Phase 20 now also depends on 15
- Phase 15.3 inserted after Phase 15: Research run page — engine run-events + dedicated run route. Operator decisions 2026-07-27: (a) ships in the SAME deploy batch as the 15.2 gap fixes, (b) engine events are built BEFORE the UI. Does not block 15.2's operator deploy; must merge to master before that deploy's image build. (URGENT)
- Phase 15.4 inserted after Phase 15: Research Engine Redesign — Extraction Repair (Wave 1): the <TAB> parser defect that dropped 278 claims, the loud zero-claims warning, the gemini fact-list retry, redirect resolution at ingest. Scope = ENGINE-REDESIGN-SPEC.md § 2 only; ships alone and is measured by one live run before waves 2-5. (URGENT)

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
| 260728-ftv | A transient seam 401/403 must not finalize a run as failed — retry 401/403 on a separate 10-min budget (200 x 3.0s), every other 4xx stays fatal on first occurrence; also pinned the 5xx arm, which had shipped completely UNPINNED (row added retroactively 2026-07-28 — the task completed but was never recorded here) | 2026-07-28 | 31a7f71 | [20260728-seam-401-retry](./quick/20260728-seam-401-retry/) |
| 260728-kdw | Fix DEPLOY-RUNBOOK § 15.2.k ordering that caused the 2026-07-28 incident (worker deploys LAST, after the run is resolved) + record the claims-first/sleeps-last boot mechanism + the credential-free queue-read recipe + fill the combined deploy record (TWO SHAs, not one) | 2026-07-28 | 30ea1b7 | [260728-kdw-runbook-15-2-k-ordering-and-deploy-record](./quick/260728-kdw-runbook-15-2-k-ordering-and-deploy-record/) |
| 260729-ji9 | Preserve V-01's 225 gemini citations before they expire (verified complete, not merely non-empty) + answer BOTH gating diagnostics — 1a: the missing FACTS block is FORMAT DRIFT not truncation (gemini's two LONGEST reports carry complete blocks; the block sits ~75% in with 9–15k chars of bibliography after it) so THE Q4 GROUPING GATE IS CLEARED; 1b: the distiller never failed — it returned 278 well-formed coffee claims and the parser dropped every one because gemini wrote the literal string `<TAB>` instead of a tab, while the prompt uses `<TAB>` as a placeholder describing the separator. Produced `.planning/ENGINE-REDESIGN-SPEC.md` (9 decisions, 5 waves) | 2026-07-29 | 7c81e29 | [260729-ji9-v01-diagnostics-and-citations](./quick/260729-ji9-v01-diagnostics-and-citations/) |
| 260729-eot | V-01 findings (run 7dcf51d5): cross-stream corroboration NEVER operated — merge key is exact-string so 396 claims → 396 keys → 0 merges, AND only 37/396 claims have any cross-provider partner even at Jaccard 0.2. 8 defects D-V01-1…8 incl. stage logging inert in production, a 13× contradiction shipped unflagged, and claims untraceable to their sub-question. Proposed fix specified to its invariants | 2026-07-29 | 9f22adc | [260729-eot-v01-corroboration-findings](./quick/260729-eot-v01-corroboration-findings/) |
| 260731-dbo | Correct ENGINE-REDESIGN-SPEC § 5 + the 15.7 ledger against local Wave 4 measurement (11 harness experiments, scratchpad only, no source changed). 4 of 5 headline defects had the wrong cause: the "9 of 10 winners WEAK" evidence is an artefact of `_CANDIDATE_PROMPT_CHARS=240` truncating 17 of 18 candidates mid-word; the exit rule fires (rounds 4–9) and needs NO change; population/cost are ~30× below the estimate so the ceilings are not binding; D-R11's median-Elo seed is INERT (wins is the sort key, Elo only the tie-break) → replaced by a catch-up schedule. D-R9 CONFIRMED. Validated config recorded: one global loop + floor of 5 winners/client question + 2 cross-cutting + prefer-KEEP-over-WEAK. Ledger open items 1 & 2 marked answered-by-measurement | 2026-07-31 | ddad00f | [260731-dbo-rewrite-engine-redesign-spec-section-5-w](./quick/260731-dbo-rewrite-engine-redesign-spec-section-5-w/) |

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
