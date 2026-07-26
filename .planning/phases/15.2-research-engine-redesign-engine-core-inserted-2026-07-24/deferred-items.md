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

## From 15.2-16 (2026-07-26)

### D16-1 — the resume denial tests run in NO committed gate config

**Discovered:** execution of 15.2-16, Task 3.
**Scope:** gate-coverage gap. Same class as D9-3 and D15-1 — but note this one
was *proven green out-of-band*, so the gap is the STANDING gate, not the proof.

`test_checkpoint_resume.py`'s eight Layer-B tests — including
`test_resume_cross_tenant_run_is_404`, the automated proof of this plan's only
**high**-severity threat (T-15.2-122) — need a real Postgres and a
**non-superuser** DSN. No committed config gives them both:

- `cloudbuild.test-engine.yaml` is DB-less by design. They skip there, cleanly
  and loudly (`DATABASE_URL not set … a skip here is NOT a pass`). Measured:
  **8 skipped**.
- `cloudbuild.test.yaml` cannot run them at all. Its testcontainers fixture does
  not start (`"host" network_mode is incompatible with port_bindings`), and its
  Postgres would be a SUPERUSER anyway, which makes any RLS denial assertion
  vacuous. Both facts are recorded in that config's own header by `b479499`.
  **The plan's acceptance criterion pointed at this config and is therefore
  unsatisfiable as written** — that is why the tests were re-based onto the
  `DATABASE_URL` + `require_non_superuser` idiom of `test_rls_isolation.py`
  instead of the testcontainers `async_engine` fixture.
- `cloudbuild.test-rls.yaml` is the only faithful harness (migrations and pytest
  both as the non-superuser table owner `app_user`), but **15.2-01 owns it** and
  its anti-false-green block pins an exact `6 passed` count. Adding a file there
  would break that pin.
- `cloudbuild.test-critical.yaml` has a real Postgres but connects as the
  `postgres` SUPERUSER, and its header documents that exclusion policy
  deliberately. It is owned by 15.2-02.

**Proof that they pass** (so this is a gate gap, not an unproven claim): the file
was run in Cloud Build against a purpose-built clone of `test-rls.yaml`'s
harness — `postgres:15`, `app_user` as a NOSUPERUSER owner, `alembic upgrade
head`, pytest under that DSN. All eight executed and passed by name, with the
`require_non_superuser` guard NOT tripping. The harness config was deliberately
**not committed**, because committing it would create a fifth gate config in a
phase that already has four and whose ownership is spoken for.

**Suggested fix (not done here):** either add
`nestor_pulse_sdk/tests/test_checkpoint_resume.py` to
`cloudbuild.test-rls.yaml`'s pytest line and bump its pinned pass-count from 6,
or give the phase one DB-backed config that owns every non-superuser test.
Deferred because both are the owner's call: the first changes a pinned count
that exists precisely to stop silent drift, and the second is a structural
decision about the phase's gate layout. Natural home: **15.2-17**'s green-gate
sweep, which already inherits D9-3 and D15-1.

### D16-2 — the `merge` / `gates` / `verify` checkpoints are WRITE-ONLY

**Discovered:** execution of 15.2-16, Task 3.
**Scope:** partial delivery inside this plan, stated rather than absorbed.

R3 writes all eight `ckpt_*` rows. Only three are also RESTORED — `workshop`,
`research` and `provider_jobs`, which between them cover the run's paid
deep-research and the multi-call question workshop, i.e. the overwhelming
majority of a run's spend. `merge`, `gates` and `verify` are recorded but no
restore branch reads them yet, so a resume re-runs those three stages.

**Why it was stopped there, and not quietly implemented anyway.** Restoring them
is not a data problem, it is an IDENTITY problem: `_group_selected` works because
`apply_gates` mutates the very claim dicts the clusters hold *by identity*, and a
JSON round-trip destroys identity. A correct restore has to rebuild that coupling
from claim indexes (the `merge` payload is already written in that shape, ready
for it). That rebuild sits in the most delicate part of a paid pipeline, and
nothing in the tree exercises it end-to-end: the stubbed full-pipeline harness
(`test_engine_e2e_stubbed.py`) is not written yet, and no live run may be spent
against the Anthropic cap before 2026-08-01. Shipping an unexercised restore
branch on the hot path could corrupt a real run's claim set, which is a worse
failure than re-running a cheap stage.

**Consequence for the operator:** a run parked mid-verification resumes with its
research intact (the expensive part) but re-runs the gates and the skeptic
sessions. The must-have "re-uses every paid stage result" is therefore **met for
research and the workshop, and not yet met for gates/verify**.

**Suggested fix (not done here):** wire the three restores once
`test_engine_e2e_stubbed.py` exists to prove the index-rebuild, or after the
August live run makes a real park available to replay.

## From 15.2-19 (2026-07-26)

### D19-1 — `test_mail_render.py::test_invite_carries_link` has been failing, in no gate

**Discovered:** Task 1 verification (observed in BOTH the RED and the GREEN build).
**Scope:** pre-existing, unrelated to plan 15.2-19.

The test asserts the raw action link
`https://auth.example/action?mode=resetPassword&oobCode=XYZ123` appears in the
rendered invite body. Jinja `autoescape` is ON, so the `&` is rendered as `&amp;`
and the raw substring is never present. The rendered HTML *does* contain
`...mode=resetPassword&amp;oobCode=XYZ123`, i.e. the link is correct and the mail
works — the ASSERTION is wrong, not the renderer.

Measured in Cloud Build `52e63276` (before this plan's changes): `7 failed, 24
passed`, of which 6 failures were this plan's deliberate RED and the 7th was this
test. After the plan: `1 failed, 36 passed` — the same single pre-existing failure.

**Why this went unnoticed:** `test_mail_render.py` carries no `integration` marker,
and the repo-ROOT `cloudbuild.test.yaml` — the only committed backend gate — runs
`pytest tests -m integration`. So the file runs in NO committed gate config. Same
class as D9-3 / D15-1 / D16-1.

**Not fixed here** because it is outside this plan's blast radius (the invite mail
is Phase-11 work) and because the honest fix is two decisions, not one: correct the
assertion to expect the escaped form, AND decide whether the non-integration unit
tests get a committed gate at all. Natural home: **15.2-17**'s green-gate sweep,
which already inherits D9-3, D15-1 and D16-1.

### D19-2 — the non-integration backend unit suite runs in NO committed gate

**Discovered:** Task 1 / Task 2 verification.
**Scope:** gate-coverage gap, pre-existing, repo-wide.

`cloudbuild.test.yaml` (repo root, the only backend build config in the tree) runs
`python -m pytest tests -m integration`. Everything without that marker — including
`test_mail_render.py` and `test_research_run_task.py`, which between them hold all
12 of this plan's new non-DB proofs — is deselected and never runs on any committed
gate. Measured: the integration gate reports `155 deselected`.

This plan's 12 unit tests WERE proven green, out of band, in Cloud Build
`76153e23` against an ad-hoc uncommitted config (`python:3.12-slim`, no DB, the two
files by name). Deliberately not committed, for the same reason 15.2-16 gave for
D16-1: this phase already has four gate configs with assigned owners, and adding a
fifth is a structural decision, not an executor's call.

This plan's four *denial* tests are NOT affected — `test_research_cross_tenant.py`
is `integration`-marked and all four ran and passed by name in the committed gate.

**Suggested fix (not done here):** add a second step to `cloudbuild.test.yaml`
running `pytest tests -m "not integration"`, or mark the affected files. Either
changes what the required merge gate means. Natural home: **15.2-17**.

### D19-3 — D9-1 (Windows CRLF vs LF blobs) is still live despite `.gitattributes`

**Discovered:** Task 3 verification.
**Scope:** pre-existing, repo-wide, unrelated to plan 15.2-19.

A `.gitattributes` now exists at the repo root, but `npm run lint` still reports
**25,971 errors**, essentially all `Delete ␍` from `eslint-plugin-prettier`, across
files this plan never touched (`vitest.config.ts`, `eslint.config.js`, ...). The
working tree is still CRLF while the blobs are LF, so the whole-repo lint command
remains unusable as a local gate on this machine. It is presumably green in Linux
CI.

**How 15.2-19 proved no regression anyway** (the method is worth reusing): for each
touched frontend file, the `HEAD` blob and the working copy were both normalised to
LF into sibling temp files and linted separately, then the counts compared.
Result — `research.ts` 16 vs 16, `ResearchRunProgress.tsx` 11 vs 11,
`admin.pulse.intakes.$id.tsx` 1173 vs 1173. Zero new findings. Two authored lines
were reshaped during this check to keep the counts identical (a collapsed
`resumeResearch` signature and a single-line `<ResearchRunProgress …/>` render
site, because that JSX region carries pre-existing indentation drift that taxes
every added line).

**Suggested fix (not done here):** verify the `.gitattributes` actually covers
`*.ts`/`*.tsx`/`*.js` with `eol=lf` and re-normalise the working tree
(`git add --renormalize .`), or set `core.autocrlf=input` on the dev box. Repo-wide,
well outside a single plan's blast radius.
