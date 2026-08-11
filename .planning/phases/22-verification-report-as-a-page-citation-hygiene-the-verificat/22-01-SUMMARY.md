---
phase: 22-verification-report-as-a-page-citation-hygiene-the-verificat
plan: 01
subsystem: testing
tags: [citations, url-normalization, dedupe, python, pure-function, engine-gate]

# Dependency graph
requires:
  - phase: 15.4
    provides: "`source.resolved_url` / `source.resolution_status` (migration 0016, D-V01-11) — the columns the normalizer prefers as the identity key"
  - phase: 15.2
    provides: "`citations/numbering.py::number_citations` and its pinned 10-key entry shape — the input this plan's collapse consumes"
provides:
  - "`normalize_source_url` — the ONE source-identity key, pure and stdlib-only, importable by both the read path and the future write path"
  - "`collapse_citations_by_url` — one entry per normalized URL, preserving every survivor's original number"
  - "`also_claim_ids` on survivors — the alias that stops an absorbed source's claim losing its marker"
  - "`test_citation_dedupe.py` inside the engine fast gate (44 -> 45 files)"
affects: [22-05, write-side-source-identity-phase, verification-report-page]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "One shared identity function for read-time display and write-time conflict keys"
    - "Dedupe AFTER numbering, never inside it — sparse numbers are the intended output"
    - "Total (never-raising) parsing of remote-host-supplied strings on the read path"

key-files:
  created:
    - tribunal/nestor_pulse_sdk/citations/dedupe.py
    - tribunal/nestor_pulse_sdk/tests/test_citation_dedupe.py
    - .planning/phases/22-verification-report-as-a-page-citation-hygiene-the-verificat/deferred-items.md
  modified:
    - tribunal/cloudbuild.test-engine.yaml

key-decisions:
  - "Scheme excluded from the identity key — http and https of one page are one source (22-CONTEXT orchestrator decision, honoured)"
  - "The bare `ref` query parameter is PRESERVED; only `ref_src` / `ref_url` are stripped"
  - "Survivors keep the number `number_citations` assigned; the emitted list is deliberately sparse"
  - "Unparseable URLs are passed through and never merged with one another"
  - "`_TRACKING_PARAMS` named with a leading underscore to match the house convention in `numbering.py`"

patterns-established:
  - "Identity-key sharing: any layer that decides 'same source' calls `normalize_source_url`, never its own normalization"
  - "Sparse citation numbering: a gap in the `[n]` sequence is correct output, guarded by a comment and a named test"

requirements-completed: [D-22-4]

# Metrics
duration: 18min
completed: 2026-08-11
---

# Phase 22 Plan 01: The One Source-Identity Function Summary

**A pure stdlib `citations/dedupe.py` exposing `normalize_source_url` (resolved-URL-preferring, scheme/www/port/fragment/tracking-param-stripping, path-case-preserving, never-raising) and `collapse_citations_by_url` (one survivor per normalized URL that assigns no numbers, so the list goes sparse), pinned by 34 named tests now inside the 45-file engine fast gate.**

## Performance

- **Duration:** ~18 min
- **Started:** 2026-08-11T15:33Z (approx)
- **Completed:** 2026-08-11T15:50Z
- **Tasks:** 3
- **Files modified:** 4 (3 created, 1 modified)

## Accomplishments

- **One identity function exists and is importable unchanged by the Python write path.** `dedupe.py` imports only `__future__`, `typing` and `urllib.parse` — no sqlalchemy, no `nestor_pulse_sdk.*`, no DB, no network. That import list is an asserted acceptance criterion, not a convention.
- **Collapse is proven to preserve numbering.** The load-bearing test builds a 4-entry fixture where entry 3 duplicates entry 2 and asserts the output numbers are exactly `[1, 2, 4]`. Nothing in the module assigns a number: the forbidden-pattern grep (`enumerate(`, loop-index arithmetic, writes to the number field) returns no match.
- **Over-merging is refused explicitly, and each refusal is a named test.** Path case survives, the bare `ref` parameter survives, percent-encoding is untouched, and two URLs that both fail to parse are never merged with each other.
- **`citations/numbering.py` is byte-identical to the phase base commit** — verified with `git diff --quiet` against `9afdf2d`. The dedupe deliberately lives downstream of the tests that pin contiguous `1..N` and the exact 10-key entry shape.
- **The engine fast gate names 45 files and asserts 45**, both moved in one commit per the config's own rule.

## Task Commits

1. **Task 1: `normalize_source_url` — the one identity key** (TDD)
   - `9e80fa1` test — 18 failing tests (RED: `ModuleNotFoundError`)
   - `a23df1b` feat — implementation (GREEN: 18 passed)
2. **Task 2: `collapse_citations_by_url` — one number per source, never a new number** (TDD)
   - `a9c49e2` test — 16 further failing tests (RED: `ImportError`)
   - `bc7e13c` feat — implementation (GREEN: 34 passed)
3. **Task 3: the new test file inside the engine fast gate**
   - `81dcdbe` chore — `WANTED` + `EXPECTED_FILES` 44 -> 45, and `deferred-items.md` seeded with DEF-22-01
   - `c844c89` docs — DEF-22-02 appended after measuring the gate locally

No REFACTOR commits: neither implementation needed cleanup after going green.

## Files Created/Modified

- `tribunal/nestor_pulse_sdk/citations/dedupe.py` (created, 307 lines) — `normalize_source_url` + `collapse_citations_by_url` + the closed `_TRACKING_PARAMS` frozenset. Carries the "Do NOT do any of these" merge-hazard block and the never-renumber rationale.
- `tribunal/nestor_pulse_sdk/tests/test_citation_dedupe.py` (created, 477 lines) — 34 tests, one named test per property, no table-driven loop.
- `tribunal/cloudbuild.test-engine.yaml` (modified, 2 lines) — one path added to `WANTED`, `EXPECTED_FILES` 44 -> 45.
- `.planning/.../deferred-items.md` (created) — the phase's single deferred-items file, seeded with DEF-22-01 and DEF-22-02.

## Verification Results

All measured with the venv python from `tribunal/`:

| Check | Result |
|-------|--------|
| `pytest nestor_pulse_sdk/tests/test_citation_dedupe.py -q` | **34 passed**, 0 failed, 0 errors (plan floor: 16) |
| `pytest nestor_pulse_sdk/tests/test_suite_hygiene.py -q` | **3 passed** — the new file trips neither the duplicate-binding rule nor the `ast`-lift ban |
| `pytest test_citation_anchors.py test_citation_numbering.py test_suite_hygiene.py -q` | **67 passed, 4 skipped** |
| `pytest nestor_pulse_sdk/tests/test_verification_report_endpoint.py -q` | **9 passed** — exactly the baseline measured at `658591b`, confirming nothing is wired into the report yet |
| distinct test paths in `WANTED` | **45**, counted (not estimated); `EXPECTED_FILES=45` at one site only |
| all 45 `WANTED` paths resolve on disk | **45 of 45** — the gate's `COLLECTED -ne EXPECTED_FILES` assertion passes |
| `git diff --quiet ... -- citations/numbering.py` | clean — **byte-identical to base** |
| files changed vs base | exactly the 4 in `files_modified`, no others |

**Grep criteria, all satisfied:**
- `grep -c "^ref\b\|'ref'\|\"ref\"" dedupe.py` -> `0` (the bare name is never a quoted member; comments reference it in backticks only)
- `grep -nE "^from |^import " dedupe.py` -> only `__future__`, `typing`, `urllib.parse`
- `grep -nE "enumerate\(|\bn\b *= *[a-z_]* *\+ *1|\[.n.\] *=" dedupe.py` -> no match
- `grep -n "duplicate_count" dedupe.py` -> no match
- `git diff --stat cloudbuild.test-engine.yaml` -> 2 lines (bound was 3)

⛔ **No yield claim is made here.** Whether this collapses many duplicates or few depends entirely on how often the best-effort HEAD resolution succeeded on `vertexaisearch` redirect tokens in a given run, which is runtime data and not knowable before one runs. This plan proves MECHANISM only, and the module emits no `duplicate_count` or equivalent field precisely so that no UI can invent such a reading.

## Decisions Made

- **`_TRACKING_PARAMS` over `TRACKING_PARAMS`.** The plan called for "a module-level frozenset" without naming it. Leading-underscore matches `numbering.py`'s `_TIER1_SUFFIXES` / `_TIER2_HOST_HINTS`, and this suite already imports private names from production modules (`test_citation_anchors.py` imports `_ANCHORS_ENABLED`, `_LEDGER_CHARS`). The closed-set membership is asserted directly by a test.
- **`normalize_source_url` returns `None`, never `""`.** A URL that parses to an empty key (`https://`) would otherwise collide with every other such URL on a falsy key — reintroducing the over-merge the module exists to prevent, in the one case nobody would test for.
- **Unparseable entries pass through by reference, not as copies.** Keeps `out[0] == original` exactly true and avoids adding `also_claim_ids` to a row that never participated in collapsing.
- **Scheme-less input needs no special case.** `urlparse("example.com/a")` puts everything in `path`, which assembles to the same key as `https://example.com/a`. Verified rather than assumed.

## Deviations from Plan

### 1. [Documentation] The plan named a route file that does not exist

- **Found during:** Task 3 (writing DEF-22-01)
- **Issue:** Task 3's text says `admin.pulse.runs.$runId.index.tsx` imports `useActiveResearchRun` from `ResearchRunProgress`. **No such file exists.** `frontend/src/routes/` contains exactly one `runs` route file, `admin.pulse.runs.$runId.tsx`, and the import is at line 11 — which is what 22-CONTEXT.md's D-22-5 amendment says.
- **Fix:** Recorded the correct path in DEF-22-01 rather than copying the plan's wording forward. Verified by grep before writing.
- **Why it matters:** DEF-22-01's whole purpose is to stop a future agent deleting `ResearchRunProgress.tsx`. An item that justifies keeping the file by pointing at a non-existent importer is an item the next reader disbelieves. **Plan 22-04 should use the real filename.**
- **Committed in:** `81dcdbe`

### 2. [Rule 3 boundary — logged, NOT fixed] The full engine gate cannot run locally on Windows

- **Found during:** Task 3, running all 45 gate files locally to prove the `EXPECTED_FILES` bump is safe
- **Issue:** `test_dispatch_pii.py::test_never_raises` produces 4 errors and `test_fact_list_parser.py` cannot be collected at all, both with `ValueError: the environment variable is longer than 32767 characters`. Their deliberately enormous parametrized input strings become the pytest test ID, which pytest writes to `PYTEST_CURRENT_TEST`, which exceeds Windows' per-variable cap.
- **Decision:** **Not fixed** — both files are untouched by phase 22, predate it, and were already among the 44. The Cloud Build gate runs on Linux (`python:3.11-slim`), which has no such cap, so this is a local-harness limitation and not evidence the gate is red. Logged as **DEF-22-02**.
- **Measured anyway:** the other 44 files give **1824 passed, 13 skipped, 4 errors** — all 4 errors being the above.
- **Committed in:** `c844c89`

### 3. [Process] Test-file scope corrected mid-execution

- **Found during:** Task 1
- **Issue:** I first wrote both tasks' tests in one pass. That would have made Task 1's GREEN gate fail on Task 2's assertions, collapsing two TDD cycles into one and destroying the RED evidence for each.
- **Fix:** Trimmed to Task 1's tests before the first RED run, then extended in Task 2. Both cycles show a genuine RED (`ModuleNotFoundError`, then `ImportError`) followed by a green implementation commit.
- **Impact:** None on output; the gate sequence is intact in git history.

---

**Total deviations:** 3 (1 plan-text correction, 1 out-of-scope discovery logged not fixed, 1 self-corrected process slip)
**Impact on plan:** No scope creep. No acceptance criterion was weakened, skipped, or reinterpreted — every criterion in both tasks was run as written and passed.

## Acceptance-Criteria Integrity Note

Every criterion in this plan was satisfiable as literally written and none was vacuous. Two were worth stating explicitly because they are the kind that usually go soft:

- **The `ref` criterion** is written as a `grep -c` whose expected value the plan does not state, with an instruction to "verify by reading the frozenset literal". Both were done: the grep returns `0` and the literal contains `ref_src` and `ref_url` with no bare member. Comments in the module mention the parameter in backticks specifically so the grep stays meaningful rather than matching prose about the rule.
- **The no-number-assignment grep** would match its own explanation. The plan asks for a docstring stating the rule "in these terms" while also requiring the grep to find nothing, so the rationale is written in prose ("never derives a number from a loop position") rather than as forbidden code tokens. The rule is enforced by the grep AND by `test_numbers_go_sparse_and_are_never_reassigned`; the docstring only explains it.

## Issues Encountered

- **Stale worktree base, again.** The worktree spawned at `a3a0c96` (merge-base `!=` the expected `9afdf2d`), the same failure this project has now hit 24 times. Caught by the merge-base check, corrected by `git reset --hard`, and both positive-presence sentinels then passed. The `rev-list --count` form would have read green.

## Known Stubs

None. Both functions are fully implemented; nothing returns a placeholder.

`collapse_citations_by_url` has no production caller yet — by design. Plan 22-05 wires it into `verification/report.py:661`, and the write-side conflict key lands in its own phase (D-22-4 sequencing). `test_verification_report_endpoint.py` still measuring exactly 9 passed is the evidence that nothing was wired early.

## Threat Flags

None. This plan adds no network endpoint, no auth path, no file access and no schema change. T-22-01 (a remote `Location` header reaching the parser) is mitigated as planned: the function is total, the parse is wrapped in `except Exception`, and the result is used only as a dict key — never to build a request. T-22-SC is satisfied trivially: **no package was installed**, and the stdlib-only import list is an asserted criterion.

## Next Phase Readiness

**Ready for 22-05.** The interface is exactly as the plan specified, so 22-05 needs no signature negotiation:

```python
normalize_source_url(url, resolved_url=None, resolution_status=None) -> str | None
collapse_citations_by_url(numbered, resolution=None) -> list[dict[str, Any]]
```

`resolution` maps `source_id` (str) -> `(resolved_url, resolution_status)`; absent or partial is fine.

**Three things 22-05 must not get wrong:**

1. **Index `citationsByClaim` under `first_claim_id` AND every id in `also_claim_ids`.** Skipping the alias silently drops the marker from any verdict row whose only source was absorbed — the failure is invisible on screen.
2. **Do not close the number gaps** anywhere in the frontend either. The sparse list is the correct render.
3. **The read-time collapse changes DISPLAY only.** Cost and corroboration figures still count the duplicate `source` rows until the write side lands. The page must not imply otherwise.

**Carried forward:** DEF-22-01 (do not delete `ResearchRunProgress.tsx`; correct importer is `admin.pulse.runs.$runId.tsx:11`) and DEF-22-02 (the local gate ceiling).

---
*Phase: 22-verification-report-as-a-page-citation-hygiene-the-verificat*
*Completed: 2026-08-11*
