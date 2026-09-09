import { describe, it, expect } from "vitest";
import {
  COLLAPSED_PREVIEW_ROWS,
  hasHiddenRows,
  isRowLive,
  settledSeqs,
} from "@/lib/research/feedRows";

// The two run-feed rules, MEASURED. Both used to live inside RunFeed.tsx, where the absence
// of a DOM environment and a component-render library made them unassertable — so they were
// reviewed by reading, and both were wrong on the operator's screen (21-CONTEXT, D-08/D-09).
// The absent names are spelled out in RunFeed.tsx's header rather than here, because the
// acceptance scan for this file asserts they appear nowhere in it.
//
// Every test below is named after the BEHAVIOUR it protects, not after the function it calls,
// so a regression reports the defect in the operator's words rather than a function name.

/** A feed event reduced to the two fields `settledSeqs` reads. */
function ev(seq: number, kind: string): { seq: number; kind: string } {
  return { seq, kind };
}

describe("settledSeqs — pairing starts to finishes by position (D-07: there is no key)", () => {
  it("two starts and one finish settle the OLDER start only", () => {
    const settled = settledSeqs([ev(1, "agent_run"), ev(2, "agent_run"), ev(3, "agent_done")]);
    expect(settled).toEqual(new Set([1]));
  });

  it("two starts and two finishes settle both, and a failure counts as a finish", () => {
    const settled = settledSeqs([
      ev(1, "agent_run"),
      ev(2, "agent_run"),
      ev(3, "agent_done"),
      ev(4, "agent_fail"),
    ]);
    expect(settled).toEqual(new Set([1, 2]));
  });

  it("an unmatched finish is ignored, never fabricated into a seq", () => {
    const settled = settledSeqs([ev(1, "agent_run"), ev(2, "agent_done"), ev(3, "agent_done")]);
    expect(settled).toEqual(new Set([1]));
    expect(settled.size).toBe(1);
  });

  it("agent_retry settles nothing — the unit of work is still in flight", () => {
    const settled = settledSeqs([ev(1, "agent_run"), ev(2, "agent_retry")]);
    expect(settled.size).toBe(0);
  });

  it("non-agent kinds are inert", () => {
    const settled = settledSeqs([ev(1, "dispatch"), ev(2, "thinking"), ev(3, "summary")]);
    expect(settled.size).toBe(0);
  });
});

describe("settledSeqs — correlated research events", () => {
  const task = (seq: number, kind: string, id: string, attempt = 1, execution = "pass-1") => ({
    seq,
    kind,
    meta: { trace_execution_id: execution, trace_task_id: id, trace_attempt: attempt },
  });
  it("settles the actual finishing task, not the oldest parallel start", () => {
    expect(
      settledSeqs([
        task(1, "agent_run", "a"),
        task(2, "agent_run", "b"),
        task(3, "agent_done", "b"),
      ]),
    ).toEqual(new Set([2]));
  });
  it("never pairs legacy terminals with identified tasks or vice versa", () => {
    expect(
      settledSeqs([
        ev(1, "agent_run"),
        task(2, "agent_run", "b"),
        task(3, "agent_done", "b"),
        ev(4, "agent_done"),
      ]),
    ).toEqual(new Set([2, 1]));
    expect(settledSeqs([task(1, "agent_run", "a"), ev(2, "agent_done")])).toEqual(new Set());
  });
  it("a retry settles its old start but an old failure cannot settle the new attempt", () => {
    expect(
      settledSeqs([
        task(1, "agent_run", "a"),
        task(2, "agent_retry", "a", 2),
        task(3, "agent_run", "a", 2),
        task(4, "agent_fail", "a", 1),
      ]),
    ).toEqual(new Set([1]));
  });
  it("a new pass makes an unfinished earlier pass inactive", () => {
    expect(
      settledSeqs([task(1, "agent_run", "a"), task(2, "agent_run", "a", 1, "pass-2")]),
    ).toEqual(new Set([1]));
  });
  it("a late old-pass row cannot reactivate that pass", () => {
    expect(
      settledSeqs([
        task(1, "agent_run", "a"),
        task(2, "agent_run", "a", 1, "pass-2"),
        task(3, "agent_run", "b"),
      ]),
    ).toEqual(new Set([1, 3]));
  });
});

describe("isRowLive — a spinner is a claim about NOW", () => {
  it("SC2: a finished run shows no spinner anywhere", () => {
    expect(
      isRowLive({
        kind: "agent_run",
        seq: 7,
        settled: new Set<number>(),
        isLastGroup: true,
        feedActive: false,
      }),
    ).toBe(false);
  });

  it("a phase the engine has MOVED PAST shows no spinner", () => {
    expect(
      isRowLive({
        kind: "agent_run",
        seq: 7,
        settled: new Set<number>(),
        isLastGroup: false,
        feedActive: true,
      }),
    ).toBe(false);
  });

  it("a row whose finish line already arrived is not live", () => {
    expect(
      isRowLive({
        kind: "agent_run",
        seq: 7,
        settled: new Set<number>([7]),
        isLastGroup: true,
        feedActive: true,
      }),
    ).toBe(false);
  });

  it("the one live case: an unsettled agent_run in the current phase of a running feed", () => {
    expect(
      isRowLive({
        kind: "agent_run",
        seq: 7,
        settled: new Set<number>([6]),
        isLastGroup: true,
        feedActive: true,
      }),
    ).toBe(true);
  });

  it("a non-agent_run kind never spins, even with all three other conditions true", () => {
    for (const kind of ["agent_done", "thinking"]) {
      expect(
        isRowLive({
          kind,
          seq: 7,
          settled: new Set<number>(),
          isLastGroup: true,
          feedActive: true,
        }),
      ).toBe(false);
    }
  });
});

describe("hasHiddenRows — the toggle only appears when it reveals something (D-09)", () => {
  it("an empty body hides nothing", () => {
    expect(hasHiddenRows(0)).toBe(false);
  });

  it("a body exactly as long as the preview hides nothing", () => {
    expect(hasHiddenRows(2)).toBe(false);
  });

  it("one row past the preview hides something", () => {
    expect(hasHiddenRows(3)).toBe(true);
  });

  it("the default preview length IS the shared constant, not a hardcoded 2", () => {
    expect(hasHiddenRows(COLLAPSED_PREVIEW_ROWS)).toBe(false);
    expect(hasHiddenRows(COLLAPSED_PREVIEW_ROWS + 1)).toBe(true);
  });

  it("an explicit preview length overrides the default", () => {
    expect(hasHiddenRows(3, 5)).toBe(false);
    expect(hasHiddenRows(6, 5)).toBe(true);
  });
});
