---
phase: quick-260925-dyt
plan: 01
subsystem: backend/research (raw-output bundle)
tags: [bundle, zip, research, bugfix, tdd]
requires: [app.storage.keys.sanitize_filename]
provides: [build_bundle_zip with unique question-named research entries + research/index.md]
affects: [raw-output zip download (new completions only)]
tech-stack:
  added: []
  patterns: [shared sanitizer on every path segment, pure no-I/O builder]
key-files:
  created: []
  modified:
    - backend/app/research/bundle.py
    - backend/tests/test_research_bundle.py
decisions:
  - "Research entries are named research/NN-<sanitize_filename(angle,60)>-<sanitize_filename(provider)>.md; NN is shared by the providers of one angle (grouped by _corroboration_key, else _angle); fallback research/NN-<provider>.md; -2/-3 dedupe guarantees uniqueness"
  - "The header comes before the body and is separated by a blank line, then ---, then another blank line; the body is appended byte-identical"
metrics:
  duration: ~20 min
  completed: 2026-09-25
---

# Quick 260925-dyt: Raw-output zip, one file per angle report, named by question

**One-liner:** `build_bundle_zip` used to give every research entry a provider-only name (`research/gemini.md`), so names collided. Each entry now gets a unique, question-named file, `research/NN-<question-slug>-<provider>.md`, with a question/provider header and a byte-identical body. A new `research/index.md` lists every file. Extraction no longer drops up to 12 of 15 angle reports.

## What changed

- `backend/app/research/bundle.py`: only the research loop was rewritten. The signature `(report, bundle, sources) -> bytes` is unchanged, the builder takes no rejected-claims input (D-01), and the `report.md` and `sources.json` writes are unchanged. The entry order is report.md, research files, research/index.md, sources.json. Four new private helpers were added: `_str_field`, `_collapse`, `_md_cell`, `_header` and `_index`. The module docstring (D-03 layout) and the function docstring were updated, and the old "exactly three kinds of entry" wording was replaced with the four-entry layout.
- Both path segments, the question slug (`max_len=60`) and the provider, go through the shared `sanitize_filename`. The only new `.replace` is the markdown `|` escape used in index table cells.

## Tests

`tests/test_research_bundle.py`: 17 passed with `-W error::UserWarning`, which fails on any duplicate zip name. It previously held 9 tests; 8 are new:
duplicate providers across angles all survive (9 entries in, 9 files out), grouping prefers the corroboration key, fallback without an angle or with a plain string, the `-2` uniqueness suffix, path traversal stays one entry, an accented angle gives a readable slug capped at 60 chars, the header names the questions and provider, and index.md lists the files in zip order.

**Existing tests whose assertions changed**, because the naming legitimately changed:
1. `test_layout_report_research_and_sources`: `research/angle-a.md` became `research/01-angle-a.md`. The body check changed from equality to `endswith("provider A text")` because a header now comes first, and the test also asserts that `research/index.md` is present.
2. `test_provider_name_is_sanitized_into_entry_path`: the expected name is now `research/01-Angle_One_-_Two_Three.md` and the body check is `endswith("X")`. The research-entry count now excludes `research/index.md`.
3. `test_non_dict_result_falls_back_to_str`: `research/angle-b.md` became `research/01-angle-b.md`, and the body check is now `endswith("raw string report")`.

Unchanged and still green: the empty-cleaned_reports test (no research/ entries, index.md included), the missing-key test, the report.md tests, the sources.json test, and the D-01 no-"rejected" test.

`test_path_traversal_angle_stays_single_entry` already passed during RED. The old code produced a single flat entry too, so this test is a regression guard, not a RED proof.

## Full backend suite

`python -m pytest -q` from backend/, with Python 3.12.6 and Docker Desktop up for testcontainers: **916 passed, 2 skipped, 0 failed** (155–190 s). The baseline was 908, so the difference is the 8 new tests. Neither skip is caused by Docker:
- `tests/test_tribunal_seam_denial.py:70`: `nestor_pulse_sdk` cannot be imported in the backend venv.
- `tests/test_research_runs_migration.py:382`: `RUNTIME_DB_USER` is unset. This check is env-guarded by design.

## Scope

`git diff --stat 742a3be` shows only `backend/app/research/bundle.py` and `backend/tests/test_research_bundle.py`. No tribunal, frontend, migration, research_routes.py or run_task.py files were touched, and nothing was deployed.

**Existing prod bundles were NOT rebuilt.** The 13 measured prod zips keep the old colliding layout. Only runs that complete after this code is deployed get the new layout.

## Commits

- `dab5cb6` test(260925-dyt): add failing tests for unique question-named research zip entries (RED)
- `9cb5394` fix(260925-dyt): raw-output zip — one file per angle report, named by question (GREEN)

## TDD Gate Compliance

The RED commit `test(...)` comes before the GREEN commit `fix(...)`. The plan's commit message for GREEN specified `fix`, not `feat`. No refactor commit was needed.

## Deviations from Plan

None beyond the notes above. Ruff is not installed in the local venv, so no lint was run.

## Self-Check: PASSED

- backend/app/research/bundle.py and backend/tests/test_research_bundle.py exist and are modified in the commits
- commits dab5cb6 and 9cb5394 are present on the worktree branch
