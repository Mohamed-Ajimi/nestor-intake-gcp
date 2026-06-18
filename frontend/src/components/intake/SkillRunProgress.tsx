import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { supabase } from "@/lib/supabase";

export type ActiveSkillRun = {
  id: string;
  status: string;
  triggered_at: string;
  completed_at: string | null;
  applied_at: string | null;
  error: string | null;
};

type SkillRunRealtimeRow = ActiveSkillRun & {
  error_message?: string | null;
  skill_name?: string;
  intake_id?: string;
};

/**
 * Latest nestor-intake skill_run for an intake.
 *
 * Replaces the previous 5s polling with a single Supabase Realtime
 * subscription on nestor.skill_runs filtered by intake_id. One persistent
 * websocket — no per-tick refetches, no state accumulation.
 *
 * The second argument is kept for API compatibility with the previous
 * polling hook but is no longer used.
 */
export function useActiveSkillRun(
  intakeId: string | undefined,
  _forcePoll = false,
): { data: ActiveSkillRun | null } {
  void _forcePoll;
  const [data, setData] = useState<ActiveSkillRun | null>(null);

  useEffect(() => {
    if (!supabase || !intakeId) {
      setData(null);
      return;
    }
    let cancelled = false;
    let pollTimer: ReturnType<typeof setTimeout> | null = null;
    const pollStart = Date.now();
    const MAX_POLL_MS = 10 * 60 * 1000;

    const fetchLatest = async () => {
      const { data: row, error } = await supabase!
        .schema("nestor")
        .from("skill_runs")
        .select("id, status, triggered_at, completed_at, applied_at, error:error_message")
        .eq("intake_id", intakeId)
        .eq("skill_name", "nestor-intake")
        .order("triggered_at", { ascending: false })
        .limit(1)
        .maybeSingle();
      if (cancelled) return null;
      if (error) {
        console.warn("[SkillRunProgress] latest run fetch failed", error.message);
        return null;
      }
      const next = (row as ActiveSkillRun | null) ?? null;
      setData(next);
      return next;
    };

    const schedulePoll = (status: string | undefined) => {
      if (pollTimer) {
        clearTimeout(pollTimer);
        pollTimer = null;
      }
      if (cancelled) return;
      if (status !== "running") return;
      if (Date.now() - pollStart > MAX_POLL_MS) return;
      pollTimer = setTimeout(async () => {
        const next = await fetchLatest();
        schedulePoll(next?.status);
      }, 5000);
    };

    // Initial lightweight fetch, then bounded polling fallback while running.
    void fetchLatest().then((next) => schedulePoll(next?.status));

    // Realtime subscription (primary update channel when wired up).
    const channel = supabase
      .channel(`skill_runs:${intakeId}`)
      .on(
        "postgres_changes" as never,
        {
          event: "*",
          schema: "nestor",
          table: "skill_runs",
          filter: `intake_id=eq.${intakeId}`,
        },
        (payload: {
          new: Record<string, unknown> | null;
          old: Record<string, unknown> | null;
        }) => {
          const row = (payload.new ?? payload.old) as SkillRunRealtimeRow | null;
          if (!row) return;
          if (row.skill_name && row.skill_name !== "nestor-intake") return;
          setData((prev) => {
            const merged: ActiveSkillRun = {
              id: row.id,
              status: row.status,
              triggered_at: row.triggered_at,
              completed_at: row.completed_at ?? null,
              applied_at: (row as { applied_at?: string | null }).applied_at ?? null,
              error: row.error ?? row.error_message ?? null,
            };
            if (!prev) {
              schedulePoll(merged.status);
              return merged;
            }
            if (row.id === prev.id || row.triggered_at >= prev.triggered_at) {
              schedulePoll(merged.status);
              return merged;
            }
            return prev;
          });
        },
      )
      .subscribe();

    return () => {
      cancelled = true;
      if (pollTimer) clearTimeout(pollTimer);
      void supabase!.removeChannel(channel);
    };
  }, [intakeId]);

  return { data };
}

/**
 * Fetches the full skill_run row (including heavy output_parsed) once,
 * only when explicitly enabled (i.e. after status='succeeded').
 *
 * No polling, no caching beyond component lifetime.
 */
export function useSkillRunFull(
  skillRunId: string | undefined,
  enabled: boolean,
): {
  data:
    | { id: string; output_parsed: unknown; cost_estimate_usd: number | null }
    | null;
} {
  const [data, setData] = useState<{
    id: string;
    output_parsed: unknown;
    cost_estimate_usd: number | null;
  } | null>(null);

  useEffect(() => {
    if (!supabase || !skillRunId || !enabled) return;
    let cancelled = false;
    void supabase
      .schema("nestor")
      .from("skill_runs")
      .select("id, output_parsed, cost_estimate_usd")
      .eq("id", skillRunId)
      .single()
      .then(({ data: row }) => {
        if (cancelled) return;
        setData(
          (row as {
            id: string;
            output_parsed: unknown;
            cost_estimate_usd: number | null;
          } | null) ?? null,
        );
      });
    return () => {
      cancelled = true;
    };
  }, [skillRunId, enabled]);

  return { data };
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
