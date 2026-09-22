# Deferred items — phase 23.5

## DEF-23.5-04-01 — `test_scrub_research.py` fails whenever another async test module runs first

**Found:** 2026-09-22, during plan 23.5-04 Task 3 verification.
**Status:** PRE-EXISTING, out of scope for plan 04. NOT caused by this plan.

`nestor_pulse_sdk/tests/test_scrub_research.py:41` runs its coroutines through

```python
return asyncio.get_event_loop().run_until_complete(coro)
```

`asyncio.get_event_loop()` raises `RuntimeError: There is no current event loop
in thread 'MainThread'` on Python 3.12 once any earlier test module has closed
the loop. All 8 tests pass when the file runs alone; 5 of the 8 fail when it runs
after, for example, `test_citation_anchors.py`.

**Proof it is pre-existing:** the same pair was run with
`citations/extractor.py` restored byte-for-byte from the plan's base commit
`235ae850148fc0ea5990c9c4ebe86e5c83aa27a4` — identical 5 failures. Plan 04's
changes are not in that file's import graph (`scrub_research` lives under
`pipeline/`, which this plan does not touch).

**Fix when someone owns it:** replace the `_run` helper with
`asyncio.run(coro)`, or make the tests `async def` and let the suite's asyncio
plugin drive them. One file, one helper. Not done here because `pipeline/` and
unrelated test modules are outside plan 04's declared surface, and the phase's
own guard requires `git diff --stat tribunal/nestor_pulse_sdk/pipeline/` to be
EMPTY.

## DEF-23.5-04-02 — the tribunal suite is not isolation-clean across modules

**Found:** 2026-09-22, during plan 23.5-04 verification.
**Status:** PRE-EXISTING, out of scope for plan 04. NOT caused by this plan.

Three separate cross-module interactions, all reproduced byte-for-byte with
`citations/extractor.py` restored from the plan's base commit
`235ae850148fc0ea5990c9c4ebe86e5c83aa27a4`:

| Symptom | Alone | Combined |
|---|---|---|
| `test_scrub_research.py` (see DEF-23.5-04-01) | 8 passed | 5 failed |
| `test_engine_e2e_stubbed` + `test_report_sections` + `test_claim_distiller` | 22 / 43 / 32 passed | 15 failed |
| `test_citation_roundtrip.py` (4 DB-backed tests) | each passes in its own process | 4 failed as a file |

The third is a distinct cause from the first two: the four DB-backed roundtrip
tests each insert an organisation with the same slug and do not clean up, so the
second one to run hits `UniqueViolationError: duplicate key value violates
unique constraint "org_slug_key"` during fixture setup, before any citation code
executes. Reproduced on a FRESH `pgvector/pgvector:pg16` testcontainer, at base
and at HEAD alike. All four pass individually against a real Postgres with plan
04's refactored persist loop — which is the coverage that matters here, since
they are the tests that exercise `source.title` and
`claim_source.provider_quality` end to end.

**Why it is not fixed here:** the fixes live in test modules outside plan 04's
declared surface, and one of them (`test_scrub_research`) sits over `pipeline/`,
which the phase's own guard requires to stay untouched. Worth a small dedicated
plan: per-test unique org slugs, and `asyncio.run` in place of
`get_event_loop().run_until_complete`.
