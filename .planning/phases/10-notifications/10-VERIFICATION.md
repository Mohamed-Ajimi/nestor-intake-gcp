---
phase: 10-notifications
verified: 2026-07-14T12:00:00Z
status: human_needed
score: 7/7 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 5/7
  gaps_closed:
    - "CR-01 — handleSendMail now reads res.data.success; Resend failure keeps picker open and toasts Dutch error (commit 2b036b8)"
    - "WR-01 — _run_intake_send refuses (returns success:false, no stamp) when APP_BASE_URL unset; _base.html.j2 guards logo with {% if app_base_url %} (commit 1131777)"
    - "WR-02 — list_members filters email IS NOT NULL; SpaceMember.email aligned to string | null; picker label hardened (commits 1131777, 67be932)"
    - "WR-03 — ResearchArtifactRepository added to intake_routes.py import block (commit 1131777)"
    - "WR-04 — send_invite_mail wraps link-gen + render + send in try/except, returns MailResult(success=False) on failure; both frontend consumers (InviteUserDialog, admin.users) check res.data.success (commit bbb8535)"
  gaps_remaining: []
  regressions: []
human_verification:
  - test: "RecipientPicker visual/functional verification (Plan 10-04 Task 4)"
    expected: "Running the frontend locally (npm, localhost:8081) against the deployed backend rev: the RecipientPicker opens on clicking validation/reminder/results CTA with the space's active members preselected; the confirm CTA is disabled with a Dutch 'Nodig eerst iemand uit' hint for a space with zero active members; a send shows a success or clear failure toast (failure now keeps picker open after CR-01 fix). Both invite-mail surfaces (InviteUserDialog success state + member-list row) show a working 'Verstuur uitnodigingsmail' / 'Herstuur uitnodiging' action alongside the copy-link fallback."
    why_human: "Visual and interactive verification of a React Dialog component against a deployed backend — cannot be verified by static grep. Requires a running frontend and a backend with active test memberships seeded."
  - test: "Live invite click-through: mailed action link -> /auth/action -> set password -> login (Plan 10-05 Task 2)"
    expected: "The mailed Firebase invite link lands on the branded in-app /auth/action route (not Firebase's hosted page), the 'Kies je wachtwoord' form renders in Dutch, setting a password navigates to /auth/login and the user can log in with the new password. An expired/reused link shows the friendly 'Deze link is verlopen of ongeldig' message."
    why_human: "Requires a live Identity Platform (FIREBASE_PROJECT_ID), a deployed backend with APP_BASE_URL + RESEND_API_KEY set (runbook Steps 10.1-10.4), and an actual mailed action link click-through — none of which can run in CI or be verified by static analysis."
---

# Phase 10: Notifications Verification Report

**Phase Goal:** Transactional email becomes notification-only — it carries no access token and links route to authenticated pages — covering the full set of lifecycle events.
**Verified:** 2026-07-14 (re-verification after CR-01 + WR-01..WR-04 fixes)
**Status:** human_needed
**Re-verification:** Yes — after gap closure (previous: gaps_found 5/7; now: 7/7, human items outstanding)

## Goal Achievement

### Observable Truths

| #   | Truth | Status | Evidence |
| --- | ----- | ------ | -------- |
| 1   | Every transactional email carries no access token; links point to authenticated app routes ("log in to view") | VERIFIED | Backend: templates scrubbed, CTA URLs are `{app_base_url}/intake/{id}`, render tests pin invariant, APP_BASE_URL refusal guard in place (WR-01). Frontend: CR-01 closed — `handleSendMail` now reads `res.data.success` and keeps picker open on failure (commit 2b036b8, confirmed at lines 564-572 of admin.pulse.intakes.$id.tsx). |
| 2   | Email is sent for invitation, validation-ready, results-ready, and reminder events | VERIFIED | `POST /intakes/{id}/mail/validation`, `/mail/reminder`, `/mail/results`, `POST /admin/users/{id}/invite-mail` all exist. `admin_validated` fires automatically inside `submit_intake` on the reviewed→validated_by_client edge. |

**Score:** 7/7 truths verified (all automated checks pass; 2 human-UAT items outstanding)

### Deferred Items

None.

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `backend/app/mail/resend.py` | Resend transport; RESEND_API_KEY at call time | VERIFIED | `send()` reads `os.environ["RESEND_API_KEY"]` inside function body; sync httpx.post; FROM = "Nestor Pulse <nestor@agenic.be>". |
| `backend/app/mail/render.py` | Jinja2 Environment + 4 render functions | VERIFIED | `Environment(FileSystemLoader, autoescape=select_autoescape(["html","j2"]))` confirmed; 4 `render_*` functions exported. |
| `backend/app/mail/templates/_base.html.j2` | Shared layout; logo guarded by `{% if app_base_url %}` (WR-01) | VERIFIED | Line 25: `{% if app_base_url %}<img src="{{ app_base_url }}/agenic-logo.png" ... />{% endif %}`. No unconditional `None/agenic-logo.png` render. |
| `backend/app/mail/templates/validation.html.j2` | No client_validation_token; CTA is intake-id route | VERIFIED | CTA: `{{ cta_url }}`; comment "NEVER a bearer validation token"; no forbidden substrings. |
| `backend/app/mail/templates/results.html.j2` | No client_results_token; CTA is intake-id/results route | VERIFIED | CTA: `{{ cta_url }}`; comment "NEVER a bearer results token". |
| `backend/app/mail/templates/admin_validated.html.j2` | Admin route CTA; no token | VERIFIED | CTA: `{{ cta_url }}`; no token. |
| `backend/app/mail/templates/invite.html.j2` | Only template carrying an action link | VERIFIED | `cta_url` is the Firebase action link; the ONLY link-carrying template (D-09). |
| `backend/app/core/config.py` | `nestor_admin_email` + `app_base_url`; no `resend_api_key` | VERIFIED | Both fields present with env name comments; no `resend_api_key` field in Settings. |
| `backend/pyproject.toml` | `jinja2>=3.1,<4` in runtime deps; httpx promoted | VERIFIED | Both in `[project.dependencies]`. |
| `backend/app/api/intake_routes.py` | GET /{id}/members + 3 send endpoints + admin_validated auto-fire + ResearchArtifactRepository import (WR-03) | VERIFIED | All endpoints present; WR-03: `ResearchArtifactRepository` now appears in the import block at line 66. WR-01: APP_BASE_URL refusal guard at lines 761-765. WR-02: `list_members` filters `OrganizationMembership.email.is_not(None)` at lines 659-662. |
| `backend/app/api/admin_routes.py` | invite-mail endpoint with try/except failure contract (WR-04) | VERIFIED | Lines 318-325: full try/except wrapping link-gen + render + send; returns `MailResult(success=False)` on any exception; `_log.warning` on failure; audit written only on success path. |
| `backend/tests/conftest.py` | `fake_resend` fixture | VERIFIED | Fixture present; no network calls. |
| `backend/tests/test_mail_render.py` | 7 render tests including NOTIF-01 invariants | VERIFIED | 7 tests confirmed by review. |
| `backend/tests/test_mail_endpoints.py` | Contract tests: members_read, timestamp_on_success_only, no_free_address, deactivated exclusion, invite tests | VERIFIED | File exists; all named test IDs present. |
| `backend/tests/test_mail_denial.py` | Cross-space 404 + zero send assertions | VERIFIED | File exists; pins exactly-404 + zero sends on cross-space access. |
| `backend/tests/test_intake_validate_mail.py` | admin_validated auto-fire + client-not-blocked | VERIFIED | File exists; `admin_validated_fires_on_validate` and `validate_not_blocked_by_mail_failure` confirmed. |
| `frontend/src/lib/api/intakes.ts` | `listSpaceMembers` + `sendIntakeMail`; `SpaceMember.email: string \| null` (WR-02) | VERIFIED | Both functions present; `SpaceMember.email` is `string \| null` at line 100 (WR-02 type alignment). |
| `frontend/src/lib/api/admin.ts` | `sendInviteMail` seam function | VERIFIED | `sendInviteMail(membershipId)` posts to `/admin/users/${membershipId}/invite-mail`. |
| `frontend/src/components/intake/RecipientPicker.tsx` | Member picker dialog: preselect, empty-guard, no free-text | VERIFIED | Dialog present; loads via `listSpaceMembers`; preselects all; disables confirm with "Nodig eerst iemand uit" when empty; no free-text input. |
| `frontend/src/routes/admin.pulse.intakes.$id.tsx` | `handleSendMail` checks `res.data.success`; keeps picker open on failure (CR-01) | VERIFIED | Lines 564-572: `if (!res.data.success) { toast.error("Versturen mislukt..."); return; }` — returns before `setMailPickerType(null)`, keeping picker open. `toast.success` + `setMailPickerType(null)` + `void load()` only on full success. |
| `frontend/src/components/admin/InviteUserDialog.tsx` | `res.data.success` check after transport check (WR-04) | VERIFIED | Lines 133-143: transport check (`!res.success`) then body check (`!res.data.success`) with Dutch error toast; `setMailSent(true)` only on success. |
| `frontend/src/routes/admin.users.tsx` | `handleResendInvite` checks `res.data.success` (WR-04) | VERIFIED | Lines 124-134: same two-level check pattern; Dutch error toast on `!res.data.success`; `toast.success` only on success. |
| `frontend/src/routes/auth.action.tsx` | Branded /auth/action oobCode handler route | VERIFIED | `createFileRoute("/auth/action")`; `verifyPasswordResetCode` + `confirmPasswordReset` from `firebase/auth`; 4-state machine; Dutch copy; navigates to `/auth/login` on success. |
| `frontend/src/routeTree.gen.ts` | /auth/action registered in route tree | VERIFIED | `/auth/action` registered (12 occurrences confirmed by prior review). |
| `frontend/public/agenic-logo.png` | Logo asset for mail templates (D-15) | VERIFIED | File exists (417x104 RGBA PNG). |
| `infra/main.tf` | resend_api_key secret + IAM + secret_key_ref env; NESTOR_ADMIN_EMAIL + APP_BASE_URL | VERIFIED | All Terraform resources confirmed by prior review. |
| `infra/variables.tf` | resend_api_key_secret_id, resend_api_key (sensitive), nestor_admin_email, app_base_url | VERIFIED | All 4 variables present. |
| `infra/DEPLOY-RUNBOOK.md` | Phase-10 section with all env vars; jinja2 rebuild; 5-mail UAT gate | VERIFIED | Phase-10 section present with Steps 10.1-10.5. |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | -- | --- | ------ | ------- |
| `backend/app/mail/render.py` | `backend/app/mail/templates/*.html.j2` | `FileSystemLoader` | VERIFIED | `FileSystemLoader(str(_TEMPLATES_DIR))` where `_TEMPLATES_DIR = Path(__file__).parent / "templates"` |
| `backend/app/mail/resend.py` | `os.environ["RESEND_API_KEY"]` | read at call time inside `send()` | VERIFIED | `api_key = os.environ["RESEND_API_KEY"]` on line 58 inside function body. |
| `backend/app/api/intake_routes.py` send endpoints | `app.mail.resend.send` | render then send; refuse on unset APP_BASE_URL; timestamp on success only | VERIFIED | WR-01 guard at lines 761-765 returns `{"success": False}` when `app_base_url` is falsy. D-16 send-then-stamp confirmed. |
| `backend/app/api/intake_routes.py submit_intake` | `_send_admin_validated` | `if new_status == "validated_by_client"` wrapped in try/except | VERIFIED | Confirmed by prior review. |
| `backend/app/api/admin_routes.py invite-mail` | `admin_users.generate_set_password_link` + `mail_resend.send` | try/except; MailResult(success=False) on failure | VERIFIED | WR-04: full try/except wrapping at lines 318-325; audit only on success. |
| `backend/app/auth/admin_users.py generate_set_password_link` | `/auth/action` route | `ActionCodeSettings(url=f"{app_base_url}/auth/action")` | VERIFIED | `handle_code_in_app=True` confirmed. |
| `frontend/src/routes/admin.pulse.intakes.$id.tsx handleSendMail` | `sendIntakeMail` via RecipientPicker | picker → seam call → `res.data.success` check → toast | VERIFIED | CR-01 closed: body-level check at lines 569-572 keeps picker open on false, toasts success only when true. |
| `frontend/src/components/admin/InviteUserDialog.tsx` | `sendInviteMail` | success-state button; both transport + body check | VERIFIED | WR-04: `res.data.success` checked at line 140. |
| `frontend/src/routes/admin.users.tsx handleResendInvite` | `sendInviteMail` | resend button; both transport + body check | VERIFIED | WR-04: `res.data.success` checked at line 130. |
| `frontend/src/routes/auth.action.tsx` | `verifyPasswordResetCode` + `confirmPasswordReset` | Firebase SDK oobCode consume | VERIFIED | Both imported and called in correct sequence. |
| `frontend/src/routes/auth.action.tsx` | `/auth/login` | `navigate({ to: "/auth/login" })` on success | VERIFIED | Confirmed by prior review. |

### Data-Flow Trace (Level 4)

Not applicable for this phase. The phase produces backend send endpoints and frontend dialog components. The critical failure (CR-01) was a contract mismatch now resolved. No hollow data-flow paths identified.

### Behavioral Spot-Checks

Step 7b skipped per project convention: no local Python/Docker on the dev machine; pytest cannot run locally. Tests are authored-by-construction; Cloud Build is the gate of record (per MEMORY and STATE.md). TypeScript: `npx tsc --noEmit` reported as clean by the fixer in Plan 10-04 and 10-05 summaries.

### Probe Execution

No `probe-*.sh` files declared or found for Phase 10.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ----------- | ----------- | ------ | -------- |
| NOTIF-01 | 10-01, 10-03, 10-04 | Transactional email is notification-only — carries no access token; links point to authenticated routes | SATISFIED | Backend: templates clean, render tests pin invariant, D-16 send-then-stamp. Frontend: CR-01 closed — `res.data.success` now checked; Resend failure keeps picker open. WR-01: APP_BASE_URL refusal prevents dead-link mails. |
| NOTIF-02 | 10-01, 10-02, 10-03, 10-04, 10-05 | Email sent for invitation, validation-ready, results-ready, and reminders | SATISFIED | invite, validation, reminder, results, admin_validated all implemented with endpoints, frontend wiring, and test coverage. WR-04: invite-mail now matches intake send failure contract. |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| None | — | — | — | All CR/WR blockers and warnings resolved. Info-level items (IN-01..IN-05) remain out-of-scope and do not affect phase goal. |

No `TBD`, `FIXME`, or `XXX` debt markers found in phase-modified files (verified by code review covering 29 files, confirmed unchanged).

### Human Verification Required

The following items require human verification against the deployed backend. They are explicitly deferred from blocking checkpoints (Plans 10-04 Task 4 and 10-05 Task 2) per the executor convention noted in the phase context. No automated fix can substitute for these.

#### 1. RecipientPicker visual/functional verification

**Test:** Run the frontend locally (npm, localhost:8081 per MEMORY) against the deployed backend rev (after runbook Steps 10.1-10.4 complete). Navigate to an intake at the awaiting-validation phase. Click "Verstuur validatie-link".
**Expected:**
- The RecipientPicker dialog opens with the space's active members as preselected checkboxes (label = email since name=null by backend contract).
- For a space with zero active members, the confirm CTA is disabled with a Dutch "Nodig eerst iemand uit" hint visible.
- Confirming a send (with Resend live) shows "E-mail verstuurd." toast; a simulated Resend failure (backend RESEND_API_KEY temporarily unset) shows the Dutch failure toast and keeps the picker open for retry (CR-01 fix verified in code; visual confirmation here).
- The InviteUserDialog success state shows "Verstuur uitnodigingsmail" alongside "Kopieer link".
- The admin.users.tsx member-list rows show "Herstuur uitnodiging" for active members with email.
**Why human:** Visual confirmation of a React Dialog component and interactive state against a live backend; cannot be verified by static grep.

#### 2. Live invite click-through: mailed action link -> /auth/action -> set password -> login

**Test:** Against the deployed backend rev with APP_BASE_URL + RESEND_API_KEY set per runbook, invite a test user and send the invitation mail via POST /admin/users/{id}/invite-mail. Click the mailed Firebase action link.
**Expected:**
- The link lands on `/auth/action` (NOT Firebase's hosted page) with the branded Dutch "Kies je wachtwoord" form.
- Setting a password navigates to `/auth/login` with a success toast; the user can log in with the new password.
- An expired or reused link shows "Deze link is verlopen of ongeldig — vraag een nieuwe link aan." and a "Naar inloggen" link; no crash.
**Why human:** Requires a live Identity Platform (FIREBASE_PROJECT_ID), a deployed Cloud Run rev with all Phase-10 env vars set (runbook Steps 10.1-10.4), and an actual mailed action link click-through. Cannot run in CI or be verified by static analysis.

### Gaps Summary

No automated gaps remain. All 5 reviewer findings (CR-01, WR-01..WR-04) are confirmed closed in code:

- **CR-01** (BLOCKER): `handleSendMail` now reads `res.data.success`; false body on HTTP 200 triggers Dutch error toast and returns before `setMailPickerType(null)`, keeping the picker open for retry. (commit 2b036b8, lines 564-572 of admin.pulse.intakes.$id.tsx)
- **WR-01**: `_run_intake_send` returns `{"success": False}` immediately when `settings.app_base_url` is falsy; `_base.html.j2` wraps logo `<img>` in `{% if app_base_url %}`. (commit 1131777)
- **WR-02**: `list_members` adds `.where(OrganizationMembership.email.is_not(None))`; `SpaceMember.email` typed `string | null` in the frontend seam. (commits 1131777, 67be932)
- **WR-03**: `ResearchArtifactRepository` added to the `from app.db.repository import (...)` block in intake_routes.py. (commit 1131777)
- **WR-04**: `send_invite_mail` wraps link-gen + render + send in `try/except`; returns `MailResult(success=False)` on any exception; both `InviteUserDialog` and `admin.users.tsx handleResendInvite` check `res.data.success` with Dutch failure toast. (commit bbb8535)

Phase is complete pending the 2 human-UAT items above (visual dialog verification + live invite click-through). Both require a deployed backend with Phase-10 env vars active.

---

_Verified: 2026-07-14_
_Verifier: Claude (gsd-verifier)_
