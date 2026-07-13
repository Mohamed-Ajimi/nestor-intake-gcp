---
phase: 10-notifications
plan: 05
subsystem: frontend/auth
status: checkpoint
tags: [notifications, auth, firebase, password-set, oobCode, NOTIF-02, invite]
requires:
  - "Plan 10-03 — generate_set_password_link ActionCodeSettings continue URL -> /auth/action (D-11)"
  - "frontend/src/lib/firebase.ts — the exported Firebase `auth` singleton"
  - "frontend/src/routes/auth.login.tsx — the branded route shell + Dutch style to copy"
provides:
  - "frontend route /auth/action — the branded Firebase oobCode consume handler (verifyPasswordResetCode + confirmPasswordReset)"
  - "one handler serving BOTH invite set-password and (later) forgot-password (D-12), neutral 'Kies je wachtwoord' copy"
affects:
  - "Closes the invite-mail dead end: the mailed action link now lands on a branded in-app route instead of Firebase's hosted page (D-11)"
  - "The (later) forgot-password entry point can reuse this route with no rework (D-12)"
tech-stack:
  added: []
  patterns:
    - "read mode+oobCode from window.location.search (SSR-guarded URLSearchParams)"
    - "verify-then-render: verifyPasswordResetCode gates the form on a valid code; expired/invalid -> friendly re-request page"
    - "FirebaseError code mapping to Dutch messages (weak-password inline; expired/invalid whole-page)"
    - "useEffect cancel flag (let cancelled = false) for the async verify, matching auth.login.tsx conventions"
key-files:
  created:
    - frontend/src/routes/auth.action.tsx
  modified:
    - frontend/src/routeTree.gen.ts
decisions:
  - "verify-then-render state machine (verifying|ready|invalid|unsupported): verifyPasswordResetCode runs on mount so an expired/invalid link shows the friendly re-request page WITHOUT ever rendering the password form — the form is only reachable for a validated code."
  - "Unknown/unsupported `mode` (e.g. verifyEmail) is handled with a neutral 'kan niet worden verwerkt' message + a link back to login rather than a crash (D-12 graceful unknown mode)."
  - "Weak-password is surfaced as an INLINE field error (form stays); expired/invalid mid-submit falls back to the whole-page re-request message (the code is dead — the form can't recover)."
  - "Client-side min-length + confirm-match pre-checks before the round-trip; Firebase's auth/weak-password remains the authoritative gate (T-10-14)."
metrics:
  duration: ~20 min
  completed: 2026-07-13
  tasks: 1 of 2 (Task 2 is a pending human-verify checkpoint)
  files: 2
---

# Phase 10 Plan 05: /auth/action oobCode Handler Route Summary

The one genuinely-new frontend route this phase needs: the branded in-app `/auth/action` handler that consumes the Firebase password-reset action code (`oobCode`). It reads `mode`/`oobCode` from the URL, verifies the code with `verifyPasswordResetCode` (surfacing the target email), renders a neutral Dutch "Kies je wachtwoord" form, applies the new password via `confirmPasswordReset`, and navigates to `/auth/login`. One route serves both the invite set-password flow and the (later) forgot-password flow (D-11/D-12). It closes the invite mail's dead end — Plan 10-03 pinned the invite action link's continue URL to exactly this route, so the whole first-run flow now stays in the app's look and language instead of Firebase's hosted page.

**Status: checkpoint.** Task 1 (the route) is complete and committed. Task 2 is a `checkpoint:human-verify` — the live invite → mailed link → set password → login click-through against the deployed Identity Platform (cannot run in CI). It is pending human verification.

## What Was Built

### Task 1 — `frontend/src/routes/auth.action.tsx` (committed 623c789)
- **Route registration:** `export const Route = createFileRoute("/auth/action")({ component: ActionPage })`, matching the file-route convention copied from `auth.login.tsx`. Imports the Firebase `auth` singleton from `@/lib/firebase`, `verifyPasswordResetCode` + `confirmPasswordReset` from `firebase/auth`, `FirebaseError` from `firebase/app`, and `toast` from `sonner`.
- **URL read (SSR-guarded):** on mount, reads `mode` and `oobCode` from `window.location.search` via `URLSearchParams`, guarded with `typeof window !== "undefined"` (the app SSRs via Nitro; `window` is undefined server-side, so it falls back to an empty search string until the browser effect runs).
- **Verify-then-render state machine** (`VerifyState`: `verifying` | `ready` | `invalid` | `unsupported`): a `useEffect` (with a `let cancelled = false` cancel flag, the codebase's unmount-safety convention) calls `verifyPasswordResetCode(auth, oobCode)` for `mode === "resetPassword"` with a present `oobCode`. On success it stores the returned target email and flips to `ready` (the form only renders for a validated code). On failure it flips to `invalid` (the friendly re-request page). An unknown/missing `mode` flips to `unsupported` (neutral message, no crash — D-12).
- **Neutral Dutch form (D-12):** the header is "Kies je wachtwoord" (never "reset"), so it reads correctly for a freshly-invited user who never knew their random password. Two password inputs (new + confirm) styled to exactly match `auth.login.tsx` (the `bg-paper2` / `border-ink` card, IBM Plex mono/serif chrome, the `Agenic × Nestor` eyebrow). On submit: client-side min-length (6) + confirm-match pre-checks, then `confirmPasswordReset(auth, oobCode, newPassword)`; on success `toast.success` + `navigate({ to: "/auth/login" })`.
- **Firebase error handling (no unhandled throw):**
  - `auth/expired-action-code` / `auth/invalid-action-code` → the friendly Dutch "Deze link is verlopen of ongeldig — vraag een nieuwe link aan." message with a link back to `/auth/login` (whole-page, since the code is dead). Handled BOTH at verify time (the initial page state) and mid-submit (falls back from the form to the re-request page).
  - `auth/weak-password` → an INLINE field error under the form (the form stays so the user can pick a stronger password) — this is the T-10-14 mitigation surfaced as a field error rather than accepted.
  - Any other Firebase code → a neutral Dutch fallback message via `dutchAuthError()` + a toast.
  - Unknown `mode` (e.g. `verifyEmail`) → the `unsupported` page, never a crash.

## Verification

- **`cd frontend && npx tsc --noEmit` passes (exit 0).** The dev-machine has no node_modules inside the isolated worktree, so the verify was run against the main checkout's toolchain: the new route file was copied into the main checkout, the TanStack router plugin regenerated `routeTree.gen.ts` to include `/auth/action` (12 references; `id`/`path` registration + the `FileRoutesByPath`/`FileRoutesByTo`/`FileRoutesById` unions), `npx tsc --noEmit` returned exit 0 with no diagnostics, then the main checkout was restored to pristine (temp file removed, original route tree restored) and the **regenerated** route tree was copied into the worktree and committed alongside the route.
- The route tree now type-registers `/auth/action`, so `createFileRoute("/auth/action")` and `navigate({ to: "/auth/login" })` both type-check.

## Deviations from Plan

None — Task 1 was executed exactly as written. The four verify/render states (verifying / ready / invalid / unsupported) are the natural expansion of the plan's "handle a missing/unknown `mode` gracefully" + "surface expired/invalid with a friendly message" requirements, not a scope change.

## Authentication Gates

None (no live auth was required to author or type-check the route; the live click-through is the Task 2 human checkpoint, not an auth gate).

## Known Stubs

None. The route is fully wired to the real Firebase `auth` singleton and the real `verifyPasswordResetCode`/`confirmPasswordReset` SDK calls. There is no mock/placeholder data path.

## Threat Flags

None. The route's surface is exactly the plan's `<threat_model>`:
- **T-10-13 (reused/never-expiring bearer link):** the link is a Firebase single-use, short-lived action code — `verifyPasswordResetCode` rejects expired/invalid codes and the handler surfaces that as the friendly re-request message (never renders the form for a dead code). Mitigated.
- **T-10-14 (weak password via the handler):** `auth/weak-password` is caught and surfaced as an inline field error, never silently accepted; a client-side min-length pre-check adds a first line of defence. Mitigated.

## Pending Checkpoint

**Task 2 — Live click-through verification of the invite action link** (`checkpoint:human-verify`, gate=blocking). The end-to-end invite → mailed link → set password → login flow requires a live Identity Platform + a real mailed link, so it is proven in UAT (10-VALIDATION.md Manual-Only), not in CI. See the checkpoint return for the exact steps.

## Commits

- 623c789 — `feat(10-05): branded /auth/action Firebase oobCode set-password handler`

## Self-Check: PASSED

- `frontend/src/routes/auth.action.tsx` exists on disk (FOUND).
- `frontend/src/routeTree.gen.ts` contains `/auth/action` registration (12 references).
- Commit 623c789 is reachable in git (FOUND).
- `npx tsc --noEmit` exit 0, no diagnostics.
