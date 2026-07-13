import { apiFetch, type ApiResult } from "@/lib/api/client";
import type { PhaseSkillRunInput } from "@/lib/intake-phase";

// frontend/src/lib/api/skillRuns.ts — read-only skill-run projection over the
// token-attaching `apiFetch` transport. Mirrors `admin.ts`: never fork the transport.
//
// COLUMN RECONCILE (Pitfall 1, load-bearing). The OLD frontend read the legacy
// Supabase shape (`skill_name`, `status='succeeded'`, ordered by `completed_at` — see
// IntakeForm.tsx). The new backend `SkillRunView` is `{ id, status, applied_at,
// completed_at }`. `derivePhase` (intake-phase.ts:26-29) consumes only the
// `PhaseSkillRunInput` shape `{ status, applied_at }`, and treats `status === "succeeded"`
// as the terminal value (Assumption A1). `latestPhaseInput` performs that mapping so the
// phase machine is fed correct data with no silent drift (T-06-15) — the backend `status`
// is consumed verbatim, never re-derived client-side.

/** Mirrors the backend `SkillRunView`. */
export type SkillRun = {
  id: string;
  status: string;
  skill: string;
  applied_at: string | null;
  completed_at: string | null;
};

/** Mirrors the backend `SkillRunsView` (latest + full list). */
export type SkillRunsView = {
  latest: SkillRun | null;
  runs: SkillRun[];
};

/** List an intake's skill runs (latest + full list). */
export function listSkillRuns(
  intakeId: string,
): Promise<ApiResult<SkillRunsView>> {
  return apiFetch<SkillRunsView>(`/intakes/${intakeId}/skill-runs`, {
    method: "GET",
  });
}

/**
 * Mirrors the backend `SkillRunFullView` — the heavy projection carrying the
 * parsed skill output and the run's cost estimate. Read once, on demand, when the
 * admin enters review mode (Phase 8 D-08 un-stubs this end of the seam).
 */
export type SkillRunFull = {
  id: string;
  output_parsed: unknown;
  cost_estimate_usd: number | null;
};

/**
 * Fetch a single skill run's full projection (`output_parsed` + cost). Space-scoped
 * server-side; a run outside the caller's space is existence-hidden as 404 (D-04).
 * Uses the standard short request-response transport — NOT the SSE stream (never fork
 * the transport): this is a one-shot read the review flow performs after the terminal
 * event, not a live push.
 */
export function getSkillRunFull(
  intakeId: string,
  runId: string,
): Promise<ApiResult<SkillRunFull>> {
  return apiFetch<SkillRunFull>(`/intakes/${intakeId}/skill-runs/${runId}`, {
    method: "GET",
  });
}

/**
 * Fetch the latest skill run and reconcile it into the `PhaseSkillRunInput` shape
 * `derivePhase` expects (`{ status, applied_at }` or null). The backend `status` is
 * passed through verbatim — `derivePhase` is the sole authority on what `"succeeded"`
 * means for the phase machine.
 */
export async function latestPhaseInput(
  intakeId: string,
): Promise<ApiResult<PhaseSkillRunInput>> {
  const res = await listSkillRuns(intakeId);
  if (!res.success) return res;
  const latest = res.data.latest;
  const mapped: PhaseSkillRunInput = latest
    ? { status: latest.status, applied_at: latest.applied_at }
    : null;
  return { success: true, data: mapped };
}
