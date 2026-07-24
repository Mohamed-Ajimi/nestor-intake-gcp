---
quick_id: 260724-vyf
slug: broaden-researchrunprogress-mount-gate-t
description: Broaden ResearchRunProgress mount gate to show post-run research surfaces on in_research/delivered/archived intakes
date: 2026-07-24
tasks: 1
---

# Quick Task 260724-vyf: Broaden ResearchRunProgress mount gate

## Problem

Phase-15 added persistent post-run forensic surfaces to `ResearchRunProgress`
(D15 agent-feed replay, "View verification report" button, facts-only cost,
numbered citations). But the component is mounted in
`frontend/src/routes/admin.pulse.intakes.$id.tsx` behind
`intake.status === "in_research"` only (a Phase-16 live-window gate). The moment
the operator uploads the report PDF and the intake flips to `delivered`, every
Phase-15 surface disappears — the superadmin can no longer review the run.

Found during operator UAT (Phase 15 SC1–SC4 walkthrough): a `delivered` intake
showed no "View verification report" button because the whole panel unmounts.

## Fix

`ResearchRunProgress` already handles the terminal/completed run state (it renders
a frozen "replay" summary card with the verification button when the mirrored run
is terminal — `ResearchRunProgress.tsx:583`). So broadening the mount gate to the
post-research statuses is safe: for a terminal run it shows the frozen replay.

Raw intake statuses (STATUS_VALUES): draft, submitted, reviewed,
validated_by_client, decomposed, in_research, delivered, archived. There is NO
raw `completed` status — the phase machine derives the "completed" phase from
`delivered` + `results_link_sent_at`. So the "research has run" status set is:
`in_research`, `delivered`, `archived`.

## Task 1 — Introduce RESEARCH_SURFACE_STATUSES and gate on membership

**files:** frontend/src/routes/admin.pulse.intakes.$id.tsx

**action:**
1. Add a module-level `RESEARCH_SURFACE_STATUSES` Set (`in_research`, `delivered`,
   `archived`) alongside `STATUS_WITH_BANNER` / `STATUS_WITH_HINT` (~line 166).
2. Change the mount condition (~line 1171) from
   `intake.status === "in_research"` to
   `intake.status && RESEARCH_SURFACE_STATUSES.has(intake.status)`.
3. Update the adjacent comment to note the surfaces persist post-delivery for
   superadmin review (frozen replay), not just during the live run.

**verify:** `cd frontend && npx tsc --noEmit` clean; grep confirms the new set is
defined and the gate references it; `ResearchRunProgress` still mounts only on the
admin route (unchanged — client blindness / 16-D-08 intact).

**done:** A `delivered` (and `archived`) intake with a completed run renders the
ResearchRunProgress replay card + "View verification report" button for the
superadmin; `in_research` behavior unchanged.

## Out of scope / notes

- Does NOT populate Phase-15 data on pre-Phase-15 runs — a real delivered run from
  before the migration still has NULL verification_summary, so the report body will
  be empty/404 (existence-hidden). This task only fixes *surfacing*, not backfill.
- No i18n, backend, or route-guard changes. Client-role blindness is unaffected
  (the panel mounts only under `admin.pulse.*` and server proxies stay superadmin-only).
</content>
</invoke>
