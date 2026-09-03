# Quick Task 260903-fbt — The Nestor Pulse Handbook

**Date:** 2026-09-03 (written), 2026-09-03 (gap-fill review pass — see § 8)
**Base commit:** `c8b8583` (asserted before any edit; tree clean apart from untracked `.claude/`)
**Status:** COMMITTED. ⛔ **NOT PUSHED** — `git push` is blocked by the permission classifier and
must be run by the operator. Documentation only: **zero code changed, zero spend, no deploy**.

---

## 1. What was produced

`docs/handbook/`, **24 chapters, 8,801 lines, 40 Mermaid diagrams**, verified at `c8b8583`.

| # | Chapter | Lines |
|---|---|---|
| 00 | README and index | 111 |
| 01 | Executive overview | 152 |
| 02 | History and timeline | 253 |
| 03 | Architecture | 262 |
| 04 | Domain model and lifecycles | 229 |
| 05 | Data model | 660 |
| 06 | Backend: the intake API | 653 |
| 07 | AI skills | 500 |
| 08 | The research seam | 772 |
| 09 | Tribunal: service, worker, events, audit, cost, citations | 553 |
| 10 | Tribunal: the research pipeline | 655 |
| 11 | Models and providers | 377 |
| 12 | Frontend | 747 |
| 13 | Infrastructure and deploy | 522 |
| 14 | Security and compliance | 219 |
| 15 | Quality and testing | 189 |
| 16 | Operations runbook | 243 |
| 17 | Decision log | 372 |
| 18 | Market positioning | 196 |
| 19 | Known gaps and roadmap | 167 |
| 20 | Glossary | 180 |
| 21 | Configuration reference | 437 |
| 22 | Development workflow | 219 |
| 23 | Repository map | 133 |

⚠ An earlier revision of this summary carried per-chapter line counts from a draft state and claimed
the work had been pushed. Both were wrong; the table above is measured and the push is still owed.

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
  **SUPERSEDED in part by § 8.2:** the test-count difference was resolved (loop-generated tests).
  The Anthropic-secret question remains open and needs a live `describe`.

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

---

## 8. Gap-fill review pass (2026-09-03, second pass)

The handbook was audited against the tree rather than re-read for style. The audit method was to
compare structure and claims to the repository: heading outline of all chapters, diagram census,
every "not determined from the code" placeholder, and a sweep for tree paths that no chapter
referenced.

### 8.1 Three factual errors found and corrected

| Chapter | Was | Is |
|---|---|---|
| 11 § 11.2 | "No call sets a temperature." | **False.** `critique/judge.py:176` and `critique/content_compare.py:98,168` pass `temperature=0.0`, and the Gemini distiller passes `0.0` with `thinking_budget=0` (`synthesis/steps.py:1539,1548`). The synthesis call deliberately passes **none**, because with Opus 5 extended thinking on, `temperature`/`top_p`/`top_k` are an **HTTP 400** (`steps.py:161-165`). Replaced with a four-row table and the "do not restore it" trap |
| 19 § 19.2 | The wallet cap is `_D6_MAX_WINNERS = 15` | **Two constants were conflated.** `_D6_MAX_WINNERS = 32` (`research_division.py:260`) is the dispatch cap and the real wallet; `_WINNERS_MAX = 15` (`workshop_rank.py:1012`) is the workshop cap. The old text understated the spend ceiling by 2× |
| 01 § 01.7, 02 § 02.7 | "27 phase directories, 30 quick tasks" | Measured: **30** phase directories, **31** quick tasks at `c8b8583` |

Also corrected: `00-README.md` claimed twenty diagrams and twenty chapters.

### 8.2 Three open questions closed

- **The 136-vs-140 frontend test count is arithmetic, not a discrepancy.**
  `funnelLabels.test.ts:222` puts two `it()` declarations inside a loop over the three locale
  catalogues (`:215-219`), so two static declarations register six tests: 136 − 2 + 6 = **140**.
  Both numbers were right; only one is countable with grep. (ch. 12 § 12.16)
- ⚠ **The structural scope-ceiling guard cannot pass, and is therefore inert.** Two tests named
  `test_app_exposes_no_deep_research_route` (`test_scope_guard_ai.py:141`,
  `test_no_run_research_route.py:61`) scan `main.app.routes` for a token set including the bare word
  `research`, while `research_router` is mounted **unconditionally** (`app/main.py:152`) with eleven
  matching paths. If the imports succeed the assertion cannot hold, so the test fails; if it passes,
  it skipped. There is no third outcome, and since the 2026-08-31 run reported four failures with
  neither of these among them, they skipped. The *preventive* shell guard
  (`ci_no_run_research.sh`) is correct and unaffected — it deliberately never matches the bare
  token. Fix: narrow the token set to the verbs the ceiling forbids. (ch. 15 § 15.7, propagated to
  ch. 06 and ch. 19)
- **Sampling parameters** — see 8.1.

### 8.3 Three chapters added

| # | Chapter | Why it was a gap |
|---|---|---|
| 21 | Configuration reference, 437 lines | The system has ~136 `NESTOR_*` engine dials plus the backend's typed settings and the frontend's build-time values, and **no chapter indexed any of them**. The only way to find a dial was to grep the engine. Extracted mechanically with defaults, grouped by subsystem, with the spend-bounding dials ranked and the six dead-or-test-only names called out |
| 22 | Development workflow, 219 lines | The project mandates a planned workflow in `CLAUDE.md` and carries 638 tracked planning files, and the handbook mentioned it in **one line**. Now documents the artefact tree, the change lifecycle, phases vs quick tasks, waves and the stale-base trap, what a gate is worth, and identifier/honesty discipline |
| 23 | Repository map, 133 lines | `docs/design/`, `attached_assets/` and `AGENTS.md` were referenced by **zero** chapters. Now every tracked path has an owner, including the tracked residue (two `.claude-phase18-*.tmp` image-tag files, the Replit set, and `tribunal/nestor_pulse/` — the four-file rejected predecessor that is easily mistaken for the engine) |

### 8.4 Nine diagrams added

Five chapters had none. Added: the project timeline (02), the model division of labour (11), the
incident triage tree (16 — first branch is the silent feed that has already cost real money), the
positioning quadrant (18, explicitly labelled editorial not measured), the gap dependency graph
(19), the configuration-flow diagram and two workflow diagrams (21, 22), and the repository tree
(23). Census: **31 → 40**.

### 8.5 Structural consistency

"Where to look" tables were added to chapters 11, 14, 15 and 16, which lacked the closing table that
chapters 03–13 all carry. Chapters 01, 02, 17, 18, 19 and 20 still lack one by design: they are
narrative or registers whose sources are named in the header block.

### 8.6 Verification

```
24 files, 8,801 lines
internal links: 0 broken
code fences: balanced in all 24 files
mermaid diagrams: 40
git diff --stat over backend/ frontend/ tribunal/ infra/: EMPTY
```

⛔ Still not verified by running the system, and still not pushed.
