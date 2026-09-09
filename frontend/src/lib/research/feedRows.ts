import type { RunEvent } from "@/lib/api/research";
import { latestTraceExecutionId, traceIdentity } from "@/lib/research/groupedTrace";

// frontend/src/lib/research/feedRows.ts — the two rules the run feed renders by, lifted OUT
// of RunFeed.tsx so they can be MEASURED rather than inspected.
//
// This module imports no React and nothing from `@/components`; the only import above is a
// TYPE. That is what lets `feedRows.test.ts` drive both rules under the existing
// node-environment vitest config with zero new dependencies and zero config change — the
// repo has vitest 3.2.4 and `frontend/vitest.config.ts`, but no jsdom and no
// `@testing-library/react`, so a rule that lives inside a component is a rule that cannot be
// asserted.
//
// Two defects live here, both named in 21-CONTEXT:
//   D-08 — an append-only feed can only make claims about NOW on its newest rows, yet an
//          `agent_run` row kept animating forever. `settledSeqs` + `isRowLive` are the fix.
//   D-09 — the collapse toggle rendered on `isComplete` alone while the preview slices
//          `body`, which excludes dividers and summaries. `hasHiddenRows` is the fix.

/** Rows previewed when a completed phase is collapsed — two, per the design. */
export const COLLAPSED_PREVIEW_ROWS = 2;

/**
 * The kinds that END a unit of agent work.
 *
 * `agent_retry` is DELIBERATELY EXCLUDED. A retry means the unit of work is still in flight —
 * the engine is having another go at the same thing — so settling on it would re-create the
 * very defect this module exists to kill, one row earlier and harder to see.
 */
export const AGENT_TERMINAL_KINDS: ReadonlySet<string> = new Set(["agent_done", "agent_fail"]);

/**
 * Which `agent_run` rows in a group have already had their finish line arrive.
 *
 * New research events settle by execution/task/attempt identity. Older events and workshop
 * rows have no reliable key: retain their historical FIFO display heuristic, but NEVER pair
 * them with correlated rows. FIFO is not proof of a specific parallel task's completion.
 *
 * Walk the group's events in order holding a FIFO of the `seq` values of `agent_run` rows seen
 * and not yet paired. Each terminal row shifts the OLDEST unpaired `seq` off that list and
 * settles it. A terminal row arriving with nothing unpaired is IGNORED — never a thrown error
 * and never a fabricated seq, because a feed row is not worth an exception and inventing a
 * seq would settle a row the engine never finished.
 *
 * The two degradations, and why both fail in the right direction:
 *   - MORE terminals than starts (a backfill page that begins mid-stage) settles nothing
 *     extra; the surplus finishes are dropped.
 *   - FEWER terminals than starts leaves the NEWEST rows unsettled, so the spinner survives
 *     on the most recent work rather than on the oldest — which is the correct direction to
 *     fail, since the newest row is the one for which "now" is still plausible.
 */
export function settledSeqs(
  events: ReadonlyArray<Pick<RunEvent, "seq" | "kind" | "meta">>,
): Set<number> {
  const settled = new Set<number>();
  const unpaired: number[] = [];
  const correlated: { seq: number; identity: string; attempt: number; execution: unknown }[] = [];
  const latestExecution = latestTraceExecutionId(events);
  for (const ev of events) {
    const identity = traceIdentity(ev);
    if (identity) {
      const attempt = typeof ev.meta?.trace_attempt === "number" ? ev.meta.trace_attempt : 1;
      if (ev.kind === "agent_run") {
        correlated.push({ seq: ev.seq, identity, attempt, execution: ev.meta?.trace_execution_id });
      } else if (AGENT_TERMINAL_KINDS.has(ev.kind) || ev.kind === "agent_retry") {
        for (const start of correlated) {
          if (
            start.identity === identity &&
            (start.attempt === attempt || (ev.kind === "agent_retry" && start.attempt < attempt))
          )
            settled.add(start.seq);
        }
      }
      continue;
    }
    if (ev.kind === "agent_run") {
      unpaired.push(ev.seq);
      continue;
    }
    if (AGENT_TERMINAL_KINDS.has(ev.kind)) {
      const oldest = unpaired.shift();
      if (oldest !== undefined) settled.add(oldest);
    }
  }
  for (const start of correlated) {
    if (start.execution !== latestExecution) settled.add(start.seq);
  }
  return settled;
}

/**
 * Whether ONE row may still animate — the single place the word "live" is defined.
 *
 * Three conditions in the operator's terms, and a row is live only if none of them bites:
 *   - A run that has ENDED has no live rows at all. `feedActive` false ⇒ false, everywhere.
 *   - A phase the engine has MOVED PAST has no live rows. `isLastGroup` false ⇒ false.
 *   - A row whose FINISH LINE HAS ALREADY ARRIVED is not live, even in the current phase.
 *
 * Written as a single conjunction on purpose. Expressed as a chain of `if` branches, someone
 * later adds a fourth case that grants liveness on three of the four conditions and the
 * spinner comes back. There is no branch here to add one to.
 */
export function isRowLive(input: {
  kind: string;
  seq: number;
  settled: ReadonlySet<number>;
  isLastGroup: boolean;
  feedActive: boolean;
}): boolean {
  return (
    input.kind === "agent_run" &&
    input.feedActive &&
    input.isLastGroup &&
    !input.settled.has(input.seq)
  );
}

/**
 * Whether a collapsed phase is actually hiding anything (D-09).
 *
 * `body` — the array whose length this takes — EXCLUDES dividers and summaries, and
 * `_stage_event_boundary` emits exactly those two for every stage automatically. So a phase
 * that never emits detail rows has an EMPTY `body`, and a toggle rendered above it expands to
 * reveal nothing. That is precisely what the eight silent stages did on the operator's screen.
 * Gate the toggle on this, not on completion.
 */
export function hasHiddenRows(
  bodyLength: number,
  previewRows: number = COLLAPSED_PREVIEW_ROWS,
): boolean {
  return bodyLength > previewRows;
}
