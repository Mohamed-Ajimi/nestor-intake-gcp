# Quick Task 260903-fbt — The Nestor Pulse Handbook

**Date:** 2026-09-03
**Base commit:** `c8b8583` (asserted before any edit; tree clean apart from untracked `.claude/`)
**Status:** COMMITTED and PUSHED. Documentation only — **zero code changed, zero spend, no deploy**.

---

## 1. What was produced

`docs/handbook/`, 21 chapters, **7,793 lines**, 31 Mermaid diagrams, verified at `c8b8583`.

| # | Chapter | Lines |
|---|---|---|
| 00 | README and index | 116 |
| 01 | Executive overview | 152 |
| 02 | History and timeline | 233 |
| 03 | Architecture | 262 |
| 04 | Domain model and lifecycles | 229 |
| 05 | Data model | 400 |
| 06 | Backend: the intake API | 653 |
| 07 | AI skills | 500 |
| 08 | The research seam | 772 |
| 09 | Tribunal: service, worker, events, audit, cost, citations | 340 |
| 10 | Tribunal: the research pipeline | 330 |
| 11 | Models and providers | 250 |
| 12 | Frontend | 747 |
| 13 | Infrastructure and deploy | 522 |
| 14 | Security and compliance | 207 |
| 15 | Quality and testing | 162 |
| 16 | Operations runbook | 210 |
| 17 | Decision log | 372 |
| 18 | Market positioning | 173 |
| 19 | Known gaps and roadmap | 129 |
| 20 | Glossary | 190 |

`README.md` gained a pointer paragraph. Nothing else outside `docs/handbook/` and `.planning/`.

## 2. Method

**Wave 0 — evidence.** Six fact-sheet agents read the tree at `c8b8583` and produced ~3,300 lines of
`path:line`-cited facts in the scratchpad (backend core, backend API layer, frontend, infra and
history, Tribunal service, Tribunal pipeline). The pipeline sheet was delivered in two parts
(workshop, synthesis) before its agent hit a session limit; the orchestrator wrote chapter 10 from
those parts plus the planning record.

**Wave 1 — writing.** Five module chapters (06, 07, 08, 12, 13) were written by dedicated agents from
the fact sheets against a binding style guide. The orchestrator wrote the twelve chapters that need
the reasoning record in context (00, 01, 02, 03, 04, 14, 15, 16, 17, 18, 19, 20) and, after three
writer agents hit the session limit, also 05, 09, 10 and 11.

**Wave 2 — verification.** All internal links resolve (checked mechanically). All code fences are
balanced. Each writer agent independently re-derived its `path:line` cites against the tree and
reported corrections: `write-06` fixed one wrong fact-sheet cite (`protected_router` is
`auth_routes.py:57`), `write-07` recomputed offsets for three concatenated reads, `write-08`
corrected four ranges, `write-12` removed a revision id that came from session memory rather than a
file, `write-13` corrected twelve derived ranges.

## 3. Standards applied

- Diátaxis-informed split; each chapter declares its type in a header block that also names the
  files a reader opens to verify it and the commit it was verified against.
- Mechanism before tables: every module chapter narrates how the thing works before any inventory.
- Reasoning as context → options → decision → consequence, linked to chapter 17 by identifier rather
  than restated.
- Every disputable fact cites `path:line` or `path::symbol`; run numbers cite the run id;
  unestablished facts say "not determined from the code".
- The project's honesty markers (⛔ never executed / unobserved, ⚠ n=1 or fragile, **SUPERSEDED**
  kept not deleted).
- Mermaid for all 31 diagrams so they render on GitHub with no build step.

## 4. Decisions taken while writing

- **Chapter 17 is the single decision register.** Roughly 200 decisions across 14 identifier
  families were consolidated into one ADR-format chapter; module chapters link by id. Superseded
  rulings are kept and marked, per the project's own convention.
- **Two synthetic identifier families were introduced** for decisions the planning record states
  without ids: `P-01…P-13` (the founding v1.0 project decisions) and `M-01…M-10` (the v1.1 milestone
  decisions). Both are listed in chapter 20 as handbook numbering, so they cannot be mistaken for
  planning-record ids.
- **Chapter 11 exists as its own chapter** rather than a section of 10, because "which models and
  why" was an explicit ask and the answer spans the intake platform, the engine, the three adapters
  and the cost table.
- **Nothing was smoothed over.** Every contradiction the fact sheets found is recorded in the
  relevant chapter's "Known gaps and traps": 59 in the Tribunal service sheet alone, plus the
  frontend's dead code and embedded legacy credentials, the backend's route-table test contradiction,
  and the two-policy-form inconsistency in the engine schema.

## 5. Corrections made to the source material

- `D-R4` in the decision log was stated as "an LLM groups winners into ≤5 groups". That was the
  ruling, but `D-W4-4a` (2026-07-31) later made **one deterministic group per client question the
  primary path** with the LLM topic mode kept as an option. Both are now recorded, with the
  supersession visible.
- Chapter 04's noun table was corrected the same way after the workshop fact sheet landed.
- Two figures that disagree between sources are stated as disagreeing rather than reconciled: the
  frontend test count (136 `it()` cases counted in the files against 140 reported in STATE.md), and
  which Anthropic secret wins at runtime on the engine services (the deploy mounts `Nestor_Claude2`,
  the in-process bootstrap re-exports `Nestor_Claude`).

## 6. What this does not claim

- ⛔ **No code was read from `.claude/worktrees/`** — an orphaned stale copy of the whole repo that
  has twice made correct deletions read as incomplete. Every writer was instructed to exclude it.
- ⛔ **Nothing here was verified by running the system.** The handbook documents the tree and the
  recorded runs. The engine models deployed 2026-09-01 have still never executed a run, and every
  chapter that mentions their cost or quality says the figure is arithmetic.
- Line numbers drift. The header block of every chapter names the commit it was verified against, so
  a stale cite is detectable rather than misleading.

## 7. Verification evidence

```
21 files, 7793 lines
internal links: 0 missing
code fences: balanced in all 21 files
mermaid diagrams: 31
```

No test suite covers documentation; the checks above are the gate. The repository's own gates were
not run because no source file changed (`git diff --stat` over `backend/`, `frontend/` and
`tribunal/` is empty for this task).
