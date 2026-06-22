---
phase: 05-user-space-management
plan: 01
subsystem: backend-tests
tags: [tests, red-scaffold, auth, audit, admin, user-management, wave-0]
requires:
  - "Phase 1 schema-shape + RLS test harness (conftest engine/two_spaces fixtures)"
  - "Phase 3 app.auth.session / app.auth.dependencies / app.auth.identity contracts"
  - "Phase 4 test_cross_tenant_denial endpoint-drive pattern (superadmin_engine, _patch_engine_factories)"
provides:
  - "RED faked-SDK invite/deactivate/reactivate/re-invite composition suite (USER-01, AUTH-04)"
  - "RED endpoint suite driving the real admin_router as superadmin + 403-for-user (USER-01/03, QA-04)"
  - "RED audit-row suite asserting audit.log writes exactly one audit_log row (QA-04)"
  - "AUTH-04 specific-message assertions (Session revoked / Account disabled) (AUTH-04)"
  - "USER-02 login-sync-against-invite-row assertion (USER-02)"
  - "schema-shape: audit_log root table + status NOT NULL columns (USER-03/AUTH-04 schema)"
affects:
  - "backend/tests/ (3 new + 3 extended suites; the binding coverage contract for plans 02/03/04)"
tech-stack:
  added: []
  patterns:
    - "Wave 0 RED scaffold: pytest.importorskip guards collect clean, fail on missing behavior"
    - "Mockable Admin-SDK seam: patch the wrapper module's own auth.* symbol (no live IdP)"
    - "Drive the REAL route + fabricated Identity override + patch only the engine factory (CR-01 parity)"
key-files:
  created:
    - backend/tests/test_admin_users.py
    - backend/tests/test_admin_routes.py
    - backend/tests/test_audit.py
  modified:
    - backend/tests/test_auth_dependency.py
    - backend/tests/test_auth_session.py
    - backend/tests/test_schema_shape.py
decisions:
  - "audit_log added to ROOT_TABLES (NOT TENANT_TABLES): root table, nullable FK-less space_id, NOT RLS-scoped (D-07)"
  - "AUTH-04 tests assert the SPECIFIC 401 messages (Session revoked / Account disabled), not a generic 401, so the subclass-ordering regression (Pitfall 2) is caught at test time"
  - "USER-02 proven by driving the EXISTING sync_claims_from_membership against an invite-shaped (provider_user_id) row — no new production code expected"
  - "Endpoint suite patches ONLY session_mod.get_superadmin_engine so the REAL get_admin_session body runs (CR-01 parity with the Phase-4 denial suite)"
metrics:
  duration: ~30 min
  completed: 2026-06-22
  tasks: 3
  files: 6
---

# Phase 5 Plan 01: Wave 0 RED Test Scaffold Summary

Authored the Wave 0 RED test scaffold for Phase 5 — 3 new + 3 extended pytest suites that
encode the invite / deactivate / reactivate / audit / AUTH-04 / USER-02 contract against the
FINAL plan-02/03/04 interfaces, so every Phase-5 requirement (USER-01, USER-02, USER-03,
AUTH-04, QA-04) is verifiable by an automated command from the first commit. All suites are
RED-by-design (importorskip-guarded so they collect on this Python-less dev box and stay RED
until the production modules land).

## What Was Built

### Task 1 — `test_admin_users.py` + `test_audit.py` (commit d54761b)

- **`test_admin_users.py`** (faked Admin SDK, no DB): invite composition asserts
  `create_invited_user` composes `create_user` -> `set_custom_user_claims("new-uid",
  {"role":"user","space_id":...})` and returns the uid; `deactivate_user` calls BOTH
  `update_user(uid, disabled=True)` AND `revoke_refresh_tokens(uid)` (and never a nonexistent
  `disable_user`); `reactivate_user` calls `update_user(uid, disabled=False)`;
  `generate_set_password_link` delegates to `generate_password_reset_link`; re-invite catches
  `EmailAlreadyExistsError` and reconciles via `get_user_by_email`. Module-level
  `pytest.importorskip("app.auth.admin_users")`.
- **`test_audit.py`**: a no-DB unit test asserts `audit.log` maps the `metadata=` kwarg onto
  the ORM attribute `event_metadata` (DB column `"metadata"`) and defaults to `{}`; a
  `@pytest.mark.integration` round-trip writes via the helper on the request session, commits,
  and asserts EXACTLY one `audit_log` row with the expected actor/event_type/space_id and a
  round-tripped `event_metadata` JSONB. Guarded by
  `pytest.importorskip("app.db.audit" / "app.db.models.audit")`.

### Task 2 — `test_admin_routes.py` (commit 2b6e7a5)

Endpoint-integration suite (`pytestmark = pytest.mark.integration`) that mounts the REAL
`admin_router` under `protected_router`, overrides `get_current_identity` with a fabricated
superadmin, patches ONLY `session_mod.get_superadmin_engine` -> a connect-as `app_superadmin`
engine (so the production `get_admin_session` body runs verbatim, CR-01 parity), and fakes the
`admin_users.*` SDK calls. Cases pin: invite -> 200 + action LINK only (no token/password,
T-5-02) with a `role="user"`/`status="active"` membership row + exactly one `user.invited`
audit row in PG; deactivate/reactivate flip membership status + audit; space
create/edit/soft-deactivate + an explicit assertion that NO `DELETE /admin/spaces/{id}` route
exists (404/405, D-10); template clone + schema PATCH scoped to the target space; a `user`
Identity gets EXACTLY 403 on EVERY admin route (parametrized across all 8 routes, T-5-03); and
self-deactivation / last-active-superadmin / duplicate-invite all map to 409.

### Task 3 — extend `test_auth_dependency.py` + `test_auth_session.py` + `test_schema_shape.py` (commit 0976db4)

- **`test_auth_dependency.py`**: two new cases mirroring `test_invalid_token_401` —
  `RevokedIdTokenError` -> 401 with detail EXACTLY `"Session revoked"`; `UserDisabledError`
  -> 401 with detail EXACTLY `"Account disabled"`. The specific-message assertions make the
  subclass-ordering regression (Pitfall 2 / T-5-01) a test failure, not a silent downgrade.
- **`test_auth_session.py`**: `test_login_sync_invite_created_row` (selectable with
  `-k invite_created_row`) seeds an invite-shaped membership row (`provider_user_id` = the
  invited uid, `role="user"`) and asserts `sync_claims_from_membership` attaches the
  `{"role":"user","space_id":...}` claim (USER-02, no new production code).
- **`test_schema_shape.py`**: `audit_log` added to `ROOT_TABLES` (so `test_all_expected_tables_exist`
  covers it); a new `test_status_columns_exist_not_null` asserts
  `organization_memberships.status` and `organizations.status` exist NOT NULL; a new
  `test_audit_log_is_root_not_tenant_scoped` statically pins that `audit_log` is in
  `ROOT_TABLES` and ABSENT from `TENANT_TABLES` (so the `space_id`-FK / RLS loop skips it, D-07).

## Deviations from Plan

None — plan executed exactly as written. Every acceptance-criterion identifier was verified
present by static grep (see Self-Check). The plan's per-task `--collect-only` verifications
could not be RUN live (see below) but each file is authored to collect cleanly by construction
(importorskip guards confirmed present in every suite).

## Live Test Execution: DEFERRED

This dev machine has NO Python / pip / pytest / Docker (confirmed project constraint), so the
plan's `python -m pytest ... --collect-only -q` verification commands and the
`@pytest.mark.integration` live-DB cases were NOT executed here. Correctness was established by
construction against the contracts in 05-RESEARCH.md / 05-PATTERNS.md / 05-VALIDATION.md and by
mirroring the already-GREEN harness shape of the existing Phase 1/3/4 suites
(`test_auth_session.py`, `test_auth_dependency.py`, `test_cross_tenant_denial.py`,
`test_schema_shape.py`). Collection-clean-ness is guaranteed structurally: every new/extended
suite is guarded by module-level `pytest.importorskip` (ModuleNotFound -> skip, not a
collection error) and every live-DB case carries `@pytest.mark.integration` (skips without
Docker). Full collect + integration runs are deferred to CI / a Python-capable environment when
plans 02/03/04 land the production modules.

## Self-Check: PASSED

Files created (all present in the worktree):
- FOUND: backend/tests/test_admin_users.py
- FOUND: backend/tests/test_admin_routes.py
- FOUND: backend/tests/test_audit.py

Files modified (all present + carry the new assertions):
- FOUND: backend/tests/test_auth_dependency.py (RevokedIdTokenError/UserDisabledError + "Session revoked"/"Account disabled")
- FOUND: backend/tests/test_auth_session.py (-k invite_created_row, provider_user_id seed)
- FOUND: backend/tests/test_schema_shape.py ("audit_log" in ROOT_TABLES, status NOT NULL, audit_log NOT in TENANT_TABLES)

Commits (all on branch worktree-agent-a53e308c18cabae99):
- FOUND: d54761b test(05-01): RED faked-SDK invite/deactivate + audit-row suites
- FOUND: 2b6e7a5 test(05-01): RED admin-endpoint suite drives real admin_router
- FOUND: 0976db4 test(05-01): extend AUTH-04 + USER-02 + schema-shape suites

Acceptance-grep summary (all required identifiers present, no forbidden references):
- test_admin_users.py: create_invited_user / deactivate_user / reactivate_user / update_user /
  revoke_refresh_tokens present; ZERO `auth.disable_user` / `admin_users.disable_user` calls.
- test_admin_routes.py: pytestmark integration; dependency_overrides[get_current_identity];
  admin_router; get_superadmin_engine; 403 (user-role); 409 (guardrails); DELETE assertion.
- test_audit.py: audit.log + event_metadata; importorskip guards.
- test_auth_dependency.py: RevokedIdTokenError, UserDisabledError, "Session revoked", "Account disabled".
- test_auth_session.py: invite_created_row + provider_user_id.
- test_schema_shape.py: "audit_log" in ROOT_TABLES, status NOT NULL assertion, audit_log absent from TENANT_TABLES.
