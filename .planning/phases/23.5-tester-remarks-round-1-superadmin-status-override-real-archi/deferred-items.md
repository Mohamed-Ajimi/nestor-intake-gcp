# Deferred items — phase 23.5

## DEF-23.5-03-01 — `test_timestamp_on_success_only` is order-dependent (counts audit rows without an intake filter)

**Found:** 2026-09-22, during plan 23.5-03 Task 2 verification.
**Status:** PRE-EXISTING, out of scope for plan 03. NOT caused by this plan.

`tests/test_mail_endpoints.py:207` `_count_mail_sent_audit(engine, space_id)`
counts EVERY `audit_log` row with `event_type == "mail.sent"` visible under the
space GUC — no intake filter, and no per-test cleanup of the shared container.
`test_timestamp_on_success_only:319` then asserts that count `== 1`.

Run in the order the plan's own acceptance command specifies
(`test_mail_render.py test_mail_locale.py test_mail_endpoints.py
test_intake_validate_mail.py`) it fails with `assert 7 == 1`: the sends driven by
`test_mail_locale.py` have already written six `mail.sent` rows that the helper
happily counts.

**Proof it is pre-existing and not this plan's doing:**

| Command | Result |
|---|---|
| FULL backend suite (`python -m pytest -q`) | **871 passed, 2 skipped** — exactly plan 23.5-02's baseline |
| `pytest tests/test_mail_endpoints.py` | 13 passed |
| `pytest tests/test_mail_endpoints.py tests/test_mail_locale.py` (endpoints FIRST) | 33 passed |
| `pytest ... test_mail_locale.py test_mail_endpoints.py ...` (locale FIRST) | 1 failed, 56 passed |

The only behavioural thing plan 03 changed on the mail path is one line of prose
inside `admin_validated.html.j2`; `git diff backend/app/api/intake_routes.py`
filtered to non-comment lines is EMPTY. Neither can create an `audit_log` row.
The full suite runs alphabetically, so `test_mail_endpoints` sorts before
`test_mail_locale` there and the defect stays hidden in CI.

**Fix when someone owns it:** give `_count_mail_sent_audit` an `intake_id`
parameter and filter on it (the `mail.sent` rows carry the intake), or truncate
`audit_log` between tests. One helper, one call site. Not done here because
`tests/test_mail_endpoints.py` is outside plan 03's declared surface and the
scope boundary forbids fixing failures the plan's own changes did not cause.

## DEF-23.5-03-02 — `ci_no_hardcoded_dutch.sh` is red on two COMMENT lines

**Found:** 2026-09-22, during plan 23.5-03 Task 1 verification.
**Status:** PRE-EXISTING, out of scope. The plan did not name this gate.

`bash frontend/scripts/ci_no_hardcoded_dutch.sh` (run from the repo root — from
`frontend/` it aborts with "scan dir does not exist: frontend/src") fails on:

- `frontend/src/components/admin/adminNav.ts:6` — `// Beheer routes rely on reference equality.`
- `frontend/src/components/admin/ProductShell.tsx:91` — `Skipped when the primary nav already IS the manage nav (Beheer pages pass the`

Both are COMMENTS, in files plan 03 did not touch (`git diff --name-only`
contains neither). The script greps source text without excluding comments, so
these are false positives on prose, not untranslated UI copy. Note also that the
script's own usage is undocumented: it only works from the repo root.

**Fix when someone owns it:** strip `//` and `/* */` regions before matching, or
allow-list the two lines. Two lines, one script.

## DEF-23.5-03-03 — the client mails greet the recipient with the PROJECT name

**Found:** 2026-09-22, during plan 23.5-03 Task 2's mail audit.
**Status:** PRE-EXISTING defect, deliberately NOT fixed — out of D-23.5-03's
label-only scope.

`intake_routes._run_intake_send` passes `first_name=client` where
`client = intake.client_name or "team"` — i.e. the PROJECT name — into
`render_results` / `render_intake` / `render_validation`. The templates render
`<h1>Hi {{ first_name or "team" }}</h1>` (and the fr/nl equivalents), so a real
client receives "Hi Marktintrede Benelux".

This is NOT a mislabel — no surrounding word claims the value is a client — so
it fell outside the relabel audit, which is why it is recorded rather than
changed. Fixing it needs a recipient first-name to exist (the send path resolves
memberships, so one is reachable) and is a behaviour change, not a copy change.

**Fix when someone owns it:** resolve the recipient's own name per locale group
and pass it, or drop the name from the greeting entirely ("Hi" / "Bonjour").

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

## DEF-23.5-06-01 — phase 23.5's four new tribunal test files are in NO Cloud Build gate

**Found:** 2026-09-22, during plan 23.5-06 Task 1.
**Status:** OUT OF SCOPE for plans 04/05/06 — each declares its files and
`tribunal/cloudbuild.test-engine.yaml` is not among them.

`cloudbuild.test-engine.yaml` runs an EXPLICIT `WANTED` list of 45 paths and
asserts `EXPECTED_FILES=45` so that a missing file fails the gate instead of
silently shrinking it. That list is a closed set: a new test file is not picked
up by adding it to `tests/`, it has to be NAMED.

Not named, and therefore not run by any gate:

| File | Plan | Tests |
|---|---|---|
| `tests/test_runtime_flags.py` | 23.5-04 | 26 |
| `tests/test_citation_replay.py` | 23.5-04 | 41 |
| `tests/test_citation_replay_anchors.py` | 23.5-05 | 29 |
| `tests/test_sources_render.py` | 23.5-06 | 13 |
| `tests/test_synthesis_continuation.py` | 23.5-06 | 16 |

125 tests, all pure (no DB, no network, no provider call), all green locally,
none of them defending anything in CI. That is precisely the shape
`test_suite_hygiene.py`'s own preamble calls false assurance: the gate is green
and says nothing about the code these files cover.

**Fix when someone owns it:** add the five paths to `WANTED` and change
`EXPECTED_FILES` from 45 to 50 IN THE SAME EDIT — the config says in words that
the number and the list move together. One file, two lines. The natural home is
the phase's ship wave (plan 23.5-07), which already touches build and deploy.

**Why not done here:** `cloudbuild.test-engine.yaml` is outside the declared
surface of all three tribunal plans, and this is the sensitive wave. Changing a
gate's own assertion count is not something to slip into a plan that did not
name it.
