---
phase: 03-identity-platform-auth
plan: 04
subsystem: frontend-auth
tags: [auth, identity-platform, firebase, frontend, bearer-removal, AUTH-01, AUTH-05]
requires:
  - "Identity Platform enabled (GCP) — public VITE_FIREBASE_* config provided at deploy time"
  - "backend POST /auth/session endpoint (plans 02/03) — the claims-sync handshake target"
provides:
  - "frontend signs in via Identity Platform email+password (Firebase JS SDK)"
  - "real beforeLoad auth guard on /admin redirecting unauthenticated users to /auth/login"
  - "post-sign-in POST /auth/session + getToken(true) claims-refresh handshake"
  - "getToken(forceRefresh) helper on the auth context (Phase-6 token-attach seam)"
  - "all 5 never-expiring bearer-link routes + the OTP callback removed (AUTH-05)"
affects:
  - "frontend/src/lib (auth singleton swapped Supabase -> Firebase)"
  - "frontend/src/routes (login rewritten, /admin guarded, 6 routes deleted)"
tech-stack:
  added:
    - "firebase ^12.15.0 (Firebase JS SDK v12 modular API — firebase/app + firebase/auth)"
  patterns:
    - "env-guarded module-level auth singleton (mirrors supabase.ts shape)"
    - "onAuthStateChanged-driven AuthProvider keeping the {session, loading} contract"
    - "beforeLoad guard awaiting an onAuthStateChanged-derived auth-ready promise"
key-files:
  created:
    - "frontend/src/lib/firebase.ts"
  modified:
    - "frontend/src/lib/auth-context.tsx"
    - "frontend/src/routes/auth.login.tsx"
    - "frontend/src/routes/admin.tsx"
    - "frontend/src/routeTree.gen.ts"
    - "frontend/package.json"
  deleted:
    - "frontend/src/routes/intake.$token.tsx"
    - "frontend/src/routes/results.$token.tsx"
    - "frontend/src/routes/sales.intake.$token.tsx"
    - "frontend/src/routes/sales.results.$token.tsx"
    - "frontend/src/routes/sales.validate.$token.tsx"
    - "frontend/src/routes/auth.callback.tsx"
decisions:
  - "D-01: Identity Platform email+password sign-in (no magic-link / no SSO / no email-link)"
  - "D-02: sign-in only — no public self-registration affordance on the login page"
  - "D-08: 5 bearer-token routes deleted AND the @agenic.be (+Gmail) login allowlist dropped"
  - "D-09: author-by-construction — bun unavailable on dev box; firebase declared in package.json by hand and routeTree.gen.ts hand-stripped; bun install + plugin regen deferred to next CI/GCP build"
metrics:
  duration: "~12 min"
  completed: "2026-06-19"
  tasks: 3
  files_changed: 11
requirements: [AUTH-01, AUTH-05]
---

# Phase 03 Plan 04: Frontend Auth Swap (Identity Platform) Summary

Swapped the frontend auth layer from Supabase GoTrue to Identity Platform (Firebase JS SDK v12) without touching the data layer or shadcn UI: an env-guarded Firebase singleton, an `onAuthStateChanged`-driven `AuthProvider` that keeps the `{session, loading}` contract plus a `getToken(forceRefresh)` handshake helper, an email+password login page (allowlist dropped) running the `POST /auth/session` + `getToken(true)` claims-refresh handshake, a real `beforeLoad` redirect guard on `/admin`, and deletion of all five never-expiring bearer-link routes plus the dead OTP callback (route tree hand-stripped of their ids).

## What Was Built

### Task 1 — Firebase singleton + AuthProvider rewrite (commit `bc5b444`)
- **`frontend/src/lib/firebase.ts` (new):** `export const auth = getAuth(initializeApp({ apiKey, authDomain, projectId }))` reading only public `VITE_FIREBASE_*` env. `connectAuthEmulator(auth, "http://localhost:9099")` guarded behind `VITE_FIREBASE_EMULATOR === "1"`. No Supabase env / DB DSN shipped.
- **`frontend/src/lib/auth-context.tsx`:** rewritten onto `onAuthStateChanged(auth, …)` (its return value used as the cleanup unsubscribe), preserving the `AuthProvider`/`useAuth` exports, the `{session, loading}` context value, and the `cancelled`/`settled`/`settle()` cancel-flag idiom. `session` is typed as Firebase `User | null`. Added a `getToken(forceRefresh = false)` helper exposing `auth.currentUser ? getIdToken(auth.currentUser, forceRefresh) : Promise.resolve(null)`. The Supabase `onAuthStateChange`/`exchangeCodeForSession`/`getSession` OTP path was removed entirely.
- **`frontend/package.json`:** `"firebase": "^12.15.0"` added to `dependencies`.

### Task 2 — Email+password login + handshake + real /admin guard (commit `b904d6f`)
- **`frontend/src/routes/auth.login.tsx`:** rewritten to `signInWithEmailAndPassword(auth, email, password)` (D-01) with a password input alongside email and no self-registration affordance (D-02). The `ALLOWED_DOMAINS` / `ALLOWED_EXPLICIT` allowlist and the magic-link / `?error=` callback UI were deleted (D-08b). On success it runs the handshake — `getToken()` → `fetch("/auth/session", { method:"POST", headers:{ Authorization: \`Bearer ${token}\` } })` → `getToken(true)` (force-refresh so the next request carries the claims — Pitfall 2) — then navigates to `/admin`. Failures surface via a `sonner` toast. The page kept its chrome and the `useAuth()` redirect-when-logged-in effect.
- **`frontend/src/routes/admin.tsx`:** the no-op `AdminGuard` was replaced with a real `createFileRoute("/admin")({ beforeLoad, component })`. `beforeLoad` awaits an `authReady()` promise derived from `onAuthStateChanged` (Firebase populates `currentUser` only after the first tick — Open Q2) and `throw redirect({ to: "/auth/login" })` when there is no authenticated user. Placed on the `/admin` layout route only, so `/` and `/auth/login` stay public. The component still renders `<Outlet />`. A comment records that this is UX gating; the backend `get_current_identity` dependency (plans 02/03) is the authoritative control.

### Task 3 — Delete bearer routes + OTP callback, strip route tree (commit `40ef0c4`)
- Deleted the five never-expiring bearer-link routes (`intake.$token.tsx`, `results.$token.tsx`, `sales.intake.$token.tsx`, `sales.results.$token.tsx`, `sales.validate.$token.tsx`) and `auth.callback.tsx` (the dead Supabase OTP code-exchange route under email+password, D-01).
- Hand-stripped `frontend/src/routeTree.gen.ts` of all six routes' imports, `*.update({...})` definitions, `FileRoutesBy*`/`FileRouteTypes` entries, the `declare module` blocks, and the `rootRouteChildren` wiring — leaving every other route intact.
- No DB model was touched; `deliverables.client_view_token` (out-of-scope Tribunal table) left untouched (D-08).

## Verification

All `<automated>` `node -e` checks pass (Node v22 available; Bun is not):
- Task 1: `firebase.ts` exports `getAuth` with only `VITE_FIREBASE_*` (no `VITE_SUPABASE`); `auth-context.tsx` uses `onAuthStateChanged`/`useAuth`/`getToken`; `package.json` declares `firebase`.
- Task 2: `auth.login.tsx` uses `signInWithEmailAndPassword`, has no `ALLOWED_DOMAINS`, posts to `/auth/session`, calls `getToken(true)`; `admin.tsx` has `beforeLoad` + `redirect`.
- Task 3: all six route files absent; `routeTree.gen.ts` references none of the six route ids.

Cross-checked the plan-01 guard `backend/tests/test_no_bearer_routes.py`:
- `test_bearer_route_files_absent` — GREEN (all six files gone).
- `test_routetree_has_no_bearer_refs` — GREEN (the gen file is present and clean; the coded `pytest.skip` path is not needed since the file was hand-stripped in place, not removed).

A `Grep` for any residual reference to the deleted routes/route-objects across `frontend/src` returned **no matches**.

## Deviations from Plan

None — plan executed exactly as written, taking the explicitly-sanctioned author-by-construction path (D-09) for the two tool-dependent steps.

## Deferred to Live / CI (D-09)

- **`bun install`:** `firebase ^12.15.0` is declared in `frontend/package.json` but `node_modules`/lockfile were not materialized — the dev box has no Bun. The next GCP/CI build must run `bun install` to fetch the package.
- **Route-tree regeneration:** `routeTree.gen.ts` was hand-stripped (correct and consistent), but the TanStack Router plugin should regenerate it deterministically on the next CI/GCP build to guarantee byte-for-byte correctness (accepted risk T-03-23 — low risk, the gen file is rebuilt deterministically from the routes dir).
- **Live behavior (Phase 12):** the GCP frontend is not live until Phase 12, so the user must validate in GCP: (a) the Firebase singleton initializes with no console error and `useAuth()` resolves `{session, loading}`; (b) sign-in at `/auth/login` with the seeded superadmin, `POST /auth/session` returns `{"synced":true}`, `getToken(true)` carries the `role` claim, `/admin` loads; (c) an unauthenticated visit to `/admin` redirects to `/auth/login`.

## Notes

- `frontend/src/routes/admin.login.tsx` (a legacy duplicate login route) was intentionally **not** modified — it is out of this plan's scope and now simply sits behind the new `/admin` guard. The `__root.tsx` `AuthRedirector` continues to handle `/admin/login` and `/auth/login` without change.
- No secret or browser→DB path was introduced: `firebase.ts` ships only the public `VITE_FIREBASE_*` web config (the web `apiKey` is a public project identifier, not a credential).
- LF→CRLF line-ending warnings on commit are the platform default on Windows and are benign.

## Threat Surface

No new security surface beyond the plan's `<threat_model>`. The change is net-reducing: it removes five anonymous bearer-link entry points (T-03-18) and the dead OTP callback, restores the `/admin` guard (T-03-19), and adds the claims-refresh handshake (T-03-21). No new endpoint, schema change, or trust boundary introduced.

## Self-Check: PASSED

- `frontend/src/lib/firebase.ts` — FOUND
- `.planning/phases/03-identity-platform-auth/03-04-SUMMARY.md` — FOUND
- commit `bc5b444` (Task 1) — FOUND
- commit `b904d6f` (Task 2) — FOUND
- commit `40ef0c4` (Task 3) — FOUND
