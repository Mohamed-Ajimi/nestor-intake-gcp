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

## From 15.2-17 (2026-07-26)

### D17-1 — `own_research` is a DECLARED stage that nothing writes

**Discovered:** the stubbed end-to-end run (Task 1).
**Scope:** small operator-facing defect, in production since 15.2-03/12/13.

`ENGINE_STAGES["tribunal"]` declares `{"key": "own_research", "label": "Own
research"}`. Nothing writes it:
`grep -rn 'own_research"' --include=*.py` outside `tests/` returns exactly ONE
hit, the declaration itself. 15.2-03 declared it up front (WR-03: declare before
any plan writes it) and 15.2-12/13 wired the fourth STREAM — it researches, emits
facts through `emit_fact_list`, and its claims reach the merge — but no
`set_stage(..., "own_research", ...)` call was ever added.

**Operator consequence:** the run feed shows a stage that never leaves `pending`,
on every run, including runs where the own-researcher worked perfectly. A
permanently-pending stage reads as a stage that hung.

**Not fixed here** because this plan writes no production code beyond the three
Rule-1 defects the e2e caught, and adding a stage write is a feed-design choice
(where in `run_angles` does it fire, and what does its detail row say when the
stream is refused before any call?) that belongs to whoever owns the fourth
stream's UX.

**Pinned rather than left invisible:**
`test_engine_e2e_stubbed.py::test_own_research_is_a_declared_stage_that_nothing_writes`
asserts the gap explicitly, in 15.2-15's D15-2 register. It is SELF-RETIRING: the
moment someone writes the key it fails and forces this item closed.

### D17-2 — the four inherited gate-coverage gaps, RESTATED and re-evidenced

**Scope:** D9-3, D15-1, D16-1 and D19-2 all named 15.2-17's green-gate sweep as
their natural home. They are **not closed**, and this section says why rather
than letting them lapse.

Measured on the final tree during the six-gate sweep:

| Item | Where it lands today | Evidence |
|------|----------------------|----------|
| D9-3 `test_research_bundle_endpoint.py` | full suite only; its 5 DB tests SKIP | build `1e45857d`, `Docker not available for testcontainers` ×5 |
| D15-1 `test_citation_roundtrip.py` | full suite only; its 5 DB tests SKIP | build `1e45857d`, same reason ×5 |
| D16-1 `test_checkpoint_resume.py` | engine gate + full suite; its 8 DB tests SKIP | builds `fcb632ca` / `1e45857d`, `DATABASE_URL not set` ×8 |
| D19-2 backend non-integration units | deselected by the only committed backend gate | build `1900f247`, `155 deselected` |

**Why none of them is closed here — and this is the load-bearing part.**

*Three of the four share one root cause: the full suite's testcontainers fixture
does not start* (`"host" network_mode is incompatible with port_bindings`).
"Just fix the fixture" is the obvious move and it is a TRAP, for a reason
`tribunal/cloudbuild.test.yaml`'s own header already records: **testcontainers'
Postgres runs as SUPERUSER, and RLS never applies to a superuser.** Repairing the
networking would turn 10 currently-honest skips into green assertions, of which
the RLS-denial half would be VACUOUS — they would pass because the policy was
never consulted, not because it holds. That is strictly worse than a loud skip,
and it is the exact false-green class this phase exists to close. The same
objection blocks the other obvious move, adding these files to
`cloudbuild.test-critical.yaml`: that config connects as the `postgres`
superuser and its header documents that exclusion policy deliberately.

The faithful harness is `cloudbuild.test-rls.yaml` (migrations and pytest both as
the non-superuser owner `app_user`), but **15.2-01 owns it and its anti-false-green
block pins an exact `6 passed` count** — adding files there breaks the pin that
exists precisely to stop silent drift. This plan's brief forbids weakening it.

D19-2 is a different shape: the fix is additive (a second step running
`pytest backend/tests -m "not integration"` on the repo-root `cloudbuild.test.yaml`,
which no 15.2 plan owns and which pins no count). It is still not done here
because that step would land RED on day one — **D19-1's
`test_invite_carries_link` is still failing**, asserting a raw `&` URL against
autoescaped HTML — so closing D19-2 means first correcting a Phase-11 mail
assertion, and then deciding what a REQUIRED merge gate means. The second half is
a structural decision, not an executor's call, and 15.2-19 said so when it filed
the item.

**The honest summary:** all four remain open, all four now have measured
evidence and a named blocker, and the blocker is the same one in three cases —
**the phase has no committed non-superuser DB gate with room in it.** That is one
decision, not four, and it is the thing to put to the operator.

---

## D24-1 — `caplog` captures NOTHING for `app.research.run_task` in the backend suite

**Filed by:** plan 15.2-24, wave 3, 2026-07-27.
**Status:** OPEN. Worked around, not diagnosed.

Plan 15.2-24 added `pytestmark = pytest.mark.integration` to
`backend/tests/test_research_run_task.py` — a NARROW fix for D19-2 scoped to that
one file, because the plan adds behaviour to `run_task.py` and shipping an ungated
proof of it would be the "green because it ran nothing" failure this phase spent
six waves removing.

Putting the file in the gate immediately surfaced a **pre-existing** failure that
nothing had ever run:

```
tests/test_research_run_task.py::test_parked_mail_not_resent_for_same_seq FAILED
>       assert "[park#1]" in caplog.text
E       AssertionError: a SKIPPED mail must be logged at WARNING naming the marker
E       assert '[park#1]' in ''
```

`caplog.text` is the EMPTY STRING. The WARNING itself is definitely emitted — the
same test proves the branch that logs it ran (zero mails sent, finalize still
written). So the record is produced and pytest's capture does not see it. There is
no `logging.config`, no `basicConfig`, no `propagate = False` and no `setLevel`
anywhere in `backend/`, and this was the ONLY file in the whole backend suite
using `caplog`, so there is no working counter-example to compare against.

**A second capture route was tried and ALSO came back empty.** Before settling on
a workaround, a real `logging.Handler` was attached directly to `run_task.log`
with the logger's level explicitly lowered to `WARNING`. It recorded nothing
either — measured in build `b0a94294`, where the failure reads
`warning_sink = [], bad = 1785159456`. Two independent capture routes going silent
is consistent with logging being globally suppressed in this suite (a
`logging.disable()` at WARNING or above short-circuits `Logger.isEnabledFor` and
would defeat both), but that is a HYPOTHESIS — nothing in `backend/` calls it, and
the dependency set was not searched.

**What 15.2-24 did:** replaced the capture mechanism with a `warning_sink` fixture
that monkeypatches `run_task.log` with a recording double, sidestepping the
logging framework entirely. **The assertion is unchanged** — the same WARNING, the
same marker, the same property; what it now proves is that the module CALLED
`log.warning` with the right content. The pre-existing test was NOT deleted and
NOT skipped.

**What is still open:** why both capture routes are inert here. Candidates not yet
excluded: a global `logging.disable()` from a third-party import, a pytest plugin
interaction, or something in the `uv pip install -e '.[dev]'` dependency set. It
matters beyond this file — the next person to reach for `caplog` in
`backend/tests` will write an assertion that cannot fail, which is the same
false-green class in a new place.

**Not closed by this plan** because it is a suite-wide diagnosis, not an
executor's call, and the workaround is strictly stronger than what it replaced (it
asserts on the module's own logger rather than on global capture).

D19-2's broader question — whether the non-integration backend unit suite gets a
committed gate at all — is UNCHANGED and still open. One file joining the gate is
not that decision.

---

# From 15.2-26 — the gap phase's closing reconciliation (2026-07-27)

Filed by the plan that closed the gap phase. Everything below was **measured on
the final gap-phase tree**, not inferred from a plan's prose. Six items, then a
restatement of the four inherited gate gaps, then one correction to an entry that
this phase proved wrong.

The first item is the highest-value one in this file.

## D26-1 — the five D-E proofs are COLLECTED but SKIPPED by every committed gate

**Filed by:** 15.2-26, from 15.2-20's own "Honest limitation" section.
**Status:** OPEN. This is the money defect, and it currently rests on ONE
recorded build rather than on a standing gate.

`test_stale_reclaim.py` holds the five SQL-level proofs of D-E — the defect that,
unfixed, re-bills a stuck run every 60 minutes forever, unattended. The file is
DB-bound. `cloudbuild.test-engine.yaml` provisions no Postgres by construction,
so it collects the file and **skips all five**, loudly and contract-compliantly.
Measured in build `6ed343db` (this plan's final green run):

```
SKIPPED [1] nestor_pulse_sdk/tests/test_stale_reclaim.py:300: DATABASE_URL is unset
(or is not a postgresql+asyncpg:// DSN), so the D-E stale-reclaim proofs did NOT
run. THIS IS NOT A PASS: the money defect these tests cover is unproven in this
build. The harness that runs them faithfully is tribunal/cloudbuild.test-critical.yaml.
```
(×5, at lines 300 / 342 / 402 / 437 / 496.)

Measured coverage across the committed configs:

```
grep -rn "test_stale_reclaim" tribunal/*.yaml
  → cloudbuild.test-engine.yaml only (the list + two comments). No other config.
```

So the file runs in **no committed gate**. It was proven green — all five PASSED
by name, `35 passed, 0 skipped` — in Cloud Build `2e55aeaa`, against a **scratch**
config that mirrors `cloudbuild.test-critical.yaml`'s Postgres provisioning and
substitutes the file list. That config was deliberately not committed because
`cloudbuild.test-critical.yaml` is owned by plans 15.2-01/02.

**What it would take:** add `nestor_pulse_sdk/tests/test_stale_reclaim.py` to
`cloudbuild.test-critical.yaml`'s pytest file list. That config has a real
Postgres and pins no exact pass-count, so — unlike the `test-rls.yaml` route —
adding a file there breaks no anti-drift pin.

**Why 15.2-26 did not do it:** `cloudbuild.test-critical.yaml` is not in this
plan's `files_modified`, and its header documents a deliberate
superuser-DSN-vs-RLS exclusion policy that is the owner's judgement to change.
The D-E tests do not assert RLS denial, so the superuser objection that blocks
D9-3/D15-1/D16-1 does **not** apply here — which is exactly why this one is
cheap and should be done first.

**Until it lands:** the regression protection for the phase's most expensive
defect is a build id in a SUMMARY. A future edit to `CLAIM_SQL` or `REAP_SQL`
will not turn any gate red.

## D26-2 — `CONFIG_ERROR` is never reached on the deep-research angle path

**Filed by:** 15.2-26, from 15.2-22's "Open Caveats" item 3.
**Status:** OPEN, and the honest framing matters more than the fix.

15.2-22 added `reliability.CONFIG_ERROR` so that a refused model id — D-A's
shape — trips the circuit breaker on first sight instead of degrading into
seven quiet per-angle warnings. The classification is correct and unit-proven,
and it is **live for every path that RAISES**: Anthropic calls, SerpApi, the
own-researcher.

It is **not reached by the path D-A actually took.** Both deep-research angle
consumers take a provider ERROR ENVELOPE (`{"status": "error", "error_message":
…}`) and log a warning; neither raises, so `classify` and the breaker are never
consulted. Verified on this tree:

```
tribunal/nestor_pulse_sdk/pipeline/tribunal/research_division.py:1329
    reason = result.get("error_message") if isinstance(result, dict) else repr(result)
tribunal/nestor_pulse_sdk/pipeline/deep_researchers/degraded_parallel.py:236
    reason = result.get("error_message") or f"status={result.get('status')!r}"
```

(15.2-22 cited `research_division.py:~1270` and `pipeline/tribunal/
degraded_parallel.py:236`; the first line has moved and the second file lives
under `pipeline/deep_researchers/`. The line numbers above are the measured
ones on the gap-phase tree.)

**State the consequence plainly, because a green unit test invites the wrong
conclusion: what protects this deployment against D-A recurring is the PINNED
MODEL ID (`gpt-5.6-sol`), not the breaker.** If OpenAI retires that id too, the
run will again fail one angle at a time with a warning per angle, exactly as it
did on `d6bb3aae` — the breaker will not stop it. The breaker half is proven and
inert on this path.

**What it would take:** convert the error envelope into a classified failure at
those two sites (raise, or call `classify` on the envelope and consult the
breaker). `research_division.py` belonged to 15.2-23 in the gap wave, and
neither file is in 15.2-26's `files_modified`.

## D26-3 — `is_poisoned_turn_error` ships EXPORTED but UNWIRED

**Filed by:** 15.2-26, from 15.2-22's "Deferred Issues".
**Status:** OPEN. Half of D-B, deliberately.

`skeptic.is_poisoned_turn_error` (`skeptic.py:330`) is the bounded D-B recovery
predicate: it recognises the 400 that a replayed failed `web_fetch` result
produces, and consults `reliability._CAP_MARKERS` so a cap error can never be
swallowed by a drop-and-retry. Verified on this tree — it is referenced by its
definition and by `test_web_fetch_replay.py` **only**:

```
grep -rn "is_poisoned_turn_error" tribunal/nestor_pulse_sdk/
  → skeptic.py:330 (def) + 4 test references. No production caller.
```

Wiring it means threading the predicate through the own-researcher's retry call
at **`own_researcher.py:599`** (`resp = await with_retry(`) — 15.2-22 cited
`:575`; 599 is the measured line on this tree. `own_researcher.py` belonged to
15.2-23 that wave.

**What is and is not covered:** the D-B *shape* fix (`skeptic._to_plain` /
`_content_to_serialisable`) IS wired and is what makes the stream work. This
predicate is the *recovery* — what would let the stream survive a SECOND bad
page rather than losing the session. Its absence is a resilience gap, not a
broken stream.

## D26-4 — `caplog` captures NOTHING in `backend/tests` (sharpened restatement of D24-1)

**Status:** OPEN, unchanged, and under-rated at its original filing.

D24-1 above records the mechanics: `caplog.text` is the empty string for
`app.research.run_task` records, a second independent capture route (a real
`logging.Handler` attached directly to `run_task.log` with the level lowered)
ALSO recorded nothing (build `b0a94294`, `warning_sink = []`), there is no
`logging.config` / `basicConfig` / `propagate = False` / `setLevel` anywhere in
`backend/`, and there is **no working counter-example in the suite** to compare
against because that was the only file using `caplog`.

**The sharpening — this is not a one-test problem.** The next person to reach
for `caplog` in `backend/tests` will write an assertion that **CANNOT FAIL**,
and it will look exactly like a passing test. That is the same false-green class
this phase spent six waves closing (D9-3, D15-1, D16-1, D19-2, and the engine
gate's own silent-skip arrangement that 15.2-26 just closed), appearing
somewhere new and unguarded.

15.2-24's workaround — a `warning_sink` fixture monkeypatching the module logger
with a recording double — is strictly stronger than what it replaced and the
assertion was NOT weakened. But it is a workaround for one file, and it leaves
the trap armed for everyone else.

**Root cause unchased.** The stated hypothesis (a global `logging.disable()` at
WARNING or above from something in the dependency set, which would short-circuit
`Logger.isEnabledFor` and defeat both capture routes) is UNCONFIRMED: nothing in
`backend/` calls it and the dependency set was not searched.

**Suggested first move for whoever picks this up:** write a deliberately trivial
`caplog` assertion in a NEW backend test and confirm it fails — establishing the
counter-example that does not exist today — before hunting the cause.

## D26-5 — `ci_no_raw_db_access.sh` is RED, pre-existing, and a probable FALSE POSITIVE

**Status:** OPEN. **Narrow the guard; do not retire it.**

Measured on the final gap-phase tree:

```
bash backend/scripts/ci_no_raw_db_access.sh   → EXIT 1
backend/app/research/run_task.py:147:    return get_engine()
ERROR: raw DB access (engine/session construction) found outside app/db/.
```

**It is pre-existing.** The line existed at phase start (then at line 103) and
was introduced by commit `f48ec06` (phase 16-02). This gap phase only moved its
line number — 15.2-24 added code above it. 15.2-25 independently reported the
same single offender at `:103` and correctly declined to touch it.

**Why it is probably a false positive.** `get_engine` is *imported from the
seam*: `run_task.py:65` reads `from app.db.base import get_engine`. The call at
`:147` is inside `get_engine_for_pool_check()`, a thin indirection that exists
so the pool-safety test can assert `engine.pool.checkedout() == 0` against the
same pool the real writes use. So the call **does** go through `app/db/`, which
is what D-03 requires; the guard's regex matches the call site rather than
engine/session *construction*.

**The recommended resolution is to NARROW the guard deliberately** — e.g. anchor
it on construction (`create_engine` / `sessionmaker` / `async_sessionmaker`) or
allowlist symbols imported from `app.db.*`, in the register 15.2-17 already used
when it narrowed `ci_no_run_research.sh` with an import-anchored allowlist and
then verified the narrowed guard was still non-vacuous.

**Never retire it, and never "fix" it by moving the line.** A guard that is red
for a sanctioned call site teaches people to ignore it, and an ignored guard is
how D-03 comes back. Whoever narrows it must re-prove it still fails on a real
violation.

## D26-6 — CORRECTION: D9-2 is STALE. `ci_no_run_research.sh` PASSES.

**Status:** the deferred item D9-2 (above, filed by 15.2-09) is **WRONG at this
tree** and should be closed or rewritten rather than left standing.

D9-2 says the INTAKE-05 scope guard "has been failing since phase 16-02" because
its pattern matches the legitimate seam import `from app.research import
tribunal_client`. Measured on the final gap-phase tree:

```
bash backend/scripts/ci_no_run_research.sh
OK: no run-research/Tribunal invocation in .../backend/app .../frontend/src.
EXIT 0
```

15.2-25 reported the same result independently ("the plan expected a pre-existing
failure here … the guard is green at this base"). The most likely explanation is
15.2-17's green-gate sweep, which narrowed this guard with an import-anchored
allowlist and verified it non-vacuous — i.e. D9-2 was **fixed upstream and the
item was never closed**.

**Why this is worth an entry rather than a silent delete:** a deferred-items file
containing a known-wrong entry is worse than one item shorter. Somebody will
plan work against it. Whoever next touches this file should confirm the narrowing
in `ci_no_run_research.sh` and mark D9-2 CLOSED with that commit named.

## The four inherited gate-coverage gaps — RESTATED, unchanged, one blocker

D9-3, D15-1, D16-1 and D19-2 are **not closed by the gap phase**, and this
section exists so they do not lapse into silence because a newer phase closed
different ones. 15.2-17 restated them once (D17-2); this is the second
restatement, re-measured on the gap-phase tree.

| Item | Where it lands today | Evidence on THIS tree |
|------|----------------------|-----------------------|
| D9-3 `test_research_bundle_endpoint.py` | full suite only; its DB tests SKIP | `grep -rln test_research_bundle_endpoint tribunal/ --include=*.yaml` → no config lists it |
| D15-1 `test_citation_roundtrip.py` | full suite only; its DB tests SKIP | named ONLY in `cloudbuild.test-engine.yaml`'s deliberate-EXCLUSION comment, never in the file list |
| D16-1 `test_checkpoint_resume.py` | engine gate + full suite; its 8 DB tests SKIP | build `6ed343db`: 8 × `DATABASE_URL not set … A skip here is NOT a pass` |
| D19-2 backend non-integration units | deselected by the only committed backend gate | `cloudbuild.test.yaml:86` runs `python -m pytest tests -m integration` |

**The blocker is UNCHANGED and it is ONE decision, not four: the phase has no
committed non-superuser DB gate with room in it.**

- The obvious move — repair the full suite's testcontainers fixture — is a TRAP:
  testcontainers' Postgres runs as SUPERUSER and RLS never applies to a
  superuser, so repairing it would turn honest skips into VACUOUS green
  assertions. Strictly worse than a loud skip.
- The same objection blocks adding these files to `cloudbuild.test-critical.yaml`
  (connects as the `postgres` superuser; its header documents that exclusion).
- The faithful harness is `cloudbuild.test-rls.yaml` (migrations and pytest both
  as the non-superuser owner `app_user`), but its anti-false-green block pins an
  exact `6 passed` count, and adding files there breaks the pin that exists
  precisely to stop silent drift.

**Note the contrast with D26-1**, which looks like the same shape and is not:
the D-E tests assert claim/reap SQL behaviour, not RLS denial, so the superuser
objection does not apply and `cloudbuild.test-critical.yaml` is a faithful home
for them. D26-1 is cheap; these four are one structural decision for the
operator.

**D19-2 specifically** remains additive-but-blocked: a second step running
`pytest backend/tests -m "not integration"` on the repo-root `cloudbuild.test.yaml`
would land RED on day one, because D19-1's `test_invite_carries_link` still
asserts a raw `&` URL against autoescaped HTML. 15.2-24 fixed ONE file into the
gate (`test_research_run_task.py`, via `pytestmark = integration`) as an
explicitly narrow move; that is not the decision.

## Gap-phase items that CLOSED — recorded so nobody re-opens them

- **15.2-23's deviation 1** (the D-I redaction count not rendered on the
  operator's feed row) was carried forward and **CLOSED by 15.2-24**, commit
  `58a5c1e`, with the read hardened to `isinstance(int) and not bool and > 0`
  and both rows pinned by test. It is not an open item.
- **The engine gate's silent-skip arrangement** (the standing instruction that
  "plan 15.2-26 reconciles the final collected count") is **CLOSED by 15.2-26**:
  `EXPECTED_FILES=27` is asserted, proven GREEN at 27/27 (build `6ed343db`) and
  proven RED on a mistyped name (build `c84a4201`, scratch copy — the assertion
  fired, named the path, and pytest never ran).
