// frontend/src/lib/research/verificationGate.ts — the one rule for whether a research run's
// claims-verification report can exist yet, extracted as a pure module so it can be measured
// by real assertions rather than asserted in a comment (21-02, SC4/D-11).
//
// WHY THIS IS ITS OWN FILE. `ResearchRun` (`lib/api/research.ts`) carries no
// `verification_summary` field, so no page can learn from the run row whether a report was
// written. The only thing the browser holds is the run's STATUS, so the gate is on status —
// and `VerificationReport` owns its own empty/error state for the case where the status
// allows a report that the run never actually produced. That is one request, made only when
// the operator asks for it, and one honest error line.
//
// THE SET IS ENUMERATED ON PURPOSE. It is deliberately NOT derived from the terminal-status
// set in `lib/api/research.ts` and deliberately NOT written as a negation of `queued` and
// `running`. Those two shortcuts happen to produce today's answer, and both would silently
// change this rule the next time the set they lean on is edited for its own unrelated reason —
// terminality answers "when does the stream stop", which is a different question that merely
// shares an answer right now. A negation is worse still: it defaults every status nobody has
// thought about INTO the affordance.

/**
 * Whether a research run in `status` can have a claims-verification report.
 *
 * True for exactly five statuses, each for its own reason:
 *
 * - `completed` — the clean case.
 * - `completed_degraded` — a degraded run still cost around forty-five dollars and keeps
 *   everything a clean run keeps, its verification report included. This is the same trap
 *   `components/research/RunStatusCard.tsx:20-27` records: routing a degraded run anywhere
 *   near the failure treatment strips evidence off a run already paid for in full.
 * - `failed` and `cancelled` — these are the two states whose evidence matters MOST, and the
 *   two the embedded intake card throws away. The run page's card/feed sibling rule and D-11
 *   exist precisely to stop that, and the verification report is evidence in the same sense
 *   the feed is. A run that failed AFTER the verify stage has real verdicts; refusing to show
 *   them would repeat the exact defect this phase is closing.
 * - `parked` — a park happens AFTER paid work. Whatever verification had completed by then is
 *   still real, and the run is not finished, only waiting on a human.
 *
 * False for everything else:
 *
 * - `queued` and `running` — the pipeline has not reached the verify stage, so there is
 *   nothing to fetch. Offering the affordance would be an offer the page cannot keep.
 * - `needs_input` — the clarification pause fires BEFORE research (16-CONTEXT D-01/D-01b
 *   records that it never fires for seam runs at all), so like `queued` there is nothing
 *   behind it.
 * - An UNKNOWN status — during a rolling deploy an unheard-of status is the NORMAL state of
 *   the world, not an anomaly. Defaulting a new status into the affordance is how an offer the
 *   seam refuses reaches the screen; a new status that should be offered is a deliberate
 *   one-line edit here, made by someone who has read the reasons above.
 */
export function canHaveVerificationReport(status: string): boolean {
  return (
    status === "completed" ||
    status === "completed_degraded" ||
    status === "failed" ||
    status === "cancelled" ||
    status === "parked"
  );
}
