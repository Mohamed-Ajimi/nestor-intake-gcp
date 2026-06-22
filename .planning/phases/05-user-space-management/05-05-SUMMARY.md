---
phase: 05-user-space-management
plan: 05
subsystem: frontend
tags: [frontend, admin-ui, api-client, superadmin, ui-spec, user-01, user-03, phase-6-seam]
requires:
  - "frontend/src/lib/auth-context.tsx (Firebase auth/getIdToken seam — token source for apiFetch)"
  - "backend /admin/* endpoints from 05-04 (the typed admin.ts client mirrors their response models)"
  - "VITE_API_BASE_URL + apiUrl() helper (backend base URL — never hardcoded)"
  - "existing shadcn primitives + admin patterns (ProductShell, ClientFormModal, salesMail.ts)"
provides:
  - "frontend/src/lib/api/client.ts (apiFetch<T> token-attach client, {success,error} union)"
  - "frontend/src/lib/api/admin.ts (12 typed admin calls — the Phase 6 data seam)"
  - "Four superadmin screens (users/spaces/templates) + InviteUserDialog + SpaceFormModal + nav"
affects:
  - "frontend/src/components/admin/ProductShell.tsx (Beheer superadmin nav section)"
tech-stack:
  added: []
  patterns:
    - "Token-attaching apiFetch<T>(path, init?): Bearer Firebase id token via the auth-context seam, never throws on non-2xx (returns {success,error})"
    - "Typed admin module over apiFetch mirroring backend response models — no inline Supabase in route files"
    - "Shared ADMIN_NAV source of truth (adminNav.ts) consumed by ProductShell + the three route shells"
    - "JSON editor with live validation: invalid disables save + inline red message; valid shows GELDIGE JSON"
key-files:
  created:
    - "frontend/src/lib/api/client.ts"
    - "frontend/src/lib/api/admin.ts"
    - "frontend/src/routes/admin.users.tsx"
    - "frontend/src/routes/admin.spaces.tsx"
    - "frontend/src/routes/admin.templates.tsx"
    - "frontend/src/components/admin/InviteUserDialog.tsx"
    - "frontend/src/components/admin/SpaceFormModal.tsx"
    - "frontend/src/components/admin/adminNav.ts"
  modified:
    - "frontend/src/components/admin/ProductShell.tsx"
decisions:
  - "adminNav.ts added (not in plan files_modified, Rule-3 supporting module) so ProductShell + route shells share one ADMIN_NAV source instead of duplicating nav items."
  - "Clone dialog follows the REAL backend body {name, schema?, source_template_id?} from commit 2ce5c66 (broader than the plan's {source_template_id} note) — requires Naam + optional source-template picker."
  - "routeTree.gen.ts left untouched (generated file per CLAUDE.md); bun dev/build regenerates it and registers the three new /admin routes."
  - "No ui/ (shadcn) edits — screens compose existing primitives only."
checkpoint:
  type: human-verify
  gate: blocking
  resolution: "approved by user 2026-06-23 (locked UI-SPEC contract accepted)"
metrics:
  duration: "~10 min (auto tasks); checkpoint approved by user"
  completed: "2026-06-23"
  tasks: 3
  files: 9
---

# Phase 05 Plan 05: Frontend Superadmin Slice Summary

One-liner: A reusable `lib/api` slice — a Firebase-token-attaching `apiFetch<T>` client and a typed `admin.ts` module mirroring the plan-04 backend — plus four superadmin screens (users / spaces / templates) with `InviteUserDialog`, `SpaceFormModal`, and shared `ProductShell` nav, all composing existing shadcn primitives per the locked Dutch editorial UI-SPEC, with the human-verify checkpoint approved by the user.

## What Was Built

### Task 1 — `lib/api` slice (commit `6a148e1`)
- `frontend/src/lib/api/client.ts`: generic `apiFetch<T>(path, init?)` attaching the Phase 3 Firebase id token (`Authorization: Bearer …` via the same `auth`/`getIdToken` seam as `auth-context.tsx`), prefixing the backend base URL via `apiUrl()` (reads `VITE_API_BASE_URL`, never hardcoded), returning the project's `{success,error}` union — never throws on a non-2xx. This is the Phase 6 data seam.
- `frontend/src/lib/api/admin.ts`: typed `inviteUser / listUsers / deactivateUser / reactivateUser / listSpaces / createSpace / updateSpace / deactivateSpace / reactivateSpace / listTemplates / cloneTemplate / updateTemplate` over `apiFetch`, with `AdminUser / Space / Template / InviteResult` types mirroring the plan-04 response models. No Supabase import.

### Task 2 — four screens + nav (commit `a0366d4`)
- `admin.users.tsx`, `admin.spaces.tsx`, `admin.templates.tsx` route shells, `InviteUserDialog.tsx`, `SpaceFormModal.tsx`, and the `ProductShell.tsx` Beheer nav section, plus shared `adminNav.ts`. Built composing existing shadcn primitives only (no `ui/` edits), Dutch copy per UI-SPEC, `sonner` toasts, `let cancelled=false` effects, `<Skeleton>` loading, inline `text-sm text-red-600` errors, zod validation. Invite shows the copyable action link + `HANDMATIG BEZORGEN — nog geen e-mail` marker with read-only role; guardrail disabled-states for self-deactivation and last-superadmin; no hard-delete control on any entity; templates JSON editor with live validation.

### Task 3 — human-verify checkpoint (blocking) — APPROVED
The user verified the locked UI-SPEC contract (copy, states, copyable action link, no-hard-delete rule, JSON editor, guardrail disabled-states) and approved on 2026-06-23. Live IdP behavior is verified separately in GCP per 05-VALIDATION.md.

## Deviations from Plan

1. **`adminNav.ts` added** (Rule-3 supporting module, not in `files_modified`) — shared `ADMIN_NAV` so `ProductShell` and the three route shells share one source of truth.
2. **Clone body follows the real backend** `{name, schema?, source_template_id?}` (commit `2ce5c66`), broader than the plan's `{source_template_id}` interface note — the clone dialog requires a `Naam` + optional source-template picker.

## Authentication Gates

None during execution. The screens consume the Phase 3 superadmin session; the backend `get_admin_session` 403 gate (05-04) enforces superadmin-only access server-side.

## Verification

- Human-verify checkpoint **APPROVED** by the user (2026-06-23) — the locked UI-SPEC contract holds.
- By-construction against existing frontend patterns (`auth-context.tsx`, `salesMail.ts`, `admin.pulse.clients.tsx`, `ClientFormModal.tsx`, `ProductShell.tsx`) and the exact plan-04 backend response shapes (commit `2ce5c66`).
- **DEFERRED:** `bunx tsc --noEmit` + `eslint` (frontend `node_modules` not installed locally) and live IdP behavior (GCP, per 05-VALIDATION.md). Recommend running the typecheck after `bun install` before deploy.

## Known Stubs

None. `routeTree.gen.ts` is intentionally not hand-edited (generated file — regenerates on `bun dev`/build, registering the three new `/admin` routes).

## Self-Check: PASSED

- FOUND: frontend/src/lib/api/client.ts
- FOUND: frontend/src/lib/api/admin.ts
- FOUND: frontend/src/routes/admin.users.tsx, admin.spaces.tsx, admin.templates.tsx
- FOUND: frontend/src/components/admin/InviteUserDialog.tsx, SpaceFormModal.tsx, adminNav.ts
- FOUND: frontend/src/components/admin/ProductShell.tsx (modified)
- FOUND commit 6a148e1 (Task 1)
- FOUND commit a0366d4 (Task 2)
- Checkpoint (Task 3): human-verify APPROVED
