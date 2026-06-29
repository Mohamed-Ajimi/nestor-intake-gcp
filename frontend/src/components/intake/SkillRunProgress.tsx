import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { listSkillRuns, type SkillRun } from "@/lib/api/skillRuns";

export type ActiveSkillRun = {
  id: string;
  status: string;
  triggered_at: string;
  completed_at: string | null;
  applied_at: string | null;
  error: string | null;
};

/**
 * Reconcile the backend `SkillRunView` (`{ id, status, applied_at, completed_at }`) into
 * the `ActiveSkillRun` contract this component exposes to its callers. The view does not
 * project a trigger timestamp, so we fall back to the applied/completed markers to give
 * the elapsed-timer banner a sensible start point.
 */
function toActiveSkillRun(r: SkillRun | null): ActiveSkillRun | null {
  if (!r) return null;
  return {
    id: r.id,
    status: r.status,
    triggered_at: r.applied_at ?? r.completed_at ?? new Date().toISOString(),
    completed_at: r.completed_at,
    applied_at: r.applied_at,
    error: null,
  };
}

/**
 * Latest skill-run for an intake, via a POLLED `skillRuns.listSkillRuns` read.
 *
 * This replaces the previous realtime websocket subscription (Bucket C). The live SSE
 * push lands in Phase 8 (API-04); until then a bounded 5s poll while the run is active
 * keeps the lifecycle UI live. The external contract (`{ data: ActiveSkillRun | null }`
 * and the second `_forcePoll` arg) is intentionally unchanged so callers — and the
 * Phase-8 SSE swap — need no edits.
 */
export function useActiveSkillRun(
  intakeId: string | undefined,
  _forcePoll = false,
): { data: ActiveSkillRun | null } {
  void _forcePoll;
  const [data, setData] = useState<ActiveSkillRun | null>(null);

  useEffect(() => {
    if (!intakeId) {
      setData(null);
      return;
    }
    let cancelled = false;
    let pollTimer: ReturnType<typeof setTimeout> | null = null;
    const pollStart = Date.now();
    const MAX_POLL_MS = 10 * 60 * 1000;

    const fetchLatest = async (): Promise<ActiveSkillRun | null> => {
      const res = await listSkillRuns(intakeId);
      if (cancelled) return null;
      if (!res.success) {
        console.warn("[SkillRunProgress] latest run fetch failed", res.error);
        return null;
      }
      const next = toActiveSkillRun(res.data.latest);
      setData(next);
      return next;
    };

    const schedulePoll = (status: string | undefined) => {
      if (pollTimer) {
        clearTimeout(pollTimer);
        pollTimer = null;
      }
      if (cancelled) return;
      // Keep polling only while the run is still in flight (status verbatim from backend).
      if (status !== "running" && status !== "queued") return;
      if (Date.now() - pollStart > MAX_POLL_MS) return;
      pollTimer = setTimeout(async () => {
        const next = await fetchLatest();
        schedulePoll(next?.status);
      }, 5000);
    };

    // Initial fetch, then bounded polling while the run is active.
    void fetchLatest().then((next) => schedulePoll(next?.status));

    return () => {
      cancelled = true;
      if (pollTimer) clearTimeout(pollTimer);
    };
  }, [intakeId]);

  return { data };
}

/**
 * The full skill-run row (heavy `output_parsed` + cost) is produced by the Phase-7
 * apply-intake-skill backend and is NOT projected by the read-only skill-run seam
 * (`SkillRunView` carries only `{ id, status, applied_at, completed_at }`). Until Phase 7
 * there is nothing to fetch, so this returns `null` with its contract unchanged — the
 * admin AI-review flow simply does not enter review mode (correct pre-Phase-7, since no
 * real skill output exists yet).
 */
export function useSkillRunFull(
  skillRunId: string | undefined,
  enabled: boolean,
): {
  data:
    | { id: string; output_parsed: unknown; cost_estimate_usd: number | null }
    | null;
} {
  void skillRunId;
  void enabled;
  return { data: null };
}

export function SkillRunProgress({ triggeredAt }: { triggeredAt: string }) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const start = new Date(triggeredAt).getTime();
    const tick = () => setElapsed(Math.max(0, Math.floor((Date.now() - start) / 1000)));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [triggeredAt]);

  const mm = String(Math.floor(elapsed / 60)).padStart(2, "0");
  const ss = String(elapsed % 60).padStart(2, "0");

  return (
    <div
      className="mb-5 flex items-center gap-4 border border-ink/30 border-l-4 bg-paperLight px-6 py-5"
      style={{ borderLeftColor: "#FF2D87" }}
      role="status"
      aria-live="polite"
    >
      <Loader2 className="h-5 w-5 animate-spin text-ink" />
      <div className="flex-1">
        <div
          className="mb-1 font-mono text-[11px] uppercase tracking-wider"
          style={{ color: "#FF2D87" }}
        >
          Nestor analyseert
        </div>
        <div className="font-sans text-[15px] leading-relaxed text-ink">
          Nestor verwerkt je intake. Gemiddeld 90–120 seconden voor een uitgebreide intake. Je mag
          deze tab open laten — we tonen het resultaat zodra het klaar is.
        </div>
      </div>
      <div className="font-mono text-2xl tabular-nums text-ink">
        {mm}:{ss}
      </div>
    </div>
  );
}
