# Testing Patterns

**Analysis Date:** 2026-06-18

## No Test Infrastructure Exists

**This codebase has zero test setup. This is a critical finding for the re-platform.**

Confirmed by exhaustive search:
- No `*.test.ts`, `*.test.tsx`, `*.spec.ts`, `*.spec.tsx` files anywhere in the repo
- No `vitest`, `jest`, `@testing-library/*`, `playwright`, or `cypress` in `frontend/package.json` (neither `dependencies` nor `devDependencies`)
- No `vitest.config.*` or `jest.config.*` files
- No `test` script in `frontend/package.json` scripts block (only `dev`, `build`, `build:dev`, `preview`, `lint`, `format`)

## Available Scripts (Actual)

```bash
bun run dev        # Vite dev server
bun run build      # Production build
bun run lint       # ESLint
bun run format     # Prettier write
```

There is no `bun run test` command.

## What Exists Instead of Tests

**Utility scripts in `frontend/scripts/`** — these are one-off bun scripts that hit the live Supabase database directly. They are not automated tests:

| Script | Purpose |
|--------|---------|
| `frontend/scripts/check.ts` | Ad-hoc query to inspect intake/answer data for a specific client |
| `frontend/scripts/seedDemo.ts` | Seeds a demo client + intake into the live Supabase project |
| `frontend/scripts/cleanup.ts` | Cleans up demo/test data from live DB |
| `frontend/scripts/c.ts`, `c2.ts`, `q.ts` | Ad-hoc query utilities |

These scripts use hardcoded Supabase URLs and publishable keys. They are not safe to commit long-term and not a substitute for automated testing.

## Testable Code That Currently Has No Tests

The following units are pure functions or near-pure and are prime candidates for unit tests when a framework is introduced:

**Pure logic — highest priority:**
- `frontend/src/lib/intake-phase.ts` — `derivePhase()` function: a pure state machine with many conditional branches covering all `Phase` values. Ideal for exhaustive unit tests.
- `frontend/src/lib/research-question.ts` — `isAnchorQuestion()`, `stripAnchorPrefix()`, `displayQuestionText()`: pure string utilities.
- `frontend/src/lib/salesLabels.ts` — label lookup functions (`meetingTypeLabel`, `dealStageLabel`, `klantTypeLabel`).
- `frontend/src/lib/intake-phase.ts` — all `phaseShows*` visibility helpers.

**Component rendering — medium priority:**
- `frontend/src/components/intake/NextStepBanner.tsx` — renders different UI per `Phase` value (12 cases in switch statement). Snapshot or behavioural tests per phase.
- `frontend/src/components/intake/FieldRenderer.tsx` — renders different field controls per `field.type`.
- `frontend/src/components/ui/*` — shadcn primitives (already tested upstream by Radix UI; low value to re-test here).

**Integration / E2E — lower priority for initial setup:**
- Admin login flow (`frontend/src/routes/auth.login.tsx`)
- Client-facing intake form submission (`frontend/src/routes/intake.$token.tsx` + `frontend/src/components/intake/IntakeForm.tsx`)

## Recommended Test Setup for Re-Platform

When introducing tests, use **Vitest** (aligned with the Vite build stack already in use):

```bash
bun add -d vitest @testing-library/react @testing-library/user-event jsdom
```

Suggested `vitest.config.ts` location: `frontend/vitest.config.ts`

Suggested `package.json` additions:
```json
{
  "scripts": {
    "test": "vitest",
    "test:ui": "vitest --ui",
    "coverage": "vitest run --coverage"
  }
}
```

**First tests to write (in priority order):**
1. `frontend/src/lib/intake-phase.test.ts` — unit test `derivePhase()` for all status transitions
2. `frontend/src/lib/research-question.test.ts` — unit test anchor prefix helpers
3. `frontend/src/components/intake/NextStepBanner.test.tsx` — render test per phase
4. `frontend/src/components/intake/FieldRenderer.test.tsx` — render test per field type

## Coverage

**Current coverage:** 0% — no tests exist.

**Requirements:** None enforced (no CI coverage gate configured).

## CI / Automated Checks

There is no CI pipeline configured in this repo. The only automated quality gate is:
- `bun run lint` — ESLint (can be run manually or in a pre-commit hook)
- `bun run format` — Prettier

No pre-commit hooks (no `.husky/` or `.lefthook.yml` found).

## Risk Assessment

The absence of tests on a re-platform project carries concrete risks:

| Risk Area | Specific Concern |
|-----------|-----------------|
| Phase machine (`intake-phase.ts`) | `derivePhase()` has 12+ branches. A logic error silently shows the wrong CTA to admins. |
| Auth flow | No regression protection when switching from Supabase GoTrue to Identity Platform. |
| Field validation | `validateField()` in `IntakeForm.tsx` uses `any` typed inputs; edge cases are untested. |
| Supabase → GCP data layer | When the API layer is re-pointed, there is no test harness to catch regressions. |

---

*Testing analysis: 2026-06-18*
