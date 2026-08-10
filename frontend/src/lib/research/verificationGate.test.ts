import { describe, it, expect } from "vitest";
import { canHaveVerificationReport } from "@/lib/research/verificationGate";

// 21-02 Task 1 — the availability rule for the run page's verification report, pinned over
// ALL EIGHT run statuses (`components/research/RunStatusCard.tsx:52-60`) plus an unknown one.
//
// WHY EIGHT NAMED TESTS AND NOT ONE TABLE LOOP. The point of this suite is that a future edit
// which flips `failed` or `cancelled` back out of the set fails a test whose NAME says what
// was lost. A loop over a fixture table would go red with a message naming a row index, and
// the reviewer would then be free to "fix" it by editing the table. These names are the
// argument; the assertions are only the proof.

describe("canHaveVerificationReport — the five statuses that can have a report", () => {
  it("completed — the clean case has a report", () => {
    expect(canHaveVerificationReport("completed")).toBe(true);
  });

  it("completed_degraded — a degraded run keeps everything a clean run keeps, report included", () => {
    expect(canHaveVerificationReport("completed_degraded")).toBe(true);
  });

  it("failed — D-11: a run that failed after the verify stage has real verdicts, and this is one of the two states whose evidence the embedded intake card throws away", () => {
    expect(canHaveVerificationReport("failed")).toBe(true);
  });

  it("cancelled — D-11: the other state whose evidence the embedded intake card throws away; the run page must not repeat that", () => {
    expect(canHaveVerificationReport("cancelled")).toBe(true);
  });

  it("parked — a park happens after paid work, so whatever verification completed is still real", () => {
    expect(canHaveVerificationReport("parked")).toBe(true);
  });
});

describe("canHaveVerificationReport — the three statuses with nothing behind them", () => {
  it("queued — the pipeline has not reached the verify stage, so the affordance would be an offer the page cannot keep", () => {
    expect(canHaveVerificationReport("queued")).toBe(false);
  });

  it("running — same as queued: verify has not run yet", () => {
    expect(canHaveVerificationReport("running")).toBe(false);
  });

  it("needs_input — the clarification pause fires BEFORE research, so there is nothing to fetch", () => {
    expect(canHaveVerificationReport("needs_input")).toBe(false);
  });
});

describe("canHaveVerificationReport — the unknown status", () => {
  it("an unheard-of status is NOT offered — a rolling deploy makes this the normal state of the world, and defaulting a new status into the affordance is how an offer the seam refuses reaches the screen", () => {
    expect(canHaveVerificationReport("teleported")).toBe(false);
  });

  it("the empty string is not a status and is not offered", () => {
    expect(canHaveVerificationReport("")).toBe(false);
  });
});
