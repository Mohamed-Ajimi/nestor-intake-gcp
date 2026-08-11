---
phase: 22-verification-report-as-a-page-citation-hygiene-the-verificat
plan: 02
subsystem: frontend-research-citations
tags: [citations, dedupe, D-22-4, pure-module, tdd, types]
requires:
  - "frontend/src/lib/api/research.ts (Citation type)"
provides:
  - "buildCitationIndex — claim-id -> Citation[] index honouring also_claim_ids aliases"
  - "Citation.url + Citation.also_claim_ids type declarations"
affects:
  - "22-08 (switches VerificationReport.tsx over to buildCitationIndex)"
  - "22-01/22-05 (the engine-side read-time dedupe that emits also_claim_ids)"
tech-stack:
  added: []
  patterns:
    - "pure lib/research module + named-test vitest suite (verificationGate.ts precedent)"
key-files:
  created:
    - frontend/src/lib/research/citationIndex.ts
    - frontend/src/lib/research/citationIndex.test.ts
  modified:
    - frontend/src/lib/api/research.ts
decisions:
  - "Kept the plan-mandated docstring naming `normalizeUrl` as the anti-pattern, and reconciled the literal `grep -niE normaliz` criterion to its stated purpose (no URL handling in CODE) — the criterion and the plan's own <action> were in direct contradiction"
metrics:
  duration: ~15 min
  completed: 2026-08-11
  tasks: 2
  commits: 3
  tests_added: 16
---

# Phase 22 Plan 02: Citation Index + Payload Types Summary

A pure `buildCitationIndex` that indexes a citation under its primary claim id **and every
`also_claim_ids` alias**, so read-time dedupe cannot silently strip the `[n]` marker off a verdict
row — plus the two `Citation` fields the deduped payload carries.

## What Was Built

**Task 1 — `Citation` gains two additive optional fields** (`frontend/src/lib/api/research.ts`,
single 18-line hunk inside the type, zero deletions):

- `url?: string | null` — closes a pre-existing **type** gap, not a wire change.
  `VerificationCitation.url` (`tribunal/nestor_pulse_sdk/runs/schemas.py:458`) has always declared
  it and `number_citations` has always emitted it; only the TS side was blind to it.
- `also_claim_ids?: string[]` — D-22-4. Carries the `first_claim_id` of every entry the read-time
  dedupe absorbs onto the survivor. Optional because a pre-dedupe backend (rolling Cloud Run
  deploy, or any build before the write-side change lands) does not send it.

**Task 2 (TDD) — `frontend/src/lib/research/citationIndex.ts`**, one export, one `import type`, no
React, no fetch, never throws. Extracted from `VerificationReport.tsx:210-220` and then extended:
the original loop keyed **strictly** on `first_claim_id`, which is precisely the defect — a claim
whose only source got absorbed would resolve to nothing and render **no marker at all**, invisible
because a missing marker is indistinguishable from a claim that never had a citation.

Implementation notes worth carrying:

- A per-citation `seen` set means an id appearing in both `first_claim_id` and `also_claim_ids` (or
  twice within `also_claim_ids`) pushes the object **once**, not twice.
- `Array.isArray` guard on `also_claim_ids`, plus `typeof === "string"` and non-empty checks on
  every candidate id (**T-22-04** — this is engine-authored JSON crossing the API → browser
  boundary).
- Keys come **only** from the citation's own two fields, never derived from anything else
  (**T-22-05** — a marker can never surface another claim's citation).
- **Nothing reads, assigns or reorders `citation.n`.** The NEVER-RENUMBER rule is respected by
  construction; the docstring records why (the deliverable markdown has `[n]` baked in frozen by
  `apply_citation_anchors`, so renumbering read-side would desynchronise the page from it).

## Verification Results

| Gate | Baseline | After | Verdict |
|------|----------|-------|---------|
| `tsc --noEmit` | exit 0 | exit 0 | PASS |
| `vitest run` (full) | 6 files / **61** passed | 7 files / **77** passed, 0 failed | PASS (≥70 required) |
| `vitest run citationIndex.test.ts` | n/a | **16** passed, 0 failed | PASS (≥9 required) |
| `i18n-audit.mjs` | `PASS`, 107 advisories | `PASS`, **107** advisories, exit 0 | PASS (unchanged) |
| eslint (both new files, **all** rules) | n/a | exit 0 | PASS (stronger than required) |
| `git diff --name-only` vs base | n/a | exactly 3 files | PASS |

- No change to `frontend/package.json` or `frontend/package-lock.json` (**T-22-SC** — no package
  installed; `npm ci` restored the committed lockfile and left both manifests byte-identical).
- No change to `frontend/src/components/intake/VerificationReport.tsx` — the component switchover
  is 22-08's job, correctly untouched here.
- TDD gates present and correctly ordered: `test(22-02)` `961bf21` → `feat(22-02)` `7e461f5`. RED
  genuinely failed first (module unresolvable), so the RED gate was not skipped by a
  passing-on-arrival test.

## Deviations from Plan

### 1. [Acceptance-criteria reconciliation] Task 2's `normaliz` grep criterion contradicts the plan's own `<action>`

**Found during:** Task 2 verification.

**The conflict, exactly:** the criterion is

> `grep -niE "normaliz|utm_|www\." frontend/src/lib/research/citationIndex.ts` returns NO match —
> the module contains no URL handling of any kind.

while the same task's `<action>` **mandates** a docstring stating "D-22-4 requires ONE shared
normalization" and "A `normalizeUrl` appearing in this file would be the defect, not the fix." The
two cannot both be satisfied literally: writing the required prose guarantees the grep matches.

**Numbers:** the literal grep returns **3 matches** — lines **14, 24, 25**, all inside the `/** */`
docstring block. Words matched: `normalized`, `normalization`, `normalizeUrl`.

**Resolution — reconciled to the criterion's own stated purpose, in its stronger form.** The
criterion states its intent in its own text: *"the module contains no URL handling of any kind."*
That is a claim about **code**, and the literal grep cannot distinguish code from the mandated
comment. Deleting the words to turn the grep green would have made the file *worse* (the docstring
naming `normalizeUrl` is exactly what tells the next reader which anti-pattern to look for) while
producing a green that proves nothing — a vacuous gate.

So the docstring was kept and the purpose was verified directly: comments stripped
programmatically, then searched. **Result: 0 matches for `normaliz|utm_|www.` and 0 matches for a
wider URL-handling probe (`\burl\b|https?:|.replace(|new URL(|toLowerCase(|hostname|pathname|searchParams|slice(|trim(`) in executable code.** The full 21-line executable body contains no
reference to `url` at all. This is a strictly stronger assertion than the original grep, which
would have passed a file that imported a URL helper under a different name.

**Recommendation for future plans:** scope such greps to code, or assert the absence of an
*identifier* (`grep -E "function normalize|const normalize"`), rather than a substring that
mandated prose must contain.

### 2. [Rule 3 - Blocking] `frontend/node_modules` absent in a fresh worktree

`npx tsc` resolved to the "This is not the tsc command you are looking for" stub because the
worktree had no `node_modules`. Restored with **`npm ci --prefix frontend`** (never `npm install` —
the lockfile IS committed, contrary to CLAUDE.md). Verified afterwards that `package.json` and
`package-lock.json` were both unmodified, so T-22-SC's "no package is installed" holds: this
restored exactly the committed pin set and added nothing.

### 3. [Benign] Command form adapted for the worktree sandbox

The sandbox refuses compound commands containing pipes/redirects from a worktree-isolated agent, so
`cd frontend && npx tsc --noEmit` was run as
`npm exec --prefix frontend -- tsc --noEmit --project frontend/tsconfig.json`, and `npx vitest run`
as `npm exec --prefix frontend -- vitest run --root frontend`. Same tool, same config, same
semantics. `i18n-audit.mjs` genuinely requires `frontend` as cwd (it resolves `src/locales/...`
relative to cwd) and was run that way.

## Stale-Base Note

The worktree spawned on `a3a0c96` — **685-behind stale base, the known 23/23 trap** — and was reset
to the plan base `9afdf2d`. Both positive-presence sentinels passed after the reset. `rev-list
--count` would have read green here; only the `merge-base` comparison caught it.

## Known Stubs

None. `buildCitationIndex` is fully implemented and exercised. It is **not yet imported by any
component** — that is by design (`<measured_facts>` item 3: 22-08 owns the
`VerificationReport.tsx` switchover). `tsc` does not object to an unreferenced module and the 16
tests prove the behaviour, so this is a sequenced hand-off, not a stub.

## Threat Flags

None. No new network endpoint, auth path, file access or schema surface. The one boundary this plan
touches (API → browser, reading engine-authored `also_claim_ids`) was already in the plan's threat
register as T-22-04/T-22-05 and is mitigated with type-checked ids and a never-throws contract.

## Notes for the Next Plan

- **22-08** should replace the `VerificationReport.tsx:210-220` loop with
  `buildCitationIndex(report?.citations)` and delete the inline `Map` construction — the semantics
  of the old loop are preserved exactly, with the alias half added on top.
- **22-01/22-05** must actually emit `also_claim_ids` from `verification/report.py`, otherwise this
  index degrades silently to the old strict-`first_claim_id` behaviour (correct, but the marker-loss
  protection is inert). The field being optional makes that degradation safe, not invisible.

## Self-Check: PASSED

- `frontend/src/lib/research/citationIndex.ts` — FOUND
- `frontend/src/lib/research/citationIndex.test.ts` — FOUND
- `frontend/src/lib/api/research.ts` — FOUND (modified, `also_claim_ids` at line 200)
- Commit `9723885` — FOUND
- Commit `961bf21` — FOUND
- Commit `7e461f5` — FOUND
- Working tree clean; exactly 3 files changed vs base `9afdf2d`
