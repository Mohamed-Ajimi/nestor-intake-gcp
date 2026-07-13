---
phase: 10-notifications
plan: 04
subsystem: frontend/notifications-ui
status: checkpoint
tags: [notifications, frontend, recipient-picker, invite-mail, seam, NOTIF-01, NOTIF-02]
requires:
  - "GET /intakes/{id}/members + POST /intakes/{id}/mail/{validation|reminder|results} (Plan 10-03)"
  - "POST /admin/users/{membership_id}/invite-mail (Plan 10-03)"
  - "frontend/src/lib/api/client.ts apiFetch + ApiResult (Phase 6 transport seam)"
  - "NextStepBanner CTA props + BusyKey union sendValidation/sendReminder/sendResults (Phase 8/9)"
provides:
  - "listSpaceMembers + sendIntakeMail seam functions (intakes.ts)"
  - "sendInviteMail seam function (admin.ts)"
  - "RecipientPicker.tsx — members-only recipient dialog (preselect + empty-guard, D-06/D-07)"
  - "un-stubbed validation/reminder/results CTAs wired to the picker"
  - "send/resend invitation-mail action in InviteUserDialog + member list (D-10)"
  - "frontend/public/agenic-logo.png (D-15) — mail-template logo asset"
affects:
  - "Plan 10-05 / phase-level UAT consumes these operator-facing send surfaces"
tech-stack:
  added: []
  patterns:
    - "one thin seam function per backend route over apiFetch, returns ApiResult<T>, never throws"
    - "controlled shadcn Dialog mirroring InviteUserDialog (reset-on-open, sonner toasts)"
    - "recipient picker offers ONLY server-provided membership rows — no free-text address (D-06)"
    - "membership id resolved from the reloaded user list (invite response carries a uid, not a membership id)"
key-files:
  created:
    - frontend/src/components/intake/RecipientPicker.tsx
    - frontend/public/agenic-logo.png
  modified:
    - frontend/src/lib/api/intakes.ts
    - frontend/src/lib/api/admin.ts
    - frontend/src/routes/admin.pulse.intakes.$id.tsx
    - frontend/src/components/admin/InviteUserDialog.tsx
    - frontend/src/routes/admin.users.tsx
decisions:
  - "listSpaceMembers is keyed on intakeId (GET /intakes/{id}/members) per the plan's authoritative <action>/<interfaces> — PATTERNS.md §seam's `listSpaceMembers(spaceId)` label is superseded by the concrete intake-scoped endpoint delivered by Plan 03."
  - "InviteUserDialog resolves the membership id via a parent-supplied resolveMembershipId(email, spaceId) backed by the reloaded user list — NO backend change (the invite response's uid != membership id); if unresolved it toasts a fallback pointing at the member-list resend, never guesses."
  - "invite-mail row action shown on ACTIVE members only (a deactivated member cannot log in, so a set-password link is a dead end — mirrors the D-06 members-only rationale)."
metrics:
  duration: ~9 min
  completed: 2026-07-13
  tasks: 3 auto complete + 1 checkpoint pending
  files: 6
---

# Phase 10 Plan 04: Notification Send UI (RecipientPicker + invite-mail surfaces) Summary

The operator-facing surface of the notifications phase: the `RecipientPicker` (the one
genuinely new UI element) fed by `listSpaceMembers`, the three un-stubbed client-facing CTA
handlers (validation / reminder / results) posting through `sendIntakeMail`, the send/resend
invitation-mail action added to both the `InviteUserDialog` success state and the member-list
rows via `sendInviteMail`, the three frontend API seam functions, and the real Agenic logo
static asset the mail templates reference. Everything typechecks (`tsc --noEmit` clean).

## What Was Built

### Task 1 — seam functions + RecipientPicker + logo (commit a03fadb)
- **`intakes.ts`**: `listSpaceMembers(intakeId)` → `GET /intakes/{id}/members` returning
  `ApiResult<SpaceMember[]>` (`SpaceMember = {id, email, name?}`); `sendIntakeMail(intakeId, type, recipients)`
  → `POST /intakes/{id}/mail/{type}` with body `{ recipients }`. Added `IntakeMailType` and
  `MailResult` exports. Both go over the shared `apiFetch` transport (never forked) and never throw.
- **`admin.ts`**: `sendInviteMail(membershipId)` → `POST /admin/users/{id}/invite-mail`, plus a
  local `MailResult` type.
- **`RecipientPicker.tsx`** (NEW): a controlled shadcn `Dialog` mirroring `InviteUserDialog`
  (reset-on-open via `useEffect`, sonner toasts). On open it calls `listSpaceMembers(intakeId)`,
  renders each active member as a `Checkbox` row (label = `name ?? email`), **preselects all**
  (D-07), and returns the selected membership ids on confirm. Loading state (Skeletons), inline
  error toast on fetch failure, and — when the resolved list is empty — a **disabled confirm CTA**
  with the Dutch "Nodig eerst iemand uit" hint (D-07). No free-text address field anywhere (D-06).
  Dutch copy, `font-mono uppercase` labels matching the invite dialog.
- **`frontend/public/agenic-logo.png`** (D-15): the **real** Agenic logo (417×104 RGBA PNG),
  copied from the existing `frontend/src/assets/agenic-logo.png` — not a placeholder.

### Task 2 — un-stub the 3 CTA handlers (commit 8177895)
- In `admin.pulse.intakes.$id.tsx`, the three `toast.message("… komt in Phase 10.")` stubs
  (`onSendValidationMail` / `onSendValidationReminder` / `onSendResultsMail`) now each set
  `mailPickerType` to open the `RecipientPicker`. A single `handleSendMail(recipients)` reads the
  active type, sets the matching busy key (`sendValidation` / `sendReminder` / `sendResults` — the
  exact keys `NextStepBanner` already reads via `MAIL_BUSY_KEY`), calls `sendIntakeMail(intake.id, type, recipients)`,
  toasts success/failure, clears the picker, and reloads the intake (`load()`) so the sent-at
  markers re-drive `derivePhase`. The picker is mounted once in the render tree beside
  `NextStepBanner` with per-type open state; the banner CTA props are unchanged.
- Grep-confirmed: zero "komt in Phase 10" strings remain in the route.

### Task 3 — invite-mail action in dialog + member list (commit 2189126)
- **`InviteUserDialog.tsx`**: added a "Verstuur uitnodigingsmail" `Button` (with `Mail` icon) in
  the success state beside "Kopieer link" (D-10); the copy-link fallback stays (D-04). It resolves
  the just-invited membership id via a new `resolveMembershipId(email, spaceId)` prop (the invite
  response carries a `uid`, not a membership id) and calls `sendInviteMail`. On an unresolved id it
  toasts a clear fallback ("stuur … opnieuw vanuit de gebruikerslijst") rather than guessing. The
  stale "e-mailverzending wordt later toegevoegd (Fase 10)" / "HANDMATIG BEZORGEN — nog geen e-mail"
  copy is replaced with mail-aware wording (`MAIL VERSTUURD` / `MAIL OF HANDMATIG BEZORGEN`).
- **`admin.users.tsx`**: added a per-member "Herstuur uitnodiging" row action (active members only,
  disabled when the member has no email) calling `sendInviteMail(u.id)` and toasting; wired the
  `resolveMembershipId` resolver (backed by the reloaded `users` state) into the dialog.

## Verification

- `cd frontend && npx tsc --noEmit` — **PASS** after each task (run via the shared-checkout
  TypeScript install junctioned into the worktree; the junction was removed before committing so
  it never enters git state).
- Grep: no "komt in Phase 10" in `admin.pulse.intakes.$id.tsx`; no "Fase 10" / "nog geen e-mail"
  in `InviteUserDialog.tsx`.
- Manual/functional verification (picker preselect, empty-space guard, toasts, both invite-mail
  surfaces) is the pending **Task 4 checkpoint** — requires the frontend run against the deployed
  backend; not executed here.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 — Blocking] InviteUserDialog membership-id resolution (invite response lacks it)**
- **Found during:** Task 3
- **Issue:** `sendInviteMail` keys on `membership_id`, but the invite response (`InviteResult`)
  carries only `uid` (the IdP provider_user_id) + `action_link` — no membership id. The plan
  flagged this exact case ("if the invite response lacks a membership id, surface that … rather
  than guessing").
- **Fix (in-scope, no backend change):** Threaded a `resolveMembershipId(email, spaceId)` prop into
  the dialog, backed by the parent `admin.users.tsx` `users` state (reloaded via the existing
  `onInvited`). The dialog resolves the id at send time; if not yet visible it toasts a fallback
  pointing at the member-list resend. This keeps the plan's frontend-only file scope (no backend /
  cross-wave edit) and avoids guessing.
- **Files modified:** `InviteUserDialog.tsx`, `admin.users.tsx`
- **Commit:** 2189126

**Note (not a deviation):** PATTERNS.md §seam labels the members read `listSpaceMembers(spaceId)`,
but the plan's authoritative `<action>`/`<interfaces>` and the Plan-03 backend deliver the
intake-scoped `GET /intakes/{id}/members`. Implemented per the plan (keyed on `intakeId`).

## Authentication Gates

None.

## Known Stubs

None. All three CTA handlers, the picker, and both invite-mail surfaces are wired to real Plan-03
endpoints via the seam functions. `SpaceMember.name` is `null` by backend contract (no name column
on `organization_memberships`) — the picker labels on `email` in that case; this is the documented
shape, not a stub. The logo is the real asset, not a placeholder.

## Threat Flags

None. The one new client surface (RecipientPicker → send endpoints) is enumerated in the plan's
`<threat_model>` and mitigated as specified (T-10-11): the picker offers ONLY server-provided
membership rows — no free-text address input (D-06) — and posts membership ids the backend
re-validates. The invite action link stays in the copy-link fallback (T-10-12, accepted).

## Checkpoint Pending

Task 4 (`checkpoint:human-verify`) is the final task and was NOT executed. A human must run the
frontend locally against the deployed backend and confirm: the picker opens with active members
preselected, the confirm CTA is disabled with an "invite someone first" hint for a zero-member
space, sends surface a success/failure toast, and both invite-mail surfaces (dialog success state
+ member list) work alongside the copy-link fallback. Real Resend delivery + Firebase click-through
are proven in the phase-level live UAT (VALIDATION.md Manual-Only), not here.

## Commits

- a03fadb — `feat(10-04): mail seam functions + RecipientPicker + logo asset`
- 8177895 — `feat(10-04): un-stub validation/reminder/results CTAs via RecipientPicker`
- 2189126 — `feat(10-04): send invitation mail from InviteUserDialog + member list`

## Self-Check: PASSED

All created files exist (`RecipientPicker.tsx`, `agenic-logo.png`) and all three feat commits
(a03fadb, 8177895, 2189126) are reachable in git; `tsc --noEmit` is clean.
