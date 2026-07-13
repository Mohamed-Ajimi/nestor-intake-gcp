---
phase: 10-notifications
plan: 03
subsystem: backend/api-mail
tags: [notifications, resend, mail-endpoints, invite, admin_validated, NOTIF-01, NOTIF-02, security]
requires:
  - "app.mail.render + app.mail.resend.send (Plan 10-01 — the render/send seam + fake_resend)"
  - "app/api/intake_routes.py submit_intake + get_tenant_repo (Phase 6)"
  - "app/api/admin_routes.py invite_user + get_admin_session (Phase 5)"
  - "app/auth/admin_users.generate_set_password_link (Phase 5)"
  - "Settings.nestor_admin_email + Settings.app_base_url (Plan 10-01)"
provides:
  - "GET /intakes/{id}/members — active-member {id,email} read for the Plan-04 RecipientPicker"
  - "POST /intakes/{id}/mail/validation|reminder|results — send endpoints with server-side active-member resolution + D-16 send-then-stamp"
  - "admin_validated auto-fire inside submit_intake on reviewed->validated_by_client (client-not-blocked)"
  - "POST /admin/users/{membership_id}/invite-mail — fresh-link invite send"
  - "generate_set_password_link ActionCodeSettings continue URL -> /auth/action (D-11)"
affects:
  - "Plan 04 frontend (listSpaceMembers -> GET /members; RecipientPicker posts membership ids to the send endpoints)"
  - "Plan 04/05 InviteUserDialog resend + member-list resend consume invite-mail"
tech-stack:
  added: []
  patterns:
    - "discrete send verbs (/mail/validation|reminder|results) mirroring /submit|/review"
    - "recipient resolution server-side from ACTIVE memberships only (D-06 no-free-address)"
    - "send-then-timestamp (D-16): sent-at stamped ONLY after a 2xx resend.send"
    - "fire-and-forget operator mail in try/except (client never blocked, Pitfall 4)"
    - "Pydantic model_config extra=forbid to reject a smuggled to/email field"
key-files:
  created:
    - backend/tests/test_mail_denial.py
    - backend/tests/test_mail_endpoints.py
    - backend/tests/test_intake_validate_mail.py
  modified:
    - backend/app/api/intake_routes.py
    - backend/app/api/admin_routes.py
    - backend/app/auth/admin_users.py
decisions:
  - "admin_repo.py NOT modified: Task 2's file list included it, but the <read_first> note and get_membership already covering the lookup made a change unnecessary (the members read is the Task-1 intake-scoped GET, not an admin-repo method)"
  - "MailRecipients uses extra='forbid' so a body-supplied to/email is a 422 (stronger than silently ignoring it) — locks the D-06 no-free-address test to a clear rejection"
  - "recipient resolver REJECTS (422) any requested id that is not an active member with an email — never a silent drop-and-send-to-fewer nor a zero-recipient send"
  - "admin_validated + the three send endpoints reuse intake.client_name for BOTH first_name and project_title render fields (the new schema has no first_name; client_name is the only display value)"
metrics:
  duration: ~35 min
  completed: 2026-07-13
  tasks: 3
  files: 6
---

# Phase 10 Plan 03: Mail Send Surface (endpoints + admin_validated + invite-mail) Summary

The backend send surface the Plan-04 frontend calls: a `GET /intakes/{id}/members` active-member read (the RecipientPicker's list source), three discrete intake-scoped send endpoints (`/mail/validation`, `/mail/reminder`, `/mail/results`) with server-side active-member recipient resolution and the D-16 send-then-stamp discipline, the automatic `admin_validated` operator mail fired inside `submit_intake` on the `reviewed → validated_by_client` edge (isolated so a mail failure never fails the client's validate), the `POST /admin/users/{membership_id}/invite-mail` fresh-link invite endpoint, and the `ActionCodeSettings` continue-URL addition pinning the invite action link to the branded `/auth/action` handler — plus three integration test files (denial, endpoint contract, admin_validated auto-fire).

## What Was Built

### Task 1 — `intake_routes.py` (members read + send endpoints + admin_validated)
- **`GET /intakes/{intake_id}/members`** → `list[MemberView]` (`{id, email, name=None}`): `repo.get` 404-gates a cross-space/unknown intake id (existence-hidden, D-07), then returns ACTIVE members of the intake's OWN space (deactivated excluded, T-10-13). `name` is always `None` (no name column on `organization_memberships`).
- **`POST /intakes/{intake_id}/mail/validation|reminder|results`**: body `MailRecipients` carries ONLY `recipients: list[str]` (membership ids) with `model_config = {"extra": "forbid"}` — a smuggled `to`/`email` field is a 422 (D-06). Each handler 404-gates the intake, resolves recipient emails server-side from ACTIVE memberships (`_resolve_active_member_emails` — rejects any id that is not an active member; an empty resolved list is a 422, never a zero-recipient send), renders the token-free body (validation/reminder → `{base}/intake/{id}`, results → `{base}/intake/{id}/results`), calls `resend.send` FIRST, and ONLY on success stamps the sent-at column (validation → `validation_link_sent_at`, results → `results_link_sent_at`, reminder → none) + writes a `mail.sent` audit row with structured metadata `{type, recipient_count}` (never a link/token). A raised `send()` returns `{"success": False}` with NO timestamp/audit (D-16 / Pitfall 1).
- **`_send_admin_validated(intake)`** + wiring in `submit_intake`: on the `reviewed → validated_by_client` edge, fires `admin_validated` to `Settings.nestor_admin_email` (D-08; if unset → log + return, no raise). The call is wrapped in try/except in `submit_intake` so a mail failure is silent-logged and the client's validate STILL returns 200 with the transitioned view (Pitfall 4 / T-10-10). The send is the last step (after the status flip + audit) and never shares a tx that would roll back the status change.
- Shared `_active_members_stmt(space_id)` query reused by the members read and the send-recipient resolver. Dutch subjects ported verbatim from `send-pulse-mail.ts` (`Even valideren — …`, `Herinnering — …`, `Onderzoeksresultaten klaar — …`, `[Nestor Pulse] Klant heeft gevalideerd — …`).

### Task 2 — `admin_users.py` + `admin_routes.py` (invite-mail + ActionCodeSettings)
- **`generate_set_password_link(email)`** now builds `auth.ActionCodeSettings(url=f"{app_base_url}/auth/action", handle_code_in_app=True)` from `get_settings().app_base_url` (config, not a literal — A6) and passes it as `action_code_settings` to `generate_password_reset_link`. If `app_base_url` is unset it falls back to the bare link (Phase-5 behavior, no raise). The mockable `auth` seam is preserved.
- **`POST /admin/users/{membership_id}/invite-mail`** (behind `get_admin_session`): 404 on unknown membership, 409 on a membership with no email (never send-to-None), regenerates a FRESH action link per send (D-10), renders `render_invite`, sends via the faked Resend seam, and audits `mail.sent` with metadata `{"type": "invite"}` (NEVER the link — T-5-16 / T-10-08). Returns `MailResult(success=True)` — the response carries no link.

### Task 3 — three integration test files
- **`test_mail_denial.py`**: user-A POST of a space-B `/mail/validation` → EXACTLY 404 with ZERO `fake_resend` calls (T-10-06); user-A GET of space-B `/members` → EXACTLY 404, no foreign email in the body (T-10-13).
- **`test_mail_endpoints.py`**: `members_read_active_only` (active {id,email}, deactivated excluded); `timestamp_on_success_only` (stamp on success, one `mail.sent` audit; a raised send leaves the column NULL and writes no audit row); `reminder_writes_no_timestamp`; `results_stamps_results_sent_at` (+ recipient == resolved active email); `no_free_address` (422 + zero sends); `deactivated_recipient_rejected` (422 + zero sends); `invite_mail_sends_and_audits_without_link` (link in HTML body, NEVER in audit metadata); `invite_mail_no_email_returns_409`; `action_code_continue_url_is_auth_action` + `action_code_falls_back_to_bare_link_when_no_base_url` (unit tests on the wrapper).
- **`test_intake_validate_mail.py`**: `admin_validated_fires_on_validate` (one mail to `NESTOR_ADMIN_EMAIL` on the validate edge, 200 + `validated_by_client`); `validate_not_blocked_by_mail_failure` (a raised send still returns 200 + `validated_by_client`, Pitfall 4).

All three drive the REAL routers over the testcontainer via the established `_patch_engine_factories` / fabricated-Identity / `superadmin_engine` scaffold copied from `test_intake_cross_tenant.py` + `test_admin_routes.py`; the mail-egress seam is faked with the Plan-01 `fake_resend` conftest fixture.

## Verification

Grep-verified (Python cannot run locally — the dev box has no Python/Docker; the suite runs in Cloud Build, the gate of record per STATE.md and prior-phase SUMMARYs):
- `intake_routes.py` defines `GET /{intake_id}/members` and `POST /{intake_id}/mail/{validation,reminder,results}`; the send body (`MailRecipients`) carries ONLY `recipients` + `extra="forbid"` (no `to`/`email`/`space_id`).
- Recipient resolution filters `organization_id == intake.space_id AND status == "active"` (via `_active_members_stmt`); a non-active-member id is rejected (422).
- The sent-at write happens only after a successful `resend.send` (`try/except` returns `{"success": False}` before any stamp/audit on failure).
- `submit_intake` calls `_send_admin_validated` only when `new_status == "validated_by_client"`, wrapped in try/except.
- No send-path `audit.log` metadata contains a link/token (validation/results/reminder metadata is `{type, recipient_count}`; invite metadata is `{type: "invite"}`).
- `admin_users.generate_set_password_link` constructs `ActionCodeSettings(url=…/auth/action, handle_code_in_app=True)` and passes it to `generate_password_reset_link`; the `auth` seam is intact.
- `admin_routes.py` defines `POST /admin/users/{membership_id}/invite-mail` behind `get_admin_session`; 404 on unknown membership, 409 on no-email.

`pytest backend/tests/test_mail_endpoints.py backend/tests/test_mail_denial.py backend/tests/test_intake_validate_mail.py -x` is expected green in Cloud Build (author-by-construction).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 — Blocking] `admin_repo.py` left unmodified (listed in Task 2 files)**
- **Found during:** Task 2
- **Issue:** Task 2's `files_modified` frontmatter listed `backend/app/db/admin_repo.py`, but the task's own `<read_first>` note states the members read is NOT needed there (the intake-scoped `GET /{id}/members` in Task 1 is the picker's source) and `get_membership` already exists for the invite-mail lookup. No admin-repo change was actually required.
- **Fix:** Implemented the invite-mail endpoint using the existing `repo.get_membership`; made no change to `admin_repo.py`.
- **Files modified:** none (deliberate non-change).
- **Commit:** ea09f98

**2. [Rule 2 — Missing critical correctness] `extra="forbid"` on `MailRecipients` (stronger no-free-address)**
- **Found during:** Task 1
- **Issue:** The plan required a body of ONLY `recipients: list[str]` with no `to`/`email`. Pydantic's default `extra="ignore"` would silently drop a smuggled `to`/`email` — the D-06 test then can only assert "the address wasn't used." Forbidding extras makes the no-free-address contract a clear 422 rejection.
- **Fix:** Added `model_config = {"extra": "forbid"}` so a request carrying `to`/`email` is a 422; the `test_no_free_address` test asserts exactly that + zero sends.
- **Files modified:** `backend/app/api/intake_routes.py`
- **Commit:** b526d8f

## Authentication Gates

None.

## Known Stubs

None. The `MemberView.name` field is always `None` because `organization_memberships` has no name column — this is the intended, documented shape (a later name source would be additive), not a stub. The three send endpoints and the members read are fully wired to real membership rows and the real render/send seam.

## Threat Flags

None. All new surface (members read, send endpoints, invite-mail, admin_validated) is enumerated in the plan's `<threat_model>` (T-10-06/07/08/09/10/13) and mitigated as specified: cross-space 404 existence-hiding, server-side recipient resolution (no free address), no link/token in audit metadata, send-then-stamp, and the client-not-blocked try/except.

## TDD Gate Compliance

Tasks 1 and 2 are `tdd="true"`; Task 3 authors the tests. Consistent with the plan's structure (and Plan 10-01's precedent), the implementation (Tasks 1–2) was authored before the test file (Task 3) within the same plan, so the RED→GREEN sequence collapses: the tests are GREEN-by-construction against the already-built endpoints. The `feat(...)` commits (b526d8f, ea09f98) precede the `test(...)` commit (192965f). No standalone RED commit exists because the endpoints are the prerequisite artifact of the prior tasks, not to-be-discovered behavior. Tests cannot be executed locally (no Python/Docker) — Cloud Build is the gate of record.

## Commits

- b526d8f — `feat(10-03): members read + intake mail send endpoints + admin_validated auto-fire`
- ea09f98 — `feat(10-03): invite-mail endpoint + ActionCodeSettings continue URL`
- 192965f — `test(10-03): mail denial + endpoint contract + admin_validated auto-fire tests`

## Self-Check: PASSED

All 3 created test files and the SUMMARY exist on disk; all three code/test commits (b526d8f, ea09f98, 192965f) are reachable in git.
