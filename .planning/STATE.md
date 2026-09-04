---
gsd_state_version: 1.0
milestone: v1.1
milestone_name: Tribunal Integration
status: executing
stopped_at: context exhaustion at 83% (2026-09-03)
last_updated: "2026-09-04T13:06:04.134Z"
last_activity: "2026-09-04 -- Phase 23.1 EXECUTED: all 15 plans landed, backend suite 599 passed / 2 skipped / ZERO failed (was 4 failed / 450 passed at 047dcfe). SEC-01 measured closed: 8 operator verbs and 7 AI routes went 200/202 -> 404 for a role=user caller, while the 10 client routes stay 200 and test_client_surface_open.py is byte-unchanged. Migrations 0014 + 0015 written and both directions exercised locally, NOT YET APPLIED to prod. ZERO provider spend, NO deploy, NO run. Every one of the 15 plans carried at least one false acceptance criterion; 7 CONTEXT corrections landed during execution. Blocking on the operator: deploy, both migrations, 2 Cloud Build runs, the tribunal CI gap (37 of 37 tests gate nothing), tfstate bucket, app_superadmin rotation decision."
progress:
  total_phases: 21
  completed_phases: 15
  total_plans: 145
  completed_plans: 143
  percent: 71
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-07-20)

**Core value:** A logged-in superadmin can run a full deep-research cycle on a decomposed intake — Tribunal research, human-crafted report delivery, and client Q&A over the findings — on the same GCP platform, with every client's data isolated to its own space and the legally required audit trail intact.
**Current focus:** Phase 23 — report-legibility-business-friendly-funnel-labels-and-an-hon

## Current Position

Phase: 23.1 (platform-hardening-authorization-boundary-space-deactivation) — EXECUTED, awaiting operator
Plan: 15 of 15 complete (plan 15 at a blocking human-verify checkpoint)
Plans 1–14 are COMPLETE. `15.8-15` (the ONE ~$45 measuring run) is the only one left, and it is
**NOT complete**: its three tasks are all `checkpoint:human-verify gate="blocking"` operator actions.
**No run has been triggered and no measurement exists.** What is done is the credential-free
preparatory half — the five-point STOP PROCEDURE, the Q-PRE-0…Q-PRE-4 pre-flight command set with
15.8-14's digest baseline quoted for character-by-character comparison, the cost-floor reading
discipline, the run-identity skeleton and the eleven-query measurement set — all written into
`15.8-UAT.md` with `«OPERATOR: …»` fill markers and **zero fabricated values**.

⛔ **The plan is blocked on the operator, in this order (all four are ABORT gates and none costs
money): Q-PRE-0 account+project → Q-PRE-1 revisions/digests → Q-PRE-2 empty queue → Q-PRE-3 worker
env → Q-PRE-4 the `logging.logWriter` grant, which is STILL UNPAID.**

<!-- NOTE 2026-08-05: the GSD state tooling rewrote this line to a bare "Plan: 1 of 15" at
     execute-phase start, which is a regression of a curated position. Restored with the real
     position rather than committed as-is. -->

⚠️ **Recorded defect in `15.8-15`'s own Task-1 `<automated>` gate:** it greps the WHOLE of
`15.8-UAT.md` for `TBD` and requires zero, but 15.8-12 deliberately seeded every observed/verdict
cell with `TBD` as an "owed" marker, and those are filled by Tasks 2–3. The gate is therefore
unsatisfiable at Task 1 time — the same whole-file-versus-section scoping defect 15.8-14 booked as
its deviation #9. Task 1's own acceptance criterion is correctly scoped to the run-identity block.

  ## ✅ 2026-08-05 — THE ONE DEPLOY IS DONE. FIVE WAVES ARE LIVE.
  Shared SHA **`20260805-111647`**, master `8dc2fa3`, tree clean, no worktrees.
  `tribunal-api-20260805-111647-115349` + `tribunal-worker-00004-gnv`, both 100%, digest-pinned.
  `nestor-api-00044-8bz` / `nestor-frontend-00028-q52` CONFIRM-ONLY (empty `backend/`+`frontend/`
  diff — D-W5-16 vindicated). **All three unpaid migrations PAID** (`tribunal-migrate-gqmtk`, all
  three literal `Running upgrade` lines). Chain GREEN on DEPLOYED data post-`0018`. Queue proven
  empty 4×. Worker deployed LAST. `NESTOR_WORKER_STALE_MINUTES=60`; every `NESTOR_TRIBUNAL_WORKSHOP_*`
  ABSENT (the positive finding — the validated Wave-4 code defaults are what will run).

  **⚠ THE ENTIRE BLOCK BELOW ABOUT A RED GATE IS SUPERSEDED AND KEPT ONLY AS THE ORIGIN RECORD.**
  The 15.8-13 gate defect was fixed the same day; the gate was then re-run ON THE DEPLOYED TREE at
  `collecting: 43 of 43`, **1812 passed / 0 failed / 13 skipped** (build `3a7a580a`), gates
  `13 of 13`, 187 passed / 2 deselected (`f1322c33`). 1777 → 1812 is exactly +35 — the
  `test_cost_serpapi.py` tests that had never executed in Cloud Build.

  ## ⛔ BEFORE `15.8-15` SPENDS THE ~$45 — Q-PRE-4 IS UNPAID
  **Grant `roles/logging.logWriter` to `nestor-run@` and prove it with a visible `SELECT 1`.**
  D-W5-18: the yield tables have NO endpoint, NO seam verb, NO UI, and the only credential-free DB
  path returns **a boolean in its exit status, not a table of numbers**. Without the grant Wave 5's
  own § 8 criterion is UNREADABLE AFTER the money is spent. Every value in the deploy record had to
  be pinned by PAIRED runs for exactly this reason.

  ## Reading discipline for the run — never present a floor as a total
  `SUM(cost_usd)` is a FLOOR for THREE mechanically distinct reasons: (1) `gpt-5.6-sol` rows that
  wrote NULL before the cost ruling — `SUM` skips NULLs and the openai branch never sets
  `cost_pending`; (2) **WR-02** — a failed/timed-out angle emits NO `assignment_yield` row at all, so
  reconcile row count against dispatched-angle count; (3) the **272K long-context meter** —
  flat rates under-report 2×/1.5× above it, and 15.8-15 owes a measurement of actual `prompt_tokens`
  against that boundary. Also: measure `corroboration_key` at the **ANGLE** level (claim-level NULLs
  are by design); **three locales `en/fr/nl`, not four**; V-02 item #6 is N/A (the `own` stream was
  removed by design, #5 drops to 3 of 3); and V-01's "9 of 10 winners WEAK" baseline is contaminated
  by a 240-char truncation.

  ## Four instructions in the deploy path that READ LIKE CHECKS AND CANNOT BE EXECUTED
  `public.alembic_version` SELECT (refused for BOTH `app_user` and `worker_user` — INTAKE head is
  recorded NOT OBTAINED, its evidence labelled INFERENCE); the § 15.2.k queue recipe that exists ONLY
  as prose; `gcloud beta run jobs executions logs read` (dies on bundled-Python self-update — use
  **`gcloud logging read`** with the execution-name filter); and the run-page UI path —
  `/admin/pulse/runs/$runId` is deliberately bookmarkable yet **login discards the destination**, and
  there is no runs list page. UAT items, booked as one class.

  ## Two traps that nearly produced false results
  **Asserting on a JSON response: assert the KEY EXISTS as a separate arm from its VALUE.** The
  orchestrator propagated `chain_status` (nestor-api's WRAPPER shape) when `tribunal-api` returns
  `{"ok","broken_at"}` — three builds failed and read exactly like a red chain.
  **`gcloud auth login` silently switched account AND project mid-deploy** and overwrote a correction
  seconds after a live API call had already succeeded. Four accounts on this machine. **Assert account
  and project immediately before EVERY gcloud operation** — `tools@dotto.be` /
  `project-cb01b861-cb4a-438d-b9a`. Deploy scripts inherit ambient config and never complain.

---

**SUPERSEDED — origin record only, do not act on it:**
GATE GREEN, VERIFIED (`gaps_found`, 57/58). NOT DEPLOYED.** Verification ran 2026-08-03 at `94a7647`
(`15.7-VERIFICATION.md`). **`/gsd-verify-phase` DOES NOT EXIST** and never did; earlier handoffs
instructed it and it was carried forward unverified across two sessions — the `gsd-verifier` agent
is the real mechanism.

  **THE BLOCKER VERIFICATION FOUND IS NOW CLOSED** (quick task `260804-dbd`, 2026-08-04, commits
  8eff424 / 868775b / 9f5a120). `exit_verdict`'s criterion 3 (SATURATION) was VACUOUSLY TRUE in
  round 1 — no candidate carries a `born_round` yet and there was no minimum-round floor — so on a
  KEEP-heavy brief coverage+quality+saturation all held at the end of round 1 and the loop BROKE
  AFTER ONE PASS: nothing loop-born, no COMBINE, no cross-question synthesis, meta-review guidance
  unused, no INVENT reaching the evidence gate, and the 2 cross-cutting slots filled by ordinary
  single-parent candidates. The count stayed 17; the validated SHAPE did not. Wave 4 degenerated
  into the straight line it was built to replace, and 15.8's single measuring run would have
  measured a loop that ran once. Operator ruled `round_no >= 4` (D-W4-9). Two more rulings landed
  with it: D-W4-10 (dead `max_size` removed) and D-W4-11 (`workshop_notes` persisted as run events).

  ⚠ **THOSE THREE COMMITS ARE UNGATED.** No pytest exists on this machine. Baseline to beat in
  15.8's Cloud Build (`tribunal/cloudbuild.test-engine.yaml`): `7c89be5c` = 1538 passed / 0 failed /
  13 skipped, `collecting: 36 of 36`. No new test FILE was added, so EXPECTED_FILES stays **36** and
  the passed count must rise by **exactly 10**. A count that does not rise must be EXPLAINED, not
  merely noted. Read the build TEXT via `gcloud builds describe` — `builds submit | tail` returns
  the PIPE's status, so a FAILED build reports exit 0.

  **STILL OPEN in 15.7-VERIFICATION.md** — three gaps and two unruled decisions:

    - D7 `langs`: the `_normalise_langs` sweep runs 165 lines BEFORE `enforce_group_coverage`, whose
      two repair rungs both yield empty `langs`. Unreachable in default per-question mode, reachable
      in `topic` mode. Pre-existing at the phase base (67fce9f), but plan 09 asserts the invariant
      unconditionally.

    - `DROP_CLUSTERED_ONTO_LIVE` has NO production writer — only tests write it, so `drop_summary`'s
      third branch is dead and only HALF of D-W4-1's drop signal (loop SPINNING) can be recorded;
      the opposite failure (over-eager dedup strangling discovery invisibly) cannot.

    - `barred_block` renders `entries[:limit]` at `_BARRED_MAX_ENTRIES = 24` — it shows the OLDEST
      bars and hides the NEWEST, which are exactly the ones the model is about to re-propose.
      Bites past the 25th bar. Fix is `entries[-limit:]`.

    - **NOT RULED, awaiting operator:** (a) `catch_up_matches` counts newcomers in its own median —
      verification CORRECTED the review here: D-W4-3 IS honestly delivered, at most 6 newcomers
      enter a field of ~36 so the median is 6 and the schedule fires. Do NOT reverse the two
      committed assertions; document the boundary and warn when it binds. (b) `actions` semantics —
      `_stage_b_feed_finish(actions=calls)` sums `admission_resolver_calls`, an HTTP redirect
      resolution, alongside LLM calls (`workshop_rank.py:4920`), and it is the run's ONLY spend signal.

  Full state + the remaining open operator calls: `.planning/phases/15.7-*/.continue-here.md`
  (written 2026-08-03 18:00, so it PREDATES both the verification and these rulings).

  **PHASE 15.8 IS PLANNED** (2026-08-04, `1e6cda2`) — **15 plans, 6 waves, 20 decisions D-W5-1…20**,
  in `.planning/phases/15.8-*/`. `15.8-CONTEXT.md` is THE AUTHORITY. No RESEARCH.md and no
  VALIDATION.md exist, deliberately — the operator declined the research agent and the scope was
  already written down. **Do not record their absence as a gap.**

  Wave 1 = 8 file-disjoint plans (verified, not assumed) · Wave 2 = the two yield writers, each
  inheriting a file from wave 1 · Wave 3 = test-file review + runbook re-scope · Wave 4 = the gate ·
  Wave 5 = the ONE deploy · Wave 6 = the ONE ~$45 run. Every debt item in D-W5-3 was reconciled
  against plan coverage: **no uncovered item.**

  ⛔ **THREE OPERATOR DECISIONS BLOCK EXECUTION** (15.8-06 is a wave-1 decision checkpoint):

    - **`catch_up_matches`' own-median boundary** (D-W5-8). Recommend **accept + document + warn**.
      Verification CORRECTED the review here — D-W4-3 IS honestly delivered; option (b) reverses two
      named committed assertions.

    - **`actions` semantics** (D-W5-9). Recommend **remove the resolver from the sum**. D-W5-14
      sharpened this: `resolver_calls = 1` is assigned BEFORE the await and regardless of the kill
      switch, so the counter means *"the resolver was invoked"* — not work, not spend — and may count
      an operation issuing **zero** HTTP requests inside the number a reader uses to judge the run.

    - **Whether to widen the frozen yield columns** (D-W5-17). As frozen, `winners`, `weak_winners`,
      `barred`, `lookups` and `calls` have **no home**, so **WEAK-winners-per-round is NOT cross-run
      queryable** — a real gap in D-R8's purpose. Cheap now, expensive once 15.8-05 executes.

  ⛔ **AND ONE BLOCKING PRE-CONDITION FOUND DURING PLANNING (D-W5-18):** the yield tables have **NO
  READ SURFACE** — no endpoint, no seam verb, no UI, and the only credential-free DB path lacks
  `roles/logging.logWriter`, so it returns a boolean and not a table. **Wave 5's own § 8 criterion
  would be unreadable AFTER the $45 is spent.** Ruled into 15.8-15's pre-flight as gate Q-PRE-4.

  Also found in planning, each of which would have produced a phantom result (D-W5-19): the
  `corroboration_key` check **fails by design at claim level** (distiller-fallback claims are
  permanently NULL — measure at the ANGLE level); **there are THREE locales, not four**
  (`_LANGS_MAX = 3`); **V-02 item #6 asks about the `own` stream Wave 3 REMOVED**; and
  `NESTOR_WORKER_STALE_MINUTES` is **60**, not 525600. And a live redaction defect (15.8-08):
  `_redact_dict` matches **key names only**, and `upload_audit_body` leaves the **response half
  unredacted entirely** — audit blobs sit under 7-year retention. If the bucket scan is positive the
  **SerpApi key must rotate**, and that is NOT covered by the `Nestor_Claude_Temp` deferral.

  **The deploy surface is TWO services, not four** (D-W5-16): `git log 31a7f71..HEAD -- backend/
  frontend/` returns **0 of 291 commits**. And **`--set-secrets` in the deploy SCRIPTS is CORRECT** —
  the `--update-secrets` rule governs hand-typed updates; applying it to the scripts would DROP
  bindings.

  **NEXT: `/gsd-execute-phase 15.8`** once the three decisions are ruled.

Gates (15.8, CURRENT — these SUPERSEDE the 15.7 numbers below; plan 15.8-13, 2026-08-04):
  ⛔ **THE ENGINE GATE IS RED ON THE MERGED TREE, AND IT IS A REAL DEFECT — 15.8-14 IS BLOCKED.**
  Engine `cloudbuild.test-engine.yaml` build **b1397467** = **1 failed / 1753 passed / 13 skipped**,
  `collecting: 43 of 43 expected files`. `EXPECTED_FILES` moved 36 → **43** in ONE edit by the phase's
  single owner (D-W5-5), derived from the merged tree and reconciled three ways (list count / git-diff
  additions / per-plan stated contributions — all 43, zero deletions, zero renames).
  **The passed floor of 1754 = 1538 + 10 (D-W5-4) + 176 (7 new files) + 30 (functions added to five
  ALREADY-REGISTERED files) is met EXACTLY, as 1753 passed + 1 failed.** The +30 term is the one nobody
  stated until wave 3: new FILES are not the only source of new TESTS.
  **THE FAILURE, and it is not a config problem:**
  `test_research_division_yield.py::test_hostile_input_returns_the_conservative_shape_rather_than_raising[hostile5]`
  — `assert '<object object at 0x…>' is None`. `research_division.assignment_identity:1179`
  stringifies ANY non-None `corroboration_key`, so a hostile shape writes a **non-deterministic memory
  address into a provenance column** of `assignment_yield`. The identical shape sits at `:1199` for
  `client_question` and **no test covers that half**. Candidate fix: accept only `isinstance(str)` at
  both sites. NOT applied — it is a cross-plan contract decision about a DB column, owned by 15.8-09,
  one plan before a deploy and a $45 run. **Settles by: fix or rule, then re-run the engine gate and
  require 43 of 43 with 0 failed.**
  Gates `cloudbuild.test-gates.yaml` build **68699517** = **187 passed, 2 deselected**,
  `collecting: 13 of 13 expected files` — 15.8-07's new assertion running for the first time.
  **A FLAT 187 IS A GENUINE REGRESSION PASS, NOT INSULATION (D-W5-12).** Measured on this tree
  2026-08-04 with `pipeline\.tribunal|from nestor_pulse_sdk\.pipeline`: **10 of 13** of those files
  import the modules 15.8-02/-03/-09/-10 all edit; the 3 that do not are `test_fail_loud.py`,
  `test_verdict_publication.py`, `test_verdict_write_path.py`. The 15.6 note below ("none of which 15.6
  touched") **does not transfer**. Per D-W5-15 neither config carries that integer — the criterion is in
  the YAML, the measurement is here.
  **THE MUTATION DEBT IS PAID, batched, two builds, both FAILURE by design.** Mutant A `b90cbe2a`
  (5 mutations, 5 distinct symbols, disjoint node sets): 9 failed / 1745 passed at 43 of 43 — every row
  BITES, **no vacuous test found**. Mutant B `b2ee86d2`: 8 failed / 1746 passed — `15.4-05`'s **P4 is
  byte-exact** (`recorded 0 done line(s), not 1` × 5) and **P3 is settled in both directions** (its two
  inverted tests passed clean and went red reverted). Route taken: the TARGETED HELPER mutation, not
  `git revert 6980fda`. Both P3 and P4 leave `PENDING-CLOUDBUILD` (since 2026-07-29) as **PAID**.
  Still OWED: `test_tribunal_pipeline.py` is in NEITHER config while guarding `pipeline.py` (which
  15.8-02 and 15.8-09 both edit) — NOT registered on purpose, its raw-text `persist_tribunal_claims`
  assertion must be tightened to an AST check FIRST, then path + count in one edit.

Gates (15.7, superseded by the 15.8 block above, kept for the reasoning):
  Engine `cloudbuild.test-engine.yaml` build **7c89be5c** = **1538 passed / 0 failed / 13 skipped**,
  `collecting: 36 of 36 expected files`. **THE FIRST FULLY GREEN ENGINE GATE IN THE PROJECT'S HISTORY**
  — and the suite had **never been executed anywhere** before 2026-08-03. Run history, each number a
  real discovery: **29 → 18 → 22 → 4 → 0**. One run in between **EXPIRED in the Cloud Build queue**;
  an EXPIRED build is visually identical to QUEUED and **is not a result**.
  Fixed this session: **D-DEF-01** (prompt injection) + **CR-01…CR-09** from `15.7-REVIEW.md`, plus two
  found while fixing — `workshop.cluster_candidates` assigning rather than accumulating its call count,
  and **three test helpers defined TWICE** in `test_workshop_critique.py` (Python keeps the last, and
  the shadowed versions had been silently degrading fixtures on tests that still **passed**).
  ⛔ **THE VERIFICATION LESSON, above any single defect:** the `ast`-lift harness all nine plans used
  **injects module globals**, so it MANUFACTURED `DISCOVERY_PARENT` — a name `workshop_admission` never
  imported and used at four sites. That collapsed the **entire workshop** to verbatim client questions
  at runtime while reading green through nine plans, `py_compile`, and *"38 lifted tests green"*. **The
  instrument was lying, not the tests.** Prefer real imports; use the lift for behaviour only, never
  name resolution; run the static undefined-global check (CLEAN across all 20 `pipeline/tribunal/*.py`,
  non-vacuous). Corollary, proved four times in one day: **the harness lies before the code does.**
  Gates `cloudbuild.test-gates.yaml` last known build **2eae97e6** = **187 passed**, 2 deselected —
  NOT re-run this session.

Gates (15.6, superseded, kept for the reasoning):
  Engine build **dfdcae3d** = **1293 passed / 0 failed / 13 skipped**, `collecting: 35 of 35`.
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

Status: Executing Phase 23
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
Last activity: 2026-09-01 -- DEPLOYED tag `20260901-134253`: claude-sonnet-5 + gemini-3.7-flash live on tribunal-api-00023-bc6 / tribunal-worker-00009-fkm, both digests proven, NO run triggered. Tree is FULLY DEPLOYED — nothing committed-but-unbuilt.

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

- Phase 24 added 2026-08-13: Deep research re-runs — version history, superadmin steering note, real citation excerpts and per-link grouping. Operator feature request during the Phase 22 UAT, verbatim: *"add the possibility to rerun a deepresearch and keeping track of versions while adding a note a super admin can put to ask for something different than previous runs"*, bundled with UAT-22-F2/F3. **Depends on Phase 22, NOT on 23** — independent of it. Three rulings: separate counters so a deliberate re-run cannot consume the 3-attempt failure-recovery cap; typed confirmation with NO cost quoted (a per-run figure would be fabricated); the note steers the run with no length cap, mitigated by injecting it once in a delimited block rather than per sub-question. Half the plumbing already exists — `research_runs.attempt` is already bumped, and a re-trigger path exists; the real gaps are that a COMPLETED run cannot be re-run (`RunActions.tsx:104-108` gates to failed/cancelled/needs_input on purpose), no note column, and no version-history read path. ⭐ **Bundled deliberately: F2, F3 and the re-run are EACH unprovable without a real run, so ONE ~$45 run validates all of it — and finally discharges the validation deferred since Phase 21.** ⛔ Carries the alembic 0019 collision with DEF-22-06.
- Phase 23 added 2026-08-13: Report legibility — business-friendly funnel labels and an honest work-phase banner. Two findings from the operator's Phase 22 UAT (UAT-22-F1, UAT-22-F4): the gate funnel renders the engine's raw snake_case dict keys instead of readable labels with tooltips, and the "Work phase" banner says research is running for the whole `in_research` phase — which by design spans both *running* and *finished, awaiting delivery* — while also telling the operator to "let run-research run", a function nothing invokes and the scope ceiling bars. **Frontend + 3 locales only, zero spend, verifiable on recorded data** — split from Phase 24 precisely so it need not wait on a paid run.
- Phase 22 added (2026-08-11): Verification Report as a Page + Citation Hygiene. Sourced directly from the operator's Phase 21 UAT walkthrough (verbatim in `21-UAT.md`): report onto its own route rather than an inline dropdown (too long), restyled as a dashboard, citations on hover with the list collapsed by default, duplicate citations collapsed to one number per source, and the embedded activity feed removed from the intake detail page. NOTE: the last item deliberately REVERSES Phase 21's R2, which kept that card by an explicit out-of-scope ruling — the operator reversed it with the reversal in front of them. Root cause found for the duplicates: source dedupe keys on `(tenant_id, content_hash)` — a hash of snapshot TEXT, not the URL (`citations/extractor.py:289-322`), and dedupe is skipped entirely when there is no snapshot.
- Phase 15 edited: Deferred after Phase 19 (operator decision 2026-07-21): spine 16-19 ships on engine as-is; Phase 16 dep on 15 removed (dynamic stage-list contract added); Phase 20 now also depends on 15
- Phase 15.3 inserted after Phase 15: Research run page — engine run-events + dedicated run route. Operator decisions 2026-07-27: (a) ships in the SAME deploy batch as the 15.2 gap fixes, (b) engine events are built BEFORE the UI. Does not block 15.2's operator deploy; must merge to master before that deploy's image build. (URGENT)
- Phase 15.4 inserted after Phase 15: Research Engine Redesign — Extraction Repair (Wave 1): the <TAB> parser defect that dropped 278 claims, the loud zero-claims warning, the gemini fact-list retry, redirect resolution at ingest. Scope = ENGINE-REDESIGN-SPEC.md § 2 only; ships alone and is measured by one live run before waves 2-5. (URGENT)
- Phase 21 added 2026-08-10: Research Run Feed Completion. Operator UAT of the run page found four defects, three of which trace to ONE root cause — Phase 15.3 shipped the run-event contract but wired only 4 of 13 stages (measured: `deep_research` 24 emit sites, `own_research` 7, `workshop` 2, `research_division` 2, and **zero** for `distill`/`merge`/`gate`/`verify`/`adjudicate`/`coverage`/`conflict`/`synthesize`). The silent stages render as a label with nothing under it, and their empty bodies are also why the "Show more" toggle reveals nothing. Separately: `RunFeed.tsx` renders `agent_run` with a perpetual spinner because the feed is append-only (start and finish are two rows, not one row updating), and `VerificationReport` exists but is wired only to the intake card, never to the run page. **Sequenced BEFORE the first measured run** so the ~$45 validates the engine changes and the feed together. (URGENT)
- Phase 23.1 inserted after Phase 23: Platform hardening: authorization boundary, space deactivation cascade, AI cost control, tribunal run ownership, and CI coverage (URGENT)

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
- [Phase ?]: Nestor_Claude_Temp rotation DEFERRED to go-live (operator, 2026-08-03)

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
| 260803-g6z | Close D-DEF-01, the prompt-injection channel in `workshop._findings_block` — it truncated but never collapsed `\n`/`|`, so a finding from a FETCHED WEB PAGE forged a second addressable record. Proven non-vacuously against the real committed source (ast-lift + source-text mutation): baseline renders 2 records `['0','1']`; restoring the old slice renders **3**, `['0','9','1']` — the forged record INTERLEAVES between two genuine ones. Fixed via function-local `workshop_rank._flatten` (ONE authority) — the recorded "one-line fix" would have been a CIRCULAR IMPORT. Also fixed the `_asks_block` sibling (`_ASPECT_LINE_RE` captures `(.*)` under `re.DOTALL`, so `|` survived; mutant leaves 3 pipes vs 1). Byte-identical on the already-protected rank path is NOT achievable — bounded instead to one trailing space via the proven identity `_flatten(_flatten(x,N),N) == _flatten(x,N).rstrip(" ")`. Retired 3 rationale comments that cited this defect to justify their own flattening (two-authorities, inverted); `workshop_admission.py` verified still true and untouched. **Survived all of phase 15.7 because its deferral named plans 07 and 09, neither of which owns `workshop.py`** | 2026-08-03 | b65d9b5 | [260803-g6z-findings-block-injection-fix](./quick/260803-g6z-findings-block-injection-fix/) |
| 260804-dbd | Close three 15.7 verification gaps by operator ruling: **D-W4-9** a minimum-round floor (`_LOOP_MIN_ROUNDS = 4`) enforced INSIDE `exit_verdict` — criterion 3 (SATURATION) was VACUOUSLY TRUE in round 1 because nothing carries a `born_round` yet, so a KEEP-heavy brief broke the loop after ONE pass and Wave 4 degenerated to the straight line it replaced; the floor sits in the verdict (not at the `break`) so `should_exit` stays the single authority, `effective_floor = min(floor, cap)` keeps the cap the sole termination bound, and a new `hold_reason` distinguishes "criteria met, floor not reached" from "criteria not met". **D-W4-10** `attach_discovery_riders`' inert `max_size` REMOVED caller-first (zero remaining callers proved by AST over 20 call sites BEFORE the signature changed; `clamp_groups`' 14 sites untouched). **D-W4-11** every `workshop_note` now persists via `run_events.emit_safe` (`stage="workshop"`, `kind="plan"` — a real member of the closed 12-value `RUN_EVENT_KINDS`, since an out-of-vocabulary kind is DROPPED at `emit` and would have reproduced the very defect); text built INSIDE the `build=` thunk with the loop var default-bound, and the log's `[:4]` cap now NAMES its truncation. ⚠ **PYTEST GATE NOT RUN — OWED AT 15.8** (no Python/pytest here): baseline `7c89be5c` = 1538/0/13, `collecting: 36 of 36`; no new test FILE so EXPECTED_FILES stays 36 and passed must rise by exactly 10 | 2026-08-04 | 9f5a120 | [260804-dbd-close-three-15-7-verification-gaps-round](./quick/260804-dbd-close-three-15-7-verification-gaps-round/) |
| 260731-dbo | Correct ENGINE-REDESIGN-SPEC § 5 + the 15.7 ledger against local Wave 4 measurement (11 harness experiments, scratchpad only, no source changed). 4 of 5 headline defects had the wrong cause: the "9 of 10 winners WEAK" evidence is an artefact of `_CANDIDATE_PROMPT_CHARS=240` truncating 17 of 18 candidates mid-word; the exit rule fires (rounds 4–9) and needs NO change; population/cost are ~30× below the estimate so the ceilings are not binding; D-R11's median-Elo seed is INERT (wins is the sort key, Elo only the tie-break) → replaced by a catch-up schedule. D-R9 CONFIRMED. Validated config recorded: one global loop + floor of 5 winners/client question + 2 cross-cutting + prefer-KEEP-over-WEAK. Ledger open items 1 & 2 marked answered-by-measurement | 2026-07-31 | ddad00f | [260731-dbo-rewrite-engine-redesign-spec-section-5-w](./quick/260731-dbo-rewrite-engine-redesign-spec-section-5-w/) |
| 260806-dn8 | **Report synthesis moved to `claude-opus-5`** (operator decision 2026-08-06), 3 commits `74cdf94`/`5e6425c`/`70f9f11`. The three report-writing calls — `final_synthesis_audited`, `_one_section`, the wrap — now run on `audited.anthropic_messages`; distiller/conflict-detector/scrubber stay on Gemini (4 `gemini_generate` sites remain, covering 3 model constants). `_make_synthesis_config` REPLACED by `_synthesis_kwargs`: Anthropic requires `max_tokens`+`messages`, so the optional-config-or-None shape could not survive, and `temperature=0.2` is DROPPED — with thinking on by default `temperature`/`top_p`/`top_k`/`budget_tokens` are an HTTP 400. `_synthesis_text` reads `stop_reason` FIRST and joins EVERY `type=="text"` block (never `content[0]` — thinking blocks come first); a refusal discards partial content into the SAME degraded path. **⛔ THE CAP IS BOUNDED BY THE SDK, NOT THE MODEL:** `anthropic 0.104.1`'s `_calculate_nonstreaming_timeout` raises `ValueError: Streaming is required...` when `3600*max_tokens/128_000 > 600`, and all three trigger conditions hold in production (`build_audited_client` builds a bare `AsyncAnthropic()` with no timeout; `claude-opus-5` is absent from `MODEL_NONSTREAMING_TOKENS` so only the time clause applies) — so both caps went 8192 → **20_000** under a named, arithmetic-checked `_ANTHROPIC_NONSTREAMING_MAX_TOKENS = 21_333`. **A "raise it to 64000 for headroom" edit would have thrown on EVERY synthesis call.** Added the `anthropic/claude-opus-5` price row (5.00/25.00; cache fields are DERIVED 0.1×/1.25× multipliers, recorded as such, and INERT until something sends `cache_control`) — RED-proved first: `compute()` returned `None` + `writing NULL cost_usd`, the booked **G-7** shape. **G-10 CLOSED:** heading + Verification-appendix keys now render the client's FULL question through ONE resolver reading `focus_areas[*].research_prompt` (the CR-08 field that already carried it), degrading to the label; RED-proved reproducing run `368ff3a0`'s exact `...hoe wordt dit operat`. `_LABEL_MAX_CHARS`/`_GATE_DECISION_CONTEXT_CHARS`/`_QUESTION_MAX_CHARS`/`_DECISION_MAX_CHARS` verified byte-identical. Engine gate registered 43 → **44** files (`EXPECTED_FILES` + path in one edit — an unregistered test file never runs in CI). Local suite 1809 → **1850 passed / 0 failed** (+41 = exactly the new file); 6 errors are the Windows 32767-char `PYTEST_CURRENT_TEST` limit and are present identically at base. **⛔ NOT DEPLOYED — voids the digest baseline verified 2026-08-06; all five 15.8 pre-flight gates must be re-run before any measured run** | 2026-08-06 | 70f9f11 | [260806-dn8-synthesis-opus5-uncap-g10](./quick/260806-dn8-synthesis-opus5-uncap-g10/) |
| 260806-lvt | **The client's chosen report LANGUAGE and SIZE now reach synthesis.** 3 commits `39fec86`/`1de2346`/`911318c`. Two defects, both MEASURED from run `368ff3a0`'s GCS audit blobs (`request.query`, untruncated) rather than inferred. **(1)** `mission_brief["language"]` was EMPTY on every call — all five dispatch assignments read carry the fallback *"Report all findings in the language of the assignment above."*, a branch that fires ONLY when the value is empty, and the same value feeds `_language_directive`, so **every writing step also took its weak branch and the strong "Write EVERYTHING in {lang} and ONLY {lang} … Never mix languages" directive has never fired in production.** `adaptive_intake` was its only producer and D-03 unwired it. **(2)** `output_size` was read by NOTHING — length was proxied off `question_count > 8`, and `pipeline.py`'s zero-touch path hardcoded `report_spec=None`, so the `REPORT SHAPING (client-chosen — honor these)` block the engine ALREADY knew how to emit reached zero prompts. `368ff3a0` delivered **356,352 chars** against a form whose largest option offers *"approx. 10-20 pages"* and whose help text reads *"Dikker ≠ beter."* Adds a required `report_language` field (nl/fr/en) and a parsed `[REPORT]` block beside `[DECISION]` — **a block, not prose**, because both consumers interpolate the value into a prompt and neither can read a sentence. **OPERATOR RULING: `output_size` maps to BOTH a keyword AND a page range** (compact→brief+2-5 · standard→5-10 with NO keyword · extended→comprehensive+10-20 · other→`instructions`, no invented range). ⛔ **The conditional `LENGTH:` prefix is the subtle part** — the old function emitted a LENGTH line only for brief/comprehensive, so a pages-only spec produced NOTHING and the whole standard tier would have been silently inert; RED-proved as `assert 'LENGTH: Target length: approximately 5-10 pages.' in ''`. **DRIFT GUARD** asserts every mapped page range appears in all three locale labels of the live template — two places now show the client a number. `_radio_answer` was NOT in the plan and is not optional: `FieldRenderer` stores an `allow_text` radio as `{choice,text}` and `_first_nonempty` would `str()` it into its repr and report the answer as unset. ⚠ **Engine tests moved to `test_report_sections.py` — `test_synthesize_report.py` is NOT in the gate's `WANTED` list**, so tests written there would never run. `EXPECTED_FILES` stays **44**; no new test file. Gate **1850 → 1869 passed / 0 failed** (+19 = exactly 11+8 new tests); backend **127 → 137** (+10). ⚠ **BREAKS OUTPUT COMPARABILITY WITH `368ff3a0`** — same class as the parked `_GATE_DECISION_CONTEXT_CHARS` ruling, accepted because the current behaviour is a defect not a baseline. The page target is a TARGET, NOT A CAP — the real ceiling is the per-section budget × one section per question. **⛔ NOT DEPLOYED — joins `260806-dn8` as committed-but-unbuilt; one rebuild covers both** | 2026-08-06 | 911318c | [260806-lvt-wire-intake-report-language-and-size-to-](./quick/260806-lvt-wire-intake-report-language-and-size-to-/) |
| 260806-o96 | **G-5 ANSWERED — and the answer inverted the question. The claim gate now sees the client's WHOLE question.** Commit `85c3aa9`. Measured from run `368ff3a0`'s GCS audit blobs (7 gate calls, all identical): the decision context was **576 chars against a 1200 cap — the 1200 NEVER BOUND**, 624 chars spare. **What bound was `workshop._LABEL_MAX_CHARS = 120`**: the gate's TEST 2 (*"does the client's decision actually turn on this claim?"*) was answered against three questions cut MID-WORD — *"…hoe wordt dit operat"*, *"…op koff"*, *"…in de retailmar"*. **Every KEEP/DROP decision in that run was made against half-sentences.** The cap everyone suspected was innocent; the cap nobody suspected was the whole defect. `_gate_decision_context` now resolves the label to the full question through **the ONE existing resolver** `synthesis.steps.focus_area_questions` (from `70f9f11`/G-10), falling back to the label — no second mapper, no second copy of the 120. That resolver is documented **DISPLAY ONLY**; the docstring now states why this honours it (the decision context is PROMPT TEXT — nothing is keyed, joined or stored by it). **`_LABEL_MAX_CHARS` NOT widened and pinned at 120 by a test** — it is an IDENTITY key and the parked note calling it *"safe to remove"* was wrong. ⚠ **BOTH caps moved together, 1200→4000 and 2000→4000, because they truncate the same string IN SERIES** — raising the pipeline one alone past 2000 changes the number, produces NO observable effect, and reads as *"the cap was not the problem"*; a test pins the **RELATIONSHIP, not the values**. Why now and not later: three FULL questions measure **1164**, which fitted the old 1200 by only **35 chars**; FOUR measure ~1484 and the intake admits **5** — the cap was **LATENT, not dead**. Neither cap REMOVED (client-typed text going verbatim into a prompt beside 40 claims). **Corrected rather than carried:** the 1200's own comment claimed it protected *"the 4096-token gate budget"* — that 4096 is `max_output_tokens`, and input cannot consume an output budget. RED-proved against the stashed modules: *the gate is still being handed a truncated question* · **`AssertionError: 576`** (the exact measured live value) · *the fixture no longer exercises the old cap*; the three guards passed in the same RED run, correctly. Gate **1869 → 1875 passed / 0 failed** (+6 = exactly the new tests); no new test file, `EXPECTED_FILES` stays 44 — `test_engine_e2e_stubbed.py` was chosen because it imports BOTH modules AND is in the real `WANTED` list. ⚠ **CHANGES WHICH CLAIMS REACH PAID VERIFICATION → breaks comparability with `368ff3a0`**, on top of `260806-lvt`'s report-output break. **⛔ NOT DEPLOYED — THREE changes now committed-but-unbuilt (`dn8`, `lvt`, `o96`); ONE rebuild covers all three** | 2026-08-06 | 85c3aa9 | [260806-o96-feed-the-claim-gate-the-full-client-ques](./quick/260806-o96-feed-the-claim-gate-the-full-client-ques/) |
| 260831-gk7 | **The client can now choose which AI-proposed extra questions to add.** 2 commits `41d6810`/`73651b7`. Defect 2 of the 2026-08-31 operator intake test, and it was TWO bugs that had to ship together. **(1)** `routes/intake.$id.tsx:106` sets `editable: status === "draft"`, but the client-validation phase is entered at status `reviewed` — so `editable` was ALWAYS false there, `IntakeForm` passed `disabled={!editable}` down, and the proposal checkboxes **rendered inert**. **(2)** `AIReviewPanel.tsx:352` writes `show_to_client` (the operator's decision about which proposals to put in front of the client) and **NOTHING read it — one occurrence in the whole repo, the write itself**, so the client would have been offered every proposal including the operator's explicit exclusions. Fixing (1) alone would have been **WORSE than the bug**: it turns an inert list of all-proposals into a LIVE one, letting the client commission research the operator rejected. ⚠ **THE TRAP:** `ProposalListControl`'s toggle maps over the item array and passes the WHOLE result to `onChange`, so filtering the array itself would have written back only the client-visible subset and **permanently deleted every operator-excluded proposal on the client's first click, silently**. The filter is therefore DISPLAY-ONLY — `items` stays the full write surface, `visible` is a projection carrying each entry's index in the FULL array, and `toggle`/`key` both address the stored array. `show_to_client === true` is **strict, not `!== false`**: an entry with no explicit operator include is not offered, which fails safe (an empty list the operator can notice) rather than leaking exclusions. Scope held tight: only `proposal_list` re-opens and only in the validation phase — the rest of the form stays read-only because those answers were validated at submission and re-opening them would let the client silently rewrite reviewed content. **`routes/intake.$id.tsx` has an EMPTY diff** (the status gate deliberately untouched; `payload.phase` already carried what was needed) and no save wiring was required. Data model unchanged — operator sets `show_to_client`, client sets `approved`, `brief.py` counts only `approved`. tsc 0 errors, **135/135** tests (none of which touch this code). ⛔ **NO `.tsx` TEST EXISTS IN THIS REPO** (`vitest.config.ts` includes only `src/**/*.test.ts`) — the tick, the filter and the index mapping are verified by typecheck and inspection, NOT by rendering. **The write-back preservation most deserves a click-through, because its failure mode is silent data loss.** Frontend-only, zero backend, safe to land mid-research-run. **⛔ NOT DEPLOYED** | 2026-08-31 | 73651b7 | [260831-gk7-client-can-tick-ai-proposed-extra-questi](./quick/260831-gk7-client-can-tick-ai-proposed-extra-questi/) |
| 260901-lf2 | **The five tribunal Flash stages moved to `gemini-3.7-flash`, and two stale Gemini price rows were corrected.** 1 commit `300be1a`, +91/−9. ⭐ **JUSTIFIED BY MEASURED POSITION BIAS, NOT PRICE.** All **267** real Flash prompts from run `fb9484dd` were replayed through both models with the exact production config (`maxOutputTokens=4096, temperature=0, thinkingConfig.thinkingBudget=0`), **0 errors either side**: on the pairwise judge, where option A is always listed first, **2.5-flash picks A 69.9%** (137/59) while **3.7-flash picks A 58.4%** (94/67) — the tournament was ranking research questions partly by LIST ORDER, a classic pairwise-judging failure. **23% of verdicts flip** (77% agreement, 124/161). ⭐ **THE DOCUMENTED REGRESSION DID NOT OCCUR:** `workshop_rank.py:190` warns in capitals that thinking makes *"a critic that rejects nothing"*; measured, 2.5 gave KEEP 9 / WEAK 35 / **KILL 0** and 3.7 gave KEEP 17 / WEAK 21 / **KILL 6** — MORE decisive at both ends. That warning is still true of enabling thinking on 2.5 and was NOT deleted. ⚠ **3.7 ignores `thinkingBudget=0` on real prompts** (it honours it on a trivial one-liner, which is how the first test looked clean), so output rises **4.2×** — flash $0.54 → $2.04, **+$1.50/run, operator-accepted**. Sites: `gates._GATE_MODEL`, `grouping._GROUPER_MODEL`, `report_planner._PLANNER_MODEL`, `workshop_rank._RANK_MODEL`, `workshop_admission:921` — **plus a SIXTH by inheritance**, `workshop_evolve._META_MODEL`, which defaults to `_RANK_MODEL` and moved with no evidence of its own. ⛔ **THE CLAIM DISTILLER WAS DELIBERATELY LEFT ON 2.5-flash**: it contributed **ZERO** of the 267 prompts (it is the D-14 fallback and every stream returned its own fact list), and it feeds `_split_distiller_line` — the parser behind the V-01 incident where **278 well-formed claims were ALL dropped because the model emitted the literal `<TAB>`**. `test_factlist_fallback.py:1739` pins the literal as a guard. (Checked and dismissed as a coupling: `_DISTILLER_MAX_TOKENS = 65535`; both models report `outputLimit 65536`.) Prices: ADDED `google/gemini-3.7-flash` $0.75/$3.75/$0.075 — ⚠ **introductory, DOUBLES to $1.50/$7.50 on 2027-01-01**; CORRECTED `google/gemini-2.5-flash` $0.15/$0.60 → **$0.30/$2.50** (output was **4× understated**, so past Flash costs were too low) and `gemini-2.5-pro` cache_read $0.3125 → $0.125 (⚠ pro is TIERED — $1.25/$10 ≤200k, $2.50/$15 above; the table encodes ≤200k only). All three rows proven through the real `compute()` (4.50 / 2.80 / 11.25) with a negative control returning `None`. ⚠ **the orchestrator's own verify gate was UNSOUND** — it demanded one live grep hit, but the executor's explanatory comment quotes the string; settled by **AST** instead (5 live `gemini-3.7-flash`, 1 `gemini-2.5-flash`). Zero tests needed editing — they reference symbols, not literals. Gate **1946 passed / 13 skipped / 6 errors**, identical to a self-taken baseline; second gate 189 passed / 1 pre-existing | 2026-09-01 | 300be1a | [260901-lf2-switch-the-tribunal-flash-stages-to-gemi](./quick/260901-lf2-switch-the-tribunal-flash-stages-to-gemi/) |
| 260901-j6w | **The tribunal engine moved from `claude-sonnet-4-6` to `claude-sonnet-5`.** 1 commit `df131ea`, 9 files. Operator ruling on measured evidence: the Anthropic skeptic stage is **79% of run cost** ($19.68 of $24.78 priced on run `fb9484dd`), and Sonnet 5 is **$2/$10** against 4.6's **$3/$15**. Per-token that is 33% cheaper; **~13% after adjusting for the ~30% token increase from the newer tokenizer** used by Claude 4.7-and-later models (Sonnet 4.6 and earlier use the previous one) — about **−$2.62/run**. Seven sites: `_SKEPTIC_MODEL`, `_INTAKE_MODEL`, `_WORKSHOP_MODEL`, `_EVOLVE_MODEL`, `_GROUP_MODEL`, `own_researcher._MODEL`, **plus `workshop_admission.py:592`** — an except-branch fallback the brief missed, which if left behind would have silently billed a rarely-hit path against a differently-priced model. ⛔ **THE PRICE ROW IS MANDATORY, NOT HOUSEKEEPING:** without `anthropic/claude-sonnet-5` in `cost_prices.json`, `compute()` returns `None` and every run writes NULL `cost_usd` + `cost_pending` — a model swap alone silently destroys cost tracking on the most expensive stage. Proven through the real `compute()`: `1M in + 1M out` → **12.0** (=2+10), cache probe **2.7** (=0.20+2.50), and an invented model name → `None` with the `writing NULL cost_usd (Pitfall 5)` warning, so the lookup genuinely bites. ⛔ **`tools/claude_adapter.py` MODEL was LEFT on 4-6** — it is the `claude` deep-research stream (every `low`-stakes angle + the high-stakes redundancy copy), so **that stream gets no saving**; moving it changes research OUTPUT, not just cost. Consequently the UI label at `pipeline.py:4762` (`"Claude claude-sonnet-4-6 +web"`) is still **TRUE** and was correctly left alone — changing it would have made the UI assert a model the run never calls. Analysis/critique tooling (`critique/judge.py`, `content_compare.py`, `outcomes_spike.py`, the quality-gate rubrics) also stays on 4-6. Tests: only `test_tribunal_intake.py` touched — the literal pin updated, and deliberately NOT rewritten as `== _INTAKE_MODEL` (which would compare the constant to itself and pass for any value); TWO arms **added** — the intake/skeptic equality invariant (documented since 260721-twy, never tested) and a G-7 price-row guard. Gate **1943 passed** identical before and after; the 1 remaining failure proven pre-existing by reverting `intake.py` alone. ⚠ trap seen again: `test_outcomes_spike.py` shows 10 failures alongside other files, **32 passed alone** | 2026-09-01 | df131ea | [260901-j6w-move-the-tribunal-engine-from-claude-son](./quick/260901-j6w-move-the-tribunal-engine-from-claude-son/) |
| 260831-mgg | **The dead "Research artifacts" block is gone.** 1 commit `cbb8503`, **+10 / −1031** across 5 files. Operator saw *"No research questions yet — they appear as soon as the intake is decomposed."* on an intake that WAS decomposed with a finished run. ⭐ **IT WAS DEAD UI THAT COULD NEVER RENDER ANYTHING ELSE:** `ResearchArtifactsInner`'s `reload()` hardcoded `setQuestions([]); setArtifacts([])`, and there was **not one fetch in the whole 853-line file** — no `apiFetch`, no `useQuery`, no `fetch(`. So `visibleQuestions.length === 0` was permanently true, the empty-state paragraph was the only reachable output, and the General/upload/manual-note subtree beneath it was unreachable **by construction** (it renders only when `generalArtifacts.length > 0 \|\| visibleQuestions.length > 0`, both pinned to zero). ⚠ **THE STUB COMMENT'S OWN PREMISE WAS FALSE** — it claimed *"the block is gated off"*, but `showResearch = phaseShowsResearch(currentPhase)` is TRUE for `in_research`, `awaiting_report_upload`, `awaiting_results_send`, `completed` AND `archived`. It had been rendering the whole time; someone stubbed the loader believing it was invisible. Removed: the component (853 lines — `ResearchArtifactsBlock`, `ResearchArtifactsInner`, `QuestionBlock`, upload handlers, source-label maps), the import + `showResearch` const + mount in `admin.pulse.intakes.$id.tsx`, and the entire **`artifacts` i18n namespace — 54 keys × 3 locales**, used by nothing else (every other `artifacts.` hit in `src/` is a JS member access like `artifacts.length`, not a translation key). A tombstone comment sits at the old mount site so nobody "restores" it. **`phaseShowsResearch` DID become an unused import in the route and was removed** — ⚠ note `tsc` proved NOTHING there, `tsconfig.json` has `noUnusedLocals: false` so the compiler stays silent on dead locals; the unused-ness was established by grep. It stays EXPORTED from `intake-phase.ts` (consumed by `phaseShowsSemanticSearch`) and that module was untouched, as were `research-question.ts` (its helpers are shared with `ContextPackBlock` + `ResearchResultsPanel`), the phase machine, and `hasArtifacts` (still feeds `showSemanticSearch`). The surviving `results.noQuestions` at `:111` is a DIFFERENT key and correctly kept. **No capability lost** — the block's `onStartResearch` prop was `void`ed with the comment "banner handles it"; the live trigger is `NextStepBanner`'s `onStartAutoResearch` → `triggerResearch(id)`. Gates (orchestrator re-ran all): key parity **634→580** in each locale, 0 missing / 0 extra in all four directions, **0** `artifacts.*` keys left; `tsc` **0 errors**; vitest **140/140, 9 files, unchanged**; `i18n-audit` **PASS**, advisories **107→104** — exactly the 3 belonging to the deleted `.tsx`. ⛔ **NOT DEPLOYED** — the live service still renders the empty card. ⛔ **UNOBSERVED:** no `.tsx` test exists in this repo and none ever covered this component; 140/140 shows nothing else regressed, it is NOT evidence the route renders correctly without it | 2026-08-31 | cbb8503 | [260831-mgg-remove-the-dead-research-artifacts-block](./quick/260831-mgg-remove-the-dead-research-artifacts-block/) |
| 260831-lpm | **The research-start banner no longer names three services that do not run.** 1 commit `6d474e1`, copy-only, 6 strings across `nl`/`en`/`fr` `intake.json` (`nextStep.researchStartBody` + `researchConfirmBody`). Operator asked what *"Dit lanceert **SerpAPI + SearchAPI + Apify** (rag-web-browser + website-content-crawler)"* meant; it is stale Supabase-era copy from the retired `run-research` edge function. ⭐ **VERIFIED AGAINST THE LIVE ENGINE, AND IT IS WORSE THAN TWO-OF-THREE STALE:** `SearchAPI` and `Apify` have **zero** references anywhere in `tribunal/`; `SerpAPI` survives ONLY inside the `own` stream, which **Phase 15.6 removed from the live rotation per D-W3-3** (`research_division._D6_STREAMS = ("gemini","openai","claude")`) after it failed 2 of 4 angles on run `7dcf51d5`, answered ENGLISH in a Dutch run and contributed 2 unique URLs. `own` is reachable only on a rarely-taken **degraded broadcast** path — so on a NORMAL run **none of the three named services runs at all.** Three further false claims: *"2–5 artifacts per question"* (the output is a synthesised report), *"klaar binnen 2–5 minuten"* against a poll budget of **70 × 30s = 35 min PER ANGLE** with `_MAX_ANGLES = 28`, and the manual-add sentence (`hasResearchArtifacts` is hardcoded `false` pre-`decomposed`, `admin.pulse.intakes.$id.tsx:307`). ⚠ **THE REAL RISK WAS THE UNDERSELL:** the button POSTs `/intakes/{id}/research` and starts the paid Tribunal run, while the banner promised a cheap 2-minute scrape and the confirm dialog said only *"enkele minuten … API-kosten"* — prior runs land near **$45**. New copy names Gemini/OpenAI/Claude, states tens of minutes with the 35-minute silence called out, and puts *betaalde run · tientallen dollars · niet terugbetaald bij annulering* in the confirm dialog where the decision is made. **DELIBERATELY NO HARD DOLLAR FIGURE** — a number in UI copy is precisely what rots into the next stale claim. **`own`/SerpAPI deliberately NOT mentioned**: naming a rare degraded fallback in the main banner would re-create the defect in a new form. ⚠ **`researchStartBody` IS a `<Trans>`** (`NextStepBanner.tsx:296-300`, `components={[<strong />]}`) so its `<0>` slot is load-bearing — verified 1 open / 1 close in all three locales; **`researchConfirmBody` is a PLAIN `t()`** inside `<AlertDialogDescription>` (`:444`), where any markup would render as literal text — verified 0 tags / 0 `**` in all three. Gates (orchestrator re-ran all): JSON parse ×3, key parity **634/634/634** 0 missing, stale terms absent from both keys, `tsc` **0 errors**, vitest **140/140**, `node scripts/i18n-audit.mjs` **PASS** (107 CHECK D advisories all pre-existing `.tsx` warnings; no `.tsx` touched). `ResearchArtifacts.tsx`'s historical `serp_api`/`serpapi` source labels correctly untouched. ⛔ **NOT DEPLOYED** — the live service still shows operators the false text; ships with the next `nestor-frontend` build. ⛔ **UNOBSERVED:** no `.tsx` test exists in this repo, so the `<Trans>` interpolation is verified by inspection + tag-balance assertion, **never by rendering** — the same gap that let a Phase-23 label assert the opposite of its own figure past every green gate | 2026-08-31 | 6d474e1 | [260831-lpm-correct-the-stale-research-start-banner-](./quick/260831-lpm-correct-the-stale-research-start-banner-/) |
| 260831-ksq | **The `agent_done` feed row dropped its fact count** — `Angle 03 done — an unknown number of facts · claude` is now `Angle 03 done · claude`. 2 commits `95f9d95`/`3ecfecd`, operator ruling. ⭐ **WHY THE CLAUSE WAS NOISE:** `_fact_count_label` printed a number only when the provider's result carried a countable `facts` list, and **three of the four streams never do** — `gemini`, `openai` and `claude` all resolve to adapters returning a `{status, report}` prose envelope (`tools/claude_adapter.py` + the two raw poll methods in `audit/audited_llm_client.py`); only the fourth stream, `own` (`own_researcher.py:1063-1073`), sets `facts`. So the row said *"an unknown number of facts"* on nearly every line. ⚠ **The `own` stream's REAL count is genuinely lost from this row** — operator was told before agreeing. ⛔ **THE TRAP: deleting the helper nearly killed a structural proof.** `test_j_the_done_line_is_still_built_inside_the_emitters_try` proves **D-06** by monkeypatching `_fact_count_label` to raise, asserting the row degrades instead of escaping into `run_angles` — the guarantee whose absence lost ~20 `agent_done` rows on run `7dcf51d5` (D-V01-7), leaving the feed showing angles that started and never ended. **This edit WAS the "future edit" that docstring warned about.** ⭐ **The planner rejected BOTH orchestrator-proposed fixes, correctly:** *(a)* keeping the helper as a dead lever is **impossible, not merely untidy** — monkeypatching a function production no longer calls cannot make the thunk raise, so the test would go **RED AGAINST CORRECT CODE**, which is exactly how a real assertion gets deleted; *(b)* the proposed fallback lever (a `result` whose `.get` raises) is **unreachable** — `_record_result` is handed `_enriched`, built by dict-unpacking at `:2494`, so its `.get` cannot raise, and `result.get("status")` at `:2488` runs before the emit and outside any try, killing the paid angle rather than degrading the row. Resolution: helper deleted, lever re-pointed at a new `_agent_done_text(angle_no, provider)` that **production genuinely calls inside the thunk**. **RED-proved** (7 failed / 60 passed against unedited source, including the countable case `'Angle 01 done — 3 facts · openai'`) and **MUTATION-proved** — hoisting the construction above `emit_safe` makes the `RuntimeError` escape through `_record_result` → `_one_angle`, test red; reverted, green. **Both proofs independently re-run by the orchestrator.** Scope held: both `agent_fail` lines keep `· 0 facts ·` (zero is TRUE on a failed angle), `meta` byte-identical, `build=lambda:` still a thunk, `own_researcher.py` empty diff. `test_run_event_emit.py` **67/0/0**; 140 across the three related files, 0 skipped. Test-function count flat 52→52 so `EXPECTED_FILES=45` and `cloudbuild.test-engine.yaml:514` need no edit. ⚠ **ONE PLAN GATE WAS UNSOUND AND WAS REPORTED, NOT SATISFIED** — it demanded zero occurrences of `_fact_count_label` / "unknown number of facts" while the same plan mandated a docstring quoting both to explain the removal; unsatisfiable by construction. Sound form proven instead: `hasattr(rd,'_fact_count_label')` → **False**, `hasattr(rd,'_UNKNOWN_FACTS')` → **False**, remaining hits all comment prose. ⛔ **NOT DEPLOYED** — ships with the next `tribunal-worker`/`tribunal-api` build alongside the unbuilt `260831-jx2`. ⛔ **UNOBSERVED:** nobody has seen the shortened row in a live feed | 2026-08-31 | 3ecfecd | [260831-ksq-drop-the-fact-count-from-the-angle-done-](./quick/260831-ksq-drop-the-fact-count-from-the-angle-done-/) |
| 260831-jx2 | **The deep-research long poll no longer narrates itself in the run feed.** 3 commits `44541be`/`972e21d`/`df36c14`. Operator request, verbatim: *"remove these logs from deep research"* — the live feed was repeating a dispatch announcement plus a strided *"Still waiting … THIS IS A WAIT, NOT A STALL."* heartbeat for both providers. Removed **exactly 4** `run_events.emit_safe(kind="thinking")` blocks in `audit/audited_llm_client.py` (Google announcement + heartbeat, OpenAI announcement + heartbeat); `thinking` emissions **8 → 4**, `agent_fail` **5 → 5 untouched** — provider failures still reach the feed, only the waiting chatter went. `_POLL_EVENT_STRIDE` was left dead by the deletion and removed with it (env var `NESTOR_RUN_EVENT_POLL_STRIDE` is now inert). ⚠ **ACCEPTED CONSEQUENCE: up to 35 minutes of total feed silence during a deep-research call** — this is precisely the shape that on 2026-07-27 was misread as a stall, cost an hour and nearly re-executed a paid run. The incident history is preserved in the source and in the test docstring, flagged as *considered and overruled*, so a future reader does not "restore the heartbeat" as a bug fix. ⭐ **THREE stale narratives, not one:** the module comment at `:100-105` AND the module docstring at `:34-40` both still asserted the removed behaviour, and so did coverage item 25 in the test file — fixing only the first would have shipped two fresh lies in the same change. ⚠ **THE OBVIOUS GATE READS RED ON CORRECT CODE:** a repo-root `grep -rn` matches the orphaned `.claude/worktrees/agent-af281d695d9b34c35/` file tree (a stale leftover holding every removed string; NOT a registered worktree) and the `.pyc` as a binary hit — every gate is therefore path-scoped with `-I --exclude-dir=__pycache__`. The absence gate deliberately does NOT cover the test file, which must name the forbidden strings in order to assert them absent. The pinning test was **inverted, not deleted** (`test_a_long_poll_says_in_words_that_it_is_a_wait` → `test_a_long_poll_emits_no_waiting_chatter`) and keeps a `status == "success"` guard proving the deletion took the narration and left the 31-poll machinery intact. **RED-proved and independently re-proved by the orchestrator** against the unedited source: it failed naming the exact 4 lines the operator pasted (dispatch + polls 10/20/30). Suite **69 passed / 0 failed / 0 skipped**, orchestrator-verified — `tribunal/pyproject.toml` requires `>=3.11` and gcloud's interpreter is 3.11.9, so unlike the backend this suite DOES run locally; `openai` was installed deliberately because the 4 default skips were the OpenAI resume tests and this change edits OpenAI code. 10 failures in `test_outcomes_spike.py` were **measured, not assumed** pre-existing (identical 10 ids at base and HEAD). No cloudbuild change — both files already registered in `cloudbuild.test-engine.yaml`, and a rename moves neither file nor test count. ⛔ **NOT DEPLOYED** — ships with the next `tribunal-worker` / `tribunal-api` build; until then the live services still emit the lines. An already-finished research run is unaffected. ⛔ **UNOBSERVED:** nobody has watched the feed go quiet; the harness stubs `asyncio.sleep`, so the real 35-minute silence has not been experienced by anyone, and the OpenAI blocks are covered only by static grep plus the 15 passing resume tests | 2026-08-31 | df36c14 | [260831-jx2-remove-deep-research-long-poll-waiting-l](./quick/260831-jx2-remove-deep-research-long-poll-waiting-l/) |
| 260831-lm4 | **The intake skill now emits nl+fr+en for every generated string.** 5 commits `a374923`/`d47b22a`/`a2904a3`/`5e78394`/`17d1455`. Defect 1 of the 2026-08-31 operator test — client answered in English, asked for a French report, got proposals in **Dutch**. ⚠ **CAUSE CORRECTED MID-INVESTIGATION:** `NESTOR_INTAKE_SKILL_PROMPT` carries **NO language instruction at all** — it is simply written ENTIRELY in Dutch, field descriptions included, so the model answers Dutch. (An earlier note in-session blamed `prompts.py:141`'s explicit *"Schrijf in vloeiend Nederlands"*; that line belongs to `CONTEXT_PACK_SKILL_PROMPT`, a DIFFERENT skill — now DEF-QK-01.) The data was always there: `report_language` is a real radio and `_format_intake_markdown` renders every answer, so the model already received `**report_language**: fr`. **OPERATOR RULINGS:** all three languages in ONE call (no translation pass); the brief resolves to `report_language`. **D-1 — the tuned Dutch principles are byte-identical**; only the OUTPUT CONTRACT changed, because rewriting *"Niet braaf zijn"* in English risks changing WHAT the model produces while we only meant to change WHAT LANGUAGE. **D-2 — echoed text is never translated** (`current`/`original` are the client's own words; translating them would put words in their mouth AND make the diff UI compare a translation to an original). ⛔ **D-3 — `_APPLY_MAX_TOKENS` 8192→20000 and it MUST stay under ~21333**: the call is NON-STREAMING, and the Anthropic SDK refuses non-streaming requests above that, so the obvious "triple it to 24576" would have BROKEN THE CALL OUTRIGHT. **D-4 — fail loudly on truncation**; tripling output makes a `max_tokens` cut-off realistic for the first time, and without the guard a truncated reply recorded status **`succeeded`** (executor RED-proved this unprompted). ⭐ **THE EXECUTOR FOUND A SECOND DICT-REPR PATH THE PLAN MISSED, and a worse one:** `AIReviewPanel` overwrites the `decision_or_goal` ANSWER with the skill's `suggested` on accept, so the `[DECISION]` string the engine's Swiss tournament ranks materiality against would itself have been a Python dict repr; fixed via an **opt-in** `lang` param on `_first_nonempty` so sector/goals callers keep `str()` byte-for-byte. Also: `FieldDisplay`'s `list` case was a **crash**, not a cosmetic bug (an object as a React child blanks the page), and `pick`'s fallback scan had to be narrowed to nl/fr/en or a stakeholder row `{name,role,email}` would "resolve" to a name where a decision belongs. Task 3 (the ~$45 `brief.py` path) was RED-proved first: exactly 4 new tests failed against the unmodified `_item_text`, printing `[DECISION]` containing `{'nl': 'Moeten we uitbreiden?', ...}`. Backend **450 passed**/1 skipped; tsc 0; vitest **140** (135 + 5 new); i18n-audit PASS. ⚠ **4 backend tests fail, ALL PRE-EXISTING** (`test_ci_guard_raw_db`, `test_mail_render`, 2× `test_research_runs_migration` — one matches `server_default` inside the migration's OWN docstring); their subject files are provably untouched (`git diff 019ef7a..HEAD -- backend/` = 5 files, none related). ⛔ **The orchestrator could NOT independently re-run the backend suite** — this box's only interpreter is gcloud's Python **3.11.9** and the backend requires **≥3.12**; relying on the executor's run plus that structural argument. Docker IS present (29.6.2) — the `dev-machine-no-python-docker` note is stale. **Surface derived by import = {nestor-api, nestor-frontend}**; `tribunal/` imports NOTHING from `backend/app`. **⛔ NOT DEPLOYED at time of writing** | 2026-08-31 | 17d1455 | [260831-lm4-intake-skill-emits-all-three-languages](./quick/260831-lm4-intake-skill-emits-all-three-languages/) |
| 260903-fbt | **THE NESTOR PULSE HANDBOOK — `docs/handbook/`, 21 chapters, 7,793 lines, 31 Mermaid diagrams, verified at `c8b8583`.** Documentation only: **zero code changed, zero spend, no deploy** (`git diff --stat` over `backend/`+`frontend/`+`tribunal/` is EMPTY). Operator ask: exhaustive documentation start to finish with diagrams, schemas, reasoning, models-and-why, structure, architecture, benefits and market difference, module by module, then pushed. Method: SIX fact-sheet agents produced ~3,300 lines of `path:line`-cited evidence in the scratchpad; FIVE writer agents wrote the module chapters (06, 07, 08, 12, 13) against a binding style guide; the orchestrator wrote the twelve reasoning-heavy chapters (00-04, 14-20) and, after THREE agents hit the 2:10pm session limit, also 05, 09, 10, 11. ⭐ **Chapter 17 consolidates ~200 decisions across 14 identifier families into ONE ADR register**; module chapters link by id rather than restating, and superseded rulings are KEPT AND MARKED per project convention. Two synthetic families (`P-01..13` founding, `M-01..10` milestone) were introduced for decisions the record states without ids, and are labelled as handbook numbering in ch. 20 so they cannot be mistaken for planning ids. ⚠ **ONE SOURCE CORRECTION MADE:** `D-R4` was recorded as "an LLM groups winners into ≤5 groups" — true as the ruling, but `D-W4-4a` (2026-07-31) later made **one deterministic group per client question the PRIMARY path** with topic mode kept as an option; both are now recorded with the supersession visible (ch. 04 + ch. 17 fixed). Two figures that DISAGREE between sources are stated as disagreeing rather than reconciled: frontend tests (136 `it()` counted vs 140 in STATE.md) and which Anthropic secret wins at runtime (deploy mounts `Nestor_Claude2`, the in-process bootstrap re-exports `Nestor_Claude`). ⭐ **Nothing was smoothed over** — every contradiction the sheets found is in the owning chapter's "Known gaps and traps": 59 from the Tribunal service sheet alone, the frontend's dead code plus embedded legacy Supabase credentials in `frontend/scripts/*.ts`, the backend's route-table test contradiction, the engine's two-policy-form inconsistency. Writer agents independently re-derived cites and reported corrections (one wrong fact-sheet cite, three recomputed offsets, four ranges, twelve ranges, one memory-only revision id removed). ⛔ **`.claude/worktrees/` excluded by instruction** (orphaned stale copy; it has twice made correct deletions read as incomplete). ⛔ **Nothing verified by RUNNING the system** — the handbook documents the tree and the recorded runs; every figure for the 2026-09-01 models is marked as arithmetic. Verification: 21 files, 0 missing internal links, all fences balanced. `README.md` gained a pointer paragraph | 2026-09-03 | 82cb9be | [260903-fbt-write-the-exhaustive-project-handbook-do](./quick/260903-fbt-write-the-exhaustive-project-handbook-do/) |

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

Last session: 2026-09-03T10:43:18.426Z
Stopped at: context exhaustion at 83% (2026-09-03)
  committed 54dcc1e). Standing operator direction 2026-07-24 unchanged: run ONE combined Phase-15*
  UAT once 15/15.1/15.2 are all ready (against a live run post-2026-08-01) — do NOT UAT piecemeal.
  15.1 needs NO live LLM runs: its CI proof is a deterministic replay of the recorded 1,162-claim
  fixture; the real-classifier calibration check is hand-run after the cap resets 2026-08-01.
Resume file: None

## Operator Next Steps

- 2026-07-22: Phase 19 DEFERRED (operator) — stabilization/audit-fix pass first: F-01 tribunal group-skeptic JSON-string crash, F-02 CORS_ALLOWED_ORIGINS startup crash, F-03 4 mail test-harness defects, frontend/.env Supabase cleanup, Cloud Build suite rerun (closes a Phase-20 CLOSE-02 chore early).
- OPERATOR ACTION (blocking further Tribunal runs): the Anthropic org MONTHLY usage cap tripped mid-run 2026-07-22 (self-configured console limit, resets 2026-08-01) — raise/remove it in the Anthropic console before any new live run.
- After stabilization: resume with /gsd-discuss-phase 19 (Q&A chat). Remaining order stays 19 → 15 → 20.
- Phase 19 reminders: verify voyage-3-large 1024-dim against vendor docs BEFORE the column migration; provision VOYAGE_API_KEY; chat retrieval joins the denial suite day one.
