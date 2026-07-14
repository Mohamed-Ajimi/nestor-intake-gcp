---
phase: 11-internationalization-nl-fr-en
plan: 02
subsystem: api
tags: [i18n, locale, fastapi, alembic, postgres, error-codes, pydantic]

# Dependency graph
requires:
  - phase: 05-user-space-management
    provides: organizations/organization_memberships root tables, status server_default backfill pattern (0006), AdminRepo + get_admin_session, audit.log
  - phase: 03-identity-platform-auth
    provides: Identity (uid/role/space_id), get_current_identity verified-token boundary, protected_router default-deny mount
  - phase: 04-tenant-isolation
    provides: get_tenant_repo engine-by-role + SET LOCAL GUC pattern, session.py DI seam
provides:
  - 0010 migration adding organizations.default_locale (NOT NULL 'nl' backfill) + organization_memberships.locale (nullable override)
  - GET /me + PATCH /me/locale endpoints implementing the D-07 resolution chain (user override -> space default -> nl) with token-derived identity + {nl,fr,en} enum validation
  - CodedError additive error-code contract ({detail, code}) with curated USER_FACING_CODES enum; INVALID_LOCALE is its first consumer
  - get_me_session both-roles session dependency (no default-deny for superadmin-with-no-space)
  - three backend test modules (schema-shape, /me endpoints, error-codes) authored by construction
affects: [11-01 frontend LanguageSwitcher + error-codes map + getMe/patchLocale seam, mail locale resolution (later 11 plans)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "CodedError additive error contract: {detail:str, code:str} — detail stays a raw-fallback string, code is additive machine-readable"
    - "get_me_session: a both-roles session dependency that does NOT default-deny a superadmin with no space (unlike get_tenant_repo)"
    - "locale as display-only: identity re-derived from the verified token, never an authz input"

key-files:
  created:
    - backend/app/db/alembic/versions/0010_locale_columns.py
    - backend/app/api/me_routes.py
    - backend/app/api/errors.py
    - backend/tests/test_schema_shape_locale.py
    - backend/tests/test_me_routes.py
    - backend/tests/test_error_codes.py
  modified:
    - backend/app/db/models/organization.py
    - backend/app/db/models/membership.py
    - backend/app/db/session.py
    - backend/app/main.py

key-decisions:
  - "Superadmin locale home (Open Q1): lives in the nullable membership.locale WHEN a membership row exists; with NO row, /me returns locale null + space_default 'nl' and persists nothing (localStorage-only fallback). No user_preferences table in v1."
  - "get_me_session is a dedicated both-roles dependency (not get_tenant_repo) because a superadmin legitimately has space_id None; the /me read of two root tables must not 403."
  - "CodedError handler + me_router mount both land in main.py in the /me commit (interdependent: PATCH's INVALID_LOCALE raise needs the handler); errors.py + its test committed first as the standalone contract."

patterns-established:
  - "Additive error-code contract: new CodedError raises emit {detail, code}; existing HTTPException string-detail raises are untouched (backward-compat)."
  - "Both-roles /me session dependency: superadmin engine (no GUC) vs app engine (+ GUC), no default-deny for the no-space superadmin path."

requirements-completed: [I18N-01, I18N-02]

# Metrics
duration: 24min
completed: 2026-07-14
---

# Phase 11 Plan 02: Backend Locale Surface Summary

**0010 migration + org/membership locale columns, GET /me + PATCH /me/locale implementing the D-07 user→space→nl resolution chain with token-derived identity and {nl,fr,en} validation, and the additive CodedError {detail, code} contract with INVALID_LOCALE as its first consumer.**

## Performance

- **Duration:** ~24 min
- **Tasks:** 3 (all `type="auto"`)
- **Files modified:** 10 (6 created, 4 modified)

## Accomplishments
- **0010 migration + ORM columns:** `organizations.default_locale` (String NOT NULL, `server_default 'nl'` backfill) and `organization_memberships.locale` (nullable override), column names matching 1:1 between migration and models (alembic-check-clean intent), no new index on the scalar columns.
- **`/me` locale endpoints:** `GET /me` returns the caller's `locale` (membership override, nullable) + `space_default_locale` (org default, `nl` fallback); `PATCH /me/locale` validates the `{nl,fr,en}` enum, persists the override onto the caller's own membership (re-derived from the verified token), and persists nothing for a superadmin with no membership row.
- **CodedError contract:** `errors.py` defines `CodedError(status_code, code, detail)` + a curated `USER_FACING_CODES` enum (`INVALID_LOCALE`, `INTAKE_NOT_FOUND`, `RECIPIENT_INVALID`, `MAIL_SEND_FAILED`); the `main.py` handler emits `{detail, code}` additively with `detail` staying a plain string; `INVALID_LOCALE` is the first consumer.
- **Tests authored by construction:** schema-shape (both columns' nullability + the 'nl' default + no-index), `/me` (GET resolution, PATCH persist + re-read round-trip, invalid-locale 422 no-persist, token-derived identity with a victim-untouched assertion, superadmin-no-membership null/nl + no-row-created), and error-codes ({detail, code} shape + HTTPException backward-compat + curated-enum membership).

## Task Commits

1. **Task 1: 0010 migration + org/membership locale columns + schema-shape test** — `c6ed250` (feat)
2. **Task 3: CodedError contract (errors.py) + test** — `63bf08f` (feat) *(committed before Task 2 so main.py/me_routes could import it at a valid state)*
3. **Task 2: me_routes (GET /me + PATCH /me/locale) + resolution chain + main.py wiring + tests** — `e1b3bdd` (feat)
4. **Rule 3 fix: coerce identity.space_id to UUID in the /me org lookup** — `996daf9` (fix)

## Files Created/Modified
- `backend/app/db/alembic/versions/0010_locale_columns.py` — adds `default_locale` (org, NOT NULL 'nl') + `locale` (membership, nullable), `schema="nestor"`, down_revision "0009".
- `backend/app/db/models/organization.py` — `default_locale` mapped column (`server_default="nl"`).
- `backend/app/db/models/membership.py` — nullable `locale` mapped column.
- `backend/app/api/errors.py` — `CodedError` + curated `USER_FACING_CODES` enum.
- `backend/app/api/me_routes.py` — `me_router`, `Me`/`LocalePatchBody` models, resolution chain, `_load_membership`/`_resolve_me` helpers, both handlers sync `def`.
- `backend/app/db/session.py` — `get_me_session` both-roles dependency.
- `backend/app/main.py` — `protected_router.include_router(me_router)` + `@app.exception_handler(CodedError)`.
- `backend/tests/test_schema_shape_locale.py`, `test_me_routes.py`, `test_error_codes.py` — the three test modules.

## Decisions Made
- **Superadmin locale home (Open Q1):** the nullable membership `locale` column WHEN a row exists; otherwise `/me` returns `locale: null` + `space_default_locale: "nl"` and PATCH persists nothing (localStorage-only path). No `user_preferences` table in v1. Documented in the migration + model docstrings.
- **`get_me_session` is a dedicated dependency** (not `get_tenant_repo`): a superadmin legitimately has `space_id` None, so the `/me` read of the two root tables (`organization_memberships`, `organizations`) must not hit the tenant path's default-deny 403. Engine-by-role is preserved (superadmin engine / app engine + GUC).
- **Membership lookup key:** `provider_user_id == identity.uid` — the Identity Platform subject id the Phase-5 invite flow stamps onto the membership row (verified against `AdminRepo.create_membership` + `test_admin_routes` seeding, where `provider_user_id` carries the uid).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Coerce `identity.space_id` (str) to `uuid.UUID` in the `/me` org lookup**
- **Found during:** Task 2 (me_routes resolution chain)
- **Issue:** `identity.space_id` is a `str` and `Organization.id` is `UUID(as_uuid=True)`; comparing them directly risks an ambiguous/failed pg8000 bind on the org `default_locale` read (Pitfall 6, the exact class `AdminRepo._as_uuid` exists to prevent).
- **Fix:** Wrapped the comparison value in `uuid.UUID(str(identity.space_id))`, mirroring `AdminRepo._as_uuid`.
- **Files modified:** `backend/app/api/me_routes.py`
- **Verification:** Coercion matches the established repo-layer idiom; column/value types now agree (Cloud Build suite is the runtime gate — no local Python/Docker on this box).
- **Committed in:** `996daf9`

### Sequencing note (not a deviation of substance)
- **Task 3 was committed before Task 2** so `errors.py` existed on-disk-and-committed before `main.py`/`me_routes.py` import it, keeping every commit at a valid-import state. The `main.py` CodedError handler wiring (nominally listed under Task 3) is committed with the `/me` change (Task 2) because the PATCH `INVALID_LOCALE` raise depends on that handler being registered. Net content is exactly the plan's three tasks.

---

**Total deviations:** 1 auto-fixed (1 blocking type-coercion).
**Impact on plan:** The fix is a correctness requirement for the pg8000 bind; no scope creep. The commit ordering keeps imports valid at every commit and does not change the delivered surface.

## Issues Encountered
None — the plan's interfaces (Identity, get_current_identity, protected_router mount, 0006 backfill pattern, AdminRepo membership seeding) mapped cleanly onto the implementation. Backend tests are authored by construction and run in Cloud Build (this dev box has no Python/Docker).

## User Setup Required
None — no external service configuration required. The 0010 migration runs via the existing Cloud Run migration Job (`alembic upgrade head`) at the phase deploy gate.

## Next Phase Readiness
- **Ready for 11-01 (frontend):** the `Me` response shape (`{locale, space_default_locale}`), the `PATCH /me/locale` persist contract, and the `code` field on error responses are all in place for the LanguageSwitcher, the `getMe`/`patchLocale` seam, and the `ERROR_CODES` map.
- **Ready for later 11 mail work:** the membership `locale` + org `default_locale` columns are the source the per-recipient mail-locale resolution will read.
- **Gate:** the three test modules + the 0010 migration run in the Cloud Build suite (the phase-gate runner); no local execution on this box (dev-machine-no-python-docker).

## Self-Check: PASSED

All 6 created source/test files exist on disk; all task/fix/docs commit hashes (`c6ed250`, `63bf08f`, `e1b3bdd`, `996daf9`, `c35b974`) are present in git history.

---
*Phase: 11-internationalization-nl-fr-en*
*Completed: 2026-07-14*
