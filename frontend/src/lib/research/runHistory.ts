import type { ResearchRun, ResearchRunHistoryItem } from "@/lib/api/research";

/**
 * The run-history rules for the intake page (Phase 23.6): which run carries the "chosen run"
 * badge, when Rerun is visible/disabled, which row actions show, and what a failed rerun
 * toast is allowed to claim about money.
 *
 * This is a PURE module on purpose: no React, no i18n, no network. `vitest.config.ts`
 * includes only `src/**\/*.test.ts` in a `node` environment (no jsdom, no `.tsx`), so these
 * decisions are only testable at all if they live outside the components that render them.
 * The backend stays the authority (409 on an in-flight trigger, 409 on choosing an unfinished
 * run); these rules only decide presentation.
 */

/**
 * Mirrors backend `RESEARCH_IN_FLIGHT` in `backend/app/research/run_status.py` — that file is
 * the source of truth; edit both together. `parked` is deliberately NOT in flight (UI-6): a
 * parked run waits on a human, and the backend lets a new run start beside it.
 */
export const RESEARCH_IN_FLIGHT_STATUSES: ReadonlySet<string> = new Set([
  "queued",
  "running",
  "needs_report_spec",
]);

/** Mirrors backend `RESEARCH_SUCCESS` in `backend/app/research/run_status.py`. */
export const RESEARCH_SUCCESS_STATUSES: ReadonlySet<string> = new Set([
  "completed",
  "completed_degraded",
]);

/** Intake statuses on which Rerun is offered (UI-7: not archived, not decomposed). */
const RERUN_INTAKE_STATUSES: ReadonlySet<string> = new Set(["in_research", "delivered"]);

/** Newest first: `attempt` descending, ties by `created_at` descending. Never mutates input. */
export function sortRunsNewestFirst(runs: ResearchRunHistoryItem[]): ResearchRunHistoryItem[] {
  return [...runs].sort((a, b) => {
    if (a.attempt !== b.attempt) return b.attempt - a.attempt;
    const ta = Date.parse(a.created_at);
    const tb = Date.parse(b.created_at);
    return (Number.isNaN(tb) ? 0 : tb) - (Number.isNaN(ta) ? 0 : ta);
  });
}

/**
 * Overlay the page's single live SSE frame onto its row, so the newest run's status/cost/clock
 * are live without a second stream. An unknown id or a null frame leaves the list untouched.
 */
export function mergeLiveRun(
  runs: ResearchRunHistoryItem[],
  live: ResearchRun | null,
): ResearchRunHistoryItem[] {
  if (!live) return runs;
  if (!runs.some((r) => r.id === live.id)) return runs;
  return runs.map((r) =>
    r.id === live.id
      ? {
          ...r,
          status: live.status,
          cost_usd_total: live.cost_usd_total,
          started_at: live.started_at,
          completed_at: live.completed_at,
          chain_status: live.chain_status,
        }
      : r,
  );
}

export type ChosenRun =
  | { runId: string; source: "marked" | "default" }
  | { runId: null; source: null };

/**
 * Which row carries the chosen-run badge (UI-8). The explicitly marked run if it is in the
 * list; otherwise the newest `completed`/`completed_degraded` run as a DISPLAY DEFAULT (never
 * stored); otherwise none. A newer failed/parked run never takes the default.
 */
export function resolveChosenRun(
  runs: ResearchRunHistoryItem[],
  chosenId: string | null,
): ChosenRun {
  if (chosenId && runs.some((r) => r.id === chosenId)) {
    return { runId: chosenId, source: "marked" };
  }
  const newestFinished = sortRunsNewestFirst(runs).find((r) =>
    RESEARCH_SUCCESS_STATUSES.has(r.status),
  );
  if (newestFinished) return { runId: newestFinished.id, source: "default" };
  return { runId: null, source: null };
}

/**
 * Whether the "Use for report" action shows on a row (UI-5): finished runs only, never the
 * explicitly marked run, never on an archived intake. The default-badged row keeps the action
 * so the display default can be made explicit.
 */
export function canChooseRun(
  run: ResearchRunHistoryItem,
  chosen: ChosenRun,
  intakeStatus: string,
): boolean {
  if (intakeStatus === "archived") return false;
  if (!RESEARCH_SUCCESS_STATUSES.has(run.status)) return false;
  if (chosen.source === "marked" && chosen.runId === run.id) return false;
  return true;
}

/** Row zip download (UI-9): finished run AND a verified audit chain. Broken/unchecked -> run page. */
export function canDownloadRunZip(run: ResearchRunHistoryItem): boolean {
  return RESEARCH_SUCCESS_STATUSES.has(run.status) && run.chain_status === "verified";
}

export type RerunLoadState = "loading" | "ready" | "error";

export type RerunState = {
  visible: boolean;
  disabled: boolean;
  reason: "in_flight" | null;
  parkedNote: boolean;
};

/**
 * Rerun button state (UI-SPEC "Rerun button"). Hidden for non-superadmins and outside
 * `in_research`/`delivered`. While the list loads or after it failed, visible but disabled
 * with no reason line (those states explain themselves). A ready empty list has no Rerun.
 * Any in-flight run (any row, not only the newest) disables it with reason `in_flight`.
 * A parked newest run leaves it enabled and asks the dialog for the parked note.
 */
export function rerunState(input: {
  isSuperadmin: boolean;
  intakeStatus: string;
  runs: ResearchRunHistoryItem[];
  loadState: RerunLoadState;
}): RerunState {
  const hidden: RerunState = { visible: false, disabled: true, reason: null, parkedNote: false };
  if (!input.isSuperadmin || !RERUN_INTAKE_STATUSES.has(input.intakeStatus)) return hidden;
  if (input.loadState !== "ready") {
    return { visible: true, disabled: true, reason: null, parkedNote: false };
  }
  if (input.runs.length === 0) return hidden;
  if (input.runs.some((r) => RESEARCH_IN_FLIGHT_STATUSES.has(r.status))) {
    return { visible: true, disabled: true, reason: "in_flight", parkedNote: false };
  }
  const newest = sortRunsNewestFirst(input.runs)[0];
  return { visible: true, disabled: false, reason: null, parkedNote: newest.status === "parked" };
}

export type RerunFailure = "in_flight" | "maybe_started" | "failed";

/**
 * Classify a failed rerun request from a list refetched AFTER the failure (copy truth,
 * UI-SPEC). The trigger's 409 carries no machine code, so the decision is made from the list:
 *
 * - refetch failed (`null`) -> `maybe_started`: nothing proves no charge, so never the
 *   "nothing charged" copy (routes to `intakeDetail.toast.researchStartFailed`).
 * - an in-flight run that was ALREADY there -> `in_flight` ("no new run, nothing charged").
 * - an in-flight run that is NEW -> `maybe_started`: spend may have started.
 * - nothing in flight -> `failed` ("nothing charged").
 */
export function classifyRerunFailure(
  beforeIds: ReadonlySet<string>,
  afterRuns: ResearchRunHistoryItem[] | null,
): RerunFailure {
  if (afterRuns === null) return "maybe_started";
  const inFlight = afterRuns.filter((r) => RESEARCH_IN_FLIGHT_STATUSES.has(r.status));
  if (inFlight.some((r) => !beforeIds.has(r.id))) return "maybe_started";
  if (inFlight.length > 0) return "in_flight";
  return "failed";
}

export type RunStatusBadge = {
  className: string;
  mark: "green" | "ink" | null;
  spinner: boolean;
  /** The status to hand to `statusLabel` (needs_report_spec reads as running). */
  labelStatus: string;
};

const MUTED = "badge-outline text-ink/40 border-ink/40";

/**
 * Status badge per the UI-SPEC "Status badge mapping" table. Class strings are written out
 * literally so Tailwind's scanner sees them.
 */
export function runStatusBadge(status: string): RunStatusBadge {
  switch (status) {
    case "queued":
    case "running":
      return { className: "badge-outline", mark: "green", spinner: true, labelStatus: status };
    case "needs_report_spec":
      // In flight — never show "unknown" for a live run.
      return { className: "badge-outline", mark: "green", spinner: true, labelStatus: "running" };
    case "completed":
      return { className: "badge-ink", mark: null, spinner: false, labelStatus: status };
    case "completed_degraded":
      return { className: "badge-outline", mark: "ink", spinner: false, labelStatus: status };
    case "parked":
    case "needs_input":
      return { className: "badge-dashed", mark: null, spinner: false, labelStatus: status };
    case "failed":
      return {
        className: "badge-outline text-red-700 border-red-700",
        mark: null,
        spinner: false,
        labelStatus: status,
      };
    case "cancelled":
      return { className: MUTED, mark: null, spinner: false, labelStatus: status };
    default:
      return { className: MUTED, mark: null, spinner: false, labelStatus: status };
  }
}
