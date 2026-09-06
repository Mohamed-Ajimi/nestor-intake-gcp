# Phase 23.2 — Deferred Items

Items shipped knowingly, recorded so they are never discovered later as surprises.
Created by plan `23.2-11` (wave 5, the integration pass) at merged head `622cc89`.

Mirrors the structure of
`.planning/phases/23.1-platform-hardening-authorization-boundary-space-deactivation/deferred-items.md`
so the two read alike.

**Nothing in this file is unfinished work.** Every entry is a DECISION with a reason. The one
section that is not a deferral — the operator-facing CI warning — is marked as such and has its
own heading.

---

## ⛔ DEPLOY STATE — READ THIS FIRST

**Phase 23.2 is BUILT, TESTED and COMMITTED. Nothing is deployed.**

No `gcloud builds submit` and no `gcloud run deploy` was run in any of the eleven plans. No
provider call was made and no Tribunal run was triggered — zero spend across the phase. **No
`role=user` was ever observed against a live service.** Every confidentiality, lifecycle and
authorization claim in this phase is a LOCAL test result measured against a testcontainer
Postgres on the dev box. The live `nestor-api` revision still serves the pre-23.2 behaviour.

A skip is not a pass. Where a test skipped, it is recorded as a skip below and in the plan
SUMMARY, never folded into a "green" count.

---

## The eleven named deferrals (23.2-CONTEXT.md § 10)

Reproduced with their reasons, then checked against the ten plan SUMMARYs. Corrections are
marked inline.

| id | Item | Why deferred |
|---|---|---|
| DEF-23.2-01 | Per-request membership/space status enforcement | D-23.2-11 — changes the authorization model; own phase |
| DEF-23.2-02 | Transactional outbox for notifications | D-23.2-15 — durability, not correctness |
| DEF-23.2-03 | Durable background dispatch + reconciler (`BackgroundTasks` survives no restart) | Real, architectural, orthogonal to all seven findings |
| DEF-23.2-04 | Tribunal "ownership lost mid-provider-call": a heartbeat affecting 0 rows does not cancel the pipeline, and the advisory lock is released before execution | 23.1 fenced the WRITES; cancelling in-flight work is a different mechanism |
| DEF-23.2-05 | Versioned/immutable snapshot of approved research inputs | Larger than answer-write policy; D-23.2-05 stops the drift, versioning is the next step |
| DEF-23.2-06 | localStorage draft: user namespacing, revision compare, expiry (`IntakeForm.tsx:106` merges cache OVER server) | Frontend-only; real but not authorization |
| DEF-23.2-07 | Pagination + payload bounds on `list_intakes` (filters in Python after an unpaginated `repo.list()`) | Performance/limits, not confidentiality |
| DEF-23.2-08 | npm audit 12 findings; non-reproducible backend pins (`uv:latest`, broad ranges) | Supply chain; needs a runtime-image scan first |
| DEF-23.2-09 | Frontend lint: 28,924 errors, of which exactly **60** are non-formatting (54 `no-explicit-any`, 4 `no-empty`, 2 `prefer-const`) | A repo-wide prettier pass would bury every real diff |
| DEF-23.2-10 | Dead code: `ContextPackPDF.tsx` (zero importers — the `downloadContextPackPDF` hits are a same-named LOCAL function, the substring trap), `ResearchResultsPanel.tsx` (only a comment references it), `supabasePublic` (zero consumers) | Cleanup; verify non-TS entry points first |
| DEF-23.2-11 | Doc contradictions: `AGENTS.md:27` still says "zero automated tests" and `:41`/`:103` call the backend a placeholder | Documentation; one pass, not this phase |

**Count check: eleven rows.** ✅

**DEF-23.2-09 and DEF-23.2-10 numbers re-checked, NOT stale.** Both name measured frontend
figures, and `git diff 922fd91..HEAD --stat -- frontend/` at the merged head is **EMPTY** — not
one frontend file was touched by any of the eleven plans. Both figures therefore stand exactly
as recorded. No correction needed.

**DEF-23.2-11 is unchanged and its `AGENTS.md` claim is now MORE wrong than when written** —
the backend suite went from 608 to 736 tests during this phase. Still deferred; still a
documentation pass.

---

## DEF-23.2-12 — a client can tick "keep Nestor's proposal" and the tick is silently discarded

**Recorded by:** plan 23.2-09 (as `DEF-23.2-09-01`), promoted here to the phase-level id.
**Status: a real, user-visible DATA-LOSS defect that predates this phase.**

⚠ **Numbering note — this id was ALREADY allocated.** `23.2-CONTEXT.md:218` names
`DEF-23.2-12` in § 2, but § 10's table stops at eleven and asserts eleven rows. So CONTEXT
contradicts itself: § 2 allocates a twelfth id that § 2's own count in § 10 excludes. This
entry is that twelfth item, not a new allocation. Reported rather than silently renumbered.

### The mechanism, verified independently at `622cc89`

* `frontend/src/routes/intake.$id.tsx:106` — `editable: intake.status === "draft"`.
* `frontend/src/components/intake/IntakeForm.tsx:210` — `saveCurrentSection` opens with
  `if (!editable) return true;`.

So during the **validation phase** (status is no longer `draft`) the client's section PATCH is
**skipped entirely AND reports success**. `doSubmit` gates navigation on that return value, so
the status advances having persisted nothing. `confirmedDiffKeys` (`IntakeForm.tsx:129`) is
local `useState` and is never transmitted.

**Net effect: a client ticks "keep Nestor's proposal", presses Akkoord, and the tick is
discarded while the status advances.** An enabled control whose value is never saved.

### Why it is deferred, and why the server half still shipped

Frontend is an explicit scope fence for this phase (23.2-CONTEXT.md § 9.4) and not one
frontend file was touched. The fix is **one line** — let `saveCurrentSection` proceed for
`proposal_list` fields during the validation phase, mirroring the `disabled=` expression at
`IntakeForm.tsx:501`.

The server-side exception in **D-23.2-05 is correct and stays**: it is exactly the rule the
frontend fix will need, and writing the server to a draft-only rule would mean reopening the
backend later. But it is **defence in depth, not a live-path rescue** — this phase must not
claim it saved a working feature. Today the exception is unexercised from the browser.

---

## DEF-23.2-13 — `required` / `min_length` / `min_items` are not enforced server-side

**Recorded by:** plan 23.2-09 (as `DEF-23.2-09-02`).

These three constraints are **browser-only** today. Evidence: `IntakeForm.tsx:214-217`,
`:26-30`, `:33-40`.

Their server home is the **`POST /intakes/{id}/submit`** verb, not the answer-write path — a
per-answer PATCH legitimately saves a partial section, so enforcing a minimum there would break
save-as-you-go. D-23.2-05 deliberately scoped the write policy to lifecycle, schema membership
and field permission; minimum-constraint enforcement is a separate rule at a separate verb.

---

## DEF-23.2-14 — tribunal cross-file `caplog` pollution (a test-isolation defect, reproduced here)

**Recorded by:** plan 23.2-05. **Independently reproduced by plan 23.2-11 at `622cc89`.**

`nestor_pulse_sdk/tests/test_run_ownership_fence.py` and `test_stale_reclaim.py` reconfigure
logging such that two `caplog` assertions in `test_checkpoint_resume.py` go **red** when they
run in the same process. Both casualties assert on `caplog` for WARNINGs emitted through
**stdlib logging** from `pipeline/tribunal/checkpoints.py:234`; running either worker-facing
file first leaves that logger uncaptured.

### The isolation table — measured, DSN-dependent

| Invocation | DSN | Result |
|---|---|---|
| `test_checkpoint_resume.py` alone | `app_user` | **31 passed, 0 skipped, 0 failed** |
| `test_checkpoint_resume.py` alone | none | 23 passed, 8 skipped |
| `test_checkpoint_resume.py` + `test_run_state_cas.py` | `app_user` | **43 passed, 0 skipped, 0 failed** ← clean pair, the gate this phase uses |
| `test_run_ownership_fence.py` + `test_checkpoint_resume.py` | `app_user` | **2 failed**, 38 passed, 10 skipped ⛔ |
| `test_stale_reclaim.py` + `test_checkpoint_resume.py` | `app_user` | **2 failed**, 29 passed, 5 skipped (same two casualties) ⛔ |
| `test_run_ownership_fence.py` + `test_checkpoint_resume.py` | **none** | **32 passed, 0 failed**, 18 skipped — CLEAN |
| `test_run_api_idempotency.py` + `test_checkpoint_resume.py` | `app_user` | clean — NOT a polluter |

**Provenance.** Rows 3, 4, 5 and 6 were **re-measured independently by plan 23.2-11** at
`622cc89` rather than copied from 23.2-05's SUMMARY. Rows 1, 2 and 7 are carried from
23.2-05's SUMMARY.

The two casualties are
`test_a_payload_from_another_checkpoint_version_is_discarded` and
`test_an_oversized_payload_is_refused_and_nothing_is_written`.

⚠ **It is DSN-DEPENDENT, and that is the trap.** With no `DATABASE_URL` the poisoning
combination reads **32 passed, 0 failed** — clean — because the polluters SKIP, and a skipped
test configures no logging. So a CI job without a DSN will never see this, and the first person
to add a faithful non-superuser DSN will see two failures appear out of nowhere.

**This is a test-isolation defect, not a product defect.** It is orthogonal to every decision in
this phase and belongs to whoever owns the tribunal CI gap. Reproducible on demand — record it
as a defect, never as a flake.

---

## DEF-23.2-15 — `alembic check` has a blind spot for partial-index predicates

**Recorded by:** plan 23.2-10.

Two half-truths corrected into one fact:

* The **CLI** form of `alembic check` fails on every tree here — `alembic.ini`'s
  `sqlalchemy.url` is empty and `env.py` falls back to an unset `DATABASE_URL`, raising
  `ArgumentError: Could not parse SQLAlchemy URL`. A command that always fails is not a gate,
  which is why this plan did not run it.
* But the repository **already runs `alembic check` inside pytest**, bound to the testcontainer
  DSN — `tests/test_ai_dedup.py::test_alembic_check_reports_no_drift` (the `command.check` call
  is at `test_ai_dedup.py:541`) — and it passes against 0016. "alembic check is unavailable
  here" is therefore NOT true of the in-pytest form.

**The real hole:** alembic 1.18.4's postgresql `compare_indexes` (`alembic/ddl/postgresql.py`)
compares the **unique flag and the index expressions only** — it **never inspects
`postgresql_where`**. A partial-index predicate that drifted between the ORM declaration and the
migration would pass `alembic check` **silently**.

That is what `test_orm_declaration_matches_the_deployed_index` (in
`tests/test_research_dispatch_dedup.py`) actually closes, by comparing `pg_indexes.indexdef`
against `ResearchRun.__table__.indexes`. The blind spot in the upstream tool is deferred — it is
not ours to fix — but it must not be re-discovered as "alembic check would have caught this".

---

## ⚠ OPERATOR WARNING — do NOT append `test_checkpoint_resume.py` to `cloudbuild.test-critical.yaml:32`

**This is not a deferral. It is a note for whoever picks up the tribunal CI gap, and its whole
value is that it arrives BEFORE they spend a cycle on a revert.**

### The trap

The standing remediation for the tribunal CI gap is written down as "append the missing test
files to `cloudbuild.test-critical.yaml:32`". **Verified at `622cc89`: that line is a SINGLE
`python -m pytest <files>` invocation**, today covering exactly four files —
`test_schema_isolation.py`, `test_advisory_lock_exactly_once.py`, `test_hash_chain_replay.py`,
`test_verification_report_endpoint.py`.

One process, one logging configuration. So if `test_checkpoint_resume.py` is ever appended there
**alongside `test_run_ownership_fence.py` or `test_stale_reclaim.py`**, CI gains **two spurious
failures** from DEF-23.2-14 above.

Those two failures will read as *"the new tests broke the build"*. The change gets reverted. And
the 37-of-37 gap stays open for another cycle — **the gap closing itself out of existence by
looking like a regression.**

### The remediation is one of two things, and both are listed on purpose

1. **Give `test_checkpoint_resume.py` its OWN pytest invocation** in that config (separate
   process, separate logging state), or
2. **Fix the logging leak first** — both casualties assert on `caplog` for WARNINGs emitted via
   stdlib logging from `pipeline/tribunal/checkpoints.py:234`, and running either worker-facing
   file first leaves that logger uncaptured.

**Do NOT do either here.** The CI gap is explicitly out of scope for phase 23.2
(23.2-CONTEXT.md § 9).

---

## Still-OPEN operator work inherited from 23.1 — carried forward UNCHANGED

None of this is phase 23.2's, and none of it was attempted. Recorded so it does not get lost.

1. **Tribunal services are not deployed.** Still `tribunal-api-00023-bc6` /
   `tribunal-worker-00009-fkm` at tag `20260901-134253`.
2. **The live `role=user` 404/200 observation was never made.** No client-role request has been
   issued against a running service — the whole client-surface argument is local-only.
3. **The tribunal CI gap is still OPEN.** `cloudbuild.test-critical.yaml:32` runs four test
   files and **none** of the 37 ownership/idempotency tests.
   ⚠ **Plan 23.2-05 added `tribunal/cloudbuild.test-cas.yaml` for THIS phase's own new file.
   That is NOT the same thing and must not be reported as closing the gap.** Furthermore the
   new config **is not wired to any trigger** — running it is operator work, exactly like
   `cloudbuild.test-rls.yaml`. Its expected count of 12 is keyed to `test_run_state_cas.py`'s
   test count and must be updated in both the grep and the success echo if a test is added.
4. **The tfstate bucket.**
5. **`app_superadmin` credential rotation.**

---

## Residual-risk statements — reproduced verbatim, not paraphrased into "fixed"

### D-23.2-11 residual risk (from plan 23.2-03)

> After D-23.2-09 the database can no longer over-claim: a member whose IdP disable failed is
> not marked revoked. A token minted before an *individual* deactivation still authenticates
> until it expires. That window is bounded by the ID-token TTL (about 1h), and
> `check_revoked=True` already closes it whenever the IdP revoke succeeded.

The per-request membership/space status check was **not** implemented — it is DEF-23.2-01.
`git diff dcd79db -- backend/app/auth/` is **empty**: not one line of `dependencies.py` or
`session.py` was touched. The window is bounded, not closed.

### D-23.2-15 residual risk — the outbox (from plan 23.2-04)

> The defect fixed here is a correctness **inversion** (a success recorded as a failure). The
> outbox is a **durability** improvement (guaranteed eventual delivery). Fixing the inversion
> fully closes F-06. After this change a mail can still be lost if the process dies between the
> commit and the send; the run is then correctly labelled and the operator's notification is
> missing — a strictly better failure than the one being removed, and it is logged at WARNING
> with the run id and the subject.

No outbox, no retry queue, no `notifications` table, no background retry was built.

### The `required` / `min_length` / `min_items` non-enforcement (from plan 23.2-09)

See DEF-23.2-13 above: browser-only today (`IntakeForm.tsx:214-217`, `:26-30`, `:33-40`), and
its home is the `/submit` verb.

---

## What is NOT a deferral — corrections to stale notes

**The `upload_file` category gap is NOT deferred. It was promoted to D-23.2-17 and FIXED** in
plan 23.2-02, alongside D-23.2-08, from one shared `CLIENT_WRITABLE_CATEGORIES` constant
(`backend/app/storage/keys.py:47`). Both `upload_file` and `delete_objects` import that one
name — `grep -c "frozenset" backend/app/api/storage_routes.py` returns **0**, so neither route
defines a copy and the upload rule and the delete rule cannot drift apart.

Plan 23.2-02's own SUMMARY states this correctly ("D-23.2-17 implemented (NOT deferred)"). If
any other document still calls it a deferral, that is a stale note — corrected here.

**Plan 23.2-08 recorded no deferrals** ("None from this plan"), and that was verified against
its SUMMARY rather than assumed.
