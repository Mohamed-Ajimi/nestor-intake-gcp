---
quick_id: 260724-vyf
slug: broaden-researchrunprogress-mount-gate-t
status: complete
date: 2026-07-24
commit: 4398edb
tasks_completed: 1
---

# Quick Task 260724-vyf Summary

Broadened the `ResearchRunProgress` mount gate so the Phase-15 post-run forensic
surfaces stay reachable after a run finishes, not only during the live
`in_research` window.

## What Changed

`frontend/src/routes/admin.pulse.intakes.$id.tsx` (commit `4398edb`):

1. Added module-level `RESEARCH_SURFACE_STATUSES = new Set(["in_research",
   "delivered", "archived"])` next to `STATUS_WITH_BANNER` / `STATUS_WITH_HINT`.
2. Changed the mount condition from `intake.status === "in_research"` to
   `intake.status && RESEARCH_SURFACE_STATUSES.has(intake.status)`.
3. Updated the surrounding comment to record that the surfaces persist post-delivery
   as a frozen replay for superadmin review.

## Why

Phase 15 turned `ResearchRunProgress` into a persistent forensic surface (D15 feed
replay, "View verification report" button, facts-only cost, numbered citations), but
it was still gated to the Phase-16 live-window status `in_research`. Uploading the
report PDF flips the intake to `delivered`, which unmounted the whole panel — so the
superadmin lost the verification report/button the instant a run was delivered.
Surfaced during the Phase-15 operator UAT (a `delivered` intake had no button).

`ResearchRunProgress` already renders a terminal "frozen replay" card
(`ResearchRunProgress.tsx:583`), so showing it on terminal statuses is safe.

## Verification

- `cd frontend && npx tsc --noEmit` → exit 0 (clean).
- Statuses confirmed against `STATUS_VALUES` — no raw `completed` status exists; the
  "completed" phase is derived by the phase machine from `delivered` +
  `results_link_sent_at`, so it is correctly covered by `delivered`.
- No change to route mounting (still `admin.pulse.*` only) or server proxies →
  client-role blindness / 16-D-08 intact.

## Known Limitations (NOT bugs — out of scope)

- **Surfacing only, not backfill.** A real run that predates the Phase-15 migration
  (e.g. the live run-4cbb5311 from 2026-07-22) has NULL `verification_summary`, no
  verdict rows, and the old `stage_detail` shape. The button now appears on that
  delivered intake, but the verification report body will be empty/404
  (existence-hidden) and the feed/cost render in the old shape. Populated Phase-15
  data still requires the recorded-run seed OR a fresh post-Phase-15 run.
- **Deployed 2026-07-24.** Frontend rebuilt via Cloud Build (image
  `frontend:20260724-231312`, build `6b0f8f62` SUCCESS, Supabase-leak guard passed) and
  deployed to `nestor-frontend` — live rev **`nestor-frontend-00025-4w8`**, serving 100%
  traffic (root returns 307 SSR redirect = healthy). No pass-2 URL re-wiring needed (same
  frontend origin; CORS/APP_BASE_URL unchanged).

## Self-Check: PASSED

- File modified: admin.pulse.intakes.$id.tsx — FOUND.
- Commit 4398edb — present in git log.
- tsc --noEmit — clean.
</content>
