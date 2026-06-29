---
phase: 06-intake-crud-parity-frontend-api-seam
verified: 2026-06-29T22:00:00Z
status: human_needed
score: 8/8 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 6/8
  gaps_closed:
    - "Each client's data is fully isolated to its own space (CR-01 / TENANT-04 / D-01 on the answers write path)"
    - "Superadmin space selector/switcher filters the intake list (WR-01 / TENANT-04)"
  gaps_remaining: []
  regressions: []
human_verification:
  - test: "Space switcher behavior — superadmin sees KLANT switcher, user sees nothing"
    expected: >
      As SUPERADMIN: KLANT switcher appears below logo, above nav. Selecting a client
      re-filters the intake list in place (no navigation); label shows org name. Reload
      preserves selection. Selecting 'Alle klanten' restores all spaces (subtitle reads
      'Alle Pulse intakes.'). As USER: switcher is ABSENT from the DOM entirely
      (inspect element — not just hidden). Subtitle reads 'Alle Pulse intakes.' (no
      activeSpaceId set). Backend now honors the ?space_id param for superadmin so the
      re-filter will have a real effect.
    why_human: "Requires running frontend locally (npm run dev, localhost:8081) against the live GCP backend with real superadmin and user accounts. Cannot simulate DOM presence/absence or query-invalidation behavior with static analysis."
  - test: "Authenticated user intake journey — 06-09 Task 4"
    expected: >
      USER logs in at /intake and sees only their own space's intakes (no Klant column,
      no switcher). Opens a draft, fills a section, clicks Volgende — one save fires and
      progress is preserved. Submit transitions to submitted. For a validated_by_client or
      decomposed intake, 'Bekijk resultaat' renders the read-only FieldDisplay with no
      ResearchResultsPanel/ContextPackBlock. For a draft, /intake/$id/results redirects
      back to the fill route.
    why_human: "Requires running the app in a browser as a real user, with a live backend that has seeded intake data in a space. Cannot verify save-on-advance behavior, redirect logic, or cross-space isolation dynamically without a running stack."
---

# Phase 6: Intake CRUD Parity — Re-Verification Report

**Phase Goal:** The intake flow reaches full authenticated parity to `decomposed` with all frontend data access centralized in `frontend/src/lib/api/*`, replacing every inline Supabase call, and the scope guard prevents `run-research` invocation.
**Verified:** 2026-06-29T22:00:00Z
**Status:** human_needed — all 8 truths VERIFIED by construction; 2 human verification items remain (unchanged from initial)
**Re-verification:** Yes — after gap closure by plans 06-12 (BLOCKER 1) and 06-13 (BLOCKER 2)

---

## Re-verification Focus

Previous VERIFICATION.md (2026-06-29T18:30:00Z) reported `gaps_found` with 2 BLOCKERs:

- **BLOCKER 1 (CR-01):** `upsert_answers` lacked an ownership gate; `upsert_batch` lacked a space-scoped WHERE on `ON CONFLICT DO UPDATE`, reducing D-01 to RLS-only on the write path.
- **BLOCKER 2 (WR-01):** `list_intakes` declared no `space_id` query param, so `withActiveSpace()` was silently dropped by FastAPI. Superadmin space switcher had no functional effect on the intake list. Header copy falsely claimed filtering.

Two gap-closure plans (06-12, 06-13) were executed and merged. This report verifies both blockers are genuinely closed by reading the actual code, then confirms previously-passing truths have not regressed.

---

## BLOCKER 1 CLOSURE: Tenant isolation on the answers write path (06-12)

### CR-01 Fix — Three-layer implementation verified

**Layer 1: Combined one-transaction dependency (`session.py` lines 108-141)**

`get_intake_and_answer_repos` exists as a sync `def` generator (Pitfall 5 respected — NOT `async def`). It mirrors `get_intake_answer_repo` EXACTLY for the engine/role/GUC/transaction idiom. It yields a tuple of BOTH repos bound to the SAME `session` inside one `with maker.begin()`:

```python
yield (
    IntakeRepository(session, identity),
    IntakeAnswerRepository(session, identity),
)
```

D-02 (one transaction per request) is preserved: no second `maker.begin()`, no second dependency. The default-deny 403 on a null user space fires BEFORE any session is opened (D-04). The dependency is imported in `intake_routes.py` (line 55: `get_intake_and_answer_repos`).

**Layer 2: Ownership pre-check in `upsert_answers` (`intake_routes.py` lines 342-364)**

The handler signature is:
```python
def upsert_answers(
    intake_id: str,
    body: AnswerBatch,
    repos: tuple[IntakeRepository, IntakeAnswerRepository] = Depends(get_intake_and_answer_repos),
) -> list[AnswerView]:
```

`intake_repo.get(intake_id) is None → HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")` fires BEFORE `answers_repo.upsert_batch` is ever reached. This matches the D-07 existence-hiding contract used by sibling handlers (`get_intake`, `patch_intake`). The check and the write share one transaction (D-02).

**Layer 3: Space-scoped WHERE on `upsert_batch` (`repository.py` lines 205-211)**

```python
if self._space_id is not None:
    stmt = stmt.on_conflict_do_update(
        constraint="uq_intake_answers_intake_field",
        set_=set_,
        where=(self.model.space_id == self._space_id),
    )
```

The `uq_intake_answers_intake_field` conflict target is NOT changed (no migration). The `where=` clause means a conflicting row owned by a foreign space is never overwritten even if RLS were dropped — D-01 belt-and-suspenders restored on the write path. `space_id` comes ONLY from `self._space_id` (module invariant intact — no new method parameter).

**Test: `test_upsert_answers_cross_tenant_returns_404_answers_unchanged` (`test_intake_cross_tenant.py` lines 526-584)**

- Seeds space-A's intake, space-B's intake + one answer (`q1 = "owned-by-B"`) under space-B's GUC.
- Patches engine factories; overrides identity to `_user(space_a)`.
- `client.patch(f"/intakes/{intake_b}/answers", json={"answers": [{"field_key": "q1", "value": "HACKED-by-space-A"}]})`.
- Asserts `resp.status_code == 404` (EXACT, pinned `== 404`, never `in (403, 404)` — D-07 / T-06-10b).
- Re-reads space-B's `q1` answer as the OWNER (space_b GUC) and asserts `value == "owned-by-B"` (foreign row untouched).
- `_insert_answer` helper (lines 207-231): GUC-then-INSERT shape mirroring `_insert_intake`. Present and correct.

**Verdict: BLOCKER 1 CLOSED by construction.** The write path now has both an ownership gate (handler) and a scoped WHERE (repo), with an adversarial test pinning EXACTLY 404 + unchanged foreign answer. D-01 belt-and-suspenders are restored.

---

## BLOCKER 2 CLOSURE: Superadmin space switcher filter (06-13)

### WR-01 Fix — Three-layer implementation verified

**Layer 1: Optional `space_id` param in `list_intakes` (`intake_routes.py` lines 224-244)**

```python
@intake_router.get("")
def list_intakes(
    space_id: str | None = None,
    repo: IntakeRepository = Depends(get_tenant_repo),
    identity: Identity = Depends(get_current_identity),
) -> list[IntakeView]:
    rows = repo.list()
    if identity.role == "superadmin" and space_id:
        rows = [r for r in rows if str(r.space_id) == space_id]
    return [_view(row) for row in rows]
```

`space_id: str | None = None` is declared — FastAPI will no longer silently drop it.
Narrowing fires ONLY for `identity.role == "superadmin"` with a truthy `space_id` — a view-filter at the handler layer, never passed into the repo (repository.py no-space_id-parameter invariant intact).
A non-superadmin's param is INERT: the `if` condition is false, `rows` is left exactly as `repo.list()` returned (their token-derived scope is the sole authority — T-06-22/23).
FastAPI dependency caching means `get_current_identity` is called once per request despite appearing in both `get_tenant_repo` and the explicit `identity` parameter.

**Layer 2: Tests (`test_intake_cross_tenant.py` lines 592-696)**

- `test_superadmin_space_id_param_narrows_list` (lines 592-649): superadmin `?space_id=<B>` returns space-B's intake, excludes space-A's; superadmin without param still returns BOTH (no regression).
- `test_user_space_id_param_is_inert` (lines 657-696): user `?space_id=<B>` still returns ONLY space-A's intake, never space-B's.

Both use the correct superadmin engine fixture for the superadmin test, reuse `_seed_two_spaces` / `_cleanup_spaces` / `_as` / try-finally. Both are collected under `pytestmark = pytest.mark.integration`.

**Layer 3: Frontend header copy (`admin.pulse.intakes.index.tsx`)**

- `useActiveSpace` imported from `"@/lib/active-space"` at line 19. VERIFIED.
- `const { activeSpaceId } = useActiveSpace()` at line 53. VERIFIED.
- Subtitle at lines 115-118:
  ```tsx
  {activeSpaceId
    ? "Pulse intakes, gefilterd op de actieve klant."
    : "Alle Pulse intakes."}
  ```
  The false unconditional `"Alle Pulse intakes, gefilterd op de actieve klant."` is GONE. The subtitle now tracks the real active-space state.

**Verdict: BLOCKER 2 CLOSED by construction.** Backend now honors `?space_id` for a superadmin; a user's param is doubly inert (never sent by the UI due to the ProductShell-gated SpaceSwitcher, and ignored server-side even if forged). Header copy reflects real behavior.

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | End-to-end intake flow (form → save → submit → review → decompose) is structurally present | VERIFIED | All routes present; upsert_answers now has ownership gate (CR-01 fixed); submit/review allow-lists at lines 400-406 intact. |
| 2 | Each client's data is fully isolated to its own space | VERIFIED | Ownership gate in upsert_answers + scoped WHERE in upsert_batch + denial test — D-01 restored; D-07 existence-hiding on write path. |
| 3 | Supabase data/auth path retired from the intake surface | VERIFIED (no regression) | intake routes import only from lib/api seam; no supabase references introduced by 06-12/06-13. |
| 4 | Flow structurally capped at decomposed | VERIFIED (no regression) | _SUBMIT_TRANSITIONS and _REVIEW_TRANSITIONS at intake_routes.py:400-406 unchanged; ci_no_run_research.sh still present. |
| 5 | Frontend data access centralized in lib/api/* seam (API-03) | VERIFIED (no regression) | lib/api seam modules unchanged; 06-13 admin.pulse.intakes.index.tsx change adds only a useActiveSpace import (no Supabase). |
| 6 | Superadmin space selector/switcher filters the intake list (TENANT-04) | VERIFIED | list_intakes now accepts space_id param; superadmin narrowing confirmed by code + tests; user param is inert; header copy truthful. |
| 7 | QA-03: Phase machine characterization suite (vitest, 17 tests) | VERIFIED (no regression) | frontend/src/lib/intake-phase.test.ts unchanged by gap-closure plans. |
| 8 | INTAKE-05: CI scope guard fails on run-research/Tribunal token | VERIFIED (no regression) | backend/scripts/ci_no_run_research.sh exists (confirmed by filesystem check). |

**Score:** 8/8 truths verified

### Required Artifacts — Regression Check

| Artifact | Status | Note |
|----------|--------|------|
| `backend/app/db/session.py` | VERIFIED | `get_intake_and_answer_repos` added (lines 108-141); all prior dependencies intact |
| `backend/app/api/intake_routes.py` | VERIFIED | `upsert_answers` ownership gate added; `list_intakes` space_id param added; all prior routes/transitions intact |
| `backend/app/db/repository.py` | VERIFIED | `upsert_batch` scoped WHERE added; all prior `_scope`-based reads intact; no method parameter introduced |
| `backend/tests/test_intake_cross_tenant.py` | VERIFIED | 3 new test functions added; all 6 original tests intact |
| `frontend/src/routes/admin.pulse.intakes.index.tsx` | VERIFIED | `useActiveSpace` imported; subtitle branches on `activeSpaceId`; false copy removed |
| All other phase artifacts (lib/api seam, intake routes, CI script) | VERIFIED (no regression) | No changes made to these files by 06-12/06-13 |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `upsert_answers` handler | `IntakeRepository.get(intake_id)` | Combined dependency, ownership pre-check | WIRED | Lines 357-360: `intake_repo.get(intake_id) is None → 404` before any write |
| `upsert_batch` | `self.model.space_id == self._space_id` | `on_conflict_do_update where=` (user path) | WIRED | Lines 205-211: guarded by `if self._space_id is not None`, conflict target unchanged |
| `withActiveSpace()` | `list_intakes` backend param | `?space_id=<id>` query param | WIRED | Backend now declares `space_id: str | None = None`; FastAPI honors it |
| `list_intakes` | superadmin narrowing | `identity.role == "superadmin" and space_id` | WIRED | Lines 242-243: handler-side list comprehension, repo invariant intact |
| `useActiveSpace` | subtitle copy | `activeSpaceId` ternary | WIRED | Lines 115-118 of admin.pulse.intakes.index.tsx |
| All previously-VERIFIED links | (unchanged) | — | VERIFIED (no regression) | SpaceSwitcher, ProductShell, intake.$id.tsx, ci_no_run_research.sh, transition maps |

### Anti-Patterns — Re-Scan

No new debt markers (TBD/FIXME/XXX) introduced by 06-12 or 06-13. The pre-existing WARNING from the initial report remains:

| File | Issue | Severity | Note |
|------|-------|----------|------|
| `frontend/src/routes/admin.pulse.intakes.index.tsx` | 7 pre-existing `tsc --noEmit` errors (stale routeTree.gen.ts / missing required `search` prop on admin `<Link>` calls) | WARNING | Confirmed pre-existing at git base HEAD 1a18b7d by the executor; 06-13 introduced ZERO new type errors. Tracked in `deferred-items.md`. Follow-up required: regenerate routeTree.gen.ts and reconcile `search` props. |
| `backend/app/api/intake_routes.py` (previously flagged) | GET .../answers / GET .../skill-runs return 200 (empty) for cross-tenant intake_id — WR-02 | WARNING | Out of scope per 06-12 plan boundary. Exists but no data leaks. |

No new blockers.

### Requirements Coverage

| Requirement | Source Plan | Description | Status |
|-------------|------------|-------------|--------|
| API-03 | 06-01/05/09/13 | Frontend data access centralized in lib/api/* | SATISFIED |
| INTAKE-01 | 06-06/09 | Logged-in user can open, fill (save-as-you-go), and submit | SATISFIED (by construction; human UAT pending) |
| INTAKE-02 | 06-09 | Logged-in user can view intake results | SATISFIED (by construction; human UAT pending) |
| INTAKE-03 | 06-04/06/07/12 | Admin lifecycle through decomposed; answers write path isolated | SATISFIED |
| INTAKE-04 | 06-04 | Status transitions backend-driven via allow-listed verbs | SATISFIED |
| INTAKE-05 | 06-11 | Scope guard: run-research never invoked | SATISFIED |
| TENANT-04 | 06-08/12/13 | User sees only own space; superadmin has working space selector | SATISFIED |
| QA-03 | 06-10 | Characterization tests cover the phase machine | SATISFIED |

### Behavioral Spot-Checks

Step 7b: SKIPPED — backend requires Docker/Cloud SQL; no Python/Docker on this dev machine (D-10 pre-existing project condition). The vitest suite (QA-03) and the adversarial denial tests are the primary behavioral verification, run in CI.

### Probe Execution

| Probe | Command | Result | Status |
|-------|---------|--------|--------|
| `backend/scripts/ci_no_run_research.sh` | Filesystem existence check | File present at expected path | PASS (static; bash probe confirmed present) |

### Human Verification Required

#### 1. Space Switcher Behavior (06-08 Task 3)

**Test:** Log in as SUPERADMIN. Confirm the `KLANT` switcher appears below the logo, above the nav. Select a client → confirm the intake list re-filters in place (the backend now honors `?space_id` for superadmin, so this should be functional). Confirm the subtitle reads "Pulse intakes, gefilterd op de actieve klant." when a space is active and "Alle Pulse intakes." after selecting "Alle klanten". Reload → selection persists. Then log in as a USER — confirm the switcher is ABSENT from the DOM entirely (inspect element, not just visually hidden). Confirm subtitle reads "Alle Pulse intakes." (no false filter claim).

**Expected:** Switcher visible only to superadmin; selection persists; list re-filters on selection (now functional); subtitle tracks real state.

**Why human:** Requires a running frontend + live backend with real accounts and seeded data. DOM presence/absence and query-invalidation effect cannot be verified statically.

#### 2. Authenticated User Intake Journey (06-09 Task 4)

**Test:** Log in as a USER. Visit `/intake` — confirm only own-space intakes appear, no Klant column, no switcher. Open a draft, fill a section, click Volgende — confirm one save fires and answers persist. Submit → confirm submitted state. For a `validated_by_client`/`decomposed` intake: click `Bekijk resultaat` → confirm read-only FieldDisplay renders with no ResearchResultsPanel/ContextPackBlock. For a draft: `/intake/$id/results` redirects to the fill route.

**Expected:** Full journey flows correctly; space isolation confirmed by absence of other-space rows; scope ceiling holds.

**Why human:** Requires running app against live backend with real user credentials and intake data in a space. Save-on-advance and redirect behavior require browser execution. Note: routeTree.gen.ts regen recommended before this test (see deferred-items.md).

---

## Gaps Summary

No gaps remain. Both BLOCKERs from the initial verification are closed:

- **BLOCKER 1 (CR-01) CLOSED:** `upsert_answers` now has a combined one-transaction dependency that performs an ownership pre-check (404 before write) and `upsert_batch` carries a user-path scoped WHERE on its `ON CONFLICT DO UPDATE`. Adversarial test pins EXACTLY 404 + unchanged foreign answer.
- **BLOCKER 2 (WR-01) CLOSED:** `list_intakes` declares `space_id: str | None = None`; handler narrows for superadmin only; user param is inert; header copy branches on `activeSpaceId`. Two tests prove narrowing and inertness.

**Remaining open items (not blockers):**
- 2 human verification checkpoints (unchanged from initial — require a running stack)
- Pre-existing tsc errors in admin route tree (tracked in deferred-items.md — not caused by 06-12/06-13)
- WR-02: GET answers/skill-runs return 200 (empty) for cross-tenant id — WARNING, no data leak, out of scope for this phase

---

_Verified: 2026-06-29T22:00:00Z_
_Verifier: Claude (gsd-verifier) — re-verification after gap closure by 06-12 + 06-13_
