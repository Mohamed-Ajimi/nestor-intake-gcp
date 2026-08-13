import { describe, it, expect } from "vitest";
import { deriveWorkPhasePresentation } from "@/lib/research/workPhase";

// 23-02 Task 1 — the work-phase presentation rule, pinned over ALL EIGHT run statuses
// (`components/research/RunStatusCard.tsx:52-60`) plus the four shapes of ABSENT data.
//
// WHY NAMED TESTS AND NOT ONE TABLE LOOP. This suite exists so that an edit which routes,
// say, `parked` into `finished` fails a test whose NAME says what the operator would then be
// told. A loop over a fixture table would go red naming a row index, and the reviewer would be
// free to "fix" it by editing the table. The names are the argument; the assertions are only
// the proof. Same reasoning as `verificationGate.test.ts`.
//
// THE DEFECT THIS RULE FIXES (UAT-22-F4). The operator saw "Work phase / Research running."
// on an intake whose research had finished, because `derivePhase` returns `in_research` from
// the intake STATUS alone and that status survives until the explicit Deliver act. The last
// describe block below pins the MIRROR of that defect: absent data must never read as
// finished either.

describe("deriveWorkPhasePresentation — work is in flight", () => {
  it("running — the run is working, so the banner may say so", () => {
    expect(deriveWorkPhasePresentation("running")).toBe("running");
  });

  it("queued — accepted but not yet started; the operator's action is identical to running and it becomes running within seconds", () => {
    expect(deriveWorkPhasePresentation("queued")).toBe("running");
  });
});

describe("deriveWorkPhasePresentation — the work has ended and the run finished", () => {
  it("completed — the clean case is finished", () => {
    expect(deriveWorkPhasePresentation("completed")).toBe("finished");
  });

  it("completed_degraded — a degraded run is FINISHED; its degradation is announced by the verification report's own sentence, not by pretending it is still working", () => {
    expect(deriveWorkPhasePresentation("completed_degraded")).toBe("finished");
  });
});

describe("deriveWorkPhasePresentation — the work has ended and the run did NOT finish", () => {
  it("failed — nothing is running and nothing finished, so the banner may claim neither", () => {
    expect(deriveWorkPhasePresentation("failed")).toBe("stopped");
  });

  it("cancelled — the other end-without-finishing state; it must not read as finished", () => {
    expect(deriveWorkPhasePresentation("cancelled")).toBe("stopped");
  });
});

describe("deriveWorkPhasePresentation — nothing is running but the run is not over", () => {
  it("parked — the stream closes precisely because the wait on a human may be hours long; the run is not finished", () => {
    expect(deriveWorkPhasePresentation("parked")).toBe("paused");
  });

  it("needs_input — the clarification pause is a wait on a HUMAN, not an ending", () => {
    expect(deriveWorkPhasePresentation("needs_input")).toBe("paused");
  });
});

describe("deriveWorkPhasePresentation — absent or unheard-of data", () => {
  it("null — the hook holds null before the first SSE frame, when the intake never had a run, and when the stream is unavailable; none of those means the work ended", () => {
    expect(deriveWorkPhasePresentation(null)).toBe("unknown");
  });

  it("undefined — the same absence, reached through a missing field rather than an explicit null", () => {
    expect(deriveWorkPhasePresentation(undefined)).toBe("unknown");
  });

  it("the empty string is not a status", () => {
    expect(deriveWorkPhasePresentation("")).toBe("unknown");
  });

  it("an unheard-of status — during a rolling deploy this is the NORMAL state of the world, not an anomaly", () => {
    expect(deriveWorkPhasePresentation("a_status_nobody_has_shipped_yet")).toBe("unknown");
  });
});

describe("deriveWorkPhasePresentation — THE SAFETY ASSERTION: absence is never an ending", () => {
  it("null never reads as finished or stopped — a default of finished would reintroduce the reported defect with the sign flipped, telling the operator work is over when the page simply has no data", () => {
    const result = deriveWorkPhasePresentation(null);
    expect(result).not.toBe("finished");
    expect(result).not.toBe("stopped");
  });

  it("undefined never reads as finished or stopped — same failure, reached through a missing field", () => {
    const result = deriveWorkPhasePresentation(undefined);
    expect(result).not.toBe("finished");
    expect(result).not.toBe("stopped");
  });

  it("the empty string never reads as finished or stopped — an empty status is missing data, not an ended run", () => {
    const result = deriveWorkPhasePresentation("");
    expect(result).not.toBe("finished");
    expect(result).not.toBe("stopped");
  });

  it("an unheard-of status never reads as finished or stopped — a status this build has not been taught must not be guessed into an ending the engine never reported", () => {
    const result = deriveWorkPhasePresentation("a_status_nobody_has_shipped_yet");
    expect(result).not.toBe("finished");
    expect(result).not.toBe("stopped");
  });
});
