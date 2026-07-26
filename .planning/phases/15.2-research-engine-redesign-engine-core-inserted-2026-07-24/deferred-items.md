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
