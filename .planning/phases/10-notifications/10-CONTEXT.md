# Phase 10: Notifications - Context

**Gathered:** 2026-07-13
**Status:** Ready for planning

<domain>
## Phase Boundary

Transactional email becomes **notification-only** — no data-access token in any mail; links point
to authenticated app routes ("log in to view") — covering the full lifecycle event set:
**invitation, validation-ready, results-ready, reminders** (NOTIF-01, NOTIF-02), plus the legacy
`admin_validated` operator notification. Depends on Phase 5 (invite flow + memberships exist).

Success criteria (ROADMAP § Phase 10):
1. Every transactional email carries no access token; links point to authenticated app routes.
2. Email is sent for invitation, validation-ready, results-ready, and reminder events.

**In scope:**
- Backend mail module + endpoints replacing the legacy `send-pulse-mail` edge function (Resend,
  key via Secret Manager).
- Un-stubbing the three "komt in Phase 10" CTA handlers in
  `frontend/src/routes/admin.pulse.intakes.$id.tsx` (validation mail, reminder, results mail)
  with a recipient picker.
- "Send/resend invitation mail" action (dialog + member list) for the Phase 5 invite flow.
- Custom in-app password-set handler route consuming the Firebase oobCode (serves both invite
  set-password and forgot-password).
- `admin_validated` automatic operator notification on client validation.
- Jinja2 ports of the legacy Dutch HTML templates; logo as frontend static asset (Phase 9 D-07a
  handoff closed here).
- `validation_link_sent_at` / `results_link_sent_at` semantics on the new send paths.

**Out of scope:**
- Scheduled/automated reminders (Cloud Scheduler) — manual button only in v1.
- Email i18n — templates stay Dutch; externalization rides Phase 11.
- Forgot-password entry-point UI (the handler route supports the flow; a "forgot password?" link
  on the login page can land later without rework).
- `send-sales-mail` / `sales-friday-reminder` — sales track, not part of the Pulse intake flow
  re-platform requirements.
- Marketing email, digests, in-app notification center — new capabilities, not in NOTIF-01/02.

</domain>

<decisions>
## Implementation Decisions

### Events & Triggers
- **D-01 (manual CTA sends):** Validation-ready, results-ready, and reminder mails are sent by
  explicit admin action — the already-wired NextStepBanner CTAs (currently stubbed with "komt in
  Phase 10" toasts). No automatic sends on status transitions. Legacy parity; no surprise emails.
- **D-02 (reminders manual-only):** The reminder is the existing "send reminder" button
  (legacy `validation_reminder`). No Cloud Scheduler, no auto-reminder infra in v1.
- **D-03 (keep `admin_validated`, automatic):** When a client validates their questions, the
  backend automatically mails the operator — this is the one auto-triggered mail (the client's
  action fires it; there is no admin CTA possible). It's how the operator knows to generate the
  context pack.
- **D-04 (invitation mail is a separate action):** `POST /admin/users` (invite) keeps its current
  behavior — create the IdP user, return the action link. A **distinct** "send invitation mail"
  action/endpoint sends (and re-sends) the email. The copy-link fallback in the invite response
  stays.

### Recipients (login-only model)
- **D-05 (picker at send time):** For client-facing mails the admin picks recipient(s) when
  clicking the CTA — a member picker listing the intake's space **active memberships** (the new
  schema has no `primary_contact_email`; `organization_memberships.email` is the source).
- **D-06 (members only, no free address):** No free-text override address (legacy
  `override_email` dropped). The mail says "log in to view" — a non-member cannot log in, so a
  free address is a dead end and would undermine NOTIF-01.
- **D-07 (preselect all; block if empty):** All active members pre-checked (one click = legacy
  behavior). If the space has zero active members, the send CTA is disabled with a hint to invite
  someone first.
- **D-08 (configurable admin address):** `admin_validated` goes to a single ops address from
  config/env (Settings, like legacy `NESTOR_ADMIN_EMAIL` but not hardcoded) — not to all
  superadmins.

### Invitation Email & NOTIF-01 Interpretation
- **D-09 (action link allowed — documented interpretation):** NOTIF-01's target is the legacy
  **never-expiring data bearer links** (`client_validation_token` etc.). The invite mail MAY carry
  the one-time, short-lived Firebase set-password action link — it is an auth-bootstrap
  credential, not a data-access token; without it a new user cannot log in at all. All other
  mails carry zero tokens of any kind.
- **D-10 (send/resend surfaces):** The "send invitation mail" action lives in BOTH the
  InviteUserDialog success state (next to copy-link) AND as a per-member resend action in the
  space-management member list. One endpoint serves both; each send regenerates a fresh action
  link.
- **D-11 (custom in-app handler route):** The action link lands on a branded frontend route that
  consumes the oobCode (`confirmPasswordReset`) so the whole first-run flow stays in the app's
  look and language — not Firebase's hosted page.
- **D-12 (one handler, both flows):** That route serves invite set-password AND forgot-password —
  mechanically the same Firebase operation (Phase 5 D-02 anticipated this). Wording stays neutral
  ("Kies je wachtwoord"). The forgot-password entry point UI is out of scope but lands later
  without rework.

### Provider, Templates & Delivery
- **D-13 (keep Resend):** Same provider as legacy — the `agenic.be` sender domain is already
  verified, and it's one HTTPS POST. `RESEND_API_KEY` moves server-side into Secret Manager,
  following the Phase 7 secrets pattern. Sender stays `Nestor Pulse <nestor@agenic.be>`.
- **D-14 (port legacy HTML to Jinja2):** Recreate the existing Dutch HTML mails (inline CSS) as
  Jinja2 templates in the backend — visual parity with what clients already receive, minus the
  token links (CTAs now point to authenticated app routes). Email i18n is Phase 11's problem.
- **D-15 (logo = frontend static asset):** The Agenic logo ships in `frontend/public/` and mails
  reference the deployed app URL. Closes the Phase 9 D-07a handoff (old public Supabase URL
  dies; new bucket is fully private).
- **D-16 (synchronous send + toast):** The endpoint calls Resend in-request and returns
  success/failure; the admin sees a toast either way. `validation_link_sent_at` /
  `results_link_sent_at` update **only on successful send**. No background task, no queue.

### Claude's Discretion
- Mail module layout (`app/mail/` vs `app/notifications/`), endpoint shapes/naming, and how the
  send endpoints hang off the existing protected routers (intake-scoped for validation/results/
  reminder; admin-scoped for invite mail) — follow the existing `app/api/` conventions,
  existence-hidden 404 for cross-space intakes.
- Jinja2 environment setup, template file layout, and how faithfully the legacy HTML is ported
  (pixel parity not required — recognizable parity is).
- Exact recipient-picker UI component (dialog vs popover) built from existing shadcn primitives.
- How the Resend call is faked in tests (established fake-the-external-call pattern; live sends
  proven in UAT) and what the denial tests cover (cross-space send attempts → 404).
- Whether `admin_validated` failure is silent-logged or surfaced (it fires inside the client's
  validate action — the client should not see an operator-mail error).
- Audit logging of sends (event types, payload) following the Phase 5 `audit.log` conventions.
- The app route each mail's CTA points to (e.g. `/admin/pulse/intakes/{id}` vs a client-facing
  view) — pick whatever the logged-in recipient can actually open given current role gating.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope & requirements
- `.planning/ROADMAP.md` § Phase 10 — goal, depends-on (Phase 5), 2 success criteria.
- `.planning/REQUIREMENTS.md` — **NOTIF-01** (line 71), **NOTIF-02** (line 72).
- `.planning/PROJECT.md` — "Bearer-link client access removed; email becomes notification-only"
  requirement; login-required-for-everyone decision.

### Legacy parity source (what is being replaced)
- `docs/supabase-functions/send-pulse-mail.ts` — THE parity reference: 4 mail types
  (`validation_request`, `validation_reminder`, `results_ready`, `admin_validated`), Dutch
  subjects/HTML builders, Resend POST shape, `validation_link_sent_at`/`results_link_sent_at`
  update behavior, `FROM = 'Nestor Pulse <nestor@agenic.be>'`. The token URLs in it are exactly
  what D-09/NOTIF-01 remove.
- `.planning/codebase/INTEGRATIONS.md` § Resend (Transactional Email) — current/target summary.

### Frontend surfaces this phase un-stubs / extends
- `frontend/src/routes/admin.pulse.intakes.$id.tsx` — the three stubbed handlers (~lines 569-622,
  "komt in Phase 10" toasts) for validation mail / reminder / results mail; also holds
  `validation_link_sent_at` / `results_link_sent_at` display state.
- `frontend/src/components/intake/NextStepBanner.tsx` — the CTA props
  (`onSendValidationMail`, `onSendValidationReminder`, `onSendResultsMail`) and busy states
  already wired.
- `frontend/src/components/admin/InviteUserDialog.tsx` — success state gets the "send invitation
  mail" button next to copy-link (D-10).
- `frontend/src/lib/api/admin.ts` — `inviteUser` seam + member/space types the picker and invite
  mail action extend.
- `frontend/src/lib/api/client.ts` — `apiFetch` / `ApiResult` transport all new seam functions
  ride on (never fork it).

### Backend patterns this phase extends
- `backend/app/api/admin_routes.py` — invite flow (hard-coded `role="user"`, action link in
  response, audit contract "never log the link"); the invite-mail endpoint sits beside it.
- `backend/app/auth/admin_users.py` — `generate_set_password_link` (`:86`), regenerated per send
  (D-10); same mechanism serves forgot-password (D-12).
- `backend/app/db/models/intake.py` — `validation_link_sent_at` / `results_link_sent_at`
  (`:78-81`) already in the schema; D-16 defines their update semantics.
- `backend/app/db/models/membership.py` — `OrganizationMembership.email` / `status` / `role`
  (`:39-45`), the D-05 recipient source.
- `backend/app/api/intake_routes.py` — protected-router mounting, Identity-only dependency,
  `IntakeNotInScopeError → 404` existence-hidden pattern for the intake-scoped send endpoints.
- `backend/app/core/config.py` — `Settings` hosts the admin notification address (D-08) and
  non-secret mail config; `RESEND_API_KEY` follows the Phase 7 Secret Manager pattern.
- `backend/tests/conftest.py` + cross-tenant denial suite — harness the send-endpoint denial
  tests extend (two-space seeding).

### Prior-phase decisions that bind this phase
- `.planning/phases/09-gcs-storage/09-CONTEXT.md` — **D-07a** (fully private bucket; the email
  logo handoff this phase closes via D-15).
- `.planning/phases/05-user-space-management/05-CONTEXT.md` — invite flow decisions (D-01a role
  hard-coding, D-02 action-link mechanism, D-03 link-only response) that D-04/D-09/D-10 build on.
- `.planning/phases/07-ai-function-ports/07-CONTEXT.md` — Secret Manager secrets pattern; the
  fake-external-calls test pattern the Resend fake follows.
- `.planning/phases/08-sse-skill-run-progress/08-CONTEXT.md` — **D-04** (existence-hidden 404),
  **D-07** (infra changes go in Terraform AND the deploy runbook — applies to the new secret +
  env vars).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- NextStepBanner CTAs + busy-state plumbing — the three send buttons and their handlers exist;
  Phase 10 replaces toast stubs with real calls + the recipient picker.
- `generate_set_password_link` — already returns the Firebase action link; the invite-mail
  endpoint reuses it verbatim (fresh link per send).
- `apiFetch`/`ApiResult` + toast conventions — all new frontend seam functions
  (`sendIntakeMail`, `sendInviteMail`) follow the established return-no-throw contract.
- `intakes.validation_link_sent_at` / `results_link_sent_at` — columns already exist; no
  migration needed for sent-state (unless planning finds a need to record reminder sends).
- Legacy HTML builders in `send-pulse-mail.ts` — the Jinja2 templates port these directly
  (subjects, layout, inline CSS), swapping token URLs for app-route CTAs.

### Established Patterns
- Tenant from verified Identity only; intake-scoped endpoints 404 on cross-space access — send
  endpoints follow identically.
- External calls faked in tests, proven live in user-run UAT (dev machine has no Python/Docker —
  author by construction).
- Secrets in Secret Manager wired as env vars in `infra/main.tf` AND the deploy runbook (IaC
  drift is tracked; reconcile is a Phase-12 gate).
- Audit logging via `audit.log` with the "never log links/tokens" contract from Phase 5.

### Integration Points
- NextStepBanner CTA → recipient picker → `POST /intakes/{id}/mail/{type}` (shape at planner's
  discretion) → membership-email resolution → Jinja2 render → Resend POST → `sent_at` update →
  toast.
- Client validate action (existing endpoint) → D-03 `admin_validated` send to the configured
  admin address (non-blocking for the client's request).
- InviteUserDialog / member list → `POST` invite-mail endpoint → fresh
  `generate_set_password_link` → Resend → mail's link → custom frontend handler route
  (`confirmPasswordReset`) → login.
- `frontend/public/` logo asset → absolute URL in mail templates (base URL from config, the
  legacy `NESTOR_BASE_URL` analog).

</code_context>

<specifics>
## Specific Ideas

- The invite mail's action link is the ONLY token any mail may carry — one-time, short-lived,
  auth-bootstrap. Keep D-09's interpretation note next to wherever NOTIF-01 compliance is
  asserted (tests/docs) so the exception is visibly deliberate.
- Legacy parity matters for look & feel: clients already receive these Dutch mails today — the
  Jinja2 ports should be recognizably the same mails, just with "log in" CTAs instead of token
  links.
- The recipient picker is the one genuinely new UI element of this phase; everything else swaps
  stub → real behind existing buttons.
- The mail CTAs must link to routes the recipient can actually open: a client user lands on
  their space's intake view — verify current role gating on those routes during planning
  (client-facing intake views were reworked in Phases 6/7).

</specifics>

<deferred>
## Deferred Ideas

- **Scheduled auto-reminders** — Cloud Scheduler sweep for stale awaiting-validation intakes;
  revisit after v1 if manual reminders prove insufficient.
- **Email i18n (NL/FR/EN)** — Phase 11 owns string externalization; email templates should be
  revisited there (or explicitly scoped out of Phase 11 as a follow-up).
- **Forgot-password entry-point UI** — a "wachtwoord vergeten?" link on the login page; the D-12
  handler route already supports the flow.
- **Send-history visibility** — a per-intake log of who was mailed what and when (beyond the
  two `sent_at` timestamps); audit rows may already cover the data side.
- **`send-sales-mail` / `sales-friday-reminder` port** — sales track, outside the Pulse intake
  re-platform requirements.

</deferred>

---

*Phase: 10-Notifications*
*Context gathered: 2026-07-13*
