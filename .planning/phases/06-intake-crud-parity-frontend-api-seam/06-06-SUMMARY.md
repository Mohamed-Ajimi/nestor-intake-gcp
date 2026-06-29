---
phase: 06-intake-crud-parity-frontend-api-seam
plan: 06
subsystem: frontend-intake-surface
tags: [re-point, lib-api-seam, section-batch-save, scope-ceiling, phase-machine, realtime-to-poll]
requires:
  - "06-05 lib/api seam: intakes.ts (getIntake/submitIntake/reviewIntake), answers.ts (listAnswers/saveAnswers + AnswerInput), skillRuns.ts (listSkillRuns), templates.ts (getTemplates)"
  - "intake-phase.ts derivePhase (unchanged) + PhaseSkillRunInput { status, applied_at }"
provides:
  - "admin.pulse.intakes.$id.tsx driven entirely by lib/api (no inline supabase)"
  - "IntakeForm.tsx section-batch save (D-03) with dirty/error affordances + navigation gated on save"
  - "AIReviewPanel/SkillRunProgress/ContextPackBlock re-pointed to the seam; realtime -> bounded poll"
affects:
  - "Phase 7 wires the AI backends (apply-intake-skill, generate-context-pack, semantic-search) behind the stubs left here"
  - "Phase 8 swaps the SkillRunProgress poll for SSE without touching callers (contract stable)"
  - "Phase 10 wires transactional email behind the neutralized send-mail CTAs"
tech-stack:
  added: []
  patterns:
    - "section-batch save: per-section dirty set + one answers.saveAnswers PATCH on advance/leave/submit; navigation gated on ApiResult.success (UI-SPEC Net-New 3)"
    - "value/value_json reconcile: toAnswerInput maps string -> value, everything else -> value_json (mirrors backend AnswerView)"
    - "realtime -> polled read with a STABLE external hook contract so the Phase-8 SSE swap needs no caller edits"
    - "scope-ceiling deletion: run-research + send-pulse-mail invokes removed; status moves only via allow-listed submit/review transitions"
key-files:
  created: []
  modified:
    - "frontend/src/components/intake/IntakeForm.tsx"
    - "frontend/src/routes/admin.pulse.intakes.$id.tsx"
    - "frontend/src/components/intake/AIReviewPanel.tsx"
    - "frontend/src/components/intake/SkillRunProgress.tsx"
    - "frontend/src/components/intake/ContextPackBlock.tsx"
decisions:
  - "submitReview returns intakeId (not a minted validation token) — the token model is retired (Phase 3 D-08); the authenticated user surface reaches the intake via /intake/{id}"
  - "handleStatusChange routes only the allow-listed transitions (submitted/reviewed/validated_by_client) through submit/review verbs; any target past decomposed surfaces a not-available toast (INTAKE-05 at the UI, mirroring the data-layer 409)"
  - "Phase-7 (apply-intake-skill, generate-context-pack, semantic-search) and post-decomposed token/delivered/research surfaces are NEUTRALIZED (notice toasts / empty state), not fully wired — per RESEARCH A4 / Bucket B+E"
  - "useSkillRunFull returns null: the heavy output_parsed/cost is a Phase-7 payload not projected by the read-only skill-run seam; review-mode correctly stays inactive pre-Phase-7"
requirements: [API-03, INTAKE-01, INTAKE-03, INTAKE-05]
metrics:
  duration: "~40 min"
  completed: "2026-06-29"
  tasks: 3
  files: 5
---

# Phase 6 Plan 06: Re-point Admin Intake Lifecycle + Child Components Summary

Re-pointed the heaviest screen (the ~1500-line admin intake lifecycle page) and the four
intake child components off inline Supabase onto the `lib/api/*` seam from plan 05, and
converted `IntakeForm` from per-field debounced RPC saves to the batched save-per-section
interaction (D-03) with navigation gated on save success. The `run-research` invoke + CTA and
the `send-pulse-mail` invokes are deleted (INTAKE-05 / Phase ceiling). `derivePhase` is fed
seam data unchanged. Phase-7 AI surfaces, Phase-10 email, and the post-`decomposed`
token/delivered/research surfaces are neutralized (notice toasts / empty state) per the
Bucket B/E + Phase-Ceiling guidance — not fully wired here.

## What Was Built

### Task 1 — IntakeForm section-batch save (commit d104771)
- Removed the per-field debounced `save_intake_answer` RPC + the 800ms timer; edits now mark
  the section dirty (`dirtyFields` set) with no network call.
- Added `saveCurrentSection()` → `answers.saveAnswers(intakeId, batch)` where the batch is the
  section's dirty fields mapped through `toAnswerInput` (string → `value`, else → `value_json`).
  Wired into `goToSection`/`handleNext`/`doSubmit`: the leaving section PATCHes BEFORE
  navigating and a failed `ApiResult` does NOT advance (UI-SPEC Net-New 3 failure contract,
  with the exact Dutch copy "Opslaan mislukt — je wijzigingen in deze sectie zijn niet bewaard.
  Probeer opnieuw.").
- `SaveStatus` slot now drives `Niet opgeslagen` / `Opslaan…` / `Alle wijzigingen opgeslagen` /
  `Opslaan mislukt`; the section-nav mark shows the outline state while dirty.
- `doSubmit` → `intakes.submitIntake(id)`; the validation-phase proposals read (legacy
  skill_runs/output_parsed) removed (proposals are Phase-7 AI output). No inline supabase.

### Task 2 — admin.pulse.intakes.$id.tsx data-layer re-point + scope deletions (commit cbf4373)
- `load()` now reads `intakes.getIntake(id)` + `answers.listAnswers(id)` + `templates.getTemplates()`
  (template schema for rendering); the local rich `Intake` row is populated from the seam's
  status + five phase markers, with retired token/title/product/timestamp fields left neutral.
- `derivePhase` fed the seam intake + `useActiveSkillRun` latest run + `hasResearchArtifacts=false`.
- `handleSave` batches changed answers into one `answers.saveAnswers` PATCH; `handleStatusChange`
  routes through the allow-listed `submitIntake`/`reviewIntake` verbs only; `loadSkillRuns` reads
  `skillRuns.listSkillRuns`.
- **Deleted** the `functions.invoke("run-research", …)` call (INTAKE-05) and the three
  `send-pulse-mail` invokes (Phase 10). Neutralized the Phase-7 AI invokes
  (apply-intake-skill / generate-context-pack / semantic-search) and the post-decomposed
  token-regeneration + delivered-date writes. No inline supabase.

### Task 3 — AIReviewPanel + SkillRunProgress + ContextPackBlock (commit 973eaee)
- AIReviewPanel: `persistApprovedField` + `submitReview` write via `answers.saveAnswers`;
  `submitReview` ends with `intakes.reviewIntake(intakeId)` (submitted→reviewed) and returns
  `intakeId` (no validation-token mint).
- SkillRunProgress: the Supabase Realtime `.channel()` subscription (+ `removeChannel`) replaced
  by a bounded 5s poll over `skillRuns.listSkillRuns` (`toActiveSkillRun` reconciles the view into
  the `ActiveSkillRun` contract); the exported hook signatures are unchanged so callers — and the
  Phase-8 SSE swap — need no edits. `useSkillRunFull` returns null (heavy output is Phase 7).
- ContextPackBlock: the context-pack skill_runs reads + the `research_questions` read are guarded
  off (Phase 7 / post-decomposed); `generateContextPack` is a Phase-7 notice. No inline supabase.

## Deviations from Plan

None that change scope. All Phase-7 / Phase-10 / post-`decomposed` surfaces were **neutralized**
(notice toasts + empty state) rather than fully wired, exactly as the plan's `<action>` blocks and
RESEARCH A4 / Bucket B+E + the Phase-Ceiling Note direct (the corresponding backends land in later
phases). No new dependencies, no shared-artifact edits.

## Verification

node_modules is ABSENT in this fresh parallel worktree (per the orchestrator note), so the
authoritative `tsc --noEmit` + `npm run build` + vitest run on the merged tree is deferred to the
orchestrator. The plan's grep acceptance gates were run live and are clean:

- Task 1: `grep -oh "supabase" IntakeForm.tsx` = 0; `save_intake_answer` = 0; `submit_intake` = 0;
  `saveAnswers` present (call + import); `submitIntake` present; the Dutch save-failure copy present;
  the error branch returns before navigating.
- Task 2: `grep -oh "supabase\|run-research\|send-pulse-mail" admin.pulse.intakes.$id.tsx` = 0;
  `derivePhase` present (4); `@/lib/api/intakes` imported; no residual `.from(`/`.rpc(`/`functions.invoke`.
- Task 3: `grep -oh "supabase\|.channel(" AIReviewPanel SkillRunProgress ContextPackBlock` = 0;
  `removeChannel` = 0; `listSkillRuns` used by SkillRunProgress; exported hook signatures unchanged.
- Overall: all five files report 0 `supabase`; no dangling references to removed symbols
  (`saveField`, `saveTimers`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SkillRunRealtimeRow`,
  `validationToken`, `crypto.randomUUID`).

### Deferred live-runs (no node_modules on this machine)
- `cd frontend && npx tsc --noEmit` (touched files) — run on the merged tree by the orchestrator.
- `cd frontend && npm run build` — merged-tree build.
- `cd frontend && npm run test` (vitest derivePhase characterization) — derivePhase is unchanged,
  expected green.

## Known Stubs

All are plan-sanctioned seam-ahead-of-backend, gated so they do not render misleading data in this
milestone (the flow stops at `decomposed`):

| Stub | File | Reason / resolves in |
|------|------|----------------------|
| `runSkill` notice | admin.pulse.intakes.$id.tsx | apply-intake-skill AI backend — Phase 7 |
| `onGenerateContextPack` / `ContextPackBlock` empty state | admin route + ContextPackBlock.tsx | generate-context-pack backend — Phase 7 |
| `handleSemanticSearch` notice | admin.pulse.intakes.$id.tsx | semantic-search backend — Phase 7 (panel also gated off: hasArtifacts=false) |
| `useSkillRunFull` returns null | SkillRunProgress.tsx | heavy output_parsed not in the read-only seam — Phase 7 |
| validation-phase `proposals` stays null | IntakeForm.tsx | skill output_parsed — Phase 7 |
| email CTAs (validation/reminder/results) notice | admin.pulse.intakes.$id.tsx | transactional email — Phase 10 |
| `DeliveredAtEditor` / `ResultsLinkRow` regenerate notices | admin.pulse.intakes.$id.tsx | post-decomposed / retired token model — out of milestone |

None of these block the plan goal (admin lifecycle to `decomposed` + save-per-section + scope
ceiling), and none render hardcoded data into a path the milestone reaches.

## Threat Flags

None — all surface stays within the plan's `<threat_model>`. The three mitigations are implemented:
T-06-16 (run-research invoke + CTA deleted), T-06-17 (derivePhase is UX gating only; transitions are
backend-driven via submit/review verbs), T-06-18 (all `supabase.from(...)` removed from the five
files; data flows through the token-attaching seam).

## Self-Check: PASSED
- All 5 modified files present and re-pointed (grep `supabase` = 0 each)
- Commits d104771, cbf4373, 973eaee present in git log
- run-research / send-pulse-mail = 0 in the admin route
- SUMMARY.md created
