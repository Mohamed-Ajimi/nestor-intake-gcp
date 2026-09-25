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

> ✅ **CLOSED 2026-09-22** by plan 23.5-07 as a Rule 2 deviation: the five paths were added
> to `WANTED` and `EXPECTED_FILES` moved **45 -> 50** in one edit, committed separately as
> `e2c59cf`. The 125 tests are in a gate for the first time. The record below is kept for the
> reasoning.

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

## DEF-23.5-07-01 — the ONE dev acceptance run was never started; all five numbers are unmeasured

**Found:** 2026-09-24, writing the phase 23.5 deploy record.
**Status:** OPEN and BLOCKING the flag flip. This is the largest outstanding item in the phase.
**Still open after the second 23.5 release** (`9bdb0fb`, 2026-09-24T21:37Z): that release
carried gap plan 23.5-09 only and changed nothing about the flags or the acceptance run.

Plan 23.5-07 Task 2 step D requires exactly one research run on a `decomposed` dev intake,
with the queue otherwise empty and both kill switches ON, read against five fixed figures.
**It has not been run.** Dev has been sitting with `NESTOR_CITATIONS_V2=true` and
`NESTOR_SYNTHESIS_CONTINUE_TRUNCATED=true` since 2026-09-22 (`tribunal-api-00028-29c`,
`tribunal-worker-00015-79r`) and nothing has exercised them.

Consequence: plans 04, 05 and 06 — the entire fix for the first client defect, where roughly
two thirds of the `## Sources` list was wrong — have shipped to **two** environments on unit
tests, replay goldens and a flags-off byte-identity proof. No live run, on any environment,
has ever executed that code path.

**The five figures, and where each is read** (verbatim from runbook Step 23.5.d):

| # | Figure | Expected | Where |
|---|---|---|---|
| 1 | source labels that are not the URL's host | **0** | the rendered `## Sources` list; redirects excepted |
| 2 | anchors resolving to a URL that is not one of that claim's own provider URLs | **0** | join `claim_source` -> `source` for the numbered claims |
| 3 | stripped anchors (the "matched no claim" warning) | **0** | the run log |
| 4 | numbered redirect URLs rendered opaque while a `resolved_url` exists | **0** | the rendered list vs `source.resolved_url` |
| 5 | total numbered sources | **MEASURED, not predicted** | run `7784e71c` had 2,681; expect a collapse toward the count of distinct provider URLs |

Also read every chapter end to end: no section may stop mid-sentence, and any section still cut
must carry the one-line notice in the run's own language.

**Cost:** ~$40 on the dev Anthropic key, one run. **If any figure misses: set the master back to
`false` on dev and bisect with the five fine-grained switches — no rebuild needed.**

## DEF-23.5-07-02 — the prod flag flip is owed; the client's Sources defect is still live

**Found:** 2026-09-24, at the prod release.
**Status:** OPEN. Deliberate, by operator ruling — not an oversight.

`nestor-pulse-prod` runs the phase 23.5 code with **both kill switches `"false"`**. Read back on
2026-09-24 on `tribunal-api-00004-2zq` / `tribunal-worker-00004-z46` at the `261915a` release,
and again on `tribunal-api-00005-c7p` / `tribunal-worker-00005-fbf` after the `9bdb0fb` release
later the same day — the second release retagged and re-applied the same tribunal digests and
left both flags `"false"`, which is the intended shape. The
citation and continuation fixes are in the images and dormant in the configuration, so **the
client still gets the defective `## Sources` list** on any run started today.

Blocked by DEF-23.5-07-01. Once the dev run is read and its five figures pass, the flip is:

```bash
# 1. infra/env/client.tfvars — both to "true"
#      nestor_citations_v2                = "true"
#      nestor_synthesis_continue_truncated = "true"

TF=$HOME/AppData/Local/terraform/terraform.exe
export GOOGLE_OAUTH_ACCESS_TOKEN="$(gcloud auth print-access-token --account=tools@dotto.be)"

# 2. tribunal-api FIRST — no poll loop, so no claim risk
$TF -chdir=infra apply -var-file=env/client.tfvars \
  -target=google_cloud_run_v2_service.tribunal_api

# 3. THE IDLE GATE, as tribunal-run@ (Terraform-built env). Exit 0 is the ONLY pass;
#    90/91/92/93 are refusals. --no-source is required.
gcloud builds submit --no-source --config=infra/queue-check.yaml \
  --substitutions=_PROJECT=nestor-pulse-prod,_REGION=europe-west1 \
  --service-account=projects/nestor-pulse-prod/serviceAccounts/tribunal-run@nestor-pulse-prod.iam.gserviceaccount.com \
  --project=nestor-pulse-prod --account=tools@dotto.be
gcloud builds describe <FULL-UUID> --project=nestor-pulse-prod --account=tools@dotto.be \
  --format='value(status,steps[0].exitCode,failureInfo.detail)'

# 4. tribunal-worker LAST — a worker revision BOOTS the poll loop, which claims first and
#    sleeps last. This is a config change, and it still creates a revision.
$TF -chdir=infra apply -var-file=env/client.tfvars \
  -target=google_cloud_run_v2_service.tribunal_worker

# 5. READ BACK on both services — the two values must be equal, or one [n] means two
#    different sources depending on which service you ask.
for S in tribunal-api tribunal-worker; do
  gcloud run services describe $S --region=europe-west1 --project=nestor-pulse-prod \
    --account=tools@dotto.be --format='json(spec.template.spec.containers[0].env)' \
    | grep -A1 'CITATIONS_V2\|CONTINUE_TRUNCATED'
done
```

⚠ The agent permission classifier blocks `terraform apply`; the operator runs this via `!`.
⚠ Revert is the same sequence with `"false"` — config only, no rollback, no rebuild, and a run
in flight is unaffected until its next section.

## DEF-23.5-07-03 — `seed_superadmin` job still pinned to `backend:f5e2b9ad` on prod

**Found:** 2026-09-24, in `release-client.sh`'s final untargeted plan.
**Status:** OPEN, low severity, but it is real Terraform drift.

The release repinned and executed both migrate jobs, and applied the four services, all
targeted. `google_cloud_run_v2_job.seed_superadmin` was **not** targeted, so it still carries
`backend:f5e2b9ad` while `var.image_tag` is now `261915a`. The final plan therefore reported
**5 to change**, not the four cosmetic `scaling {}` read-backs the 23.4 record documents.

⚠ **Still open after the second 23.5 release, and the gap has widened.** The `9bdb0fb` release
(2026-09-24T21:37Z) did not target the job either. Its final untargeted plan again reported
**5 to change**, with the same `f5e2b9ad -> <current tag>` diff on `seed_superadmin` — the job
now trails **two** release tags instead of one.

Harmless today: the job is not executed by a release, and the seeded superadmin already exists.
It will move silently on the next untargeted `terraform apply`. Fix by adding
`-target=google_cloud_run_v2_job.seed_superadmin` to `release-client.sh`'s step 1 alongside the
two migrate jobs, or by accepting it and updating the runbook's "expect four" check to five.
**Note the runbook's pre-apply checklist still says "Five is not four — if the count differs,
stop".** That check is now tripped by this known item; resolve one or the other.

## DEF-23.5-07-04 — OPERATOR QUESTION OPEN: a run selector for earlier research runs

**Raised:** by the operator during the 2026-09-22 dev walkthrough. **Status:** CLOSED by phase 23.6 (2026-09-25, dev 510bbd3) — operator ruling D-23.6-02 revised: an internal chosen-run label plus the per-intake run history on the intake detail page; nothing client-facing. See 23.6 DEPLOY RECORD in infra/DEPLOY-RUNBOOK.md.

An intake can accumulate several `research_runs` over time (re-runs are phase 24's subject), but
the admin UI surfaces one. There is no way to open an earlier run's report, compare two runs, or
even see that more than one exists. Plan 23.5-08 made the delete audit row carry
`tribunal_run_ids` precisely because those rows are deliberately retained after a cascade — so
the data to select from exists and is not going away.

Needs a ruling on scope before any plan: a plain dropdown of prior runs on the intake detail
page, versus the fuller version-history surface phase 24 already contemplates. Recorded here so
the question is not lost between phases.

## DEF-23.5-09-01 — the research mails are Dutch-only; the fr/en templates are unreachable

**Found:** 2026-09-24, during plan 23.5-09 Task 1. **Status:** OPEN, shipped this way to both
environments in the `9bdb0fb` release. Explicitly out of scope for plan 09, not an oversight.

No caller passes `locale=` to `render_research_complete` / `render_research_failed` /
`render_research_parked`. All **seven** call sites — four in `backend/app/research/run_task.py`
and three in `backend/app/research/reconcile.py` — render at the `nl` default, and the three
subject bases in `run_task.py` are Dutch literals with no localized counterpart.

Consequence: a French- or English-speaking superadmin receives a Dutch research notification.
Plan 09 edited the **fr** and **en** variants of all six of those templates anyway, so the
client-name expression would not drift between languages, and they are covered by
`tests/test_mail_render.py`. They are **correct, tested and unreachable in production** — the
exact shape this project already records as a trap (a gate green over copy no user can see).

**Fix when someone owns it:** resolve the acting superadmin's locale on the research trigger
path the way the intake mails already do, thread it to all seven call sites, and give the three
subject bases nl/fr/en variants. This is a behaviour change on a paid path, not a copy change —
it needs its own plan.

## DEF-23.5-09-02 — nothing from plan 09 has been seen in an inbox or a browser

**Found:** 2026-09-24, at the `9bdb0fb` release. **Status:** OPEN — an owed verification, not a
defect.

Both items of plan 09 shipped to dev and to the client environment on the day they were written,
on unit tests alone:

| Item | Covered by | NOT covered by |
|---|---|---|
| D-23.5-08 — client name in the research mails | `tests/test_mail_render.py`, `test_research_run_task.py`, `test_research_reconciler.py` (DB-backed arm green), an AST count pinning all 7 call sites, and a rendered string table in the plan 09 summary | **any real message.** No research run has completed since the deploy, so no `render_research_*` call has produced a mail an operator could read |
| D-23.5-09 — the dropdown follows the intake | five vitest arms over `shouldSyncActiveSpace`, plus a grep count of 2/2/2 on the three routes | **any browser.** `/admin` returning 200 says the page boots, not that the top-bar client switches when an intake opens |

**The read list already exists**: the string table under "The string table (the ship-wave read
list)" in `23.5-09-SUMMARY.md` gives the nine body sentences and the three subjects verbatim.
Read the Dutch rows only — see DEF-23.5-09-01.

**Cheapest way to close the mail half:** it does not need a paid research run. The reconciler
sweep renders all three mails, and `tests/test_research_reconciler.py` already drives it against
a real Postgres; a manual send on dev against a throwaway intake would put a real message in a
real inbox for the price of one Resend call.

## Carried operational chores — NOT closed by this phase

These predate phase 23.5 and survived it. Repeated here so the phase's own record does not read
as if the environment were clean.

1. ⛔ **Rotate the superadmin password.** `nestor-superadmin-initial-password` on
   `nestor-pulse-prod` is still the seeded value and has been read in-session.
2. ⛔ **Revoke the exposed client Anthropic key.** It was pasted into a chat before being stored
   in Secret Manager. A **v2** was rolled on 2026-09-22 and the services run it, but a new
   secret version does **not** disable the old key at the provider. Both v1 and v2 should be
   treated as compromised until the v1 value is revoked upstream.
3. ⚠ **No operations mail on first submit.** A client submitting an intake for the first time
   produces no notification to the operator; it is noticed only by someone looking.
4. ⚠ **`source_urls[0]` primary-anchor rider for phase 24.** The primary-anchor mechanism
   (plan 23.5-05) currently picks the anchor from the claim's `source_urls[0]`. The durable fix
   is a first-class column, which means an intake migration — **alembic `0019`** — and phase 24
   is the next release that ships one. Carry it there rather than opening a migration of its own.
5. ⛔ **No Cloud SQL backup has ever been restored** on either project, and `nestor-pg` is still
   `ZONAL` (no HA). Backups bound the data loss; they do not remove the outage.
