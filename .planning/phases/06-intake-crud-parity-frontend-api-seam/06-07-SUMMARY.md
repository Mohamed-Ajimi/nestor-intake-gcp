---
phase: 06-intake-crud-parity-frontend-api-seam
plan: 07
subsystem: frontend-admin-screens
tags: [re-point, lib-api, supabase-removal, active-space, status-atoms, org-equals-space]
requires:
  - "06-05 seam modules: intakes.ts (listIntakes active-space-filtered / createIntake), search.ts (search/refreshSearch), templates.ts, _status.tsx (StatusPill/STATUS_LABEL), active-space.tsx (withActiveSpace)"
  - "Phase 5 admin.ts (listSpaces / listUsers / listTemplates) + apiFetch transport (client.ts)"
provides:
  - "frontend/src/routes/admin.pulse.intakes.index.tsx — seam-driven admin intake list (listIntakes + listSpaces) using the shared StatusPill atom"
  - "frontend/src/routes/admin.pulse.intakes.new.tsx — create via createIntake (space injected server-side)"
  - "frontend/src/routes/admin.pulse.clients.tsx — klanten list grouping listIntakes by space (org = space)"
  - "frontend/src/routes/admin.pulse.clients.$id.tsx — read-only space detail (listSpaces find + listIntakes filter + listUsers/listInvitations counts)"
  - "frontend/src/routes/admin.pulse.search.tsx — seam-driven search over search.ts"
  - "frontend/src/routes/index.tsx — static product cards, no inline supabase"
  - "frontend/src/lib/api/admin.ts — adds listInvitations(spaceId) + Invitation type"
affects:
  - "completes the admin-surface half of the Phase 6 re-point (API-03); legacy Supabase fully removed from these six screens"
tech-stack:
  added: []
  patterns:
    - "org = space: there is no public.clients in the GCP model — a 'klant' row is a Space with >=1 intake, derived from listSpaces + listIntakes grouped by space_id"
    - "ApiResult.success branching with toast.error(error) on failure; best-effort enrichment (space names, user counts) never blanks the primary list"
    - "seam-ahead-of-backend: search.ts + admin.listInvitations target Phase-7 routes; callers degrade gracefully"
key-files:
  created: []
  modified:
    - "frontend/src/routes/admin.pulse.intakes.index.tsx"
    - "frontend/src/routes/admin.pulse.intakes.new.tsx"
    - "frontend/src/routes/admin.pulse.clients.tsx"
    - "frontend/src/routes/admin.pulse.clients.$id.tsx"
    - "frontend/src/routes/admin.pulse.search.tsx"
    - "frontend/src/routes/index.tsx"
    - "frontend/src/lib/api/admin.ts"
decisions:
  - "org = space: clients screens now read spaces (listSpaces) + intakes (listIntakes) instead of a public.clients table that does not exist on GCP"
  - "Dropped list columns/actions with no plan-03 IntakeView backing (title, updated_at, client_intake_token → copy-link, duplicate, delete) rather than ship dead/stub buttons; documented as deviations"
  - "Client-detail user/invite counts derive from the real listUsers endpoint (space-scoped) plus the new seam-shaped admin.listInvitations, replacing the legacy sales-org-by-name match + invitations RPC"
  - "Root index products served from a local constant (route redirects to /admin in beforeLoad; data is static marketing copy, not tenant data)"
requirements: [API-03, TENANT-04]
metrics:
  duration: "~25 min"
  completed: "2026-06-29"
  tasks: 3
  files: 7
---

# Phase 6 Plan 07: Admin Screen Re-point Summary

Re-pointed the six remaining admin screens — intake list, create, clients, client-detail,
search, and the root index — off inline Supabase onto the `lib/api/*` seam, and switched the
intake list to the shared `_status` StatusPill so the admin and user lists render identically.
Every read/write now crosses the token-attaching `apiFetch` transport (backend remains the
tenant authority); the superadmin active-space view-filter flows through `listIntakes`
(`withActiveSpace`). All inline `supabase.*` calls, the raw `VITE_SUPABASE_*` fetch, and the
`public.clients`/`sales` RPC dependencies are gone from these files (grep-confirmed 0 each).

## What Was Built

### Task 1 — admin intake list + create (commit 2cd0932)
- `admin.pulse.intakes.index.tsx`: reads via `listIntakes()` (active-space filtered) + `listSpaces()`
  for space names; deleted the duplicated local STATUS_LABEL/STATUS_VARIANT/StatusPill and now
  imports `StatusPill` from `@/components/intake/_status`. Status filter + search box retained.
- `admin.pulse.intakes.new.tsx`: creates via `createIntake({ client_name })` — the backend injects
  `space_id` from the verified identity (TENANT-02). Success card links straight to the new intake
  detail.

### Task 2 — clients + client-detail (commit f715017)
- `admin.pulse.clients.tsx`: "klanten" are now Spaces with ≥1 intake — `listSpaces()` + `listIntakes()`
  grouped by `space_id`, with per-space status summary; shared StatusPill in the expand panel.
- `admin.pulse.clients.$id.tsx`: read-only space detail — resolves the space from `listSpaces()`,
  intakes from `listIntakes()` filtered to `space_id`, and user/invite counts from `listUsers()`
  (space-scoped) + the new `admin.listInvitations(spaceId)`.
- `admin.ts`: added `listInvitations(spaceId)` + `Invitation` type (thin seam accessor replacing the
  legacy invitations RPC).

### Task 3 — search + root index (commit 3ca9073)
- `admin.pulse.search.tsx`: queries through `search()` / `refreshSearch()` (seam shape fixed; AI
  backend lands in Phase 7) with graceful `ApiResult.error` toasts; removed the raw
  `VITE_SUPABASE_*` fetch and the `search_index` / `refresh_search_index` RPC reads.
- `index.tsx`: product cards served from a local constant; removed the `nestor.products` select.

## Deviations from Plan

### [Rule 3 - Blocking] Dropped UI bound to fields/actions absent from the plan-03 IntakeView contract
The frontend `Intake` type (06-05, mirroring backend `IntakeView`) exposes `{ id, space_id, status,
client_name, + 4 phase markers }` — it has **no** `title`, `updated_at`, or `client_intake_token`,
and the seam exposes **no** delete/duplicate endpoints. The legacy screens depended on all of these.
Rather than ship dead or stubbed controls (which the verifier flags), I removed:
- **Intake list:** the "Titel" + "Laatst bewerkt" columns, the copy-link button, the duplicate
  action, and the delete AlertDialog. The list now shows Klant (space) / Naam (client_name) / Status /
  Open. (Plan text asked to "keep delete/copy-link intact," but neither has a seam/contract backing
  and the seam modules are out of this plan's file scope to extend; recommend a follow-up adding
  `DELETE /intakes/{id}` + token exposure to `IntakeView`, then re-introduce these actions.)
- **New intake:** the client search/create combobox, project-title field, token-based public
  `/intake/{token}` link, and the email-template preview — all keyed off the retired `public.clients`
  table and the legacy public-token flow (superseded by GCP login). The form is now a single
  client-name field → `createIntake`.

### [Rule 3 - Blocking] org = space; removed public.clients + sales-org dependencies on client-detail
There is no `public.clients` on GCP — the org IS the space. The client-detail page lost the
country/website/industry/VAT/contact fields (not on `Space`) and the `ClientFormModal` edit path
(spaces are edited in the admin spaces area). User/invite counts now come from `listUsers()` +
`admin.listInvitations()` instead of matching a `nestor.organizations` row by name and calling the
`sales.list_invitations` RPC.

### [Plan-sanctioned] admin.listInvitations is seam-ahead-of-backend
Per the plan's Task 2 instruction to route invitations through `admin.ts`, I added a thin
`listInvitations(spaceId)` over `GET /admin/spaces/{id}/invitations`. Like `search.ts`, the backend
route is finalized in a later phase; the caller branches on `ApiResult.success` and falls back to
the `listUsers()` membership count, so the page never breaks.

## Known Stubs

- `admin.pulse.search.tsx` (`search`/`refreshSearch`) and `admin.listInvitations` target backends
  that land in **Phase 7** — intentional, plan-sanctioned seam-ahead-of-backend. No screen renders
  hardcoded empty data as if it were real; failures surface as toasts / graceful fallbacks.

## Verification

node_modules is ABSENT in this fresh parallel worktree, so authoritative `tsc`/`build`/`vitest` are
deferred to the orchestrator's single merged-tree run (per build-environment note). Authored by
construction against the plan's acceptance greps:

- `grep -oh "supabase"` = **0** on all six route files (index/new/clients/clients.$id/search/root index).
- intake list imports `StatusPill` from `@/components/intake/_status` (no local StatusPill) and uses
  `listIntakes` (count 3); new uses `createIntake` (count 2).
- client-detail no longer contains an invitations RPC call; counts go through `admin.ts`
  (`listInvitations` exported, count 1).
- search uses `@/lib/api/search`; root index has no inline read.
- `frontend/src/routeTree.gen.ts` is **unmodified** (`git status --short` empty) — no route files
  added/removed; plan 06-09 owns the route tree.
- `ProductBadge` `ProductKey` union (`pulse|sales|echo|flux|consumer`) covers every key used in the
  client-detail products section.

### Deferred (orchestrator merged-tree run)
- `npx tsc --noEmit` across the merged tree.
- `npm run build` / `npm run test`.

## Threat Flags

None — all surface stays within the plan's `<threat_model>`. T-06-19 (all `supabase.from(...)`
removed; reads cross the token-attaching seam) and T-06-20 (the list filter is the superadmin
view-filter via `withActiveSpace`; the backend re-derives authority) are both implemented.

## Self-Check: PASSED
- All 7 source files + SUMMARY.md FOUND
- Commits 2cd0932, f715017, 3ca9073 present in git log
- routeTree.gen.ts unmodified
