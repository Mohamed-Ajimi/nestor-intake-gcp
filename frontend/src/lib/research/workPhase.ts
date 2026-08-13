// frontend/src/lib/research/workPhase.ts — the one rule for what the `in_research` work-phase
// banner is allowed to CLAIM, extracted as a pure module so it can be measured by real
// assertions rather than asserted in a comment (23-02, UAT-22-F4).
//
// THE DEFECT THIS CLOSES. `derivePhase` (`lib/intake-phase.ts:65-81`) returns `in_research`
// from the intake STATUS alone, and that status deliberately survives until the explicit
// Deliver act (`components/intake/FinalReportBlock.tsx`). So one phase spans two materially
// different situations — work in flight, and work long finished awaiting a human — and the
// banner printed running copy for both. The operator's report, verbatim: "why does it say:
// Work phase / Research running. ... when research is done?"
//
// THIS MODULE SITS BESIDE THE PHASE MACHINE AND DOES NOT MODIFY IT. Splitting the intake
// STATUS is explicitly out of scope: `IntakeWorkflowStepper`, `ContextPackBlock`,
// `ResearchArtifacts` and `FinalReportBlock` all gate on `in_research`. Only the
// PRESENTATION is split here.
//
// THE VOCABULARY IS ENUMERATED ON PURPOSE. It is deliberately NOT derived from
// `RESEARCH_TERMINAL` in `lib/api/research.ts`, and deliberately NOT written as a negation of
// `queued` and `running`. That set answers "WHEN DOES THE STREAM STOP" — a different question
// that merely shares part of its answer today. It lumps `completed` together with `failed` and
// `parked`, and this rule must tell those three apart precisely because each licenses
// different words on screen. Importing it would let an edit made for the stream's own reasons
// silently rewrite what the operator is told about their run. A negation is worse still: it
// defaults every status nobody has thought about INTO one of the two confident claims.

/**
 * What the work-phase banner may claim about a research run.
 *
 * Five presentations, not two, because "not running" is three distinct situations that carry
 * three different operator actions: the run finished, the run ended without finishing, or the
 * run is waiting on a human.
 */
export type WorkPhasePresentation = "running" | "finished" | "stopped" | "paused" | "unknown";

/**
 * Map a research run's status to the one presentation the banner may use.
 *
 * Each mapping has its own reason:
 *
 * - `running`, `queued` → `running`. A queued run has been accepted and not yet started. The
 *   operator's action is identical to `running` (wait, or upload artifacts per research
 *   question), and it becomes `running` within seconds. Called out explicitly so the small
 *   imprecision is a recorded decision rather than an oversight.
 * - `completed`, `completed_degraded` → `finished`. A degraded run IS finished. Its
 *   degradation is announced by the verification report's own G-10 sentence, not by pretending
 *   the engine is still working. Routing it anywhere near the failure treatment strips
 *   evidence off a run already paid for in full — the same trap
 *   `components/research/RunStatusCard.tsx:20-27` records.
 * - `failed`, `cancelled` → `stopped`. Nothing is running, and the run did not finish. The
 *   banner must claim neither "running" nor "finished"; both would be false.
 * - `parked`, `needs_input` → `paused`. Nothing is running and the run is not over: it is
 *   waiting on a HUMAN. `parked` closes the SSE stream precisely because that wait may be
 *   hours long, which is exactly why stream terminality is the wrong question to ask here.
 * - everything else, including `null` and `undefined` → `unknown`. During a rolling deploy an
 *   unheard-of status is the NORMAL state of the world, not an anomaly. And the hook feeding
 *   this rule holds `null` in three ordinary situations — before the first SSE frame arrives,
 *   when the intake never had a run at all, and when the stream is unavailable — none of which
 *   means the work ended. A default of `finished` would reintroduce the reported defect with
 *   the sign flipped; a default of `stopped` would invent a failure. Absence of data is not a
 *   claim, and this function will not turn it into one.
 *
 * Pure: no I/O, no React, no clock, no engine import.
 */
export function deriveWorkPhasePresentation(
  runStatus: string | null | undefined,
): WorkPhasePresentation {
  switch (runStatus) {
    case "running":
    case "queued":
      return "running";

    case "completed":
    case "completed_degraded":
      return "finished";

    case "failed":
    case "cancelled":
      return "stopped";

    case "parked":
    case "needs_input":
      return "paused";

    default:
      return "unknown";
  }
}
