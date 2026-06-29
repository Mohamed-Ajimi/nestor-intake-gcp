---
phase: 06-intake-crud-parity-frontend-api-seam
verified: 2026-06-29T18:30:00Z
status: gaps_found
score: 6/8 must-haves verified
overrides_applied: 0
gaps:
  - truth: "Each client's data is fully isolated to its own space"
    status: failed
    reason: >
      The answers upsert write path (PATCH /{intake_id}/answers) never verifies that the
      target intake belongs to the caller's space before writing. upsert_answers in
      intake_routes.py:330-346 passes intake_id straight to repo.upsert_batch without an
      ownership check (no repo.get call). IntakeAnswerRepository.upsert_batch at
      repository.py:170-202 builds rows with space_id from self._space_id but the ON
      CONFLICT target (constraint=uq_intake_answers_intake_field) resolves only on
      (intake_id, field_key) — space_id is absent. models/intake.py:169-172 confirms the
      UniqueConstraint is on ("intake_id", "field_key") with no space_id column. A user in
      space A calling PATCH /intakes/{intake_B_id}/answers will: (a) insert orphan rows
      stamped space_id=A pointing at space B's intake and receive 200 with those rows, or
      (b) for a colliding field_key, hit the conflict target against space B's row. The
      D-01 belt-and-suspenders invariant (explicit WHERE + RLS independently enforce
      isolation) is reduced to RLS-only on this path — exactly the broken-RLS class of bug
      CLAUDE.md says must never recur.
    artifacts:
      - path: "backend/app/api/intake_routes.py"
        issue: "upsert_answers handler (lines 330-346) has no repo.get(intake_id) ownership gate before calling repo.upsert_batch"
      - path: "backend/app/db/repository.py"
        issue: "upsert_batch (lines 170-202) does not call _scope(); ON CONFLICT target is (intake_id, field_key) with no space_id guard"
      - path: "backend/app/db/models/intake.py"
        issue: "UniqueConstraint uq_intake_answers_intake_field on (intake_id, field_key) — space_id omitted from the conflict key"
    missing:
      - "Add intake ownership gate in upsert_answers: intake_repo.get(intake_id) is None → 404 before any upsert"
      - "Add _scope()-consistent WHERE or include space_id in the ON CONFLICT target so the repo wall stands independently of RLS"
      - "Add cross-tenant answers PATCH denial test to test_intake_cross_tenant.py (user-A PATCH /intakes/{intake_B}/answers → 404, space-B answers unchanged on owner re-read)"
  - truth: "Superadmin space selector/switcher filters the intake list"
    status: failed
    reason: >
      withActiveSpace() in frontend/src/lib/active-space.tsx:44-46 appends ?space_id=<id>
      to the /intakes GET URL. The backend list_intakes handler at intake_routes.py:223-232
      declares no space_id query parameter; FastAPI silently ignores the param. For a
      superadmin, repo.list() returns all spaces regardless of which space is selected in the
      switcher. The page header in admin.pulse.intakes.index.tsx:110 reads "gefilterd op de
      actieve klant" but no filtering occurs — neither server-side (backend ignores param)
      nor client-side (the component filters only by status/search text, not space_id). The
      SpaceSwitcher component itself is correctly built and superadmin-gated; the gap is in
      the backend endpoint lacking the optional space_id param and the frontend page lacking
      a client-side fallback filter.
    artifacts:
      - path: "backend/app/api/intake_routes.py"
        issue: "list_intakes (lines 223-232) has no space_id: str | None = None query param; superadmin space filter is silently dropped"
      - path: "frontend/src/routes/admin.pulse.intakes.index.tsx"
        issue: "Header claims 'gefilterd op de actieve klant' but listIntakes result is never filtered by activeSpaceId client-side"
    missing:
      - "Add optional space_id: str | None = None query param to list_intakes; for superadmin only, narrow repo.list() to that space"
      - "OR filter the returned rows client-side by activeSpaceId in admin.pulse.intakes.index.tsx"
      - "Update the header copy to match actual behavior until the filter is implemented"
human_verification:
  - test: "Space switcher behavior (superadmin vs user) — 06-08 Task 3"
    expected: >
      As SUPERADMIN: KLANT switcher appears below logo, above nav. Selecting a client
      re-filters the intake list in place (no navigation); label shows org name. Reload
      preserves selection. Selecting 'Alle klanten' restores all spaces. As USER: switcher
      is ABSENT from the DOM entirely (inspect element — not just hidden).
    why_human: "Requires running frontend locally (npm run dev, localhost:8081) against the live GCP backend with real superadmin and user accounts. Cannot simulate DOM presence/absence or query-invalidation behavior with static analysis."
  - test: "Authenticated user intake journey — 06-09 Task 4"
    expected: >
      USER logs in at /intake and sees only their own space's intakes (no Klant column, no
      switcher). Opens a draft, fills a section, clicks Volgende — one save fires and
      progress is preserved. Submit transitions to submitted. For a validated_by_client or
      decomposed intake, 'Bekijk resultaat' renders the read-only FieldDisplay with no
      ResearchResultsPanel/ContextPackBlock. For a draft, /intake/$id/results redirects
      back to the fill route.
    why_human: "Requires running the app in a browser as a real user, with a live backend that has seeded intake data in a space. Cannot verify save-on-advance behavior, redirect logic, or cross-space isolation dynamically without a running stack."
---

# Phase 6: Intake CRUD Parity Verification Report

**Phase Goal:** Achieve intake CRUD parity on the GCP backend behind a frontend lib/api seam — a logged-in superadmin or client user can run an intake end-to-end (form → save → submit → review → decompose) with each client's data fully isolated to its own space, the Supabase data/auth path retired from the intake surface, and the flow structurally capped at `decomposed`.
**Verified:** 2026-06-29T18:30:00Z
**Status:** gaps_found — 2 BLOCKERs
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | End-to-end intake flow (form → save → submit → review → decompose) is structurally present | PARTIAL | Routes intake.index.tsx / intake.$id.tsx / intake.$id.results.tsx exist; admin.pulse.intakes.$id.tsx wired to seam; submit/review transition verbs exist and are allow-listed. Save path has CR-01 gap (see Truth 2). |
| 2 | Each client's data is fully isolated to its own space | FAILED (BLOCKER) | intake_routes.py:330-346 upsert_answers has no ownership check; repository.py:170-202 upsert_batch skips _scope(); models/intake.py:169-172 UniqueConstraint uq_intake_answers_intake_field omits space_id. D-01 belt-and-suspenders invariant broken on the write path. |
| 3 | Supabase data/auth path retired from the intake surface | VERIFIED | intake.index.tsx, intake.$id.tsx, intake.$id.results.tsx have zero supabase references; ProductShell.tsx uses Firebase signOut; lib/api seam is comprehensive. |
| 4 | Flow structurally capped at decomposed | VERIFIED | ci_no_run_research.sh exists with adversarial pattern; no matching tokens found in backend/app or frontend/src. Transition allow-lists (_SUBMIT_TRANSITIONS, _REVIEW_TRANSITIONS) prohibit any jump past validated_by_client/reviewed. |
| 5 | Frontend data access centralized in lib/api/* seam (API-03) | VERIFIED | lib/api/intakes.ts, answers.ts, templates.ts, skillRuns.ts, admin.ts, search.ts, storage.ts all exist; intake routes import from these modules; no inline supabase in the new intake surface. |
| 6 | Superadmin space selector/switcher filters the intake list (TENANT-04) | FAILED (BLOCKER) | SpaceSwitcher.tsx exists and is correctly superadmin-gated in ProductShell. withActiveSpace appends ?space_id param. But backend list_intakes declares no space_id query param (FastAPI ignores it); client-side code in admin.pulse.intakes.index.tsx does not filter by activeSpaceId. The switcher has no functional effect on the intake list. Page header falsely claims "gefilterd op de actieve klant". |
| 7 | QA-03: Phase machine characterization suite (vitest, 17 tests) | VERIFIED | frontend/src/lib/intake-phase.test.ts exists with 17 `it()` cases covering all 12 Phase enum values plus edge cases (delivered/results_link variants, unknown/archived). Package.json defines `"test": "vitest run"`. |
| 8 | INTAKE-05: CI scope guard fails on run-research/Tribunal token | VERIFIED | backend/scripts/ci_no_run_research.sh exists with precise anchored pattern. Grep scan of backend/app and frontend/src returns no matches. Script scans both trees, exits 0 on clean tree, 1 on offender, 2 on misconfig. |

**Score:** 6/8 truths verified (2 FAILED — BLOCKERs)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/app/api/intake_routes.py` | Full intake feature router (INTAKE-01 through INTAKE-05) | PARTIAL | All routes present; upsert_answers missing ownership gate (CR-01) |
| `backend/app/db/repository.py` | TenantRepository + per-entity subclasses with _scope | PARTIAL | Base + 4 subclasses present; upsert_batch skips _scope, conflict target lacks space_id |
| `backend/app/db/models/intake.py` | Intake, IntakeAnswer, IntakeTemplate models | VERIFIED | All three models present with space_id NOT NULL; UniqueConstraint on (intake_id, field_key) correctly named but correctly identified as the gap's root cause |
| `backend/app/db/session.py` | Per-entity tenant-repo dependencies | VERIFIED | get_tenant_repo, get_intake_answer_repo, get_skill_run_repo, get_intake_template_repo all present, sync, with default-deny |
| `frontend/src/lib/api/intakes.ts` | Typed intake seam (list/get/create/patch/submit/review) | VERIFIED | All 6 functions present; withActiveSpace threaded for superadmin filter |
| `frontend/src/lib/active-space.tsx` | ActiveSpaceProvider + withActiveSpace accessor | VERIFIED | Provider, hook, module-level accessor all present; persistence to localStorage |
| `frontend/src/components/admin/SpaceSwitcher.tsx` | Superadmin-only Combobox writing ActiveSpaceProvider | VERIFIED | Component exists, reads listSpaces(), invalidates queries on select, no accent color, all states implemented |
| `frontend/src/components/admin/ProductShell.tsx` | Shell hosting switcher + Firebase logout | VERIFIED | ActiveSpaceProvider wraps tree; SpaceSwitcher inside isSuperadmin gate; Firebase signOut; zero supabase references |
| `frontend/src/routes/intake.index.tsx` | Authenticated space-scoped user intake list | VERIFIED | createFileRoute("/intake/"), beforeLoad auth guard, listIntakes(), StatusPill, contextual CTAs, no supabase |
| `frontend/src/routes/intake.$id.tsx` | User fill/submit route hosting IntakeForm | VERIFIED | createFileRoute("/intake/$id"), beforeLoad guard, getIntake+listAnswers+getTemplates, IntakeForm hosted, no supabase |
| `frontend/src/routes/intake.$id.results.tsx` | Read-only results via FieldDisplay with phase-ceiling redirect | VERIFIED | createFileRoute("/intake/$id/results"), isValidatedOrLater() redirect, FieldDisplay render, no ResearchResultsPanel/ContextPackBlock |
| `frontend/src/lib/intake-phase.test.ts` | 17-test vitest characterization suite (QA-03) | VERIFIED | 17 `it()` cases, all 12+ Phase outcomes covered, derives from vitest with no supabase dependency |
| `backend/scripts/ci_no_run_research.sh` | CI grep-guard for scope ceiling (INTAKE-05) | VERIFIED | Present, exit-code contract correct, adversarial pattern, dual-tree scan |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `upsert_answers` handler | `IntakeAnswerRepository.upsert_batch` | Direct call, no ownership pre-check | BROKEN | No `repo.get(intake_id)` before writing — CR-01 |
| `upsert_batch` | `_scope()` | Not called on upsert path | BROKEN | Only reads (list_for_intake) use _scope; the INSERT is unscoped at the repo layer |
| `withActiveSpace()` | `list_intakes` backend param | `?space_id=<id>` query param | NOT_WIRED | Backend list_intakes declares no space_id param; FastAPI silently ignores it — WR-01 |
| `SpaceSwitcher` | `useActiveSpace` / `setActiveSpace` | Called on select | VERIFIED | handleSelect calls setActiveSpace(id) + invalidateQueries() |
| `ProductShell` | `SpaceSwitcher` | Inside `isSuperadmin &&` gate | VERIFIED | Line 59: `{isSuperadmin && (<div className="mt-6"><SpaceSwitcher /></div>)}` |
| `ProductShell` | `ActiveSpaceProvider` | Wraps returned tree | VERIFIED | `<ActiveSpaceProvider>` at line 35, closed at line 126 |
| `intake.index.tsx` | `listIntakes` | useEffect + listIntakes() | VERIFIED | Fetches on mount, sets state, renders rows |
| `intake.$id.tsx` | `IntakeForm` | `<IntakeForm payload={payload} token={payload.intake.id} />` | VERIFIED | Full IntakePayload constructed from getIntake+listAnswers+getTemplates |
| `intake.$id.results.tsx` | `FieldDisplay` | Renders each field in each section | VERIFIED | `<FieldDisplay key={field.key} field={field} value={answers[field.key]} />` |
| `ci_no_run_research.sh` | `backend/app + frontend/src` | grep -rEn over both trees | VERIFIED | No matches in either tree |
| `submit_intake` / `review_intake` | allow-list maps | Dict lookup → 409 on miss | VERIFIED | _SUBMIT_TRANSITIONS and _REVIEW_TRANSITIONS block any post-decomposed jump |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `intake.index.tsx` | `intakes` | `listIntakes()` → `apiFetch` → backend `list_intakes` → `repo.list()` | Yes (DB query via TenantRepository) | FLOWING |
| `intake.$id.tsx` | `payload` | `getIntake()` + `listAnswers()` + `getTemplates()` | Yes (three seam calls → backend DB queries) | FLOWING |
| `intake.$id.results.tsx` | `schema`, `answers` | `getIntake()` + `listAnswers()` + `getTemplates()` | Yes (three seam calls with phase-ceiling redirect if not validated) | FLOWING |
| `admin.pulse.intakes.index.tsx` | `intakes` for superadmin | `listIntakes()` via `withActiveSpace()` → backend `list_intakes` | Partial — all spaces returned regardless of active space selection | HOLLOW for space filter |

### Behavioral Spot-Checks

Step 7b: SKIPPED — backend requires Docker/Cloud SQL (dev machine has no Python/Docker per MEMORY). Frontend routes require a running server. The vitest suite (QA-03) is the only locally verifiable behavioral check and was verified by static file analysis.

### Probe Execution

| Probe | Command | Result | Status |
|-------|---------|--------|--------|
| `backend/scripts/ci_no_run_research.sh` | Static grep in backend/app and frontend/src | No matching patterns found in backend/app (Python) or frontend/src (TS/TSX) — confirmed by Grep tool search | PASS (static verification; bash not runnable on this Windows dev machine) |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| API-03 | 06-01, 06-05, 06-09 | Frontend data access centralized in lib/api/* | SATISFIED | lib/api/ seam modules all exist; intake routes import from them |
| INTAKE-01 | 06-06, 06-09 | Logged-in user can open, fill (save-as-you-go), and submit | SATISFIED (code) / HUMAN PENDING | Routes and seam wired; save-as-you-go functional path exists but answers upsert has CR-01 isolation gap; human UAT checkpoint not done |
| INTAKE-02 | 06-09 | Logged-in user can view intake results | SATISFIED (code) / HUMAN PENDING | intake.$id.results.tsx exists with FieldDisplay, phase-ceiling redirect; human UAT not done |
| INTAKE-03 | 06-04, 06-06, 06-07 | Admin lifecycle through decomposed | SATISFIED | Admin routes, IntakeForm data-swap, AIReviewPanel seam stubs all present; allow-listed transitions drive the state machine |
| INTAKE-04 | 06-04 | Status transitions backend-driven via allow-listed verbs | SATISFIED | submit_intake() / review_intake() with _SUBMIT_TRANSITIONS / _REVIEW_TRANSITIONS; no generic PATCH status |
| INTAKE-05 | 06-11 | Scope guard: run-research never invoked | SATISFIED | ci_no_run_research.sh passes on the clean tree; no invocation patterns found |
| TENANT-04 | 06-08 | User sees only own space; superadmin has working space selector | BLOCKED | Switcher component exists and is superadmin-gated (correct). But backend list_intakes ignores the ?space_id param; selector has no functional effect on the list. TENANT-04's "space selector" requirement is not met end-to-end. |
| QA-03 | 06-10 | Characterization tests cover the phase machine | SATISFIED | frontend/src/lib/intake-phase.test.ts, 17 `it()` cases, all Phase enum values covered |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `backend/app/api/intake_routes.py` | 330-346 | Missing ownership check before cross-tenant write | BLOCKER | upsert_answers writes to any intake_id without verifying it's in-scope — CR-01 |
| `backend/app/db/repository.py` | 170-202 | upsert_batch never calls _scope() on the INSERT path | BLOCKER | Breaks D-01 belt-and-suspenders invariant on the answers write path |
| `backend/app/db/models/intake.py` | 169-172 | UniqueConstraint on (intake_id, field_key) omits space_id | BLOCKER | ON CONFLICT target resolves cross-tenant rows when field_key collides |
| `frontend/src/routes/admin.pulse.intakes.index.tsx` | 110 | Header claims "gefilterd op de actieve klant" — false | WARNING | Copy is misleading; space filter is inert (backend ignores ?space_id) |
| `backend/app/api/intake_routes.py` | 321-327, 354-369 | GET .../answers and .../skill-runs return 200 (empty) for cross-tenant intake_id | WARNING | Inconsistent D-07 behavior vs sibling routes that return 404; no data leaks but existence-hiding is broken |

No unreferenced TBD/FIXME/XXX debt markers found in the files reviewed. No BLOCKER debt-marker gate triggered.

### Human Verification Required

#### 1. Space Switcher Behavior (06-08 Task 3)

**Test:** Log in as SUPERADMIN. Confirm the `KLANT` switcher appears below the logo, above the nav. Select a client → confirm the intake list re-filters in place (no navigation) and the label shows the org name. Reload → the selection persists. Select `Alle klanten` → all spaces' intakes return. Then log in as a USER — confirm the switcher is ABSENT from the DOM entirely (inspect, not merely visually hidden).

**Expected:** Switcher visible to superadmin, absent from user DOM. Selection persists across reloads. List re-filters on selection.

**Why human:** Requires a running frontend + live backend with real accounts and seeded data. DOM presence/absence and query-invalidation effect cannot be verified statically. Note: the backend filter gap (WR-01) must be fixed before the re-filter behavior is testable.

#### 2. Authenticated User Intake Journey (06-09 Task 4)

**Test:** Log in as a USER. Visit `/intake` — confirm only own-space intakes appear, no Klant column, no switcher. Open a draft, fill a section, click Volgende — confirm one save fires and answers persist. Submit → confirm submitted state. For a `validated_by_client`/`decomposed` intake: click `Bekijk resultaat` → confirm read-only FieldDisplay renders with no ResearchResultsPanel/ContextPackBlock. For a draft: `/intake/$id/results` redirects to the fill route.

**Expected:** Full journey flows correctly; space isolation verified by absence of other-space rows; scope ceiling holds (no post-decomposed output).

**Why human:** Requires running app against live backend with real user credentials and intake data in a space. Save-on-advance and redirect behavior require browser execution. Note: authoritative routeTree.gen.ts regen (npm run build) must be done first (06-09 flag #1).

### Gaps Summary

Two BLOCKERs prevent the phase goal from being achieved:

**BLOCKER 1 — Tenant isolation not achieved on the answers write path (CR-01, TENANT-04 partial, D-01 broken):**
The phase goal's central claim — "each client's data fully isolated to its own space" — is NOT met for the one write path that the intake form drives on every section save: `PATCH /intakes/{intake_id}/answers`. The handler in `intake_routes.py:330-346` passes `intake_id` directly to `repo.upsert_batch` without first verifying that the intake belongs to the caller's space via `repo.get()`. The repository's `upsert_batch` at `repository.py:170-202` injects `space_id` from identity into the inserted rows (so new rows carry the correct space stamp) but the `ON CONFLICT DO UPDATE` target resolves on `(intake_id, field_key)` — a constraint that does not include `space_id` (confirmed by `models/intake.py:169-172`). This means the repo's _scope() wall — which every other read/write path applies — is absent on this write. The D-01 belt-and-suspenders invariant (explicit WHERE + RLS both independently enforce isolation) is reduced to RLS-only for this path, which is exactly the "broken-RLS class of bug must not recur" constraint in CLAUDE.md.

Fix requires: (a) add ownership pre-check in `upsert_answers` (`intake_repo.get(intake_id) is None → 404`), (b) tighten the conflict target or add an explicit scoped WHERE on the upsert, (c) add a cross-tenant denial test for this endpoint.

**BLOCKER 2 — Superadmin space switcher filter is inert (WR-01, TENANT-04 not functionally met):**
TENANT-04 requires "a superadmin has a space selector/switcher" with the implication it is functional. The SpaceSwitcher component is correctly built and superadmin-gated. `withActiveSpace()` appends `?space_id=<id>` to the `/intakes` URL. But `list_intakes` in `intake_routes.py:223-232` declares no `space_id` query parameter — FastAPI silently discards it. For a superadmin, `repo.list()` returns rows from all spaces regardless of selection. The page header (`admin.pulse.intakes.index.tsx:110`) claims "gefilterd op de actieve klant" but no filtering occurs anywhere. Selecting a space has no visible effect on the intake list. The two human-verify checkpoints (06-08 Task 3, 06-09 Task 4) are also pending — these require a running app.

Fix requires: add `space_id: str | None = None` query param to `list_intakes`; for superadmin only, narrow `repo.list()` to that space (never trust it for a user); update the header copy.

---

_Verified: 2026-06-29T18:30:00Z_
_Verifier: Claude (gsd-verifier)_
