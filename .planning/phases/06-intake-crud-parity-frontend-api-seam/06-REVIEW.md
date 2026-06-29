---
phase: 06-intake-crud-parity-frontend-api-seam
reviewed: 2026-06-29T00:00:00Z
depth: standard
files_reviewed: 38
files_reviewed_list:
  - backend/app/api/admin_routes.py
  - backend/app/api/intake_routes.py
  - backend/app/db/repository.py
  - backend/app/db/session.py
  - backend/app/db/audit.py
  - backend/app/db/models/intake.py
  - backend/app/db/alembic/versions/0002_rls_policies.py
  - backend/app/main.py
  - backend/scripts/ci_no_run_research.sh
  - backend/tests/test_admin_routes.py
  - backend/tests/test_intake_cross_tenant.py
  - backend/tests/test_intake_routes.py
  - backend/tests/test_no_run_research_route.py
  - backend/tests/test_scope_guard_run_research.py
  - frontend/src/components/admin/ProductShell.tsx
  - frontend/src/components/admin/SpaceSwitcher.tsx
  - frontend/src/components/intake/ContextPackBlock.tsx
  - frontend/src/components/intake/FieldDisplay.tsx
  - frontend/src/components/intake/FieldRenderer.tsx
  - frontend/src/components/intake/SkillRunProgress.tsx
  - frontend/src/lib/active-space.tsx
  - frontend/src/lib/api/admin.ts
  - frontend/src/lib/api/answers.ts
  - frontend/src/lib/api/intakes.ts
  - frontend/src/lib/api/search.ts
  - frontend/src/lib/api/skillRuns.ts
  - frontend/src/lib/api/storage.ts
  - frontend/src/lib/api/templates.ts
  - frontend/src/routes/admin.pulse.clients.$id.tsx
  - frontend/src/routes/admin.pulse.clients.tsx
  - frontend/src/routes/admin.pulse.intakes.$id.tsx
  - frontend/src/routes/admin.pulse.intakes.index.tsx
  - frontend/src/routes/admin.pulse.intakes.new.tsx
  - frontend/src/routes/admin.pulse.search.tsx
  - frontend/src/routes/index.tsx
  - frontend/src/routes/intake.$id.results.tsx
  - frontend/src/routes/intake.$id.tsx
  - frontend/src/routes/intake.index.tsx
findings:
  critical: 1
  warning: 7
  info: 2
  total: 10
status: issues_found
---

# Phase 6: Code Review Report

**Reviewed:** 2026-06-29
**Depth:** standard
**Files Reviewed:** 38
**Status:** issues_found

## Summary

This phase re-platforms the intake flow off Supabase onto the FastAPI/GCP backend through a
`frontend/src/lib/api` seam. The bulk of the tenant-isolation surface is built with real
discipline: the `TenantRepository._scope` always-filter, the two-engine routing keyed on
`Identity.role`, the null-space default-deny 403, the allow-listed transition maps that
structurally cap the flow at `decomposed`, and the `audit.log`-in-one-transaction pattern
are all correct, and the cross-tenant denial / scope-ceiling test suites and the
`ci_no_run_research.sh` guard are genuinely adversarial. The `space_id`-from-Identity-only
invariant holds for create, get, patch, list, and the status transitions.

However, the **answers upsert write path is the one place that breaks the architecture's
own belt-and-suspenders contract**: it never verifies the target intake belongs to the
caller's space and never applies the scoped `WHERE`, relying solely on RLS — and its
`ON CONFLICT` target omits `space_id`. That is exactly the "broken-RLS class of bug must
not recur" risk called out in CLAUDE.md, and it is the BLOCKER below. A secondary cluster
of WARNINGs concerns the superadmin active-space filter being entirely inert (advertised
but neither honored by the backend nor applied client-side) and several frontend
type/UX mismatches.

Note: the seam-stub display components (`AIReviewPanel`, `AdminResearchResultsPanel`,
`FinalReportBlock`, `HandoffBlock`, `ResearchArtifacts`, `ResearchResultsPanel`,
`_status`) were not deep-read this pass; the scope-ceiling guard test covers their
non-invocation of run-research.

## Critical Issues

### CR-01: Answers upsert never verifies intake ownership and omits the scoped WHERE — defense-in-depth wall is absent on the write path

**File:** `backend/app/api/intake_routes.py:330-346`, `backend/app/db/repository.py:170-202`

**Issue:** Every other item handler in `intake_routes.py` first does `repo.get(intake_id)`
(or relies on `repo.patch` rowcount) so a cross-tenant `intake_id` maps to a 404 and the
explicit `WHERE space_id = <identity>` independently excludes the foreign row (the D-01
belt-and-suspenders invariant the `repository.py` docstring at lines 13-16 promises). The
answers endpoints do neither:

- `upsert_answers` passes `intake_id` straight to `repo.upsert_batch` with no ownership
  check.
- `IntakeAnswerRepository.upsert_batch` (repository.py:170-202) builds the insert rows with
  `space_id` forced from `self._space_id` and `intake_id` taken from the path, then
  `pg_insert(...).on_conflict_do_update(constraint="uq_intake_answers_intake_field", ...)`.
  It does **not** call `_scope`, and the conflict constraint is `(intake_id, field_key)`
  with **no `space_id`** (confirmed in `models/intake.py:169-172`).

Consequences for a `user` in space A calling `PATCH /intakes/{intake_B_id}/answers`:

1. **D-07 contract break:** the route does not return 404 for a foreign `intake_id`. With a
   new `field_key` it inserts answer rows stamped `space_id=A` pointing at space B's intake
   and returns **200** with the just-written rows (orphan/cross-referencing data). With a
   `field_key` that collides with space B's existing answer, the `ON CONFLICT DO UPDATE`
   targets B's row (the unique index ignores `space_id`); under RLS the cross-visible update
   aborts with an **error (500)**, not a clean 404.
2. **Defense-in-depth removed:** isolation here rests entirely on the RLS `WITH CHECK`. The
   architecture explicitly requires that "even if the WHERE were dropped, RLS denies; even
   if RLS dropped, the WHERE still filters." Because there is no scoped WHERE and the
   conflict target excludes `space_id`, if RLS is ever misconfigured/dropped (the exact
   inherited-Supabase failure CLAUDE.md says must never recur) a user in space A could
   overwrite space B's answers via the `(intake_id, field_key)` conflict — a true
   cross-tenant write.
3. **Untested:** the cross-tenant suite (`test_intake_cross_tenant.py`) exercises only
   `/intakes` get/list/patch; `test_intake_routes.py::test_answers_batch_upsert` is
   same-space only. No test drives a cross-tenant `.../answers` PATCH, so this gap is
   unproven.

**Fix:** Verify intake ownership in-scope before any answer write, and tighten the conflict
target. Minimal handler-level guard plus a repo change:

```python
# intake_routes.py — upsert_answers: scope the parent intake first (404 hides existence).
@intake_router.patch("/{intake_id}/answers")
def upsert_answers(
    intake_id: str,
    body: AnswerBatch,
    answers_repo: IntakeAnswerRepository = Depends(get_intake_answer_repo),
    intake_repo: IntakeRepository = Depends(get_tenant_repo),  # same session/identity
) -> list[AnswerView]:
    if intake_repo.get(intake_id) is None:        # cross-tenant / missing -> 404 (D-07)
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")
    answers_repo.upsert_batch(intake_id, [item.model_dump() for item in body.answers])
    return [_answer_view(r) for r in answers_repo.list_for_intake(intake_id)]
```

(If a single dependency must yield both repos, add a combined dependency rather than opening
two transactions.) Additionally, prefer an `index_elements`/constraint that includes
`space_id`, or add an explicit `.where(self.model.space_id == self._space_id)` guard on the
upsert so the repo wall stands independently of RLS — restoring the D-01 invariant on the
write path. `list_for_intake` is already `_scope`-filtered, so reads stay safe.

## Warnings

### WR-01: Superadmin active-space filter is inert — advertised but never applied anywhere

**File:** `frontend/src/lib/active-space.tsx:44-46`, `backend/app/api/intake_routes.py:223-232`, `frontend/src/routes/admin.pulse.intakes.index.tsx:50-90`

**Issue:** `withActiveSpace()` appends `?space_id=<id>` to `/intakes`, but the backend
`list_intakes(repo = Depends(get_tenant_repo))` declares no `space_id` query parameter, so
FastAPI silently ignores it. For a superadmin, `repo.list()` returns rows from **all**
spaces regardless of the SpaceSwitcher selection. The intakes index page header even claims
"gefilterd op de actieve klant," yet it does not filter client-side either, so selecting a
space has no visible effect on that list. (The clients pages happen to filter client-side by
`space_id`, masking the gap there.) This is a functional defect, not a security hole — a
`user`'s param is correctly ignored and cannot widen access — but the feature does not work.

**Fix:** Either have `list_intakes` accept an optional `space_id: str | None = None` query
param and, **for superadmin only**, narrow `repo.list()` to that space (never trust it for a
user); or apply the active-space filter client-side in the index page. Update the header copy
to match actual behavior.

### WR-02: GET `.../answers` and `.../skill-runs` return 200 (empty) for a cross-tenant id instead of 404

**File:** `backend/app/api/intake_routes.py:321-327` (answers), `354-369` (skill-runs)

**Issue:** Like CR-01 these read handlers never scope the parent intake; they rely on the
answer/skill-run rows being `space_id`-filtered. For a foreign `intake_id` they return an
empty `200` rather than the `404` the `/intakes/{id}` routes return. No data leaks (the lists
are space-filtered), but it is an existence-hiding (D-07) inconsistency that also makes the
enumeration behavior differ across sibling routes.

**Fix:** Reuse the same in-scope `repo.get(intake_id)` ownership check as the CR-01 fix and
return 404 when the parent intake is not visible.

### WR-03: `create_intake` accepts `template_id` without verifying it belongs to the caller's space

**File:** `backend/app/api/intake_routes.py:235-251`

**Issue:** `create_intake` coerces `body.template_id` to UUID and passes it to `repo.create`,
which forces `space_id` from the Identity but does not validate that the referenced template
lives in that space. A crafted request (the seam never sends `template_id`, but the API
accepts it) could create an intake in the caller's own space whose `template_id` points at a
template in another space. The intake row stays in-tenant (no data exposure, and the
template content is unreadable via the space-scoped template repo), but it is a cross-space FK
reference that defeats the "tenant key is the sole isolation key" intent.

**Fix:** When `template_id` is supplied, look it up through the space-scoped
`IntakeTemplateRepository.get(template_id)` and reject (400/404) if it is not in scope before
creating the intake.

### WR-04: Admin status dropdown maps the wrong transition verb to the selected target

**File:** `frontend/src/routes/admin.pulse.intakes.$id.tsx:438-460`

**Issue:** `handleStatusChange` routes `newStatus === "submitted" || newStatus === "validated_by_client"`
both to `submitIntake()`. Because `submitIntake` is context-dependent on the backend
(`draft -> submitted` OR `reviewed -> validated_by_client`), selecting "validated_by_client"
while the intake is in `draft` actually performs `draft -> submitted`. The UI then shows
`res.data.status` (so the display self-corrects), but the operator's chosen target silently
differs from the executed transition, and selecting an unreachable target only surfaces a
generic toast. Confusing and error-prone.

**Fix:** Drive the dropdown options from the allowed transitions for the current status (only
offer the next reachable status), or map each option to the verb that actually produces it
and surface the backend 409 message verbatim when the transition is not allowed.

### WR-05: `templates.ts` `Template` type declares `space_id`, but the intake-router `TemplateView` never returns it

**File:** `frontend/src/lib/api/templates.ts:7-12` vs `backend/app/api/intake_routes.py:147-153`

**Issue:** The intake feature router's `TemplateView` is `{ id, name, schema }` (no
`space_id`), but the frontend `templates.ts` `Template` type declares `space_id: string` as a
required field. Any consumer reading `template.space_id` from `getTemplates()` gets
`undefined` at runtime while the type asserts a string — a latent type-safety lie.

**Fix:** Drop `space_id` from the `templates.ts` `Template` type (it is the admin
`admin.ts` `Template`, whose backend `TemplateView` *does* include `space_id`, that legitimately
carries it), or add `space_id` to the backend intake `TemplateView` if callers need it.

### WR-06: Intake fill/results pages always render `templatesData[0]`, ignoring the intake's own template

**File:** `frontend/src/routes/intake.$id.tsx:65`, `frontend/src/routes/intake.$id.results.tsx:96`

**Issue:** Both user-facing pages do `const template = templatesRes.data[0]` and render that
schema, regardless of the intake's actual `template_id`. If a space ever has more than one
intake template, the wrong form schema is rendered/validated against the stored answers.

**Fix:** Fetch the template by the intake's `template_id` (the backend `IntakeView` does not
currently project it — add it, or expose a `GET /intakes/{id}/template` projection), and fall
back to `[0]` only when the intake carries no template reference.

### WR-07: `SkillRunProgress` elapsed timer resets every poll for a running run with no `applied_at`

**File:** `frontend/src/components/intake/SkillRunProgress.tsx:20-30`

**Issue:** `toActiveSkillRun` sets `triggered_at = r.applied_at ?? r.completed_at ?? new Date().toISOString()`.
For a `running`/`queued` run (no `applied_at`/`completed_at` yet), every 5s poll produces a
fresh `now()` timestamp; the `SkillRunProgress` elapsed clock is keyed on `triggeredAt`
(line 121-127), so it restarts at ~0 on each poll instead of accumulating. Cosmetic, and
moot until the Phase-7 skill backend produces real runs, but the "average 90–120s" timer will
not count up correctly.

**Fix:** Carry a stable start time (e.g. the run's `created_at` once the read seam projects
it, or memoize the first observed timestamp per run id) rather than regenerating `now()` each
fetch.

## Info

### IN-01: Several admin audit calls omit `space_id` that sibling calls pass

**File:** `backend/app/api/admin_routes.py:354-360` (update_space), `374-381` (deactivate_space), `391-401` (reactivate_space), `498-505` (update_template)

**Issue:** `audit.log`'s `space_id` is optional (defaults to `None`, `audit.py:48`), so this
does not crash, but these handlers omit it while `create_space`, `invite_user`,
`deactivate_user`, `reactivate_user`, and `clone_template` all pass it. The resulting
`audit_log` rows for space edits/deactivations and template edits carry a null `space_id`,
weakening per-space audit queries.

**Fix:** Pass `space_id=<the affected space uuid>` on these calls for a consistent audit trail.

### IN-02: No test exercises a cross-tenant `.../answers` or `.../skill-runs` request

**File:** `backend/tests/test_intake_cross_tenant.py`, `backend/tests/test_intake_routes.py`

**Issue:** The denial suite proves 404/scoping for `/intakes` get/list/patch only; the
intake-routes suite covers same-space answer upsert and the transition allow-list. The
answer/skill-run sub-resources have no cross-tenant case, which is precisely why CR-01 went
unnoticed.

**Fix:** Add cases: user-A `PATCH /intakes/{intake_B}/answers` must be 404 with B's answers
unchanged on owner re-read; user-A `GET /intakes/{intake_B}/answers` and `.../skill-runs`
must be 404.

---

_Reviewed: 2026-06-29_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
