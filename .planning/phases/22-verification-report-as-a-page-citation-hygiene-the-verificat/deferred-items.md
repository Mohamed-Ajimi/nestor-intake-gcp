# Phase 22 — deferred items (out of scope, logged not fixed)

Executors append here. Out-of-scope discoveries logged during execution. Per the executor scope
boundary these were NOT fixed: each entry is a pre-existing condition, or a consequence of a ruled
decision, discovered while executing a plan but outside that plan's scope boundary.

> **⚠ THIS FILE IS CREATED ONCE, BY PLAN 22-01, IN WAVE 1.** Phase 21 produced an add/add merge
> conflict because plans 21-01 and 21-02 each created their own copy in their own worktree. The
> other wave-1 plans (**22-02, 22-03, 22-04**) must record deferred discoveries in their **own
> SUMMARY** instead. Plans in **wave 2 and later** append here directly.

---

## DEF-22-01 — `ResearchRunProgress`'s component body becomes unrendered but stays compiled

**Found during:** phase 22 planning; seeded by plan 22-01 Task 3 (this plan creates the file)
**Status:** deferred by recommendation — **the FILE must survive; only the ELEMENT is removed**
**Owner:** unassigned. A later cleanup change, not phase 22.

### The situation after D-22-5

Plan 22-04 removes the embedded `ResearchRunProgress` element from
`frontend/src/routes/admin.pulse.intakes.$id.tsx` (D-22-5, operator verbatim: *"activity shouldnt
show on the intake page"*). After that removal the `ResearchRunProgress` **component** has zero
render sites, while the **module** must stay, because the run page imports a hook out of it:

```
frontend/src/routes/admin.pulse.runs.$runId.tsx:11
  import { useActiveResearchRun } from "@/components/intake/ResearchRunProgress";
```

⛔ **DO NOT DELETE `ResearchRunProgress.tsx`.** Deleting it breaks the very run page this phase is
built around.

**Measured on the tree at the phase base commit (`9afdf2d`):** the file is 938 lines. Its top-level
declarations are `toStageRows` (106), `useActiveResearchRun` (158, exported), `OpenRunLink` (214),
`StageIcon` (228), `fmtDurationSecs` (238), `StageSummaryCard` (250), `AgentCard` (276),
`RawOutputControls` (392), `AgentFeed` (504) and `ResearchRunProgress` (586). The unrendered
component body is therefore **lines 586-937, ~352 lines**, plus the presentational helpers that only
it uses.

### Why leaving the body in place is the recommendation

22-RESEARCH § Open Question 2 recommends leaving it. Two reasons:

1. **D-22-5's ask is fully satisfied by the element removal.** The operator asked that the activity
   feed not *show* on the intake page. Removing the render site does exactly that. Deleting the
   body delivers nothing further that the operator can see.
2. **A ~350-line deletion widens the blast radius for no operator-visible gain**, in a phase whose
   acceptance rests on single-path diffs. A partial deletion that leaves orphaned state, imports,
   queries or subscriptions behind is the specific failure mode to avoid — and it is more likely
   than not in a file this size.

**Whoever picks this up:** delete the component body, its exclusive presentational helpers, and the
now-unused imports / locale keys **in one dedicated change**, keeping `useActiveResearchRun` and
`OpenRunLink`'s replacement intact. Verify by loading both the intake detail page and the run page.

### Also recorded here, both pre-existing and both untouched

**(a) `export { triggerResearch };` at `ResearchRunProgress.tsx:938` has zero importers — dead code.**
Verified by a repo-wide grep over `frontend/src/**/*.ts{,x}`: every consumer imports that function
from `@/lib/api/research` directly, never from this module —
`components/research/RunActions.tsx:13` and `routes/admin.pulse.intakes.$id.tsx:55`. The re-export
is a leftover. It predates phase 22 and is not part of D-22-5.

**(b) `AuditBodyPanel.tsx:45`'s comment is already stale, and the stale part is the SECURITY
claim.** The docstring reads:

> Superadmin-only by placement (imported only from ResearchRunProgress, which mounts only on the
> admin intake detail route).

That parenthetical is false as of phase 21: `routes/admin.pulse.runs.$runId.tsx:12` also imports
`AuditBodyPanel`, and renders it at `:196`. The **conclusion** still holds — the run route is also
admin-gated — but the **stated reason** no longer does, and a superadmin-only-by-placement argument
that names the wrong placement is the kind of comment a future reader will rely on. Worth correcting
whenever that file is next touched; not corrected here because phase 22 plan 22-01 touches only the
Python engine.

### ⚠ Correction to this plan's own text

`22-01-PLAN.md`'s Task 3 wording names the importer as `admin.pulse.runs.$runId.index.tsx`. **That
file does not exist.** The route file is `admin.pulse.runs.$runId.tsx` (the only `runs` route file
in `frontend/src/routes/`), and the import is on line 11. Recorded so a later reader does not go
looking for a file that was never there.

---

## DEF-22-02 — two engine-gate test files cannot run locally on Windows (env-var length ceiling)

**Found during:** 22-01 Task 3, while running the full 45-file engine gate locally to prove the
`EXPECTED_FILES=45` bump does not break it
**Status:** deferred — **a LOCAL HARNESS limitation, not a code defect and not a gate defect.** Both
files are untouched by phase 22 and both were already in the 44-file list before this plan.

### What was measured

Running the 45 files the gate names, with the venv python on this Windows machine:

| Set | Result |
|-----|--------|
| the 44 files other than `test_fact_list_parser.py` | **1824 passed, 13 skipped, 4 errors** |
| the 4 errors | ALL of them in `test_dispatch_pii.py::test_never_raises`, all `ValueError: the environment variable is longer than 32767 characters` |
| `test_fact_list_parser.py` alone | **cannot even be collected** — same `ValueError`, raised at `<frozen os>:685 __setitem__` |

### Mechanism

Both files parametrize `test_never_raises` / `test_parser_never_raises` with deliberately enormous
hostile input strings (thousands of `x` characters — correct, and the point of a never-raises test).
pytest writes the full test ID into the `PYTEST_CURRENT_TEST` environment variable, and **Windows
caps a single environment variable at 32767 characters.** The giant parametrized ID blows that cap,
so `os.environ.__setitem__` raises during setup/teardown.

**This is a Windows-only ceiling.** The Cloud Build gate runs these files inside
`python:3.11-slim` (`cloudbuild.test-engine.yaml`), i.e. on Linux, where no such per-variable limit
exists. Nothing here suggests the real gate is red.

### Why it was not fixed

Fixing it means giving those parametrizations short explicit `ids=` so the test ID stops carrying the
payload. That edits two test files neither of which this plan owns, in a plan whose acceptance
explicitly measures that its diff touches only its four declared paths. It is also purely a
developer-ergonomics fix — it changes no production behaviour and closes no operator-visible gap.

### ⚠ Note for whoever next runs the engine gate locally on this machine

MEMORY SAYS the full engine gate runs locally in ~50s. **That is true for 43 of the 45 files.** Do
not read these 4 errors as a regression introduced by whatever you are working on, and do not
"fix" them by deleting the hostile-input cases — those cases are the entire value of a never-raises
test. To get a clean local signal, exclude the two files:

```
... | grep -v "test_fact_list_parser.py" | xargs python -m pytest -q -m "not live"
```

and read the 4 remaining errors as known.

**Not proven by this plan:** that the Cloud Build engine gate itself is green. No build was
submitted — that is a deploy action and outside plan 22-01's scope. What IS proven: all 45 named
paths resolve on disk, so the config's `COLLECTED -ne EXPECTED_FILES` assertion passes.

---

## DEF-22-03 — the i18n audit is blind to every interpolated `t()` call (102 sites)

**Found during:** plan 22-03's execution; routed here by plan 22-08 so it is not lost with that
plan's SUMMARY
**Status:** deferred — a **gate-coverage** defect. Nothing in phase 22 relies on it being fixed, and
fixing it means editing `frontend/scripts/i18n-audit.mjs`, which no plan in this phase owns.

### Mechanism

CHECK A/B/C recognise a translation call with two regexes at `i18n-audit.mjs:126-128`:

- `RE_SINGLE` requires the call to **close immediately after the string** — `t("some.key")`.
- `RE_TWO` requires the second argument to be a **string** — `t("ns", "some.key")`.

Neither matches `t("some.key", { … })`. **Therefore no interpolated call is visible to the audit at
all**, and there are **102 such sites in `frontend/src`**. A renamed or deleted interpolated key
ships **GREEN** and renders the raw key name on screen to the operator.

### How it was measured

Plan 22-03 did this directly rather than reasoning about the regexes: it renamed keys in the locale
files while leaving the component calling the OLD name, then ran the audit. Result: `RESULT: PASS`,
exit 0. The audit did not notice.

### Impact

The audit is a real safety net for plain `t("key")` calls and **not a safety net at all** for any
interpolated one. Anyone treating a green audit as proof that every key resolves is reading more
into it than it measures. Every count-bearing, date-bearing and name-bearing string in this product
is interpolated, which is most of the ones an operator actually reads.

**Whoever picks this up:** widen the call recognition to accept an options-object second argument,
then expect a burst of newly-visible findings on the first run — those are pre-existing, not caused
by the fix.

---

## DEF-22-04 — two orphaned locale keys left by the removal of the intake-page resume action

**Found during:** plan 22-04 (the D-22-5 element removal); routed here by plan 22-08
**Status:** deferred — dead copy, zero runtime effect, and the audit will never surface it.

Removing `onResumeResearch` left these two keys present in **all three** locale files with **zero
referrers** anywhere in `frontend/src`:

```
intakeDetail.toast.researchResumed
intakeDetail.toast.researchResumeFailed
```

The audit only ever flags a key a component asks for and the locales do not have — a **missing**
key. It has no orphan check, so an unused key stays green forever and accumulates.

⛔ **Do NOT also remove `research.cancelError` / `research.cancelOk`.** Those look like siblings and
are NOT orphaned: `components/research/RunActions.tsx` still uses both. Deleting them because they
sit next to these two would break a live surface.

Not removed here because plan 22-08 touches one component file and the three locale files are
outside its declared diff — and because removing a locale key is exactly the kind of "make the grep
go green" edit this phase has repeatedly had to guard against.

---

## DEF-22-05 — five order-dependent tribunal test failures, pre-existing and not caused by phase 22

**Found during:** phase 22 execution, running the citation / verification / schema test files
together; routed here by plan 22-08
**Status:** deferred — **cross-file pollution in the test harness, NOT a product defect and NOT
introduced by this phase.**

### What fails, and only in company

Running those test files **together** yields 5 failures:

| File | Test |
|------|------|
| `test_citation_roundtrip.py` | `test_source_snapshot_text_round_trips` |
| `test_citation_roundtrip.py` | `test_source_upsert_by_content_hash_dedupes` |
| `test_citation_roundtrip.py` | `test_d13_columns_round_trip` |
| `test_citation_roundtrip.py` | `test_provider_stated_quality_beats_the_domain_heuristic` |
| `test_schema_isolation.py` | `test_upgrade_head_writes_tribunal_version_table` |

**Every one of them passes in isolation.**

### Why it is not this phase's doing

The identical five were confirmed failing at the **pre-phase commit `9afdf2d`**, where the same
selection gave **135 passed**. After the phase's engine work the same selection gives **169 passed —
+34 new tests, 0 new failures.** The failure set is byte-identical before and after.

This is the same class as the known directory-wide 180: shared module/DB state leaking between test
files, sensitive to collection order. It is a harness-isolation problem, and closing it means
per-test teardown work in files phase 22 does not own.

⚠ **For whoever reads a red local run next:** do not attribute these five to whatever you are
working on, and do not "fix" them by deleting or skipping the tests — each one asserts something
real and each one passes on its own. Reproduce in isolation first.
