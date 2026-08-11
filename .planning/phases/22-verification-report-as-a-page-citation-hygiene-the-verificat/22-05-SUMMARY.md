---
phase: 22-verification-report-as-a-page-citation-hygiene-the-verificat
plan: 05
subsystem: engine-verification-read-path
tags: [citations, dedupe, D-22-4, read-path, pydantic, rls, never-renumber]

# Dependency graph
requires:
  - phase: 22-01
    provides: "`collapse_citations_by_url` + `normalize_source_url` — the shared identity function this plan wires in, unchanged"
  - phase: 15.4
    provides: "`source.resolved_url` / `source.resolution_status` (migration 0016) — the columns `_source_resolution` reads"
  - phase: 15.2
    provides: "`number_citations` and its pinned 10-key entry shape — the input to the seam"
provides:
  - "One citation entry per normalized source URL on `GET /api/runs/{id}/verification`"
  - "`also_claim_ids` declared on `VerificationCitation` — the alias list now reaches the browser through the pydantic model"
  - "`_source_resolution` — a separate RLS-scoped read of the resolution columns, so `_CLAIM_SOURCE_SQL` stays pinned"
affects: [22-08, write-side-source-identity-phase]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Dedupe on the read path, downstream of numbering and upstream of the shaper — a pinned verbatim contract stays green by construction"
    - "A separate narrow read rather than widening a SQL whose result shape is pinned by a test"
    - "Declare, don't assume: a contract field is declared even under `extra=\"allow\"`"

key-files:
  created: []
  modified:
    - tribunal/nestor_pulse_sdk/runs/schemas.py
    - tribunal/nestor_pulse_sdk/verification/report.py

key-decisions:
  - "The mandated explanatory comment was written WITHOUT the literal token `also_claim_ids`, so the plan's `grep -c == 1` criterion stayed literally green without weakening the comment — the 22-02 grep-vs-mandated-prose contradiction was avoidable here, not inherent"
  - "`except Exception  # noqa: BLE001` for the UUID parse, matching `dedupe.py`'s own idiom in this phase, because totality is the point"
  - "Source ids de-duplicated before the `IN (...)` read — same result, smaller and deterministic query"
  - "Verified the new SELECT and the full wire serialization with a scratch harness, because the DB-bound citation tests skip locally without DATABASE_URL"

requirements-completed: [D-22-4]

# Metrics
duration: 22min
completed: 2026-08-11
tasks: 2
commits: 2
---

# Phase 22 Plan 05: Wiring the Shared Identity Function into the Read Path Summary

**`collapse_citations_by_url` now runs inside `build_verification_report` between `number_citations` and the shaper, fed by a separate RLS-scoped read of `source.resolved_url` / `resolution_status`, so one normalized URL renders as one number — with every survivor keeping the number `number_citations` assigned it and the absorbed claims' ids riding to the browser on a newly declared `also_claim_ids` field.**

## Performance

- **Duration:** ~22 min
- **Completed:** 2026-08-11
- **Tasks:** 2
- **Files modified:** 2 (0 created), 90 insertions, **0 deletions**

## Accomplishments

- **The seam is at the one place that breaks nothing.** The dedupe call sits at `report.py:738` — after `number_citations` (712) and before `shape_verification_report` (740). Because it runs *before* the shaper, `test_verification_report_endpoint.py`'s `assert report["citations"] == entries, "citations must ride through verbatim"` stays green **by construction** rather than by adjustment. Measured: **9 passed before, 9 passed after.**
- **`also_claim_ids` reaches the browser — proven, not assumed.** The endpoint does `VerificationReport.model_validate(report)` under `response_model=VerificationReport` (`runs/api.py:968,1003`), so the field had to be declared to be load-bearing. Driven end to end through the real shaper and the real model: the survivor emerges with `also_claim_ids == ["c2"]` and `list` type on the wire.
- **No number was reassigned anywhere.** The `enumerate(|[.n.] *=` grep on `report.py` measured **0 before the edit and 0 after**. The end-to-end run emits numbers `[1, 3]` from a 3-entry fixture whose second row is the same page as the first: number 2 is gone and **3 was not pulled down to 2**. The sparseness is the intended output.
- **Three pinned upstream contracts left alone.** `citations/numbering.py`, `synthesis/steps.py`, `pipeline/tribunal/pipeline.py` and all of `backend/` are **byte-identical to the phase base** (`git diff --quiet` against `3a0d74e`, each checked individually). `_CLAIM_SOURCE_SQL` did not gain a column; the resolution columns come from a separate read instead.
- **The new read widens no scope and costs nothing on an empty run.** Same session, same tenant context, filtered to ids `number_citations` already returned for this run, selecting exactly three columns. Empty input and all-unparseable input both return `{}` **without touching the session** — verified by calling the helper with `session=None`.

## Task Commits

1. **Task 1: Declare `also_claim_ids` on the wire model** — `57be129`
   - `tribunal/nestor_pulse_sdk/runs/schemas.py`, single hunk inside `VerificationCitation`, 13 insertions / 0 deletions
2. **Task 2: The dedupe seam in `build_verification_report`** — `be923ab`
   - `tribunal/nestor_pulse_sdk/verification/report.py`, 4 hunks (2 import lines, the 49-line helper, the 26-line seam + comment), 77 insertions / 0 deletions

## Verification Results

Run with the venv21 python from `tribunal/`. **Every baseline was measured at HEAD before editing**, per the phase's acceptance-criteria integrity rule.

| Check | Baseline (pre-edit) | After | Verdict |
|-------|--------------------|-------|---------|
| `test_verification_report_endpoint.py` | **9 passed** | **9 passed**, 0 failed | PASS — unchanged, as the plan required |
| `test_verdict_publication.py` + `test_verification_buckets.py` (with the endpoint file) | — | **43 passed**, 0 failed | PASS |
| `test_verification_report_endpoint` + `dedupe` + `citation_anchors` + `suite_hygiene` | — | **98 passed**, 0 failed, 0 errors | PASS |
| Full plan `<verification>` set (6 files) | **132 passed** (9 + 123) | **132 passed**, 0 failed, **0 errors** | PASS — exactly unchanged |
| `grep -c also_claim_ids schemas.py` | 0 | **1** | PASS (criterion: `1`) |
| `grep -cE "duplicate_count\|duplicates_removed" schemas.py` | 0 | **0** | PASS |
| `grep -c collapse_citations_by_url report.py` | 0 | **2** (import 41, call 738) | PASS (criterion: `2`) |
| call ordering | — | 712 `number_citations` < **738 call** < 740 shaper | PASS |
| `grep -cE "enumerate\(\|\[.n.\] *=" report.py` | **0** | **0** | PASS — no number assignment introduced |
| `grep -cE "duplicate_count\|duplicates_removed" report.py` | 0 | **0** | PASS |
| `git diff --name-only 3a0d74e` | — | exactly the **2** files in `files_modified` | PASS |
| `numbering.py` / `synthesis/steps.py` / `pipeline.py` / `backend/` | — | **byte-identical to base** | PASS |
| no `google.cloud` / `storage` / `gcs` import added | — | none — the two added imports are `citations.dedupe` and `db.models.source` | PASS (module docstring ban honoured) |

**Additional verification beyond the plan** — because the DB-bound `test_citation_numbering.py` / `test_citation_roundtrip.py` skip cleanly without `DATABASE_URL` and so exercise neither the new SELECT nor the wire shape, both were proven directly with a scratch harness:

- The new statement compiles against the postgres dialect: `SELECT source.id, source.resolved_url, source.resolution_status FROM source WHERE source.id IN (...)` — three columns, nothing widened.
- `_source_resolution(None, [])` → `{}` and `_source_resolution(None, ["not-a-uuid", ""])` → `{}`: the empty-input short circuit and the defensive UUID skip both hold, and neither raises.
- `VerificationCitation` defaults `also_claim_ids` to `[]` and round-trips `["c9","c10"]`.
- Full path — `collapse_citations_by_url` → `shape_verification_report` → `VerificationReport.model_validate` → `model_dump` — gives `numbers [1, 3]`, `aliases [["c2"], []]`, and the verbatim ride-through assertion holds inside the harness too.

⛔ **No yield claim is made.** The fixture above is a hand-built 3-entry list chosen to exercise the mechanism, **not a measurement of any run**. How many duplicates collapse in production depends entirely on how often the best-effort HEAD resolution succeeded on `vertexaisearch` redirect tokens in that run, which is runtime data. This plan proves MECHANISM only — *same normalized key ⇒ one entry* — and no count field is emitted anywhere.

⚠ **Read-time dedupe changes DISPLAY only.** Cost and corroboration metrics still count the duplicate `source` rows until the write-side identity fix lands in its own phase. Nothing in this change claims otherwise, and the seam comment says so in the code.

## The `also_claim_ids` Seam — RESOLVED (emitted, not deferred)

The orchestrator flagged this as a live cross-plan seam: 22-02 built `buildCitationIndex` to honour an `also_claim_ids` alias list, and at Wave 1's end **nothing emitted it**, so the marker-loss protection was inert dead code.

It is now emitted, and the whole chain is verified:

1. `collapse_citations_by_url` (22-01, unmodified) sets `also_claim_ids` on every survivor — `[]` when it absorbed nothing, the absorbed entries' `first_claim_id`s otherwise (`dedupe.py:292,299-305`).
2. Task 2 wires that function into the one read path the verification page uses.
3. Task 1 **declares** the field on `VerificationCitation`. This was load-bearing, not cosmetic: the endpoint validates through `VerificationReport.model_validate` under `response_model=VerificationReport`, so leaving the field to `extra="allow"` would have made the contract depend on a `model_config` nobody would think to protect.
4. It crosses the intake backend's verbatim proxy unchanged (that file is untouched).
5. 22-02 declared the frontend `Citation.also_claim_ids` as **optional**, so a rolling Cloud Run deploy that briefly serves the old payload degrades safely to strict-`first_claim_id` behaviour rather than breaking.

**Nothing about this seam is deferred.** The remaining consumer step is 22-08's switchover of `VerificationReport.tsx` to `buildCitationIndex`, which is that plan's declared scope — the payload it needs now exists.

## Deviations from Plan

### 1. [Environment] The prompt and the plan named two different test venvs

- **Found during:** setup, before Task 1.
- **Issue:** the plan's acceptance criteria name `.../04a721f7-.../scratchpad/venv21/Scripts/python.exe`; the executor prompt's `<local_test_environment>` names `.../66e17830-.../scratchpad/venv/Scripts/python.exe`. **Both exist on disk.**
- **Resolution:** used the plan's `venv21`, since every acceptance criterion is written against it and the baselines it must be compared to (`9 passed`) were measured with it. It reproduced the plan's stated baseline exactly, which confirms the right interpreter.
- **Impact:** none on output.

### 2. [Stale worktree base — the 25th occurrence] Spawned 882 commits behind

- **Found during:** first action.
- **Issue:** the worktree spawned at `a3a0c96` — the same stale commit every previous executor in this project has hit — with `merge-base != 3a0d74e` and **882 commits behind**.
- **Fix:** corrected with `git reset --hard 3a0d74e` after the HEAD/branch-namespace assertion passed, then all four positive-presence sentinels were checked and passed.
- **Worth repeating:** `git rev-list --count HEAD..base` would have looked survivable and the *sentinels* are what make this safe — had I trusted a count, Task 2's `from nestor_pulse_sdk.citations.dedupe import ...` would have failed with `ModuleNotFoundError` and looked like a plan error rather than a base error.

## Decisions Made

- **The explanatory comment deliberately avoids the literal token `also_claim_ids`.** Task 1 mandates a comment explaining the field *and* a `grep -c also_claim_ids == 1` criterion. Those can collide — it is exactly the contradiction that forced 22-02 to reconcile its `normaliz` grep. Here it was **avoidable without any loss**: the comment refers to "this list" and explains the mechanism in full, so the criterion is literally green *and* the comment is complete. **No criterion was weakened and no truthful prose was deleted.** Recommendation for future plans: assert the absence/presence of an *identifier declaration*, not a bare substring that mandated prose may legitimately contain.
- **`except Exception  # noqa: BLE001` for the UUID parse** rather than a narrow `(ValueError, TypeError)` tuple. The plan asked for a skip-not-raise; `dedupe.py` in this same phase uses exactly this idiom for the same reason. One malformed id must not be able to fail an operator's whole verification report, and totality beats precision here.
- **Source ids are de-duplicated before the `IN (...)`.** The plan's text passes the raw list. A `seen` set keeps the query small and its parameter list deterministic; the returned mapping is identical either way.
- **`c["source_id"]` kept as the plan wrote it**, not softened to `.get`. The 10-key entry shape is pinned by a test, so a missing `source_id` would be a broken contract that should surface loudly rather than silently produce an unresolvable citation.

## Acceptance-Criteria Integrity Note

**Every criterion in this plan was satisfiable as literally written, and none was vacuous or already failing at HEAD.** This is the first plan in the last several not to need a reconciliation, and two criteria are worth naming because they are the kind that usually go soft:

- **The `enumerate(|[.n.] *=` criterion** asks for the count "compared against the pre-change count, stating both numbers". Both are **0**. Note that this criterion is *weak on its own* — it was already 0, so it could not have caught renumbering written any other way (e.g. `entry["n"] = i`). It was therefore backed with the stronger positive check: the end-to-end path emits `[1, 3]`, proving no renumbering behaviourally rather than by absence of a token.
- **The 9-passed criterion** is the one that would have caught a seam placed after the shaper. It was measured at HEAD first (**9**), so the post-change **9** is evidence of preservation and not a coincidence of never having been measured.

## Known Stubs

None. Both changes are fully implemented and in the live read path. `_source_resolution` is called on every verification-report load; `also_claim_ids` is emitted on every citation entry.

## Threat Flags

None. No new endpoint, auth path, file access or schema change. The plan's register is satisfied as written:

- **T-22-12** (info disclosure via the new read) — same session, same tenant context, three columns, filtered to ids already returned for this run. Scope unwidened.
- **T-22-13** (hostile `resolved_url` reaching the parser) — `normalize_source_url` is total and pinned as never-raising by 22-01; its result is used only as a dict key, never to build a request.
- **T-22-14** (one extra query) — accepted as planned, and skipped entirely for a run with no citations (verified).
- **T-22-15** (page vs frozen deliverable disagreeing about `[n]`) — no number reassigned; verified behaviourally.
- **T-22-SC** — **no package was installed.** The change uses stdlib `uuid` plus SQLAlchemy and models already imported in this service.

## Notes for the Next Plan

- **22-08** can now rely on `citation.also_claim_ids` being present on every entry from a current backend. It is `[]`, never absent, when nothing was absorbed — so `Array.isArray` is satisfied and `buildCitationIndex`'s alias branch is live.
- **Do not close the number gaps in the frontend either.** The payload is deliberately sparse; a UI that renumbers reintroduces exactly the page-vs-deliverable divergence this plan preserved.
- **The write-side identity fix is still outstanding** (its own phase, per D-22-4 sequencing). Until it lands, duplicate `source` rows still exist in the DB and still count toward cost and corroboration — only the display collapses.

## Self-Check: PASSED

Re-verified against disk and git after writing:

- **Files (2/2 FOUND, both modified):** `tribunal/nestor_pulse_sdk/runs/schemas.py`, `tribunal/nestor_pulse_sdk/verification/report.py`
- **Commits (2/2 FOUND):** `57be129`, `be923ab`
- **Line/hunk counts as stated:** measured with `git diff --stat` and `git diff -U0`, not estimated — 13 + 77 insertions, 0 deletions, 1 + 4 hunks
- **No deletions in either commit:** `git diff --diff-filter=D HEAD~1 HEAD` empty for both
- **No untracked files left behind**
- **STATE.md and ROADMAP.md NOT touched** — orchestrator-owned, as instructed

Not claimed and not verifiable from here: that the Cloud Build engine gate is green (no build submitted — DEF-22-02 records the local ceiling), and that any real run's citations collapse, which needs a run.

---
*Phase: 22-verification-report-as-a-page-citation-hygiene-the-verificat*
*Completed: 2026-08-11*
