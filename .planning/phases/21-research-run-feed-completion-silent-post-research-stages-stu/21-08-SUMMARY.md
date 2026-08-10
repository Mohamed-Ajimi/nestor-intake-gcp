---
phase: 21-research-run-feed-completion-silent-post-research-stages-stu
plan: 08
subsystem: deploy
tags: [deploy, runbook, uat, cloud-run, cloud-build, gcp]

# Dependency graph
requires:
  - phase: 21-01..21-07
    provides: "the merged Phase 21 change set — 11 non-.planning files across frontend/ and tribunal/"
provides:
  - "infra/DEPLOY-RUNBOOK.md § Phase 21 — the DERIVED deploy surface, both gates, the ordered deploy, the digest read-backs"
  - "21-UAT.md — the recorded-run walkthrough, carrying DEF-21-02's six deferred steps as a hard obligation"
affects: [phase-21-close, the-next-measuring-run]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Deploy surface derived from the diff AND from the import graph, not from a standing note"
    - "A behaviourally-inert-but-byte-carrying service stated as an explicit operator choice rather than silently included or silently skipped"

key-files:
  created:
    - .planning/phases/21-research-run-feed-completion-silent-post-research-stages-stu/21-UAT.md
  modified:
    - infra/DEPLOY-RUNBOOK.md

key-decisions:
  - "The derived surface AGREES with 21-CONTEXT D-02 — stated explicitly, because the agreement was re-earned by measurement and the same exercise DISAGREED with a standing note on 2026-08-06"
  - "tribunal-api carries the changed bytes but is behaviourally inert; presented as a recommendation with its reasoning rather than silently included or silently skipped"
  - "No migration — DERIVED from the diff by grep, recorded with the command, not assumed"

requirements-completed: []

# Acceptance is CONDITIONAL — tasks 2 and 3 are blocking checkpoints, both open.
acceptance: conditional
open-checkpoint:
  task: 2
  type: checkpoint:human-action
  status: blocked
  blocked-by: "gcloud active account is tools@epicimpact.be, which has NO permission on the Nestor Pulse project; and the deploy surface needs operator confirmation before any spend"
  also-open:
    task: 3
    type: checkpoint:human-verify
    status: "artifact pre-created and committed; every verdict awaiting the operator"

# Metrics
duration: ~55min
completed: 2026-08-10 (Task 1 only)
---

# Phase 21 Plan 08: Ship It and Prove It Shipped — Summary

**The Phase 21 deploy surface is derived from the real diff AND the real import graph — `tribunal-worker` + `nestor-frontend` required, `tribunal-api` byte-carrying but behaviourally inert, `nestor-api` untouched — and the operator UAT is staged with DEF-21-02's six deferred steps carried in full; execution is STOPPED at Task 2 because the active gcloud identity has no access to the project.**

## Status: 1 of 3 tasks complete — STOPPED at a blocking checkpoint

| Task | Type | Status |
|---|---|---|
| 1 — Derive the surface, write the runbook | `auto` | ✅ **complete** — `508fe08` |
| 2 — Operator runs the gates and the deploy | `checkpoint:human-action` | ⏸ **BLOCKED — see below** |
| 3 — Operator UAT on recorded data | `checkpoint:human-verify` | ⏸ artifact created; verdicts awaiting operator |

## ⛔ Why execution stopped — two blockers, one of them hard

### Blocker 1 — THE GCLOUD IDENTITY IS WRONG (hard stop)

```
gcloud config get-value account  ->  tools@epicimpact.be      ❌ expected tools@dotto.be
gcloud config get-value project  ->  project-cb01b861-cb4a-438d-b9a   ✅ correct
```

The project matched; **the account did not.** Proven decisively, read-only:

```
ERROR: (gcloud.run.services.list) [tools@epicimpact.be] does not have permission to access
namespaces instance [project-cb01b861-cb4a-438d-b9a] ... This command is authenticated as
tools@epicimpact.be which is the active account specified by the [core/account] property.
```

`gcloud auth list` shows **four** credentialed accounts; `tools@dotto.be` **is** among them but is
**not active**. Per the standing rule this is a STOP-and-report condition, not something to
self-correct — so no `gcloud auth login` was run and `gcloud config set account` was **not** run
either, because changing global machine state under another agent's/operator's session is exactly
the class of silent overwrite the rule exists to prevent.

> ⭐ **THE TRAP FIRED LIVE, AND THE COUNTER-MEASURE WORKED.** The command above was deliberately run
> **without** `--format='value(...)'`. Had it used one, the permission error would have rendered as
> an **EMPTY STRING** and read exactly like *"the services are gone."* That is the documented
> 2026-08-10 confusion reproducing itself, and it is now a recorded live instance rather than a
> remembered anecdote.

**Consequence:** no gcloud read or write was possible. The free queue canary, the two Cloud Build
gate submissions, all image builds, all deploys and every read-back are **UNPERFORMED**. None of
them is reported as done, and none was inferred.

### Blocker 2 — the deploy surface needs operator confirmation before spend

Task 2 is `checkpoint:human-action` with `gate="blocking"` by design. The derived surface below is
presented for confirmation, with its evidence, before anything is built.

## The DERIVED deploy surface

**Derivation command** (`eac6f2b` = the phase base; HEAD = `2d16fdd`, plans 21-01…21-07 merged):

```bash
git diff --name-only eac6f2b..HEAD
git diff --name-only eac6f2b..HEAD | awk -F/ '{print $1}' | sort -u
# -> .planning  frontend  tribunal          (NOTE: no `backend`)
```

11 non-`.planning` files changed. Mapped to services by **build context AND import graph**:

| Path group | Files | Service | Verdict |
|---|---|---|---|
| `frontend/src/components/research/RunFeed.tsx`, `lib/research/feedRows.ts`, `lib/research/verificationGate.ts`, `routes/admin.pulse.runs.$runId.tsx` | 4 | **`nestor-frontend`** | ✅ **REBUILD — REQUIRED** |
| `frontend/src/lib/research/*.test.ts` | 2 | — | not bundled |
| `tribunal/.../pipeline/tribunal/pipeline.py`, `stage_events.py` | 2 | **`tribunal-worker`** | ✅ **REBUILD — REQUIRED** |
| `tribunal/.../runs/stages.py` | 1 | `tribunal-worker` **required**; `tribunal-api` carries the bytes | ⚖ **see the ruling** |
| `tribunal/.../tests/*.py` | 2 | — | ships nothing |
| `backend/**` | **0** | **`nestor-api`** | 🔒 **CONFIRM-ONLY** |

### ⚖ The `tribunal-api` question — the one judgement call in this plan

**Facts, each read out of the repo rather than assumed:**

1. **Both** tribunal Dockerfiles do `COPY nestor_pulse_sdk ./nestor_pulse_sdk` — the **whole**
   package. So all three changed engine files are baked into the **API image too**, and
   `build-and-push.sh` builds **both** images in ONE invocation at ONE shared `$SHA` regardless.
2. The API request path **really does** import a changed file: `runs/api.py:41`
   `from nestor_pulse_sdk.runs.stages import stages_for`, feeding `RunMetrics.stages` at
   `runs/api.py:953`.
3. **But the change is inert there.** 21-07's edit to `runs/stages.py` is **purely additive** — a
   new module-level `NON_SCHEMA_STAGE_LABELS` dict. **`ENGINE_STAGES` and `stages_for` are
   untouched**, so the API response is byte-identical.
4. The **only** non-test consumer of `NON_SCHEMA_STAGE_LABELS` is `pipeline.py:523`
   `_stage_event_label`, called **only** from `_stage_event_boundary` (`pipeline.py:597`), which
   bakes the label into the divider's `text` **at emit time — worker-side.** The API never
   re-labels.
5. `pipeline.py` / `stage_events.py` are **not** on the API's boot or request path — `TribunalPipeline`
   is imported **lazily inside a function** at `runs/adapter.py:325`/`331`.

**Therefore: functionally required = `tribunal-worker` + `nestor-frontend`. `tribunal-api` is
OPTIONAL on behaviour.**

**Recommendation: deploy `tribunal-api` at the shared `$SHA` anyway** — the image is built
regardless, so the marginal cost is one `deploy-api.sh`; skipping it leaves two images built from
one tree diverging; and it matches the Phase 15.8 precedent. **Skipping is defensible — but record
the decision and the existing revision as CONFIRM-ONLY.** This is put to the operator rather than
decided silently in either direction.

### ⛔ The surface AGREES with D-02 — and that is worth saying out loud

D-02 records the surface as "`tribunal-worker` plus `nestor-frontend`" **and in the same paragraph
says re-derive it and do not trust that line.** The derivation **agrees**. That is recorded
explicitly because **an agreement that was checked is a different object from an agreement that was
assumed** — and on 2026-08-06 the identical exercise **disagreed** with a standing note and caught
`nestor-api`, which would otherwise have shipped inert while reading as deployed.

### The migration answer — DERIVED

```bash
git diff --name-only eac6f2b..HEAD | grep -Ei 'alembic|versions/|/models?/'   # exit 1, NO output
git diff --name-only eac6f2b..HEAD | grep -Ei 'requirements.txt|package.json|package-lock.json|locales/'  # no output
```

**NO migration** (TRIBUNAL stays `0018`, INTAKE stays `0013`), **no new dependency**, **no new i18n
key**, **no new secret**. Recorded as a derived result with the command that derived it.

## Verification evidence — all re-measured at `2d16fdd`, none taken on trust

| Gate | Command | Result |
|---|---|---|
| Stale-base sentinels (×6) | see below | **6/6 PASS** |
| Engine gate, 44 files | local venv pytest over the extracted `WANTED` list | **1909 passed · 13 skipped · 6 errors · 0 FAILURES** |
| `EXPECTED_FILES` | `cloudbuild.test-engine.yaml:534` | **44**, and all 44 paths resolve on disk |
| Gates config, 13 files | local venv pytest | **190 passed · 2 skipped · 0 FAILURES** |
| `EXPECTED_FILES` | `cloudbuild.test-gates.yaml:161` | **13**, 13 paths extracted |
| Frontend type-check | `npx tsc --noEmit -p tsconfig.json` | **exit 0, no output** |
| Frontend tests | `npx vitest run` | **6 files · 61 passed** |
| i18n audit | `node scripts/i18n-audit.mjs` | **PASS — A/B/C clean**, 107 pre-existing CHECK D advisories |
| Per-file lint (4 changed sources) | `eslint --config eslint.config.js <files>` | **0 non-prettier violations** (1155 prettier = CRLF noise) |

**The 6 pytest errors are PRE-EXISTING and Windows-only** — all six carry
`ValueError: the environment variable is longer than 32767 characters` from pytest's
`PYTEST_CURRENT_TEST` teardown, confined to `test_dispatch_pii.py::test_never_raises` and
`test_fact_list_parser.py::test_parser_never_raises`. Linux CI never hits the limit. **Pass
condition is 0 FAILURES, not exit 0.** Not fixed, not reported as a regression.

**The six stale-base sentinels, each printed before any spend:**

| # | Sentinel | Result |
|---|---|---|
| 1 | `stage_events.py` exists (21-03) | PASS |
| 2 | `_sentence_or_none` (21-05) | PASS — 13 occurrences |
| 3 | `NON_SCHEMA_STAGE_LABELS` (21-07) | PASS — 1 |
| 4 | `feedRows.ts` exists (21-01) | PASS |
| 5 | `verificationGate.ts` exists (21-02) | PASS |
| 6 | `fourteen` removed (21-07) | PASS — count 0 |

## Task Commits

1. **Task 1 — derive the surface, write the runbook, stage the UAT** — `508fe08` (docs)

## Deviations from Plan

### 1. [Rule 3 — Blocking, NOT auto-fixable] The stale-base trap fired for the 28th consecutive time

- **Found during:** the very first action, before any file was read.
- **Issue:** the worktree forked at **`a3a0c96`** — **844 commits behind** the required base
  `2d16fdd`. `git rev-list --count` would have read **green**; only `git merge-base` caught it.
- **Fix:** the sanctioned `git reset --hard 2d16fdd` from `<worktree_branch_check>`, then all six
  positive-presence sentinels re-run and passed before anything else happened.
- **Why it matters here more than anywhere:** this plan submits Cloud Builds. A stale tree does not
  fail a build — it **builds the WRONG SOURCE and returns a confidently green result.**

### 2. [Rule 3 — Blocking, escalated NOT auto-fixed] Wrong gcloud identity

- Documented in full under **Blocker 1** above. Deliberately **not** self-corrected.

### 3. [Rule 1 — Unsatisfiable acceptance criterion] "`npm install` does not appear in the section"

- **Found during:** Task 1 criterion checks.
- **Issue:** Task 1's criteria say *"`npm ci` appears and `npm install` does not, within the Phase 21
  section"* — while Task 1's own **action text** instructs the section to say **"`npm ci`, NEVER
  `npm install`"** and the measured facts require recording that `npm install` caused a production
  break. **Both cannot hold literally.** This is the same collision class 21-02 hit (its Deviation 3)
  and the fifth such criterion in this phase.
- **Resolution — in favour of the criterion's evident PURPOSE:** the purpose is *"the section must
  never INSTRUCT `npm install`."* Both occurrences are **prohibitions**, quoted and verified:
  - `npm ci  # ⛔ npm ci, NEVER npm install — the lockfile IS committed`
  - `` ⛔ **`npm install` here caused a Radix/React #185 production break on 2026-07-21.** ``
- **Reported rather than silently resolved**, per the standing instruction not to contort anything
  to satisfy a grep.

### 4. [Obligation injected at execution — NOT in the plan file] DEF-21-02's six UAT steps

- **21-08's plan file was written BEFORE the 2026-08-10 operator ruling** that deferred 21-02's
  Task 3 here, so the plan does not mention it. The obligation was injected at execution and is
  **discharged**: all six steps are in `21-UAT.md` as B1…B6, with **step 5's not-a-blocker caveat**
  and **step 6's absence-is-correct semantics** both preserved verbatim and machine-verified.
- **Also carried:** DEF-21-01, DEF-21-03 and DEF-21-04 are named in the UAT as **known and out of
  scope**, so the walkthrough cannot report them as new failures.

### 5. [Out of scope — logged, NOT fixed] `npm run lint` is red tree-wide

- **DEF-21-01, operator ruling: stays deferred and OUT of Phase 21.** Verified per-file instead
  (**0 non-prettier violations** across the four changed sources). **No `prettier --write` was run.**

**Total deviations:** 5 — 2 blocking (1 auto-fixed, 1 correctly escalated), 1 criteria-collision
resolved in favour of purpose, 1 injected obligation discharged, 1 out-of-scope item honoured.

## Issues Encountered

- **A locally-green gate that ran nothing.** The first `WANTED` extraction kept the literal
  `WANTED="` prefix on the first path; pytest reported *"no tests ran in 0.00s"* while the wrapper
  script still printed **exit 0**. Caught by reading the output text rather than the exit code —
  the same discipline the runbook mandates for `gcloud builds submit`. Re-extracted, all 44 paths
  verified to resolve on disk, then re-run.
- **`.planning/` is gitignored** — `21-UAT.md` was **invisible to `git status`** and required
  `git add -f`. Confirmed present in `508fe08` before proceeding.

## Threat Flags

None. This plan adds no route, no verb, no parameter, no dependency and no secret. The only install
performed was `npm ci` from the **committed** `package-lock.json` (868 packages, all pre-pinned);
`git status` after it showed no manifest change. T-21-08-SC is satisfied by construction.

## Known Stubs

**`21-UAT.md` is deliberately unfilled** — every verdict reads *"(awaiting operator)"*. That is its
intended pre-UAT state, not a stub: **no verdict in it may be filled from inference.** It becomes
complete only when the operator walks the page.

## Self-Check: PASSED

- `infra/DEPLOY-RUNBOOK.md` — FOUND, `grep -c "^## Phase 21"` = **1** (line 4708)
- `21-UAT.md` — FOUND, and confirmed in commit `508fe08` via `git diff --cached --name-only`
- `508fe08` — FOUND in `git log`
- No deletions: `git diff --diff-filter=D --name-only HEAD~1 HEAD` is **empty**
- `STATE.md` / `ROADMAP.md` — **NOT modified** (orchestrator owns those writes)

---
*Phase: 21-research-run-feed-completion-silent-post-research-stages-stu*
*Plan 08 — Task 1 complete; Tasks 2 and 3 are OPEN blocking checkpoints*
*Nothing was deployed, no build was submitted, and NO research run was triggered*
