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
  - "Both Cloud Build gates GREEN on the merged tree, read by build id"
  - "The BEFORE digest baseline for all four services"
affects: [phase-21-close, the-next-measuring-run]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Deploy surface derived from the diff AND from the import graph, not from a standing note"
    - "A behaviourally-inert-but-byte-carrying service stated as an explicit operator choice"
    - "Build-time frontend config recovered from the LIVE bundle rather than hand-typed"

key-files:
  created:
    - .planning/phases/21-research-run-feed-completion-silent-post-research-stages-stu/21-UAT.md
  modified:
    - infra/DEPLOY-RUNBOOK.md

key-decisions:
  - "The derived surface AGREES with 21-CONTEXT D-02 — stated explicitly, because the agreement was re-earned by measurement and the same exercise DISAGREED with a standing note on 2026-08-06"
  - "tribunal-api deploys at the shared $SHA by operator ruling: built regardless, and skipping diverges two images from one tree"
  - "No migration — DERIVED from the diff by grep, recorded with the command, not assumed"
  - "STOPPED before the first deploy: the gcloud identity drifted a SECOND time, mid-session, and a mid-sequence flip would half-deploy the fleet"

requirements-completed: []

# Acceptance is CONDITIONAL — the deploy did not run and Task 3 is untouched.
acceptance: conditional
open-checkpoint:
  task: 2
  type: checkpoint:human-action
  status: "partially executed — pre-flight COMPLETE and both gates GREEN; the DEPLOY did not run"
  blocked-by: "the active gcloud account reverted from tools@dotto.be to tools@epicimpact.be DURING this session, without the agent touching it — the identity is UNSTABLE, and a flip between the frontend and worker steps would leave a half-deployed fleet"
  also-open:
    task: 3
    type: checkpoint:human-verify
    status: "artifact created and committed; every verdict awaiting the operator (requires the deploy first)"

# Metrics
duration: ~95min
completed: 2026-08-10 (Task 1 complete; Task 2 pre-flight complete, deploy NOT run)
---

# Phase 21 Plan 08: Ship It and Prove It Shipped — Summary

**The deploy surface is derived from the real diff and the real import graph, both Cloud Build gates are GREEN on the merged tree, the queue is proven empty and the BEFORE digests are captured — but NOTHING WAS DEPLOYED, because the gcloud identity silently reverted to the wrong account for the second time in one session and a mid-sequence flip would leave the fleet half-deployed.**

## Status: Task 1 complete · Task 2 pre-flight complete, deploy NOT run · Task 3 untouched

| Task | Type | Status |
|---|---|---|
| 1 — Derive the surface, write the runbook | `auto` | ✅ **complete** — `508fe08` |
| 2 — Gates and deploy | `checkpoint:human-action` | ⚠️ **pre-flight COMPLETE, both gates GREEN — DEPLOY NOT RUN** |
| 3 — Operator UAT on recorded data | `checkpoint:human-verify` | ⏸ artifact created; needs the deploy first |

## ⛔ Why the deploy did not run — the identity drifted a SECOND time, mid-session

The operator fixed the account between checkpoints. **I re-verified it myself and it was correct**,
then it **reverted on its own, roughly ten minutes later, without this agent touching it.**

| Time (UTC) | Command | Identity in force |
|---|---|---|
| 17:31 | `gcloud config get-value account` | ✅ `tools@dotto.be` |
| 17:33 | BEFORE digests, all 4 services | ✅ worked |
| 17:36 | queue canary, 2050 objects listed | ✅ worked |
| 17:37–17:39 | **both Cloud Build gates submitted and SUCCEEDED** | ✅ worked |
| ~17:40 | `gcloud builds describe` ×2 | ✅ worked |
| ~17:45 | `gcloud builds log` | ❌ **`PERMISSION_DENIED` … authenticated as `tools@epicimpact.be`** |

Diagnosis, so this is a finding and not a shrug:

- **It is not an env override.** `env | grep -i cloudsdk` shows only `CLOUDSDK_PYTHON`. No
  `CLOUDSDK_CORE_ACCOUNT`.
- **The persisted config itself was rewritten.** `gcloud config configurations list` now reports
  `default … tools@epicimpact.be`. Something on this machine ran an equivalent of
  `gcloud config set account` / `gcloud auth login` **while this plan was mid-flight**.

**This is the documented trap reproducing itself** — *"`auth login` silently picked the wrong
identity + project and overwrote a fix seconds later"* — except it overwrote the operator's OWN fix,
during a deploy window.

### Why this stops the deploy rather than being worked around

Per the standing rule (and this plan's own `T-21-08-01`) a wrong identity is a **STOP-and-report**
condition, so no `gcloud config set account` and no `gcloud auth login` was run.

**But the stronger reason is the shape of this particular deploy.** It is a **four-step ordered
sequence** — frontend, then `tribunal-api`, then `tribunal-worker` **last**. An identity that can
flip *between* steps does not fail cleanly: it deploys the frontend on new code, then denies the
worker. That is **T-21-08-03 (an inert deploy that reads as successful)** with the added damage of a
**divergent fleet**, and the worker — the one component whose staleness silently changes what the
$45 run measures — is exactly the one left behind. **The safe moment to stop is before step 1, and
that is where execution stopped.**

**Nothing is in a half-applied state.** No image was built, no service was deployed, no migration
exists to be half-run, and no research run was triggered.

## ✅ What DID complete — all of the pre-flight

### Both Cloud Build gates: GREEN, read by build id

| Gate | Build ID | Status | Duration |
|---|---|---|---|
| engine (`cloudbuild.test-engine.yaml`) | **`4dbf4097-a9dd-43f2-a4b4-037f398303a9`** | **SUCCESS** | 17:37:54 → 17:39:28Z |
| gates (`cloudbuild.test-gates.yaml`) | **`8d68ee2f-7339-47da-afed-becb764887e9`** | **SUCCESS** | 17:38:05 → 17:39:25Z |

**Read via `gcloud builds describe <id>`, never from a tailed pipeline's exit code.** Both submit
wrappers printed `exit 0` — which is exactly the value they would have printed on a FAILED build, so
it was ignored by construction.

> ⚠️ **`collecting: 44 of 44 expected files` was NOT read verbatim** — the identity flipped before
> `gcloud builds log` could run, and it returned `PERMISSION_DENIED`. Recorded as **NOT OBTAINED
> with its reason**, per the § 15.2.k precedent, rather than given a plausible line nobody read.
>
> ⭐ **However, SUCCESS ENTAILS IT, and this is a mechanism not a hope.** In
> `cloudbuild.test-engine.yaml:534-562`, the collection assertion runs **before** pytest and
> `exit 1`s on any mismatch; the `collecting:` line is printed **only after** it passes, and pytest
> runs **after that**. A build cannot reach SUCCESS with a collection count other than 44, nor with
> a failing test. **The green build is therefore proof the assertion held** — the literal string is
> what is missing, not the guarantee.

**Local pre-measurement of the same files at `2d16fdd`, for the record:** engine **1909 passed · 13
skipped · 6 errors · 0 FAILURES**; gates **190 passed · 2 skipped · 0 FAILURES**. The 6 errors are
the pre-existing **Windows-only** `PYTEST_CURRENT_TEST` env-limit failures in
`test_dispatch_pii.py` and `test_fact_list_parser.py`; **Linux CI does not hit them, and the green
Cloud Build confirms it.**

### The free queue canary: PASS — nothing running, nothing claimable

Bucket **`gs://project-cb01b861-cb4a-438d-b9a-nestor-audit`** (identified as the live one by having
the 9 known prefixes incl. `368ff3a0`, `7dcf51d5`, `d6bb3aae`; the 22-prefix `nestor-audit-prod` is
a different, older bucket).

| Measure | Value |
|---|---|
| run prefixes | **9** — unchanged from the recorded baseline |
| objects listed | 2050 |
| **newest write anywhere** | **`2026-08-05T19:21:31Z`** — **exactly** the recorded baseline |

**Nothing has claimed anything.** The always-on worker polls every 2s at `minScale=1`, so a
claimable row would already be writing blobs. This also re-confirms, independently, that **the code
deployed at `20260806-175613` has still never executed.**

### BEFORE digests — the baseline for the read-back

All four digest-pinned; **none resolves to `:latest`**.

| Service | Revision (before) | Digest (before) |
|---|---|---|
| `nestor-frontend` | `nestor-frontend-00028-q52` | `frontend@sha256:541b2b52…943dea` |
| `tribunal-api` | `tribunal-api-20260806-175613-180706` | `tribunal-api@sha256:55978d5e…03f3bc` |
| `tribunal-worker` | `tribunal-worker-20260806-175613-180925` | `tribunal-worker@sha256:ae5722bc…b66b60` |
| `nestor-api` **(CONFIRM-ONLY)** | `nestor-api-00045-hdw` | `backend@sha256:a525c6e2…d4f06a` |

⭐ **The orchestrator's staleness observation is CONFIRMED and it matters:** `nestor-frontend` was
last deployed **2026-07-28**, the rest on **2026-08-06**. Its live image tag is
`frontend:20260728-094409`. **If the post-deploy frontend digest does not move off
`sha256:541b2b52…`, the deploy silently no-op'd** — with a fleet this stale, "it looks the same" is
the expected wrong conclusion, so the before/after digest is the only honest test.

### The worker's plain env — READ BACK, not asserted

```
NESTOR_ENV=prod
NESTOR_WORKER_POLL_INTERVAL=2.0
NESTOR_WORKER_STALE_MINUTES=60          ✅ 60, not 525600
NESTOR_TRIBUNAL_UNCAPPED=1              ✅ the only tunable in the committed list
NESTOR_OPENAI_DR_MODEL=gpt-5.6-sol
```

- ✅ **NO `NESTOR_RUN_ABORTED_MARKER`** — absent, as expected.
- ⭐ **NO `NESTOR_TRIBUNAL_WORKSHOP_*` of any kind — recorded as a POSITIVE finding.** The Wave-4
  validated configuration **IS** the code defaults, so the next measuring run will measure the
  configuration that was actually validated.
- Secrets **by name only**: `ANTHROPIC_API_KEY → Nestor_Claude2`, `SERPAPI_API_KEY → Nestor_SERP`,
  plus `Nestor_Gemini`, `Nestor_OpenAI`, `DATABASE_URL_WORKER`, `AUDIT_GCS_BUCKET`. **No value was
  read.** Note the ANTHROPIC binding is `Nestor_Claude2`, i.e. the 15.8 `Nestor_Claude_Temp` burner
  is **no longer in force** — confirm that is intended before spending on the run.
- The worker's `containers[0].image` is `tribunal-worker:20260806-175613` — **a mutable tag, quoted
  here only to show it is NOT what the digest table above relies on (G-1).**

### Frontend build config — recovered from the LIVE bundle, not hand-typed

The runbook deliberately records these as placeholders, and mistyping one **breaks the live
frontend**. Rather than retype them, all four were extracted from the currently-deployed bundle
(`/assets/index-C6zuGW-Q.js`, 808 KB), which guarantees the rebuild reproduces live config exactly:

| Substitution | Source |
|---|---|
| `_API_BASE_URL` | `https://nestor-api-1055853212188.europe-west1.run.app` — inlined in the live bundle |
| `_FB_AUTH_DOMAIN` | `project-cb01b861-cb4a-438d-b9a.firebaseapp.com` |
| `_FB_PROJECT_ID` | `project-cb01b861-cb4a-438d-b9a` |
| `_FB_API_KEY` | the public Firebase web key, recovered verbatim from the live bundle — **not written into this file**, following the runbook's own `<public firebase web apiKey>` convention |

## Task Commits

1. **Task 1 — derive the surface, write the runbook, stage the UAT** — `508fe08` (docs)
2. **Summary + continuation evidence** — this commit (docs)

## Deviations from Plan

### 1. [Rule 3 — Blocking, auto-fixed] The stale-base trap fired — 28th consecutive time

Worktree forked at **`a3a0c96`**, **844 commits behind** `2d16fdd`. `git rev-list --count` would
have read **green**; only `git merge-base` caught it. Corrected with the sanctioned
`git reset --hard`, then **all six positive-presence sentinels re-run and passed** — once before any
edit, and **again before the gates were submitted**. For a plan that submits Cloud Builds a stale
tree does not fail: it **builds the wrong source and returns a confidently green result.**

### 2. [Rule 3 — Blocking, correctly ESCALATED not auto-fixed] Wrong gcloud identity, TWICE

First occurrence blocked the original checkpoint; the operator fixed it. **It then reverted
mid-session** — full timeline and diagnosis above. Not self-corrected, per the standing rule.

### 3. [Rule 1 — Unsatisfiable acceptance criterion] "`npm install` does not appear"

Task 1's criteria require `npm install` to be **absent** from the section, while Task 1's own action
text requires writing **"`npm ci`, NEVER `npm install`"** and the measured facts require recording
that it caused a production break. **Both cannot hold literally** — the fifth such collision in this
phase, and the same class as 21-02's Deviation 3. **Resolved toward the criterion's evident
purpose** ("the section must never INSTRUCT `npm install`"): both occurrences are **prohibitions**,
verified by reading every match. Reported rather than silently resolved.

### 4. [Obligation injected at execution — absent from the plan file] DEF-21-02's six UAT steps

21-08's plan predates the ruling that deferred 21-02's Task 3 here. **Discharged:** all six steps
are in `21-UAT.md` as B1…B6, with **step 5's not-a-blocker caveat** and **step 6's
absence-is-correct semantics** preserved verbatim and machine-verified. DEF-21-01/03/04 are named
there as known and out of scope so the walkthrough cannot misreport them.

### 5. [Out of scope — logged, NOT fixed] `npm run lint` red tree-wide

**DEF-21-01, operator ruling.** Verified per-file instead: **0 non-prettier violations** across the
four changed sources (1155 prettier messages, all CRLF checkout noise). **No `prettier --write` was
run.**

**Total deviations:** 5 — 1 blocking auto-fixed, 1 blocking correctly escalated (twice), 1
criteria-collision resolved toward purpose, 1 injected obligation discharged, 1 out-of-scope item
honoured.

## Issues Encountered

- ⭐ **A locally-green gate that ran ZERO tests while reporting exit 0.** The first `WANTED`
  extraction kept the literal `WANTED="` prefix; pytest printed *"no tests ran in 0.00s"* and the
  wrapper still printed **exit 0**. Caught by reading the output **text**, not the exit code — the
  same discipline later applied to `gcloud builds submit`, whose wrapper also printed `exit 0`. This
  is the phase's own lesson reproducing inside the tooling built to check it.
- **`gcloud builds log` returned `PERMISSION_DENIED`** — the identity flip, and the reason the
  `collecting:` line is recorded as NOT OBTAINED.
- **Two audit buckets exist** and only one is live. `nestor-audit-prod` has 22 prefixes;
  `project-cb01b861-…-nestor-audit` has the **9** that match the record. Using the wrong one would
  have produced a canary reading that looked plausible and meant nothing.
- **`.planning/` is gitignored** — both `21-UAT.md` and this SUMMARY were invisible to
  `git status` and needed `git add -f`.

## Threat Flags

None. No route, verb, parameter, dependency or secret added. The only install was `npm ci` from the
**committed** lockfile (868 packages, all pre-pinned), with `git status` showing no manifest change.
T-21-08-SC satisfied by construction. The public Firebase web key read from the live bundle is a
public project identifier, not a secret, and is deliberately not recorded here.

## Known Stubs

**`21-UAT.md` is deliberately unfilled** — every verdict reads *"(awaiting operator)"*. That is its
intended pre-UAT state: **no verdict may be filled from inference.**

## Self-Check: PASSED

- `infra/DEPLOY-RUNBOOK.md` — FOUND, `grep -c "^## Phase 21"` = **1** (line 4708)
- `21-UAT.md` — FOUND, confirmed in commit `508fe08`
- `508fe08` — FOUND in `git log`
- Build ids `4dbf4097-…` and `8d68ee2f-…` — both **SUCCESS**, read by `gcloud builds describe`
- No deletions across either commit
- `STATE.md` / `ROADMAP.md` — **NOT modified**

## What the next agent must do

1. **Find out WHY the gcloud account keeps reverting** before anything else. It has now overwritten
   the operator's own deliberate fix, mid-deploy-window. Until that is stable, an ordered
   multi-service deploy is unsafe.
2. Re-verify **account AND project**, then **re-run the six sentinels** (the tree must still be at
   `2d16fdd` + this plan's commits).
3. **The gates do NOT need re-running** unless the tree changes — both are green at this tree.
   **If the tree changes at all, they must be re-run.**
4. Re-run the **queue canary** immediately before the worker step; `2026-08-05T19:21:31Z` is the
   value that must still hold.
5. Deploy in order — **frontend → `tribunal-api` → `tribunal-worker` LAST** — then read back
   `status.imageDigest` per revision and **compare against the BEFORE table above**. A frontend
   digest still on `sha256:541b2b52…` means the deploy no-op'd.
6. Then Task 3: the operator walks the page and fills `21-UAT.md`. **Trigger no research run.**

---
*Phase: 21-research-run-feed-completion-silent-post-research-stages-stu*
*Plan 08 — Task 1 complete; Task 2 pre-flight complete with both gates GREEN; the DEPLOY did not run*
*Nothing was deployed and NO research run was triggered*
