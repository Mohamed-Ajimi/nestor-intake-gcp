# Deferred items — phase 15.2

Out-of-scope discoveries logged during execution. NOT fixed by the discovering plan.

## From 15.2-09 (2026-07-26)

### D9-1 — `npm run lint` cannot pass on a Windows checkout (`core.autocrlf=true`)

**Discovered:** Task 3 verification.
**Scope:** repo-wide, pre-existing, unrelated to plan 15.2-09.

`git config core.autocrlf` is `true` on the dev machine, so every checked-out file
gets CRLF while every git blob is pure LF (verified: `frontend/eslint.config.js`
blob = 0 CR, disk = CRLF). `eslint-plugin-prettier` then reports `Delete ␍` on
*every line of every file*, including `frontend/eslint.config.js` itself at line 1.

`npm run lint` is therefore not a runnable local gate on this machine. It is
presumably green in Linux CI, where the LF blobs are checked out verbatim.

**Proof this is not a 15.2-09 regression:** the two files the plan touches were
linted against their `HEAD` baselines (`git show HEAD:<path>` written to sibling
files). Baseline and post-change both report exactly **22 errors + 1 warning**,
all on lines the plan did not author. Zero new findings.

**Suggested fix (not done here):** add a `.gitattributes` with `* text=auto eol=lf`
so the working tree matches the blobs, or set `core.autocrlf=input` on the dev box.
Either is a repo-wide change well outside a single plan's blast radius.

### D9-2 — `backend/scripts/ci_no_run_research.sh` has been failing since phase 16-02

**Discovered:** Task 3 verification.
**Scope:** pre-existing, unrelated to plan 15.2-09.

The INTAKE-05 scope guard's pattern includes
`import[[:space:]]+[A-Za-z0-9_.]*tribunal`, which matches the legitimate seam
import `from app.research import tribunal_client` in **both**
`backend/app/api/research_routes.py:64` and `backend/app/research/run_task.py:57`.
Both lines are present at `HEAD` and were introduced by commit `f48ec06`
(`feat(16-02): pool-safe Tribunal poll driver`).

The guard's own header says it must not trip on "prose" mentions of Tribunal, but
its pattern was written before Phase 16 legitimately introduced the Tribunal seam
client into `backend/app/`. The guard as written now forbids the architecture the
project shipped.

**Not fixed here** because the honest fix is a policy decision, not a code tweak:
either narrow the pattern to exclude `tribunal_client` (the seam is allowed;
`run-research` invocation is not), or retire the import half of the pattern. Both
change what INTAKE-05 means and belong to whoever owns that requirement.

### D9-3 — `test_research_bundle_endpoint.py` is wired to no gate config

**Discovered:** final verification of 15.2-09.
**Scope:** gate-coverage gap, pre-existing.

`grep -rln test_research_bundle_endpoint tribunal/ --include=*.yaml` returns
nothing: the file appears in none of `cloudbuild.test-engine.yaml`,
`cloudbuild.test-gates.yaml` or `cloudbuild.test-critical.yaml`. It runs only in
the full suite (`tribunal/cloudbuild.test.yaml`), where its DB-backed tests are
`xfail(strict=True)` behind testcontainers Docker and land in that build's
**40 skipped**.

This matters because plan 15.2-09's threat T-15.2-21 names
`test_research_bundle_endpoint.py::test_cross_tenant_run_not_visible` as a
standing mitigation. That test is currently not executed by any gate. The
source-level half of the mitigation
(`test_status_gates.py::test_widened_handlers_keep_the_404_non_distinguishability`)
DID run and passed.

**Suggested fix (not done here):** add the file to `cloudbuild.test-critical.yaml`'s
pytest list. Not done by 15.2-09 because that config's own header documents a
deliberate exclusion policy (superuser DSN vs RLS) and changing it needs the
owner's judgement about whether the harness can run these tests faithfully.

### D15-1 — two D-13 persistence tests are written but have never executed

**Discovered:** execution of 15.2-15.
**Scope:** gate-coverage gap. Same class as D9-3.

The real-schema round-trip test and the provider-quality-beats-heuristic test skip
in the full suite because that build's testcontainers fixture is broken (root cause
recorded in `b479499`). `cloudbuild.test-critical.yaml` *does* have a real Postgres,
but it does not list `test_citation_roundtrip.py`, and that config is owned by
15.2-02.

Unproven until either the gate is widened or the first live run happens:
- that the `ARRAY(Text)` bind for `found_by` round-trips to a Python list, and
- that `research_gap`'s FORCE-RLS `WITH CHECK` accepts the INSERT.

The 12 pure Layer-1 tests DO execute and prove the emitted SQL and every bound
value; the executor confirmed those by name via a verbose build rather than
inferring them from suite totals. So the gap is specifically the DB round-trip,
not the query construction.

**Suggested fix (not done here):** add `test_citation_roundtrip.py` to
`cloudbuild.test-critical.yaml`'s pytest list, or fix the full suite's
testcontainers fixture. Deferred for the same reason as D9-3 — that config's
header documents a deliberate superuser-DSN-vs-RLS exclusion policy, and widening
it is the owner's judgement call.

### D15-2 — cross-provider contradictions only collide when the tagger agrees on the entity

**Discovered:** execution of 15.2-15.
**Scope:** accepted limitation, pre-existing in `grouping.py`; now asserted by test.

15.2-15's headline must-have asked that all four recorded contradictions land in
one skeptic session. Production blocks by `_norm(entity)` alone, and `_norm`
collapses formatting, not meaning. So `LUKOIL Nederland` vs `lukoil nl` — and the
run's real tags for the buyer conflict, `lukoil` vs `lukoil benelux` — never reach
the same block. `grouping.py` documents this as an ACCEPTED LIMITATION, and the
plan forbids changing the blocking key by name.

The executor did not force the must-have. It made the fixture honest and added a
test that asserts the limit explicitly rather than papering over it.

**Operator consequence:** a cross-provider contradiction reaches one session *when
the tagger names the same entity on both sides*. When the tagger splits the entity,
the contradiction still ships as two separate claims. How often that bites is what
G-05's August calibration measures.

**Suggested fix (not done here):** changing the blocking key (e.g. entity aliasing
or embedding-based blocking) is out of scope for this phase and needs a decision
about false-merge risk.
