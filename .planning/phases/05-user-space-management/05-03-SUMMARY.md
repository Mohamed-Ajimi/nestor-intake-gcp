---
phase: 05-user-space-management
plan: 03
subsystem: auth
tags: [admin-sdk, identity-platform, auth-04, user-lifecycle, check-revoked]
requires:
  - "app/auth/session.py (mockable `from firebase_admin import auth` seam — mirrored)"
  - "app/core/firebase.py (ADC process-singleton init — reused, not re-initialized)"
  - "app/auth/dependencies.py get_current_identity (the per-request boundary — extended)"
  - "app/api/auth_routes.py post_session (login-sync handler — extended)"
provides:
  - "create_invited_user / generate_set_password_link / deactivate_user / reactivate_user / resolve_existing_uid (admin_users.py)"
  - "AUTH-04 per-request check_revoked enforcement on both the hot path and /auth/session"
affects:
  - "app/auth/dependencies.py (check_revoked=True + 4-clause exception ordering)"
  - "app/api/auth_routes.py (check_revoked=True + 4-clause exception ordering at login-sync)"
tech-stack:
  added: []
  patterns:
    - "Mockable Admin-SDK seam: module-level `from firebase_admin import auth` so tests patch app.auth.admin_users.auth.*"
    - "Subclass-first exception ordering: RevokedIdTokenError + UserDisabledError caught BEFORE the generic InvalidIdTokenError"
key-files:
  created:
    - "backend/app/auth/admin_users.py"
  modified:
    - "backend/app/auth/dependencies.py"
    - "backend/app/api/auth_routes.py"
decisions:
  - "Stale 'no check_revoked (D-07)' docstrings rewritten to the honest AUTH-04/D-04 posture (the D-07 reference survives only as an explicit 'superseded — do not reintroduce' historical note, not a current claim)."
  - "reactivate_user does NOT re-issue claims (A3) — the membership row already holds role/space_id and login-sync is idempotent."
  - "resolve_existing_uid added as the re-invite reconcile helper so EmailAlreadyExistsError maps to the existing uid (caller responds 409, Pitfall 5)."
metrics:
  duration: "~25 min"
  completed: "2026-06-22"
  tasks: 2
  files: 3
---

# Phase 05 Plan 03: Admin-SDK Seam + AUTH-04 check_revoked Summary

One-liner: A mockable `app/auth/admin_users.py` Admin-SDK wrapper (invite / set-password-link / deactivate / reactivate / reconcile) plus the AUTH-04 `check_revoked=True` enforcement on both the per-request boundary and the `/auth/session` login-sync, with the load-bearing RevokedIdTokenError/UserDisabledError-before-InvalidIdTokenError exception ordering and honest docstrings.

## What Was Built

### Task 1 — `backend/app/auth/admin_users.py` (new, commit `ba37242`)
Module-level `import secrets` + `from firebase_admin import auth` (the exact mockable patch-target style of `session.py`, so tests patch `app.auth.admin_users.auth.<call>` and no live IdP is touched in CI). Functions:
- `create_invited_user(email, *, role, space_id) -> uid` — `auth.create_user(email=, password=secrets.token_urlsafe(32))` then `auth.set_custom_user_claims(uid, {"role": role, "space_id": space_id})`. The random password is never surfaced (D-02); `role` comes from the caller (D-01a) — the wrapper does not invent it (threat T-5-09).
- `generate_set_password_link(email) -> str` — `auth.generate_password_reset_link(email)` (same link serves invite + forgot, D-02).
- `deactivate_user(uid)` — `auth.update_user(uid, disabled=True)` then `auth.revoke_refresh_tokens(uid)`. There is NO `auth.disable_user()` call (all `disable_user` mentions are docstring/comment warnings against it).
- `reactivate_user(uid)` — `auth.update_user(uid, disabled=False)` only (claims unchanged, A3).
- `resolve_existing_uid(email) -> str` — `auth.get_user_by_email(email).uid`, the re-invite reconcile path for `auth.EmailAlreadyExistsError` (Pitfall 5).

### Task 2 — AUTH-04 `check_revoked` on the boundary + login-sync (commit `0a70643`)
- `backend/app/auth/dependencies.py` `get_current_identity`: `verify_id_token(cred.credentials, check_revoked=True)`; inserted `except auth.RevokedIdTokenError` → 401 "Session revoked" and `except auth.UserDisabledError` → 401 "Account disabled" AFTER `ExpiredIdTokenError` and BEFORE the generic `InvalidIdTokenError` → 401 "Invalid token". Module + function docstrings rewritten from "no check_revoked (D-07)" to the AUTH-04/D-04 posture with the accepted `get_user` round-trip cost noted.
- `backend/app/api/auth_routes.py` `post_session`: identical `check_revoked=True` + 4-clause ordering so a deactivated/revoked user cannot re-sync claims (A2 / threat T-5-08).

## Deviations from Plan

None — plan executed exactly as written.

## Authentication Gates

None.

## Verification

Static / by-construction (live pytest DEFERRED — this dev box has no Python/pytest runtime, a confirmed project constraint; the plan-01 RED suites `tests/test_admin_users.py` and the revoked/disabled cases in `tests/test_auth_dependency.py` live on the parallel plan-01 branch and are not present in this worktree):

- `admin_users.py` contains `from firebase_admin import auth`, `secrets.token_urlsafe`, `auth.update_user(`, `auth.revoke_refresh_tokens(`, `auth.get_user_by_email`; NO `auth.disable_user(` call (the three `disable_user` string matches are all docstring/comment warnings AGAINST it). `set_custom_user_claims` payload is exactly `{"role": role, "space_id": space_id}` with `role` from the caller.
- Source-order confirmed in BOTH files: `except auth.RevokedIdTokenError` and `except auth.UserDisabledError` precede `except auth.InvalidIdTokenError` (dependencies.py lines 81/85/89; auth_routes.py lines 87/89/91). Both files contain `verify_id_token(..., check_revoked=True)`.
- The dependencies.py docstring no longer asserts the file currently runs "no check_revoked"; the only surviving D-07 mention explicitly marks that posture as superseded.
- DEFERRED (GCP): live deactivation biting an in-flight token (manual verification per 05-VALIDATION.md).

## Known Stubs

None. The four wrapper functions are fully composed against the verified Admin-SDK call shapes; no placeholder/empty returns. The wrapper is consumed by the admin endpoints in a sibling plan (05-04/05-05) — its presence here is the seam those endpoints import, not a stub.

## Self-Check: PASSED

- FOUND: backend/app/auth/admin_users.py
- FOUND: backend/app/auth/dependencies.py (modified)
- FOUND: backend/app/api/auth_routes.py (modified)
- FOUND commit ba37242 (Task 1)
- FOUND commit 0a70643 (Task 2)
