---
phase: 23-report-legibility-business-friendly-funnel-labels-and-an-hon
plan: 02
subsystem: frontend-work-phase-banner
tags: [i18n, legibility, work-phase, uat-fix, honesty]
requires:
  - "frontend/src/lib/api/research.ts (the eight-status Tribunal vocabulary — read, deliberately NOT imported)"
  - "frontend/src/locales/{en,nl,fr}/{intake,admin}.json"
provides:
  - "deriveWorkPhasePresentation / WorkPhasePresentation (@/lib/research/workPhase)"
  - "nextStep.inResearch{Running,Finished,Stopped,Paused,Unknown}Body — en/nl/fr"
  - "a state-neutral intakeDetail.statusBanner.in_research — en/nl/fr"
affects:
  - "Nothing at runtime yet — 23-03 wires the rule and the five bodies into NextStepBanner"
  - "The /admin/pulse intake-detail status banner (the one live copy change in this plan)"
tech-stack:
  added: []
  patterns:
    - "Pure enumerated rule module under lib/research/ with named-per-member vitest coverage (the verificationGate.ts house pattern)"
    - "Key retained + value replaced — the only tree state that is at once renderable by a still-live referrer and free of the retired sentence"
key-files:
  created:
    - frontend/src/lib/research/workPhase.ts
    - frontend/src/lib/research/workPhase.test.ts
  modified:
    - frontend/src/locales/en/intake.json
    - frontend/src/locales/nl/intake.json
    - frontend/src/locales/fr/intake.json
    - frontend/src/locales/en/admin.json
    - frontend/src/locales/nl/admin.json
    - frontend/src/locales/fr/admin.json
decisions:
  - "The eight status literals are enumerated in workPhase.ts, not imported from RESEARCH_TERMINAL — stream terminality answers a different question and lumps completed with failed and parked"
  - "Absence (null / undefined / empty / unknown) resolves to 'unknown', never 'finished' — the mirror of the defect being fixed, pinned by four named tests"
  - "queued is presented as 'running' — a recorded imprecision, because the operator's action is identical and it becomes running within seconds"
  - "inResearchBody's KEY is retained and only its VALUE rewritten; 23-03 deletes the key with its referrer"
metrics:
  duration: ~25 min
  completed: 2026-08-13
  tasks: 2
  commits: 3
---

# Phase 23 Plan 02: The Honest Work-Phase Banner (rule + copy) Summary

A pure five-way rule now decides what the `in_research` banner is allowed to claim about a
research run, the copy exists to say each of those five things in en/nl/fr, and the sentence
telling operators to "let run-research run" is gone from the frontend entirely.

## What was built

**Task 1 — `frontend/src/lib/research/workPhase.ts` + its tests (commits `48d1e40` RED, `2aecf82` GREEN).**
`deriveWorkPhasePresentation(runStatus)` is an explicit `switch` over all eight Tribunal run
statuses with an explicit `default: return "unknown"`. Five presentations, not two, because
"not running" is three materially different operator situations: the run finished
(`completed`, `completed_degraded`), the run ended without finishing (`failed`, `cancelled`),
or the run is waiting on a human (`parked`, `needs_input`). The module imports nothing from
`lib/api/research.ts`; the reason is written into its docstring rather than left implicit.

**Task 2 — the copy, in three languages (commit `b9cc19e`).** Five new `nextStep.*` bodies at
three-way key parity, the `inResearchBody` value rewritten in place, and
`intakeDetail.statusBanner.in_research` made state-neutral in en/nl/fr.

## Metrics the plan asked for

| Measure | Result |
|---|---|
| `npx vitest run src/lib/research/workPhase.test.ts` | **16 passed** (criterion: ≥ 14) |
| `npm test` (full suite) | **123 passed / 9 files**, green — includes wave 1's 30 `funnelLabels` tests |
| `grep -rn "run-research" frontend/src \| wc -l` — **before** | **3** (exactly as the plan states) |
| `grep -rn "run-research" frontend/src \| wc -l` — **after** | **0** |
| `node scripts/i18n-audit.mjs` | **PASS**, exit **0** — A/B/C clean (107 CHECK D advisories, all pre-existing) |
| `tsc --noEmit` | **0 errors** |
| `git diff --name-only` vs base | exactly the **8** files in `files_modified`, no others |
| `git diff --stat -- frontend/src/components frontend/src/routes` | **EMPTY** — no `.tsx` touched |
| File deletions vs base | **none** |

Task 1's four grep criteria, all measured after the GREEN commit:
`grep -c 'from "@/lib/api/research"' workPhase.ts` → **0**;
`grep -v '^[[:space:]]*[*/]' workPhase.ts | grep -c RESEARCH_TERMINAL` → **0** (it appears only
inside the docstring, explaining why it is not used); `grep -c "default:" workPhase.ts` → **1**.

## The retained `inResearchBody`, verbatim after the rewrite

The plan requires this recorded exactly as written. In each language it is byte-identical to
that language's `inResearchUnknownBody`, which is asserted by the plan's own coherence check:

- **en** — `Deep research is the current work phase. Open the run for its live status.`
- **nl** — `Deep research is de huidige werkfase. Open de run voor de actuele status.`
- **fr** — `La recherche approfondie est la phase de travail actuelle. Ouvrez le run pour connaître son statut.`

The key is deliberately still present: its only referrer, `NextStepBanner.tsx:309`, is live
until 23-03 lands, so deleting it here would leave one merged state of `master` where the
banner renders a missing key. Between wave 2 and wave 3 the banner therefore prints the one
sentence a state-blind surface can honestly print — it claims neither running nor finished.

## nl/fr wording notes

**No string was changed from the text the plan gave.** All five nl bodies, all five fr bodies,
and all three `statusBanner.in_research` rewrites are verbatim from Task 2's action block. Two
observations worth a native reviewer's eye, neither of which I altered:

- **fr uses the masculine loanword `le run`** throughout the new bodies ("ouvrez le run",
  "si le run est encore en cours"). That matches the existing fr locale's treatment of this
  product's run object and the plan's given text, so it is consistent rather than novel.
- **nl `Research is gestopt voordat hij klaar was`** uses `hij` for the run. The surrounding nl
  locale already treats "de run" as masculine/common gender, so this agrees with its
  neighbours.

## Deviations from Plan

None affecting code. Two source-accuracy corrections, both measured rather than assumed, and
neither one a defect in what was built:

**1. `[Rule 0 — report, do not chase] The plan's read_first miscounts the repo-wide `run-research` mentions.**
- **Found during:** Task 2 baseline measurement.
- **Plan states:** `backend/app/db/alembic/versions/0004_triggers.py:7` is *"the ONE remaining
  `run-research` mention in the repo outside these locale files"*, and the acceptance criterion
  repeats *"the remaining repo-wide hit at ... 0004_triggers.py:7"*.
- **Measured at HEAD:** there are **many** more — `backend/scripts/ci_no_run_research.sh` (10
  occurrences), `backend/tests/test_scope_guard_ai.py` (11), `backend/tests/test_scope_guard_run_research.py`
  (8), `backend/tests/test_no_run_research_route.py` (2) and `backend/tests/test_intake_routes.py`
  (1), plus the migration comment. All are scope-guard machinery and its prose — exactly the
  kind of mention that must survive.
- **Impact: none.** The plan's actual acceptance criterion is correctly scoped to
  `frontend/src`, and that count went 3 → 0 as specified. Per the project rule, I did not edit
  untouched code to satisfy the prose. Reporting the number instead.

**2. `[Rule 0 — out of scope, flagged for 23-03] A comment in the backend scope guard is now stale.**
- **Found during:** Task 2 baseline grep.
- **Issue:** `backend/scripts/ci_no_run_research.sh:26-30` explains its own pattern precision by
  citing *"a Dutch operator UI string in NextStepBanner.tsx contains the words `run-research`"*
  as a legitimate mention that must not trip the guard. As of commit `b9cc19e` that string no
  longer exists anywhere in the frontend.
- **Why untouched:** this plan is explicitly barred from touching backend, and the guard itself
  is **unaffected** — its regex is anchored to invocation/route/call syntax
  (`invoke\([^)]*run-research`, `/run-research`, `run_research\(`, …) and never matched the
  prose string in the first place. Nothing is red; only the justifying comment is out of date.
- **➜ ACTION FOR 23-03:** carry this into `deferred-items.md` alongside that plan's own
  PLANNING CORRECTION #2 entry. I deliberately did not create `deferred-items.md` here, because
  23-03's Task 3 owns creating it and I would have pre-empted its structure.

**3. `npm ci` was run in the worktree** (as in wave 1). The worktree had no `node_modules`, so
nothing could be verified. This restores the **committed lockfile** exactly — never
`npm install`, per the project rule. `git status` is clean afterwards: no manifest and no
lockfile change. The T-23-SC disposition ("this plan installs NO packages") is intact.

## What this plan deliberately did NOT do

- `lib/intake-phase.ts` / `derivePhase` untouched — the intake STATUS is not split, only the
  PRESENTATION. Verified: `git diff` touches no `.ts` outside `lib/research/`.
- No component, route or `.tsx` file modified — asserted by an empty
  `git diff --stat -- frontend/src/components frontend/src/routes`.
- `nextStep.inResearchBody` **not deleted** — 23-03 removes the key with its referrer.
- The duplication between `inResearchBody` and `inResearchUnknownBody` was **not** "resolved"
  by aliasing. It is intended and short-lived.
- The neutral status NAMES (`admin intakeDetail.status.in_research`,
  `common status.in_research`, `intakeDetail.filter.in_research`) untouched — verified by the
  plan's no-regression assertion, which passes.
- The other seven `statusBanner` values untouched.
- Nothing wired: `deriveWorkPhasePresentation` has no caller yet. That is 23-03's task and is
  the reason this plan carries no wiring risk.

## Threat model outcomes

- **T-23-10 (information disclosure through the new bodies):** mitigated. All five new strings
  per language are STATIC — none contains `{{`, so no `error_message`, `cost_usd_total`,
  `current_stage` or run id can reach the banner. The plan's assertion reads the literal
  values, so a later edit adding an interpolation is visible in review.
- **T-23-11 (the record lies — absence read as an ending):** mitigated, and this is the single
  most important property here. Four named tests assert that `null`, `undefined`, `""` and an
  unknown literal each resolve to `"unknown"` **and** are `not.toBe("finished")` **and**
  `not.toBe("stopped")`. Each test name states what would break.
- **T-23-12 (tampering with the status vocabulary):** mitigated. The eight literals are
  enumerated locally; `RESEARCH_TERMINAL` is neither imported nor referenced in code (grep = 0
  on non-comment lines). An edit made for the SSE stream's own reasons cannot silently rewrite
  what the operator is told.
- **T-23-13 (statusBanner reachable by a client):** accepted, and re-verified at execution
  time. `grep -rn "statusBanner"` over `frontend/src` returns render sites under
  `/admin/pulse` only; the client surfaces carry no research-running claim. The UAT's
  "CLIENT-FACING" wording does not hold at HEAD — PLANNING CORRECTION #2 stands as written.
- **T-23-SC (supply chain):** no package installed. No `## Package Legitimacy Audit` required.

## Known Stubs

None in the sense of fake data on screen. One **intentional, plan-mandated temporary state**,
recorded so the verifier does not read it as a stub:

`deriveWorkPhasePresentation` and the five new bodies have **no caller** until 23-03. That is
the plan's explicit design — wave 2 carries no wiring risk, wave 3 wires it. The wave-2 tree
is nonetheless coherent on its own: the still-live `inResearchBody` now holds neutral text, so
the merged state makes no false claim while unwired.

## Self-Check: PASSED

Files verified present:
- `frontend/src/lib/research/workPhase.ts` — FOUND
- `frontend/src/lib/research/workPhase.test.ts` — FOUND
- `frontend/src/locales/{en,nl,fr}/intake.json` — FOUND (modified)
- `frontend/src/locales/{en,nl,fr}/admin.json` — FOUND (modified)

Commits verified in `git log 599c6e5..HEAD`:
- `48d1e40` test(23-02): add failing tests for the work-phase presentation rule — FOUND
- `2aecf82` feat(23-02): the enumerated work-phase presentation rule — FOUND
- `b9cc19e` feat(23-02): honest work-phase copy in en/nl/fr, and the end of the run-research sentence — FOUND

## TDD Gate Compliance

Task 1 ran the full RED/GREEN cycle with gate commits in order. RED (`48d1e40`) was a real
failure, not a skipped gate: `vitest` exited 1 with *"Cannot find package
'@/lib/research/workPhase'"* — 1 failed suite, no tests collected. GREEN (`2aecf82`) took it to
16 passed. No REFACTOR commit was needed; the first implementation was already Prettier-clean
and in the house register.

## Environment note (not a deviation)

As in wave 1, the working tree is a CRLF checkout under `core.autocrlf`, so `eslint` reports
`prettier/prettier` "Delete `␍`" errors repo-wide on untouched files. The files this plan
touches were checked with `prettier --end-of-line auto --check` — all eight report clean, and
`git add` confirmed LF normalisation on the two new `.ts` files. Zero non-CRLF findings.
