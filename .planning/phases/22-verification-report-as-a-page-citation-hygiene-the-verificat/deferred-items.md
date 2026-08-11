# Phase 22 — deferred items (out of scope, logged not fixed)

Executors append here. Out-of-scope discoveries logged during execution. Per the executor scope
boundary these were NOT fixed: each entry is a pre-existing condition, or a consequence of a ruled
decision, discovered while executing a plan but outside that plan's scope boundary.

> **⚠ THIS FILE IS CREATED ONCE, BY PLAN 22-01, IN WAVE 1.** Phase 21 produced an add/add merge
> conflict because plans 21-01 and 21-02 each created their own copy in their own worktree. The
> other wave-1 plans (**22-02, 22-03, 22-04**) must record deferred discoveries in their **own
> SUMMARY** instead. Plans in **wave 2 and later** append here directly.

---

## DEF-22-01 — `ResearchRunProgress`'s component body becomes unrendered but stays compiled

**Found during:** phase 22 planning; seeded by plan 22-01 Task 3 (this plan creates the file)
**Status:** deferred by recommendation — **the FILE must survive; only the ELEMENT is removed**
**Owner:** unassigned. A later cleanup change, not phase 22.

### The situation after D-22-5

Plan 22-04 removes the embedded `ResearchRunProgress` element from
`frontend/src/routes/admin.pulse.intakes.$id.tsx` (D-22-5, operator verbatim: *"activity shouldnt
show on the intake page"*). After that removal the `ResearchRunProgress` **component** has zero
render sites, while the **module** must stay, because the run page imports a hook out of it:

```
frontend/src/routes/admin.pulse.runs.$runId.tsx:11
  import { useActiveResearchRun } from "@/components/intake/ResearchRunProgress";
```

⛔ **DO NOT DELETE `ResearchRunProgress.tsx`.** Deleting it breaks the very run page this phase is
built around.

**Measured on the tree at the phase base commit (`9afdf2d`):** the file is 938 lines. Its top-level
declarations are `toStageRows` (106), `useActiveResearchRun` (158, exported), `OpenRunLink` (214),
`StageIcon` (228), `fmtDurationSecs` (238), `StageSummaryCard` (250), `AgentCard` (276),
`RawOutputControls` (392), `AgentFeed` (504) and `ResearchRunProgress` (586). The unrendered
component body is therefore **lines 586-937, ~352 lines**, plus the presentational helpers that only
it uses.

### Why leaving the body in place is the recommendation

22-RESEARCH § Open Question 2 recommends leaving it. Two reasons:

1. **D-22-5's ask is fully satisfied by the element removal.** The operator asked that the activity
   feed not *show* on the intake page. Removing the render site does exactly that. Deleting the
   body delivers nothing further that the operator can see.
2. **A ~350-line deletion widens the blast radius for no operator-visible gain**, in a phase whose
   acceptance rests on single-path diffs. A partial deletion that leaves orphaned state, imports,
   queries or subscriptions behind is the specific failure mode to avoid — and it is more likely
   than not in a file this size.

**Whoever picks this up:** delete the component body, its exclusive presentational helpers, and the
now-unused imports / locale keys **in one dedicated change**, keeping `useActiveResearchRun` and
`OpenRunLink`'s replacement intact. Verify by loading both the intake detail page and the run page.

### Also recorded here, both pre-existing and both untouched

**(a) `export { triggerResearch };` at `ResearchRunProgress.tsx:938` has zero importers — dead code.**
Verified by a repo-wide grep over `frontend/src/**/*.ts{,x}`: every consumer imports that function
from `@/lib/api/research` directly, never from this module —
`components/research/RunActions.tsx:13` and `routes/admin.pulse.intakes.$id.tsx:55`. The re-export
is a leftover. It predates phase 22 and is not part of D-22-5.

**(b) `AuditBodyPanel.tsx:45`'s comment is already stale, and the stale part is the SECURITY
claim.** The docstring reads:

> Superadmin-only by placement (imported only from ResearchRunProgress, which mounts only on the
> admin intake detail route).

That parenthetical is false as of phase 21: `routes/admin.pulse.runs.$runId.tsx:12` also imports
`AuditBodyPanel`, and renders it at `:196`. The **conclusion** still holds — the run route is also
admin-gated — but the **stated reason** no longer does, and a superadmin-only-by-placement argument
that names the wrong placement is the kind of comment a future reader will rely on. Worth correcting
whenever that file is next touched; not corrected here because phase 22 plan 22-01 touches only the
Python engine.

### ⚠ Correction to this plan's own text

`22-01-PLAN.md`'s Task 3 wording names the importer as `admin.pulse.runs.$runId.index.tsx`. **That
file does not exist.** The route file is `admin.pulse.runs.$runId.tsx` (the only `runs` route file
in `frontend/src/routes/`), and the import is on line 11. Recorded so a later reader does not go
looking for a file that was never there.
