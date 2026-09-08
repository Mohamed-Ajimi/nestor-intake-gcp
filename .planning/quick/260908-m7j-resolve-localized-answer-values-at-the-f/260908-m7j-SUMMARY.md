---
phase: 260908-m7j
plan: 01
subsystem: frontend-i18n
tags: [i18n, defect-fix, read-boundary, DEF-23.2-16]
requires:
  - "pick() in frontend/src/lib/i18n/localizeSchema.ts"
provides:
  - "resolveAnswerValue(value, lang) — recursive localized-answer-value resolver"
  - "localized answer text rendered in the active language on all three read boundaries"
affects:
  - "frontend/src/routes/intake.$id.tsx"
  - "frontend/src/routes/intake.$id.results.tsx"
  - "frontend/src/routes/admin.pulse.intakes.$id.tsx"
tech-stack:
  added: []
  patterns: ["read-boundary resolution (no data migration, no write-path change)"]
key-files:
  created:
    - frontend/src/lib/i18n/resolveAnswerValue.ts
    - frontend/src/lib/i18n/resolveAnswerValue.test.ts
  modified:
    - frontend/src/routes/intake.$id.tsx
    - frontend/src/routes/intake.$id.results.tsx
    - frontend/src/routes/admin.pulse.intakes.$id.tsx
decisions:
  - "Resolve on READ rather than fixing the write path — repairs already-broken intakes with no migration"
  - "Locale selection delegated entirely to pick(); no second implementation, no hardcoded locale list"
  - "Original object/array reference returned when no descendant changed, to protect the admin initial-vs-draft dirty diff"
metrics:
  duration: ~25 min
  completed: 2026-09-08
  tasks: 2
  commits: 2
requirements: [DEF-23.2-16]
---

# Quick Task 260908-m7j: Resolve Localized Answer Values at the Read Boundaries — Summary

A pure recursive `resolveAnswerValue(value, lang)` helper, delegating locale choice entirely to the
existing `pick()`, now runs at all three `answers.value_json` read boundaries — so AI-refined answer
text renders in the user's language instead of `[object Object]`.

## What was wrong

The intake skill emits every string it authors as a localized `{nl, fr, en}` object.
`AIReviewPanel.tsx:334` pushes that **raw object** into `answers.value_json` (superadmin is exempt from
canonical schema-membership checks, so nothing rejected it), and every read boundary handed it straight
to the renderers. `FieldRenderer`'s `<textarea value={value ?? ""}>` and `FieldDisplay`'s scalar branch
(`String(value)`) both produced `[object Object]`, making the client-validation step unusable on any
intake that had been through the AI review.

## Measured RED (before any implementation)

**1. The new test suite could not even collect** — `npx vitest run src/lib/i18n/resolveAnswerValue.test.ts`:

```
FAIL  src/lib/i18n/resolveAnswerValue.test.ts [ src/lib/i18n/resolveAnswerValue.test.ts ]
Error: Cannot find package '@/lib/i18n/resolveAnswerValue' imported from
'.../frontend/src/lib/i18n/resolveAnswerValue.test.ts'
 ❯ src/lib/i18n/resolveAnswerValue.test.ts:2:1
Caused by: Error: Failed to load url @/lib/i18n/resolveAnswerValue
(resolved id: @/lib/i18n/resolveAnswerValue) ... Does the file exist?

 Test Files  1 failed (1)
      Tests  no tests
```

**2. The concrete pre-fix rendered value**, measured directly rather than inferred:

```
pre-fix textarea value  => "[object Object]"
pre-fix FieldDisplay    => "[object Object]"
is [object Object]?     => true
```

**3. Baseline confirmed at HEAD** (with the new test file moved aside, so this is a true pre-change read):

| Measure | Value at HEAD |
|---|---|
| `npx tsc --noEmit` | exit 0, zero output |
| `npx vitest run` | 11 files / 161 tests passed |
| `grep -rn resolveAnswerValue frontend/src` | no matches |
| unwired `value_json ?? a.value` boundaries | 3 (lines 84 / 106 / 452, exactly as planned) |

## Post-fix green values

| Gate | Pre-fix | Post-fix |
|---|---|---|
| `vitest run resolveAnswerValue.test.ts` | FAILS to collect (module absent) | **19 tests passed** |
| exact-text regression | `[object Object]` | `"Doel NL"` / `"But FR"` / `"Goal EN"`, and explicitly not `"[object Object]"` |
| boundaries wired (`grep -c`) | 0 | **3** — `ALL_THREE_BOUNDARIES_WIRED` |
| unwired boundaries remaining | 3 | **0** — `NO_UNWIRED_BOUNDARY_REMAINS` |
| `npx tsc --noEmit` | exit 0 clean | **exit 0 clean** (no regression) |
| `npx vitest run` | 11 files / 161 tests | **12 files / 180 tests passed** (161 + 19) |
| scope fences (`git diff` on 5 fenced files) | empty | **empty** — `SCOPE_FENCES_INTACT` |
| dependency changes | empty | **empty** — `ZERO_DEPENDENCY_CHANGES` |

`pick()` and `localizeSchema.ts` are byte-identical to HEAD (verified by `git diff --exit-code`).

## Lint: the plan's baseline was not reproducible in this worktree

The plan stated "~60 pre-existing errors". **Measured here: 29,526 errors** (29,562 problems), of which
22,983 are `Delete ␍` (prettier). Cause: this worktree's working tree is **CRLF** (git `autocrlf`) while
the committed blobs are LF and prettier expects LF. The orchestrator's "~60" was measured in the main
checkout. Not a defect and not fixable here — `git add` normalises back to LF, which is why the committed
diff (reviewed) contains only the intended lines.

Because the project-wide number is dominated by that artifact, I used a **per-file** gate instead:

| Scope | Errors before | Errors after | Delta |
|---|---|---|---|
| the three route files | 2,199 | 2,223 | **+24** |

The `+24` is exactly the net number of lines I added to those files (`git diff --numstat`: 27 added, 3
removed = +24). One `Delete ␍` error per added line — the same pre-existing CRLF class as every other
line in these files, and absent from the committed LF blob. **Zero new errors of any other rule class.**

### Warnings: +1 new, and one pre-existing warning widened

Baseline warnings in these three files were 2, now 3:

- **NEW** — `intake.$id.results.tsx:125` `useEffect has a missing dependency: 'i18n.language'`.
- **Widened (pre-existing)** — `admin.pulse.intakes.$id.tsx:473` was already
  `missing dependency: 't'` at HEAD; it now also names `i18n.language`.

Neither is a behavioural defect on the client routes: I verified both client-route load effects already
depend on `t` (`intake.$id.tsx` → `[id, t]`, `intake.$id.results.tsx` → `[id, navigate, t]`). `t`'s
identity changes on `languageChanged`, so a mid-session language switch re-runs the load and re-resolves.
ESLint simply cannot prove that `t` covaries with `i18n.language`. Left unsuppressed rather than silenced.

## Deviations from Plan

**1. [Rule 3 — Blocking] `node_modules` absent in this worktree**
- **Found during:** Task 1 setup, before RED could be measured.
- **Fix:** ran `npm ci` (never `npm install`, per the standing lockfile rule). Exit 0.
- **Files modified:** none — `package.json` / `package-lock.json` verified byte-identical to HEAD.

**2. [Observation, not fixed] Worktree base was wrong on arrival**
- `git merge-base HEAD 0ba97bf` returned `a975b8ba`, not `0ba97bf`. Corrected with the
  `git reset --hard 0ba97bf` prescribed by the startup check, then verified. This is the documented
  stale-base trap; recording it because it recurred.

**3. [Observation, deliberately NOT fixed] Admin page does not re-resolve answers on a language switch**
- `admin.pulse.intakes.$id.tsx` re-localises the **schema** on language change
  (`useMemo` deps `[intake?.template?.schema, i18n.language]`, line 503) but resolves **answer values**
  inside `load`, whose deps are `[id]` only. So on a mid-session language switch on the admin page,
  field *labels* change language while answer *text* stays in the language active at load, until the next
  load trigger.
- Not introduced by this change — the missing-`t` dependency there is pre-existing (it was in the HEAD
  lint baseline). Fixing it means adding to a dependency array, which would trigger a full answers
  re-fetch on every language switch: a behaviour change outside this plan's explicit
  "do not modify any other line in these three files" fence. **Flagged for the operator, not changed.**

## Accepted consequence — FLAGGED FOR THE OPERATOR

Read-resolution means the value now held in the form/draft state is a resolved **scalar string**. If an
admin subsequently saves on `admin.pulse.intakes.$id.tsx` (write path lines ~956-958) or a client saves a
section via `IntakeForm`, **that resolved scalar is written back — collapsing that field's stored
multilingual `{nl, fr, en}` object to the single language that was active at read time.**

This is accepted by design, and only affects fields actually touched by a save:
- it is the pre-260831 answer shape, so nothing downstream breaks;
- it heals the data rather than leaving an unreadable object in the row;
- the write path is explicitly out of scope for this task.

`AIReviewPanel.tsx`, `IntakeForm.tsx` and the admin write path were **not** modified.

## Not verified live — no browser walkthrough

**No browser walkthrough was performed.** None of the three routes were opened; no intake was loaded, and
the `[object Object]` symptom was never observed disappearing in a real render. The fix is proven by
unit test and wiring gates only:

- 19 unit tests pin the resolver's behaviour, including exact expected text and an explicit
  `not.toBe("[object Object]")`;
- grep gates prove all three read boundaries call the helper and that none remain unwired;
- `tsc` and the full 180-test suite prove nothing regressed.

That is **not** the same as observing the client-validation screen render correctly. Given this project's
record of gates reading green on false content, a browser check of one AI-reviewed intake on each of the
three routes is still owed before this is called done.

## Must-not-break coverage (identity-asserted)

Every non-localized canonical shape is asserted with `toBe` (reference identity), not `toEqual`, so a
helper that rebuilt every object could not pass: plain string lists, `proposal_list` with plain text,
`materials_files` descriptors, radio-with-other `{choice, text}`, stakeholder rows `{name, role, email}`
(the exact case `pick()`'s docstring warns about — it must not resolve to `"Jan"`), `{}`, plain strings,
`null`, `undefined`, numbers and booleans. Nested-change cases additionally assert the input is not
mutated and that a changed container is a new reference.

## Commits

| Task | Commit | Description |
|---|---|---|
| 1 | `a6344e3` | `resolveAnswerValue` helper + 19 must-not-break/regression tests (RED measured first) |
| 2 | `5413bf0` | wire all three `value_json` read boundaries |

## Self-Check: PASSED

- `FOUND: frontend/src/lib/i18n/resolveAnswerValue.ts`
- `FOUND: frontend/src/lib/i18n/resolveAnswerValue.test.ts`
- `FOUND: a6344e3`
- `FOUND: 5413bf0`
- Commit trailers verified present on both commits.
- No file deletions in either commit; no untracked files left behind.
