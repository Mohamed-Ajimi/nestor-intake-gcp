# Phase 23.1 — Deferred Items

Items shipped knowingly, recorded so they are never discovered later as surprises.
Created by plan `23.1-08` (wave 1). Plans 14 and 15 append to this file in later waves.

---

## DEF-23.1-01 — dropping `rehype-raw` costs two badges on the sales battlecard

**Recorded by:** plan 23.1-08, task 1.
**Commit:** see `23.1-08-SUMMARY.md`.

### What changed

`rehype-raw` was removed from `frontend/package.json`, `frontend/package-lock.json` and from
`frontend/src/components/sales/BattlecardMarkdown.tsx` (T-23.1-30). It rendered
author-supplied HTML with no sanitiser.

### The consequence — this is NOT free

`BattlecardMarkdown.tsx` synthesises raw tags in `transformContent()`:

- `[v]` / `[!]` / `[?]` / `[x]` and the legacy emoji `✅ ❓ 🚩 ►` become `<marker data-type="…">`
- `[H]` / `[M]` become `<conf data-level="…">`

and registers `marker` / `conf` component handlers that render `MarkerBadge` and
`ConfidenceBadge`. Those handlers **only ever fired because `rehype-raw` turned the raw tags
into real nodes.** With the plugin gone, react-markdown drops the raw tags and
**neither badge renders.** Status markers and H/M confidence pills disappear from battlecard
output.

The handlers and both badge components were deliberately LEFT IN PLACE, with a comment at
the handler site, so reinstatement is a one-line change.

### Why this is acceptable

Both reachable render paths are on the legacy Supabase sales route, which is inert without
`VITE_SUPABASE_*`:

- `frontend/src/routes/admin.sales.projects.$id.tsx:1081` — the `raw_markdown` fallback
- `frontend/src/components/sales/BattlecardBlocks.tsx:39` and `:52` — the `blocks` path,
  reached from `admin.sales.projects.$id.tsx:1076`

> **Correction to the plan.** `23.1-08-PLAN.md` states the sole caller is `:1081`. That is
> wrong — `BattlecardBlocks.tsx` is a second, and in practice the PRIMARY, path (`:1073`
> prefers `battlecard.blocks` and only falls back to `raw_markdown`). Both sit on the same
> inert route, so the disposition is unchanged, but the blast radius is two call paths.

`frontend/src/lib/supabase.ts:6` exports `null` when `VITE_SUPABASE_URL` /
`VITE_SUPABASE_ANON_KEY` are absent, and every data path in the sales route is guarded by
`if (!supabase)`. No battlecard can load, so no badge can be missed.

### If the sales path is ever revived

Do **NOT** restore plain `rehype-raw` — that restores the unsanitised-HTML capability for
every caller of `ReactMarkdown`. Use `rehype-sanitize` with a schema allowing exactly
`marker[data-type]` and `conf[data-level]`. Adding that dependency is forbidden in phase 23.1
(`23.1-CONTEXT.md` § 9 defers dependency work to its own phase).

---

## DEF-23.1-02 — frontend lint is not a CI gate this phase

Carried from `23.1-CONTEXT.md` § "shipped knowingly". Restated here because plan 23.1-08
touched frontend source and did NOT run lint or any `--fix` sweep, by instruction.

Measured at this plan's base (`3c8cd10`): `npm run lint` is red — 61 errors + 38 warnings on
an LF checkout (54 `no-explicit-any`, 4 `no-empty`, 2 `prefer-const`, 1 prettier), plus
~29,300 `prettier/prettier` "Delete ␍" artifacts on this machine because `core.autocrlf=true`.
Running `eslint --fix` here would rewrite every file's line endings and bury the diff.

The gates for plan 23.1-08 were `tsc` + `vitest` + `scripts/i18n-audit.mjs`, all green.
A lint-cleanup phase should be scheduled separately.

---

## DEF-23.1-03 — docs outside `frontend/` still name the two deleted components

**Found by:** plan 23.1-08, task 2. **Out of scope, deliberately NOT fixed.**

Plan 23.1-08's `files_modified` covers `frontend/**` only, and its `<done>` grep is scoped to
`frontend/src`, which is now at zero hits. But `git grep` over TRACKED files repo-wide shows
the deleted names surviving in documentation:

| File | Line | What it says |
|------|------|--------------|
| `CLAUDE.md` | 63 | lists `NestorBriefingPDF.tsx` as a `@react-pdf/renderer` consumer |
| `AGENTS.md` | 63 | identical line |
| `docs/handbook/12-frontend.md` | 448, 635, 733 | describes both files as existing dead code |
| `docs/handbook/19-known-gaps-and-roadmap.md` | 107 | lists both as "Removable" |

Nothing is broken — these are prose, and `docs/handbook/19` in particular is now simply
DONE rather than wrong. But `CLAUDE.md:63` and `AGENTS.md:63` are load-bearing context files
read at the start of every session, and they now name a file that does not exist.

A doc-sync pass should update them. Editing them from this plan would have exceeded its
declared file scope on a wave where isolation is disabled and other plans are writing.

## DEF-23.1-04 — `ContextPackPDF.tsx` and `pdfFonts.ts` are also dead

**Found by:** plan 23.1-08, task 2. **Out of scope, deliberately NOT deleted.**

Task 2 required confirming `pdfFonts.ts` keeps a consumer after `NestorBriefingPDF.tsx` is
deleted. It does — `ContextPackPDF.tsx:2` — so no third file was dropped and the plan's STOP
condition did not trigger.

But `ContextPackPDF.tsx` is itself imported by NOTHING. The only apparent hits are a SUBSTRING
trap: `ContextPackBlock.tsx:73/374/578` define and call a local `downloadContextPackPDF`, the
jsPDF exporter, which merely CONTAINS the string `ContextPackPDF`. `docs/handbook/12-frontend.md:448`
independently records the same finding ("not imported by anything; the shipped export is jsPDF").

So the real dead set is `ContextPackPDF.tsx` + `pdfFonts.ts` + the `@react-pdf/renderer`
dependency, and removing all three together would be the complete cleanup. Plan 23.1-08
explicitly forbids removing `@react-pdf/renderer`, and deleting a third file was out of its
scope, so this is left for a follow-up. Note that the dependency removal belongs to the
dependency phase deferred by `23.1-CONTEXT.md` § 9.

---

## DEF-23.1-05 — `test_no_run_research_route.py`'s live-route assertion is VACUOUSLY GREEN

**Recorded by:** plan 23.1-09, task 2. **Measured, not inferred. Not fixed — test code is
outside this plan's file scope and this plan changes no code.**

`backend/tests/test_no_run_research_route.py:44` sets
`_FORBIDDEN_PATH_TOKENS = ("run-research", "run_research", "tribunal", "research")` — note the
bare `research` — and `test_app_exposes_no_deep_research_route` asserts NO path in
`main.app.routes` carries one. The live app mounts SEVEN `/research` route paths
(`research_routes.py:191, 249, 384, 528, 733, 793, 877`). The assertion should therefore be RED.

It is not, because of **D-23.1-14** (§ 11 of `23.1-CONTEXT.md`): under fastapi 0.141.1
`app.routes` holds 8 entries including lazy `_IncludedRouter` placeholders, so a naive flat loop
sees ZERO of the 65 real routes. Measured here: `grep -c "_flatten_routes"
backend/tests/test_no_run_research_route.py` -> **0**, i.e. the test uses exactly the naive loop
D-23.1-14 proved returns nothing.

So this test passes for the wrong reason. Two consequences:

1. It is not evidence of anything. The prohibition CLAUDE.md now names is really carried by
   `backend/scripts/ci_no_run_research.sh` (measured green at HEAD: `bash
   scripts/ci_no_run_research.sh` from `backend/` -> `exit=0`), by
   `test_scope_guard_run_research.py` which exercises that script both ways, and by
   `test_no_run_research_route.py`'s SECOND test, the `intake_routes.py` source scan — which
   DOES bite (re-implemented as a proxy here: 22 route-decorator paths seen, 0 offending).
2. If a future plan fixes route flattening (e.g. by reusing `_flatten_routes` from
   `test_client_surface_open.py`, as D-23.1-14 requires of plans 10 and 11), this test will turn
   RED against the intended, live research router. **The fix is to narrow
   `_FORBIDDEN_PATH_TOKENS` — drop the bare `research` — not to unmount the router.** The
   file's own comment "no in-scope route path contains it" is now false and should be corrected
   at the same time.

## DEF-23.1-06 — `DEPLOY.md` Step 6's "no auth required" health-probe curls are unverified

**Recorded by:** plan 23.1-09, task 1. **Deliberately NOT edited.**

Task 1 corrected `DEPLOY.md:88` against `deploy-api.sh:157`. Fifty lines later, Step 6
(`:136-148`) still instructs an operator to run `curl -sf "$API_URL/health"` under the headings
"Liveness (no auth required)" and "Readiness (no auth; ...)". With
`--no-allow-unauthenticated` those anonymous external curls would be rejected by Cloud Run's
front end before reaching FastAPI — UNLESS a separate `allUsers` IAM binding exists on the
service, which `--no-allow-unauthenticated` does not remove.

Which of those is true cannot be settled from this tree: it needs
`gcloud run services get-iam-policy nestor-pulse-api`, and `gcloud` is not on the agent shell's
PATH. Editing the text on inference would have replaced one unverified claim with another, so
it was left alone. **Resolve by reading the live IAM policy, then either correct Step 6 or add
`--header "Authorization: Bearer $(gcloud auth print-identity-token)"` to those two curls.**

The Services table (`:18-21`) and Step 4 (`:111-121`) were also checked: the table's
"JWT-gated; health probes exempt" is about the FastAPI gate and is correct, and Step 4 makes no
authentication claim at all, so neither conflicts with `deploy-worker.sh:175`'s
`--no-allow-unauthenticated`.

## DEF-23.1-07 — `AGENTS.md:63` and `docs/handbook/` still carry the corrections made here

**Recorded by:** plan 23.1-09. **Out of file scope — extends DEF-23.1-03, does not replace it.**

This plan fixed `CLAUDE.md:63` (the deleted `NestorBriefingPDF.tsx`) because `CLAUDE.md` was
already in its `files_modified`. `AGENTS.md:63` and the `docs/handbook/` lines named by
DEF-23.1-03 were NOT touched and remain stale.

Additionally, the D-23.1-10 ceiling correction was applied to `CLAUDE.md` only. Any other doc
stating that the flow ends at `decomposed` still asserts the superseded v1.0 scope. A doc-sync
pass should carry both corrections outward.

## DEF-23.1-11-01 — `app/main.py` ai_router mount comment is stale (comment-only)

Found by plan 23.1-11. `main.py:153-162` still states that `ai_router` inherits
`get_current_identity` "and nothing more". Since `c9d0587` it also carries ONE router-level
`Depends(superadmin_gate)`. `main.py` was not in plan 11's `files_modified`, so the clause was
not applied. No behavioural effect — the gate lives on the router object in `ai_routes.py`.
Exact replacement wording is in `23.1-11-SUMMARY.md` § Deviations 4. Pick up in 23.1-15.

## DEF-23.1-13-01 — `infra/DEPLOY-RUNBOOK.md:5790` warns about a column that no longer exists

Found by plan 23.1-13. The ⛔ block at `infra/DEPLOY-RUNBOOK.md:5790` reads
"`skill_runs.started_at` IS A DEAD COLUMN — do not 'improve' this by switching to it", and the
paragraph under it describes the column as present-but-unwritten. Migration **0015** (this plan)
DROPPED it, so the prose now describes a column that is not in the schema.

Not edited here for two reasons: the runbook is outside plan 23.1-13's `files_modified` pathspec,
and it is an append-only dated deploy log where rewriting a past entry falsifies the record. The
right shape is probably a dated one-line addendum ("dropped in alembic 0015, phase 23.1"), not an
edit to the original claim.

No operational risk: the advice the block gives — use `created_at` — remains correct, and the
warning "do not switch to `started_at`" is now enforced by the schema itself. Impact is a reader
who trusts the runbook's inventory of columns.

Note for whoever picks this up: `backend/app/db/alembic/versions/0001_baseline_schema.py:300`
still creates the column and MUST stay that way. It is an applied historical revision; editing it
desynchronises every database already past 0001.

---

## DEF-23.1-02 (ADDENDUM, plan 23.1-14) — the measured lint figures, and why they are ~100x the number recorded above

**Recorded by:** plan 23.1-14, task 3. **Plan 08's entry above is left INTACT** — this
corrects its numbers rather than rewriting its record.

Plan 23.1-14 added `tsc` and `vitest` steps to `frontend/cloudbuild.yaml` and deliberately
added NO lint step. Before writing that decision into the config header it re-measured the
lint state, and the figure carried since plan 08 turns out to be wrong by two orders of
magnitude.

### What was recorded (plan 08, from `23.1-CONTEXT.md`)

> 61 errors + 38 warnings on an LF checkout (54 `no-explicit-any`, 4 `no-empty`,
> 2 `prefer-const`, 1 prettier), plus ~29,300 `prettier/prettier` "Delete ␍" artifacts

That reads as: strip the CRLF noise and about 61 real problems remain.

### What is actually true — MEASURED 2026-09-04 at `6f7da8b`

The LF figure was never measured on an LF tree. It was derived by counting the
NON-`prettier/prettier` messages and assuming every `prettier/prettier` message was a CRLF
artifact. Most of them are not.

Method: `git -c core.autocrlf=false -c core.eol=lf archive HEAD frontend` (a genuine LF
tree — plain `git archive` still applies `core.autocrlf` and yields CRLF), extracted and
linted inside `node:22-slim` with `npm ci && npx eslint .` — i.e. exactly what Cloud Build
would see.

| Tree | errors | warnings | total |
|---|---|---|---|
| **True LF** (node:22-slim) | **6540** | **36** | **6576** |
| This machine's Windows working tree (`core.autocrlf=true`) | 28924 | 36 | 28960 |

LF errors by rule, across **91 files**:

| rule | count |
|---|---|
| `prettier/prettier` | **6480** (99.1% of all errors) |
| `@typescript-eslint/no-explicit-any` | 54 |
| `no-empty` | 4 |
| `prefer-const` | 2 |

LF warnings: 32 `react-refresh/only-export-components`, 2 `react-hooks/exhaustive-deps`,
2 with no rule id.

Worst single file: `src/routes/admin.pulse.intakes.$id.tsx`, **1148 errors on its own**;
then `FieldRenderer.tsx` 722, `AIReviewPanel.tsx` 667, `ui/sidebar.tsx` 583.

### The two DISTINCT problems

1. **~6480 genuine `prettier/prettier` violations, independent of line endings.** The
   repository has simply never been prettier-formatted. This is the large one, and it is
   the part plan 08's number missed entirely. Only **60** of the 6540 errors are
   non-formatting (the 54 + 4 + 2 above).
2. **The CRLF divergence.** `git config core.autocrlf` is `true` and `git ls-files --eol`
   reports `i/lf w/crlf`: committed blobs are LF, the checkout is CRLF. That inflates the
   prettier count from 6480 to 28864 (**+22384**) on this machine, and it also means
   `gcloud builds submit` from this box uploads CRLF sources. `tsc` and `vitest` are
   line-ending agnostic (both verified green in `node:22-slim` on both trees), which is
   precisely why those two are safe to gate on and lint is not.

### Disposition — unchanged, but now for a much stronger reason

No lint step was added. A blocking lint gate would land red and block every merge — the
same self-inflicted denial-of-service (T-23.1-63) that made D-23.1-09 put the backend
widening last in this phase.

The cleanup is also much bigger than "61 errors": a `prettier --write` sweep is a ~91-file,
~6500-line-touching diff. It must not ride along inside a CI change, and it must be done on
a tree where the line-ending question is settled FIRST (add a `.gitattributes` with
`* text=auto eol=lf`, or set `core.autocrlf=input`), or the sweep will itself rewrite every
line ending and bury the real changes.

**Do NOT run `eslint --fix` to make a gate go green.** The reason is recorded in two places
as the plan requires: here, and in the header of `frontend/cloudbuild.yaml`.

## DEF-23.1-14-01 — more source-text assertions in `test_research_runs_migration.py` share the shape that was just fixed

**Recorded by:** plan 23.1-14, task 1. **Deliberately NOT fixed** — the plan scopes task 1
to the three red tests and says to note the fragile ones rather than fix them all.

Plan 14 deleted two whole-file source greps and replaced them with `information_schema`
assertions. Two survivors in the same file are green today only by luck and would go red
on a single new docstring sentence:

| test | assertion | why it is fragile |
|---|---|---|
| `test_status_default_queued_not_remapped` | `assert "succeeded" not in src` over all of `0011_research_runs.py` | any comment or docstring explaining the D-05 boundary — i.e. explaining why `succeeded` must NOT appear — makes the word appear |
| `test_0012_no_rls_policy_grant_or_index` | `assert "GRANT" not in src` over all of `0012_research_run_chain_bundle.py` | 0012's docstring already says it "touches NO RLS policy, grant, or index"; it survives only because that sentence is lower-case `grant` |

The second is the closer call: it is one capitalisation away from the exact failure mode
that killed `test_0012_no_server_default_on_new_columns`.

Both should become behavioural in the same style — `pg_policies` / `pg_indexes` /
`information_schema.role_table_grants` diffs taken before and after the 0012 step — rather
than getting a cleverer regex. A comment-stripping grep is not a fix; it is the same trap
with more code.

## DEF-23.1-14-02 — `testcontainers[postgresql]` extra does not exist in the pinned version

**Recorded by:** plan 23.1-14, task 2. **Out of scope — not fixed.**

Observed while running the widened gate's install step inside `python:3.12-slim`:

    warning: The package `testcontainers==4.15.0` does not have an extra named `postgresql`

`backend/pyproject.toml`'s dev group asks for an extra the pinned version no longer ships.
It is only a warning today — `testcontainers` 4.x bundles the postgres module in the base
package, and the container path is bypassed in CI anyway because `DATABASE_URL` is set — so
the suite is unaffected (599 passed in that same run). But a request for a non-existent
extra is silently ignored by uv, which means the day it DOES matter it will fail as a
missing import rather than as a dependency error. Belongs with the dependency work
`23.1-CONTEXT.md` § 9 defers to its own phase.

## DEF-23.1-14-03 — D-23.1-15: the tribunal ownership-fence and idempotency proofs run in NO committed gate

**Recorded by:** plan 23.1-14. **NOT FIXED — `tribunal/cloudbuild.test-critical.yaml` is
OUTSIDE this plan's `files_modified`**, which is exactly four paths
(`backend/tests/test_mail_render.py`, `backend/tests/test_research_runs_migration.py`,
`cloudbuild.test.yaml`, `frontend/cloudbuild.yaml`) plus this file. Editing another config
would have exceeded the declared scope, so this is handed to plan 15 / the operator rather
than silently dropped. **This is an OPERATOR ITEM.**

### Measured at `4e3a549`, 2026-09-04

Plans 23.1-05 and 23.1-06 built LIVE proofs of the tribunal run-ownership fence and the
paid-call idempotency races. Which committed Cloud Build config runs them?

| test file | tests | named in a committed `*.yaml`? |
|---|---|---|
| `tribunal/nestor_pulse_sdk/tests/test_run_ownership_fence.py` | 16 | **NONE** |
| `tribunal/nestor_pulse_sdk/tests/test_run_api_idempotency.py` | 16 | **NONE** |
| `tribunal/nestor_pulse_sdk/tests/test_stale_reclaim.py` | 5 | only `cloudbuild.test-engine.yaml`, which runs `-m "not live"` |

(Search excludes `.claude/`, which carries worktree copies.) So 32 of those 37 tests are
named nowhere at all, and the remaining 5 are collected by a config that filters their LIVE
half out.

### Why they cannot simply be picked up by the existing "full suite" config

`tribunal/cloudbuild.test.yaml` mounts the Docker socket, but its testcontainers fixture
never starts. Its own header (`:27-40`) records the diagnosis verbatim from `pytest -rs`:

    Docker not available for testcontainers:
    "host" network_mode is incompatible with port_bindings

testcontainers 4.x requests port bindings for the Postgres container it spawns, and docker
rejects that under the `--network=host` the step requires. So `postgres_container` skips and
every dependent test skips with it — the build still exits 0, a green "full suite" that
proves nothing about the DB-backed paths. Plan 05 measured 6 passed / 13 skipped there;
plan 06 measured 6 static / 10 LIVE skipped.

**Do NOT try to repair the testcontainers path.** All three files skip on an explicit
`DATABASE_URL` guard instead (`test_run_ownership_fence.py:368`,
`test_run_api_idempotency.py:199`, `test_stale_reclaim.py:67` — each requiring a
`postgresql+asyncpg://` DSN), and plan 06 made its file DSN-capable precisely so no rewrite
is needed: it measured 16 passed against a disposable `postgres:15`.

### The fix — a one-line change plan 15 can make

`tribunal/cloudbuild.test-critical.yaml` is the ONLY config with a real DSN
(`postgresql+asyncpg://postgres:testpw@localhost:5432/postgres`, `:31`) and it names its
files BY HAND at `:32`, currently four:

    test_schema_isolation.py  test_advisory_lock_exactly_once.py
    test_hash_chain_replay.py test_verification_report_endpoint.py

Append the three above to that same `python -m pytest ...` invocation. The files' own
headers already point at this config as the place they belong —
`test_run_ownership_fence.py:91` reads "`cloudbuild.test-critical.yaml` (which does) names
four" — so the gap is self-documented and just never closed.

Two things to check while doing it: that step runs `python:3.11-slim` while the tests are
otherwise exercised on 3.12, and `test-critical.yaml` names files by hand with **no
collected-count assertion**, so a mistyped path there is a silent skip. The pattern to copy
is `cloudbuild.test-engine.yaml:520-560` (`EXPECTED_FILES`), the same one plan 23.1-14 used
for `cloudbuild.test.yaml`.
