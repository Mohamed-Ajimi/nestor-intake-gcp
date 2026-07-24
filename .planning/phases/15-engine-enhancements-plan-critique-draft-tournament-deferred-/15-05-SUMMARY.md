---
phase: 15-engine-enhancements-plan-critique-draft-tournament-deferred-
plan: 05
subsystem: operator-research-surfaces-d15-feed-verification-report
tags: [react, tanstack, i18n, verification, audit, d15-feed, superadmin, tenant-isolation]
requires:
  - getVerification-proxy                # Plan 15-04 (intake-side superadmin proxy)
  - getAuditBody-proxy                   # Plan 15-04
  - build_verification_report-shape      # Plan 15-03 (VerificationReport shape)
  - enriched-stage_detail-schema         # Plan 15-03 (cost_usd/task_prompt/facts/retry/audit_id + summary)
  - run_4cbb5311-recorded-fixture        # Plan 15-01 (seeds the enriched feed fields)
provides:
  - research.ts-getVerification
  - research.ts-getAuditBody
  - VerificationReport-AuditBody-feed-types
  - D15-agent-feed-renderer
  - AuditBodyPanel-drilldown
  - VerificationReport-component
affects:
  - Operator UAT (recorded run walkthrough vs replit view.png + D15 mockup)
  - Plan 15-06 (Citation type + source snapshot — NOT added here, deliberately deferred)
tech-stack:
  added: []
  patterns:
    - "One-shot getVerification/getAuditBody clone getBundleUrl's apiFetch shape verbatim — transport never forked (skillRuns.ts convention)"
    - "Enriched feed fields all Optional on ResearchStageItem so legacy flat {name,status} rows still type-check (D-07 additive)"
    - "toStageRows grown to a discriminated StageRow union (item | summary) carrying cost/prompt/retry/facts/audit_id + per-block summary rows"
    - "AgentFeed shared by the ACTIVE panel and the COMPLETED summary card so the feed stays frozen + clickable after the run (D15 replay)"
    - "Drill-down affordance hidden when audit_id OR run.id is absent — getAuditBody is never called without a runId"
    - "Superadmin surfaces mount ONLY under admin.pulse.* by placement; enforced by the 16-D-08 route-import grep guard (exit 0)"
    - "Cost is facts-only: cost.pending renders a LABEL, never a number for the pending class (C1)"
key-files:
  created:
    - frontend/src/components/intake/AuditBodyPanel.tsx
    - frontend/src/components/intake/VerificationReport.tsx
  modified:
    - frontend/src/lib/api/research.ts
    - frontend/src/components/intake/ResearchRunProgress.tsx
    - frontend/src/locales/en/intake.json
    - frontend/src/locales/fr/intake.json
    - frontend/src/locales/nl/intake.json
decisions:
  - "The route file admin.pulse.intakes.$id.tsx was VERIFIED no-change: it already passes intakeId={intake.id}; runId is sourced internally from the SSE run's id (run.id). An optional runId? prop was added to ResearchRunProgress for the route to lift the id if it ever prefers to, but the default (run.id) needs no route-signature change — so the route call stays as-is (per plan interfaces note)."
  - "VerificationReport + AuditBodyPanel are imported ONLY by ResearchRunProgress (a component, not a route), which is itself imported only by admin.pulse.intakes.$id.tsx — so neither ever appears in src/routes/ and the 16-D-08 guard is trivially green. No client route can reach them."
  - "The completed-run branch renders the frozen AgentFeed AND the D-09 'View verification report' toggle so the recorded (completed) run's drill-down + report are reachable at UAT — the feed is not collapsed away on terminal status."
  - "Citation type deliberately NOT added to research.ts (that is Plan 15-06); only VerificationReport/AuditBody/enriched-feed types added here, matching the plan Task 1 note."
metrics:
  duration: ~55m
  completed: 2026-07-24
---

# Phase 15 Plan 05: Operator Research Surfaces (D15 Feed + Verification Report) Summary

The operator's professionalism-and-confidence surface, built against the recorded run with no
live LLM run: `ResearchRunProgress` grows from a status checklist into the D15 Replit-style
activity feed (agent cards with task title + expandable prompt, per-row `done · N facts · $X`,
visible retry state, per-block "Worked for X · N actions · $Y" summary cards, scroll-to-latest,
and a frozen-clickable replay after the run), a real audit-body drill-down (`AuditBodyPanel`
fetching `getAuditBody(intakeId, runId, auditId)` — all three ids threaded, no no-op stub), and
a superadmin-only `VerificationReport` (gate funnel + refuted/support/insufficient verdicts +
superseded/scoped + reconciled contradictions + honest unverified list + true itemized cost with
a facts-only pending state). Both surfaces mount ONLY under `admin.pulse.*` — enforced by the
16-D-08 route-import grep guard — over the Plan 15-04 superadmin proxies, so the client sees
nothing and the broken-RLS class of bug cannot recur.

## What Was Built

**Task 1 — `research.ts`: getVerification + getAuditBody + enriched feed/verification types** (`1517c98`):
- `ResearchStageItem` gains `task_prompt?/cost_usd?/facts?/retry{attempt,max,wait_s}?/audit_id?` — ALL OPTIONAL, so today's recorded rows and legacy flat `{name,status}` rows still type-check (D-07 additive).
- New `ResearchStageSummary` (`duration_s/actions/items_read?/cost_usd`) + optional `summary` on the stage-detail group type.
- `VerificationReport` type (funnel, verdicts{support/refute/insufficient}, superseded[], reconciled[], unverified{count,items?}, cost{total,pending}) and `AuditBody` type (`{audit_id, provider, model, request, response}`) matching Plan 15-03's shaper / Plan 15-04's proxy. `Citation` intentionally NOT added (Plan 15-06).
- `getVerification(intakeId, runId)` → GET `/intakes/${intakeId}/research/${runId}/verification` and `getAuditBody(intakeId, runId, auditId)` → GET `/intakes/${intakeId}/research/${runId}/audit/${auditId}`, both cloning `getBundleUrl`'s one-shot `apiFetch` shape (transport unforked); `openResearchStream` untouched.

**Task 2 — D15 agent-feed renderer + audit-body drill-down** (`c9b9321`):
- `toStageRows` grown to a discriminated `StageRow` union: `item` rows carry `cost_usd/task_prompt/retry/facts/audit_id` additively, and a stage's optional `summary` becomes a trailing `summary` row. A row missing any enriched field renders exactly as before (D-07).
- `AgentCard`: task title, expandable `task_prompt` ("Show task"/"Show less"), status line mapping status→lucide icon (spinner/check/rotate-retry/warning-failed/dot-pending) with `done · {facts} facts · ${cost}`, and a visible retry card `retry {attempt}/{max} — waiting {wait}s` (R5 — never hidden).
- `StageSummaryCard`: D15 "Worked for {duration} · {actions} actions · {items_read} items read · ${cost}".
- `AuditBodyPanel.tsx` (created): props `{intakeId, runId, auditId, onClose}`; fetches `getAuditBody(intakeId, runId, auditId)` (return-no-throw + sonner toast on error) and renders the redacted request/response body read-only (pretty-printed JSON) with a provider+model header — NO live-URL fetch, GCS-sourced body only, NOT a no-op stub.
- `AgentFeed` (shared): owns the drill-down open state + scroll-to-latest; used by BOTH the active panel and the completed summary card so the feed stays frozen + clickable. The drill-down affordance is hidden when `audit_id` OR `run.id` is absent, so `getAuditBody` is never called without a runId. `onDrillDown` is `undefined` (not a `() => {}` stub) when a real drill-down is impossible.
- Threading: `ResearchRunProgress` receives `intakeId` (route prop, unchanged), sources `runId` from `run.id` (or an optional `runId?` prop), and passes all three into `AuditBodyPanel`.

**Task 3 — VerificationReport component + en/fr/nl i18n keys** (`eee8d03`):
- `VerificationReport.tsx` (created): fetches `getVerification(intakeId, runId)` on mount (return-no-throw + sonner toast) and renders the gate funnel (each `funnel` stage:count), verdict sections (refuted with `evidence` + `effect`, support, insufficient — each section hidden when empty), superseded/scoped findings, reconciled contradictions, the honest unverified list (`count` + items, or a "none" line), and true itemized cost. When `cost.pending` is true it renders a "tool fees: pending" LABEL beside "Total so far" — NO numeric placeholder for the pending class (C1 facts-only). Markdown fields via `react-markdown` + `remark-gfm` (admin-panel analog).
- Mounted behind the D-09 summary card's "View verification report" toggle in `ResearchRunProgress`'s completed branch — superadmin-only by placement, no new route.
- i18n: `research.feed.*` (13 keys), `audit.*` (10 keys), `verification.*` (23 keys) added to en/fr/nl `intake.json` with identical key sets — `i18n-audit.mjs` CHECK A/B/C green (exit 0).

## Verification Strategy (author-by-construction — tsc/build deferred to CI)

The worktree has NO installed frontend deps (no lockfile is committed, intentional per bunfig;
`node_modules` absent), so `npx tsc` cannot resolve — `npx` returned "This is not the tsc command
you are looking for". This is the established author-by-construction pattern for this repo. The
dep-free gates DID run and pass:

- **`node scripts/i18n-audit.mjs` — EXIT 0 (PASS).** CHECK A (3-way nl/fr/en parity), CHECK B
  (every literal `t()` key resolves in all locales), and CHECK C (no two-arg fallbacks) are all
  clean. The 107 CHECK D advisories are ALL pre-existing hits in `admin.sales.*` / `auth.*` /
  `index.tsx` / `__root.tsx` — NONE in the three files this plan touched (grep-confirmed). CHECK D
  is advisory-only and never fails the gate.
- **Client-route-import guard — EXIT 0.** `! grep -rEln 'VerificationReport|AuditBodyPanel'
  src/routes/ --include='*.tsx' | grep -v 'admin\.'` finds nothing (both components are imported
  only by `ResearchRunProgress`, itself imported only by `admin.pulse.intakes.$id.tsx`).
- **JSON validity:** all three `intake.json` files `JSON.parse` clean.

**tsc (full typecheck) is deferred to Cloud Build / CI** (`cd frontend && npx tsc --noEmit -p
tsconfig.json` once deps are installed), as is `npm run build`. Structural type-consistency was
reviewed by hand: the `StageRow` discriminated union + `Extract<StageRow,{kind:"item"}>` narrowing,
the `runId: string | null` → `string` control-flow narrowing at the `{row.audit_id && runId && ...}`
JSX guard before `<AuditBodyPanel runId={runId}/>`, the enriched-fields-Optional contract, and the
`react-markdown`/`remark-gfm` import shape (identical to `ContextPackBlock.tsx`) all check out.

## Deviations from Plan

None material — plan executed as written across all three tasks. No Rule 1-4 deviations, no auth
gates, no architectural changes, no new packages (T-15-SC holds — reused lucide-react/sonner/
react-markdown/remark-gfm already in the repo).

One implementation choice the plan left to executor judgement: the route file
`admin.pulse.intakes.$id.tsx` was left UNCHANGED (verified no-change). `intakeId` is already passed
at line 1172 and `runId` is sourced internally from the SSE run's `run.id`; an optional `runId?`
prop was added to `ResearchRunProgress` for the route to lift the id if it ever prefers, but the
default path needs no route-signature change (per the plan's interfaces note). The route file is
therefore NOT in this plan's committed diff.

## Known Stubs

None. Every surface returns REAL data through the Plan 15-04 superadmin proxies over Plan 15-03's
recorded-run shapers: the verification report shapes the persisted verdict rows + funnel + true
cost; the audit drill-down reads the actual stored (redacted) GCS blob; the feed renders the
enriched `stage_detail` fields seeded by the Plan 15-01 recorded fixture. The `cost.pending` label
is an honest reconciliation signal (C1), not a placeholder. `onDrillDown` is `undefined` (affordance
hidden), never a no-op handler, when a real drill-down is impossible.

## Threat Flags

None beyond the plan's registered surface. Both new surfaces are covered by the threat register:
- T-15-12 (VerificationReport/feed on a client route) — mounted ONLY under `admin.pulse.*`; the
  16-D-08 route-import grep guard exits 0; server proxy is superadmin-only (Plan 15-04).
- T-15-13 (estimated cost shown to operator) — `cost.pending` renders a LABEL, never a number for
  the pending class (facts-only).
- T-15-13b (audit-body drill-down on a client route / key re-exposure) — AuditBodyPanel is
  superadmin-side only (route-import guard), goes through the Plan 15-04 superadmin proxy, the body
  is already redacted server-side (Plan 15-03), and there is NO live-URL fetch here.
No new network surface (both fetches reuse the existing `apiFetch` transport), no new schema at a
trust boundary, no new packages (T-15-SC).

## Self-Check: PASSED

- Files created — `AuditBodyPanel.tsx`, `VerificationReport.tsx` — both FOUND.
- Files modified — `research.ts`, `ResearchRunProgress.tsx`, `en/fr/nl intake.json` — all present.
- Commits `1517c98`, `c9b9321`, `eee8d03` — all present in `git log`.
- Gates: `i18n-audit.mjs` exit 0 (A/B/C clean); client-route-import guard exit 0; three locales JSON-valid.
