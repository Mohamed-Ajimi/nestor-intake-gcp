---
phase: 06-intake-crud-parity-frontend-api-seam
plan: 02
subsystem: frontend-test-infra
tags: [vitest, characterization-test, phase-machine, qa-03]
requires:
  - "frontend/src/lib/intake-phase.ts (pure derivePhase, observed not modified)"
provides:
  - "frontend test runner (vitest) + non-watch `npm run test` script"
  - "QA-03 characterization suite pinning all 12 derivePhase outcomes"
affects:
  - "later plans re-pointing derivePhase inputs (D-05) now have a regression net"
tech-stack:
  added:
    - "vitest ^3.2.4 (resolved 3.2.6)"
    - "@vitest/coverage-v8 ^3.2.4"
  patterns:
    - "standalone vitest.config.ts reusing the @/ alias via vite-tsconfig-paths (not the Cloudflare/Nitro preset)"
    - "characterization test: GREEN-immediately suite that observes existing pure-function behavior"
key-files:
  created:
    - "frontend/vitest.config.ts"
    - "frontend/src/lib/intake-phase.test.ts"
    - "frontend/package-lock.json"
  modified:
    - "frontend/package.json"
decisions:
  - "vitest config is standalone (node env) — intentionally NOT extending vite.config.ts's Cloudflare/Nitro/TanStack preset, which would pull the Workers runtime into a pure unit run"
  - "test script is non-watch (`vitest run`) per plan; watch left to ad-hoc `npx vitest`"
metrics:
  duration: ~9 min
  completed: 2026-06-29
---

# Phase 6 Plan 02: Frontend Test Runner + derivePhase Characterization Suite Summary

Installed vitest as the frontend's first test runner and authored the QA-03 characterization suite that pins all 12 outcomes of the pure `derivePhase` phase machine, observing it without modifying it (D-05) so later input re-points cannot silently change a transition.

## What Was Built

- **Task 1 — vitest runner (commit 0b4e785):** Added `vitest ^3.2.4` + `@vitest/coverage-v8 ^3.2.4` to `frontend` devDependencies and a non-watch `"test": "vitest run"` script. Created `frontend/vitest.config.ts` (node environment, `include: src/**/*.test.ts`) that reuses the `@/*` → `./src/*` alias via `vite-tsconfig-paths`. Ran `npm install`, materializing `frontend/package-lock.json` (vitest resolved to 3.2.6, compatible with the project's vite ^7.3.1). Runner starts cleanly: `npx vitest run --passWithNoTests` exits 0.
- **Task 2 — characterization suite (commit 235a443):** Created `frontend/src/lib/intake-phase.test.ts` with 17 `it(...)` cases (17 `expect(derivePhase` assertions, ≥16 required) covering every branch and all 12 Phase outputs: `awaiting_client_submission`, `awaiting_skill_run`, `awaiting_review`, `awaiting_validation_send`, `awaiting_client_validation`, `awaiting_context_pack`, `awaiting_research_start`, `in_research`, `awaiting_report_upload`, `awaiting_results_send`, `completed`, `archived`. Uses a `baseIntake(status)` factory with all markers null, overriding per case, and the literal `status: "succeeded"` for skill-run cases (Pitfall 1 / Assumption A1 — the value the read seam maps onto). Suite is GREEN immediately (pins existing behavior). `git diff frontend/src/lib/intake-phase.ts` is empty — derivePhase untouched.

## TDD Note

Task 2 is tagged `tdd="true"` but is a **characterization** test of an already-existing pure function, so per the plan it is GREEN on first run rather than going through a RED→GREEN cycle. There is no implementation to add — the test only observes. The conventional `test(...)` commit (235a443) records the suite; no `feat(...)` follows because no production code changed (D-05). This is the intended shape for a behavior-pinning safety net, not a gate violation.

## Verification

| Check | Result |
|-------|--------|
| `npx vitest run --passWithNoTests` exits 0 | PASS (vitest 3.2.6) |
| `grep "\"test\"" frontend/package.json` shows `"test": "vitest run"` (non-watch) | PASS |
| `frontend/vitest.config.ts` exists, resolves `@/` alias | PASS (vite-tsconfig-paths) |
| `npm run test -- intake-phase` passes, ≥16 assertions, 0 failures | PASS (17 tests) |
| All 12 Phase strings appear in expected outputs | PASS |
| `git diff --stat frontend/src/lib/intake-phase.ts` empty (D-05) | PASS |
| `grep -c "expect(derivePhase" ...test.ts` ≥ 16 | PASS (17) |
| `npm run test` (full) exits 0, non-watch | PASS |

All verification ran live in the worktree (Node v22.14.0, npm 10.9.2 available) — no deferred live-runs.

## Deviations from Plan

None — plan executed exactly as written. Tasks 1 and 2 both completed and verified live; no deviation rules triggered.

## Threat Model

T-06-04 (Tampering — derivePhase under re-point) is mitigated: the 17-case suite pins all 12 outcomes so a later input re-point (D-05) that changes any transition turns the suite red. No new threat surface introduced (test-only plan, no runtime surface, no untrusted input).

## Notes for Downstream

- `.planning/` is gitignored in this repo; this SUMMARY was force-added (`git add -f`) to be committed in the worktree.
- The vitest config deliberately does not extend the app's Cloudflare/Nitro/TanStack vite preset. If a future suite needs DOM (component tests), add `environment: "jsdom"` (and the `jsdom` devDep) — the pure phase-machine suite intentionally uses `node`.

## Self-Check: PASSED
