import { describe, expect, it } from "vitest";

import type { ResearchRun, ResearchRunHistoryItem } from "@/lib/api/research";
import {
  RESEARCH_IN_FLIGHT_STATUSES,
  RESEARCH_SUCCESS_STATUSES,
  canChooseRun,
  canDownloadRunZip,
  classifyRerunFailure,
  mergeLiveRun,
  rerunState,
  resolveChosenRun,
  runStatusBadge,
  sortRunsNewestFirst,
} from "@/lib/research/runHistory";

/**
 * Phase 23.6 plan 03 — the run-history rules the operator relies on: which run carries the
 * "chosen run" badge, when Rerun is allowed, and what a failed rerun toast claims about money.
 */

function run(
  id: string,
  attempt: number,
  status: string,
  extra: Partial<ResearchRunHistoryItem> = {},
): ResearchRunHistoryItem {
  return {
    id,
    attempt,
    status,
    created_at: `2026-09-2${attempt}T10:00:00Z`,
    started_at: null,
    completed_at: null,
    cost_usd_total: null,
    chain_status: null,
    chosen_at: null,
    ...extra,
  };
}

function live(id: string, extra: Partial<ResearchRun> = {}): ResearchRun {
  return {
    id,
    status: "running",
    current_stage: null,
    stage_detail: null,
    cost_usd_total: null,
    started_at: null,
    completed_at: null,
    error_message: null,
    chain_status: null,
    chain_broken_at: null,
    bundle_key: null,
    event_seq: null,
    ...extra,
  };
}

describe("status sets mirror backend/app/research/run_status.py", () => {
  it("in-flight is exactly queued, running, needs_report_spec", () => {
    expect([...RESEARCH_IN_FLIGHT_STATUSES].sort()).toEqual(
      ["needs_report_spec", "queued", "running"].sort(),
    );
  });

  it("parked is NOT in flight (UI-6)", () => {
    expect(RESEARCH_IN_FLIGHT_STATUSES.has("parked")).toBe(false);
  });

  it("success is exactly completed and completed_degraded", () => {
    expect([...RESEARCH_SUCCESS_STATUSES].sort()).toEqual(["completed", "completed_degraded"]);
  });
});

describe("sortRunsNewestFirst", () => {
  it("orders by attempt descending", () => {
    const runs = [run("a", 1, "failed"), run("c", 3, "running"), run("b", 2, "completed")];
    expect(sortRunsNewestFirst(runs).map((r) => r.attempt)).toEqual([3, 2, 1]);
  });

  it("breaks an attempt tie by later created_at first", () => {
    const early = run("early", 2, "failed", { created_at: "2026-09-20T10:00:00Z" });
    const late = run("late", 2, "failed", { created_at: "2026-09-21T10:00:00Z" });
    expect(sortRunsNewestFirst([early, late]).map((r) => r.id)).toEqual(["late", "early"]);
  });

  it("does not mutate its input", () => {
    const runs = [run("a", 1, "failed"), run("b", 2, "completed")];
    const copy = [...runs];
    sortRunsNewestFirst(runs);
    expect(runs).toEqual(copy);
  });
});

describe("mergeLiveRun", () => {
  it("overlays the live frame onto the matching row", () => {
    const runs = [run("a", 1, "queued"), run("b", 2, "completed")];
    const merged = mergeLiveRun(
      runs,
      live("a", {
        status: "running",
        cost_usd_total: "3.10",
        started_at: "2026-09-25T10:00:00Z",
        completed_at: null,
        chain_status: null,
      }),
    );
    expect(merged[0]).toMatchObject({
      id: "a",
      attempt: 1,
      status: "running",
      cost_usd_total: "3.10",
      started_at: "2026-09-25T10:00:00Z",
    });
    expect(merged[1]).toEqual(runs[1]);
  });

  it("returns the runs unchanged for an unknown live id", () => {
    const runs = [run("a", 1, "queued")];
    expect(mergeLiveRun(runs, live("zzz"))).toEqual(runs);
  });

  it("returns the runs unchanged for a null live frame", () => {
    const runs = [run("a", 1, "queued")];
    expect(mergeLiveRun(runs, null)).toEqual(runs);
  });
});

describe("resolveChosenRun", () => {
  it("returns the explicitly marked run", () => {
    const runs = [run("a", 1, "completed"), run("b", 2, "completed")];
    expect(resolveChosenRun(runs, "a")).toEqual({ runId: "a", source: "marked" });
  });

  it("defaults to the newest finished run when nothing is marked", () => {
    const runs = [
      run("a", 1, "completed"),
      run("b", 2, "completed_degraded"),
      run("c", 3, "running"),
    ];
    expect(resolveChosenRun(runs, null)).toEqual({ runId: "b", source: "default" });
  });

  it("a newer failed run does NOT take the default", () => {
    const runs = [run("a", 1, "completed"), run("b", 2, "failed")];
    expect(resolveChosenRun(runs, null)).toEqual({ runId: "a", source: "default" });
  });

  it("returns none when no run finished", () => {
    const runs = [run("a", 1, "failed"), run("b", 2, "parked")];
    expect(resolveChosenRun(runs, null)).toEqual({ runId: null, source: null });
  });

  it("falls back to the default rule when the marked id is not in the list", () => {
    const runs = [run("a", 1, "completed")];
    expect(resolveChosenRun(runs, "gone")).toEqual({ runId: "a", source: "default" });
  });

  it("a marked run keeps the badge when a newer run finishes", () => {
    const runs = [run("a", 1, "completed"), run("b", 2, "completed")];
    expect(resolveChosenRun(runs, "a").runId).toBe("a");
  });
});

describe("canChooseRun", () => {
  const marked = { runId: "a", source: "marked" as const };
  const deflt = { runId: "b", source: "default" as const };

  it("allows a finished, unmarked run on an active intake", () => {
    expect(canChooseRun(run("b", 2, "completed"), marked, "delivered")).toBe(true);
    expect(canChooseRun(run("b", 2, "completed_degraded"), marked, "in_research")).toBe(true);
  });

  it("refuses the explicitly marked run", () => {
    expect(canChooseRun(run("a", 1, "completed"), marked, "delivered")).toBe(false);
  });

  it("allows the default-badged run so the default can be made explicit", () => {
    expect(canChooseRun(run("b", 2, "completed"), deflt, "delivered")).toBe(true);
  });

  it("refuses on an archived intake", () => {
    expect(canChooseRun(run("b", 2, "completed"), marked, "archived")).toBe(false);
  });

  it("refuses parked, failed and running runs", () => {
    for (const s of ["parked", "failed", "running"]) {
      expect(canChooseRun(run("b", 2, s), marked, "delivered")).toBe(false);
    }
  });
});

describe("canDownloadRunZip", () => {
  it("allows a finished run with a verified chain", () => {
    expect(canDownloadRunZip(run("a", 1, "completed", { chain_status: "verified" }))).toBe(true);
    expect(
      canDownloadRunZip(run("a", 1, "completed_degraded", { chain_status: "verified" })),
    ).toBe(true);
  });

  it("refuses a broken or unchecked chain", () => {
    expect(canDownloadRunZip(run("a", 1, "completed", { chain_status: "broken" }))).toBe(false);
    expect(canDownloadRunZip(run("a", 1, "completed", { chain_status: null }))).toBe(false);
  });

  it("refuses an unfinished run even with a verified chain", () => {
    expect(canDownloadRunZip(run("a", 1, "failed", { chain_status: "verified" }))).toBe(false);
  });
});

describe("rerunState", () => {
  const base = {
    isSuperadmin: true,
    intakeStatus: "delivered",
    runs: [run("a", 1, "completed")],
    loadState: "ready" as const,
  };

  it("is hidden for a non-superadmin", () => {
    expect(rerunState({ ...base, isSuperadmin: false }).visible).toBe(false);
  });

  it("is hidden on archived and decomposed intakes", () => {
    expect(rerunState({ ...base, intakeStatus: "archived" }).visible).toBe(false);
    expect(rerunState({ ...base, intakeStatus: "decomposed" }).visible).toBe(false);
  });

  it("is visible and disabled with no reason while loading or after a load error", () => {
    for (const loadState of ["loading", "error"] as const) {
      expect(rerunState({ ...base, loadState, runs: [] })).toEqual({
        visible: true,
        disabled: true,
        reason: null,
        parkedNote: false,
      });
    }
  });

  it("is hidden when the list is ready and empty", () => {
    expect(rerunState({ ...base, runs: [] }).visible).toBe(false);
  });

  it("is disabled with reason in_flight when any run is in flight", () => {
    for (const s of ["queued", "running", "needs_report_spec"]) {
      expect(
        rerunState({ ...base, intakeStatus: "in_research", runs: [run("a", 1, "completed"), run("b", 2, s)] }),
      ).toEqual({ visible: true, disabled: true, reason: "in_flight", parkedNote: false });
    }
  });

  it("an older in-flight row still blocks", () => {
    expect(
      rerunState({ ...base, runs: [run("a", 1, "running"), run("b", 2, "failed")] }).reason,
    ).toBe("in_flight");
  });

  it("is enabled with the parked note when the newest run is parked", () => {
    expect(rerunState({ ...base, runs: [run("a", 1, "completed"), run("b", 2, "parked")] })).toEqual(
      { visible: true, disabled: false, reason: null, parkedNote: true },
    );
  });

  it("is enabled without a note otherwise", () => {
    expect(rerunState(base)).toEqual({
      visible: true,
      disabled: false,
      reason: null,
      parkedNote: false,
    });
  });
});

describe("classifyRerunFailure", () => {
  const before = new Set(["a", "b"]);

  it("a failed refetch is maybe_started — nothing proves no charge", () => {
    expect(classifyRerunFailure(before, null)).toBe("maybe_started");
  });

  it("a pre-existing in-flight run is in_flight", () => {
    expect(
      classifyRerunFailure(before, [run("a", 1, "completed"), run("b", 2, "running")]),
    ).toBe("in_flight");
  });

  it("a NEW in-flight run is maybe_started", () => {
    expect(
      classifyRerunFailure(before, [
        run("a", 1, "completed"),
        run("b", 2, "failed"),
        run("c", 3, "queued"),
      ]),
    ).toBe("maybe_started");
  });

  it("nothing in flight is failed (nothing charged)", () => {
    expect(classifyRerunFailure(before, [run("a", 1, "completed"), run("b", 2, "parked")])).toBe(
      "failed",
    );
  });
});

describe("runStatusBadge", () => {
  it("in-flight statuses get the outline badge, green mark and spinner", () => {
    expect(runStatusBadge("queued")).toEqual({
      className: "badge-outline",
      mark: "green",
      spinner: true,
      labelStatus: "queued",
    });
    expect(runStatusBadge("running").labelStatus).toBe("running");
  });

  it("needs_report_spec is labelled running, with a spinner", () => {
    expect(runStatusBadge("needs_report_spec")).toEqual({
      className: "badge-outline",
      mark: "green",
      spinner: true,
      labelStatus: "running",
    });
  });

  it("maps finished and stopped statuses per the UI-SPEC table", () => {
    expect(runStatusBadge("completed")).toMatchObject({ className: "badge-ink", mark: null });
    expect(runStatusBadge("completed_degraded")).toMatchObject({
      className: "badge-outline",
      mark: "ink",
    });
    expect(runStatusBadge("parked").className).toBe("badge-dashed");
    expect(runStatusBadge("needs_input").className).toBe("badge-dashed");
    expect(runStatusBadge("failed").className).toBe("badge-outline text-red-700 border-red-700");
    expect(runStatusBadge("cancelled").className).toBe(
      "badge-outline text-ink/40 border-ink/40",
    );
  });

  it("an unknown status gets the muted outline and keeps its own label status", () => {
    expect(runStatusBadge("mystery")).toEqual({
      className: "badge-outline text-ink/40 border-ink/40",
      mark: null,
      spinner: false,
      labelStatus: "mystery",
    });
  });
});
