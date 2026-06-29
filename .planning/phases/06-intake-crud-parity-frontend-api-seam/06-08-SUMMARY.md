---
phase: 06-intake-crud-parity-frontend-api-seam
plan: 08
subsystem: frontend-admin-shell
tags: [tenant-isolation, active-space, superadmin, firebase-auth, ui]
requires:
  - "06-05: ActiveSpaceProvider / useActiveSpace / withActiveSpace + nestor.activeSpaceId persistence"
  - "admin.listSpaces() over the apiFetch transport (plan 04)"
  - "auth-context useAuth().isSuperadmin (Phase 3)"
  - "firebase.ts auth singleton (Phase 3)"
provides:
  - "Superadmin-only global space switcher in ProductShell (D-04 / TENANT-04)"
  - "Firebase signOut seam on the admin shell (last inline supabase removed)"
affects:
  - "All admin lists rendered under ProductShell (re-filter in place on space select)"
tech-stack:
  added: []
  patterns:
    - "TanStack Query useQuery for listSpaces; useQueryClient().invalidateQueries() on select"
    - "Combobox = Popover + Command (cmdk) shadcn primitives"
key-files:
  created:
    - frontend/src/components/admin/SpaceSwitcher.tsx
  modified:
    - frontend/src/components/admin/ProductShell.tsx
decisions:
  - "Mounted ActiveSpaceProvider inside ProductShell (wrapping its tree) rather than editing the shared __root.tsx, to respect parallel disjoint-file ownership while still making useActiveSpace resolve for the switcher and all list children."
metrics:
  duration: ~20m
  tasks-completed: 2
  tasks-total: 3
  files-changed: 2
  completed: 2026-06-29
---

# Phase 6 Plan 8: Global Space Switcher Summary

A superadmin-only global "active space" switcher in the admin shell — a Combobox that sets the app-wide view-filter via `ActiveSpaceProvider`, persists the selection, and re-reads every list in place with the new `?space_id`; the `user` role never mounts it. The ProductShell logout was swapped from Supabase to the Firebase `signOut` seam, removing the last inline supabase reference on the shell.

## What Was Built

### Task 1 — `SpaceSwitcher.tsx` (commit 9f6c131)
- New `frontend/src/components/admin/SpaceSwitcher.tsx`: a Combobox (`Popover` + `Command`) reading spaces via `admin.listSpaces()` through TanStack Query (`queryKey: ["admin","spaces"]`).
- Trigger: full-width `border border-ink bg-paper px-3 py-2 font-mono text-xs uppercase tracking-wider`, left-aligned active label + `ChevronsUpDown`; `KLANT` eyebrow (`label-mono text-ink/40`); **no accent color**.
- `CommandInput` placeholder `Zoek klant…`; first fixed item `Alle klanten` (clears the filter), then one item per space; selected item shows `Check`.
- On select: calls `useActiveSpace().setActiveSpace(id|null)` (the provider persists to `localStorage` key `nestor.activeSpaceId` and syncs the non-hook `withActiveSpace` accessor) and `queryClient.invalidateQueries()` so all lists re-read with the new `?space_id`; **never navigates**.
- States implemented: loading `Skeleton`, default `Alle klanten`, selected org name (truncate), no-spaces disabled `Geen klanten` + empty-state `Geen klanten gevonden`, error `Klanten niet geladen` + one toast.

### Task 2 — `ProductShell.tsx` (commit 67e5172)
- Mounted `<SpaceSwitcher/>` as a bordered block (`mt-6`) directly below the logo/product Link and above the primary `<nav>`; demoted the nav `mt-8`→`mt-6`.
- Gated the switcher render on the SAME `isSuperadmin` condition guarding the "Beheer" nav, so a `user` NEVER mounts it (absent from the DOM, not merely hidden).
- Replaced `handleLogout`'s `supabase.auth.signOut()` with `signOut(auth)` from `firebase/auth` (`auth` singleton from `@/lib/firebase`), then `navigate({ to: "/auth/login" })`.
- Removed the `supabase` import; `grep -c "supabase" ProductShell.tsx` == 0.
- Wrapped the shell tree in `ActiveSpaceProvider` (see deviation below).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] ActiveSpaceProvider was not mounted anywhere**
- **Found during:** Task 1.
- **Issue:** `ActiveSpaceProvider` (from plan 05's `active-space.tsx`) was defined but never mounted in the provider tree, so `useActiveSpace` in the new switcher would only ever see the default no-op context (selections would not persist or sync the `withActiveSpace` transport accessor).
- **Fix:** Mounted `ActiveSpaceProvider` inside `ProductShell`, wrapping its returned tree. This makes it an ancestor of both the switcher and the list `children` rendered in `<main>`, so `useActiveSpace` resolves and the provider effect keeps the module-level accessor synced. Chosen over editing the shared `__root.tsx` to respect parallel disjoint-file ownership (I own only `SpaceSwitcher.tsx` + `ProductShell.tsx`).
- **Files modified:** `frontend/src/components/admin/ProductShell.tsx`
- **Commit:** 67e5172

## Acceptance Criteria Verification

- `SpaceSwitcher.tsx` reads `admin.listSpaces()` and calls `setActiveSpace` on select — PASS.
- First command item is `Alle klanten` and clears the filter — PASS.
- `grep -c "invalidateQueries" SpaceSwitcher.tsx` == 1 (>= 1); does not navigate — PASS.
- Trigger uses no accent class (no `agenic-yellow`/`agenic-green`/`mark-green`) — PASS.
- `ActiveSpaceProvider` mounted above the switcher in the provider tree — PASS.
- `grep -c "supabase" ProductShell.tsx` == 0 — PASS.
- `<SpaceSwitcher` inside an `isSuperadmin &&` guard — PASS.
- Logout uses `signOut(auth)` from `firebase/auth` — PASS.

## Build Note

`node_modules` is not present in the worktree, so `npx tsc --noEmit` could not be run locally (per build-environment policy: author-by-construction against the acceptance greps; the orchestrator runs the authoritative tsc/build post-merge). All grep-based acceptance criteria pass. No pre-commit hooks are configured (no husky/lint-staged), so no auto-reformatting occurred.

## Pending Human Verification

Task 3 is a `checkpoint:human-verify` requiring a browser session, which cannot be run by an automated executor. Implementation is complete and committed; verification is deferred to the phase-level HUMAN-UAT.

**What was built:** A superadmin-only global space switcher in ProductShell that filters all lists app-wide and persists across reloads; a user role that never sees it.

**How to verify:**
1. Run the frontend locally (`npm run dev`, localhost:8081) against the live backend (per MEMORY: phases 3/4/5 deployed live).
2. Log in as a SUPERADMIN. Confirm the `KLANT` switcher appears below the logo, above the nav. Select a client → confirm the intake list re-filters in place (no navigation) and the label shows the org name. Reload → the selection persists. Select `Alle klanten` → all spaces' intakes return.
3. Log in as a USER (single space). Confirm the switcher is ABSENT from the DOM entirely (inspect — not merely hidden), and the user sees only their own space's intakes.

**Resume-signal:** Type "approved" or describe issues (e.g. switcher visible to a user, no persistence, navigation on select).

## Self-Check: PASSED

- FOUND: `frontend/src/components/admin/SpaceSwitcher.tsx`
- FOUND: `frontend/src/components/admin/ProductShell.tsx`
- FOUND commit: 9f6c131 (Task 1)
- FOUND commit: 67e5172 (Task 2)
