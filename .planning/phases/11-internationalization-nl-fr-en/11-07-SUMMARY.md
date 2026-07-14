---
phase: 11-internationalization-nl-fr-en
plan: 07
subsystem: frontend-i18n
tags: [i18n, react-i18next, admin, externalization]
dependency_graph:
  requires:
    - "11-01 (react-i18next runtime + admin.json catalog skeleton + useTranslation)"
    - "11-04 (admin.json intakeDetail/clientDrawer/spaces/spaceForm sub-objects; SpaceFormModal locale field)"
  provides:
    - "Externalized invite/user-management surfaces (InviteUserDialog, admin.users)"
    - "Externalized client/space dialogs (ClientFormModal, SpaceSwitcher)"
    - "Externalized remaining pulse routes (templates, intakes.new, clients, clients/$id, search, intakes list)"
    - "admin.json invite/users/clientModal/spaceSwitcher/templates/intakesNew/clientDetail/clients/search/intakesList keys (nl/fr/en)"
  affects:
    - "11-09 (Wave-4 CI Dutch-string guard now scans these surfaces as externalized)"
tech_stack:
  added: []
  patterns:
    - "useTranslation('admin') per component/route; namespaced keys by sub-object"
    - "zod schema built inside component so validation messages resolve via t()"
    - "count/interpolation via i18next {{count}} plural forms and {{name}} interpolation"
    - "map-variable rename (t -> tpl/src) to avoid shadowing the useTranslation t()"
key_files:
  created: []
  modified:
    - frontend/src/components/admin/InviteUserDialog.tsx
    - frontend/src/routes/admin.users.tsx
    - frontend/src/components/admin/ClientFormModal.tsx
    - frontend/src/components/admin/SpaceSwitcher.tsx
    - frontend/src/routes/admin.templates.tsx
    - frontend/src/routes/admin.pulse.intakes.new.tsx
    - frontend/src/routes/admin.pulse.clients.$id.tsx
    - frontend/src/routes/admin.pulse.clients.tsx
    - frontend/src/routes/admin.pulse.search.tsx
    - frontend/src/routes/admin.pulse.intakes.index.tsx
    - frontend/src/locales/nl/admin.json
    - frontend/src/locales/fr/admin.json
    - frontend/src/locales/en/admin.json
decisions:
  - "SpaceFormModal.tsx left untouched: already fully externalized (chrome + default_locale field) in 11-04 per the deviation handoff; verified before editing"
  - "admin.pulse.index.tsx and admin.login.tsx are pure redirect stubs (throw redirect) with zero strings — nothing to externalize; not committed"
  - "search SUGGESTIONS[] example query prompts left as data (illustrative content, not UI chrome); STATUS_LABEL usage in clients.tsx statusSummary is owned by _status.tsx (out of scope)"
  - "FR/EN authored by construction (D-12); nl is the guaranteed fallback"
metrics:
  duration: "~30 min"
  completed: "2026-07-14"
  tasks: 2
  files: 13
---

# Phase 11 Plan 07: Remaining-Admin Externalization Sweep Summary

Completed the admin-namespace externalization catch-all — invite/user-management surfaces, client/space dialogs, and the remaining pulse/admin routes now render in the active locale (NL/FR/EN) via `useTranslation("admin")`, with all new keys namespaced by sub-object under the three `admin.json` catalogs.

## Tasks Completed

| # | Task | Commit | Result |
|---|------|--------|--------|
| 1 | Externalize user/invite management surfaces | a73f69e | InviteUserDialog (18) + admin.users (17) → `t("invite.*")` / `t("users.*")`; tsc clean |
| 2 | Externalize client/space dialogs + remaining pulse routes | d18eb8c | ClientFormModal, SpaceSwitcher, templates, intakes.new, clients, clients/$id, search, intakes list → namespaced keys; tsc clean |

## Verification

- `npx tsc --noEmit` — clean (exit 0) after each task
- Per-file grep for Dutch stopwords — none outside code comments in any touched file
- All three `admin.json` catalogs parse (node JSON.parse) after every catalog edit
- `git diff --diff-filter=D` — no file deletions across either commit

## Catalog Additions (all three locales)

`invite`, `users`, `clientModal`, `spaceSwitcher`, `templates`, `intakesNew`, `clientDetail`,
`clients`, `search`, `intakesList` — added additively after the existing `spaceForm` sub-object.
No existing 11-04 keys removed or renamed.

## Deviations from Plan

### SpaceFormModal (handoff-driven, not a deviation)

Per the environment handoff, `SpaceFormModal.tsx` was already fully externalized in 11-04 (chrome
strings + the `default_locale` selector field). Verified its current state first; it needed no edits
and was not committed. The plan's Task-2 file list included it, but its externalization was a no-op.

### Redirect-stub files (no strings)

`admin.pulse.index.tsx` and `admin.login.tsx` are one-line `throw redirect(...)` route stubs with no
user-visible strings. Listed in the plan's `files_modified`, but there was nothing to externalize;
neither file was modified or committed.

### No auto-fixes required

No Rule 1/2/3 issues encountered — the sweep was mechanical (add `useTranslation`, replace literals,
add keys). Two map-variable renames (`t` → `tpl` in the template list, `t` → `src` in the clone
source list) were made in `admin.templates.tsx` to avoid shadowing the `useTranslation()` `t` — a
mechanical requirement of introducing `t`, not a behavior change.

## Threat Surface

No new network endpoints, auth paths, or trust boundaries introduced. Catalog values are interpolated
by React (auto-escaped); no `dangerouslySetInnerHTML` on any catalog value (T-11-01 held). Error
toasts continue to surface existing server `error` strings with no new detail (T-11-05 held).

## Known Stubs

None. All targeted surfaces render fully from catalogs with nl fallback guaranteed by the 11-01
runtime.

## Notes for Orchestrator

- STATE.md / ROADMAP.md deliberately NOT modified (orchestrator owns those writes for the wave).
- The FULL CI Dutch-string guard was intentionally NOT run as a pass gate — that is 11-09's (Wave-4)
  job; sibling 11-05 files still contain Dutch while this plan ran.
- Merge note: all three `admin.json` files were extended here; 11-04 was the prior sequential writer
  in the same wave chain, so these edits are purely additive after its `spaceForm` block.

## Self-Check: PASSED

- All 10 modified source files + 3 catalog files exist on disk
- SUMMARY.md exists on disk
- Commits a73f69e, d18eb8c present on `worktree-agent-a3aebac3e7efcca95`
- No file deletions across either commit
