# Phase 06 — Deferred Items

Out-of-scope discoveries logged during plan execution (do NOT fix in the discovering plan
per the executor scope boundary). Tracked here for a follow-up.

## From 06-13 (intakes index space_id filter)

- **RESOLVED 2026-06-30.** Regenerating `routeTree.gen.ts` was a no-op (it was NOT stale — byte-identical). Real cause: `/admin/pulse/clients` and `/admin/pulse/intakes/new` declared `validateSearch` returning a REQUIRED key (`{ client: string | undefined }` / `{ client_id: string | undefined }`), and `/admin/pulse/clients/$id` inherited it — so Links/navigates were forced to pass `search`. The params are never read (no `useSearch` consumers). Fixed by returning an OPTIONAL-key shape (`{ client?: string }` / `{ client_id?: string }`). `tsc --noEmit` now reports 0 errors. Behavior-preserving (type hygiene only).

- ~~**Pre-existing repo-wide tsc errors — stale `routeTree.gen.ts` / missing required `search` param.**~~
  `frontend` `tsc --noEmit` reports 7 errors across the admin route tree, all of the form
  *"Property 'search' is missing ... MakeRequiredSearchParams"* on `<Link>` / `navigate({ to })`
  calls. Affected files: `admin.clients.$id.tsx`, `admin.pulse.clients.$id.tsx`,
  `admin.pulse.clients.tsx`, `admin.pulse.intakes.$id.tsx`, and `admin.pulse.intakes.index.tsx`
  (the untouched "Nieuwe intake" Link, not the 06-13 edit).
  - **Pre-existing:** confirmed present at the worktree base (HEAD 1a18b7d) by re-running tsc with
    the 06-13 change stashed — identical 7 errors. The 06-13 change introduces ZERO new type errors
    (the index.tsx error merely shifted from line 114 to 121 as added lines pushed it down).
  - **Root cause (likely):** a route declared a required `search` schema (or the route tree was
    regenerated against a newer TanStack Router) without updating the link/navigate call sites; the
    generated `routeTree.gen.ts` and the call sites are out of sync.
  - **Out of scope for 06-13** (scope boundary: only fix issues directly caused by the current task).
    Recommend a dedicated follow-up: regenerate the route tree and add the required `search` props
    (or relax the route's search schema) across the admin routes.
