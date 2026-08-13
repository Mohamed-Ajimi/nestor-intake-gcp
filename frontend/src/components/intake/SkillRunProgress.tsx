import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2 } from "lucide-react";
import { getSkillRunFull, listSkillRuns, type SkillRun } from "@/lib/api/skillRuns";
import { openSkillRunStream } from "@/lib/api/skillRunStream";

export type ActiveSkillRun = {
  id: string;
  status: string;
  // The skill discriminator (07-09 `SkillRunView.skill`), e.g. "apply-intake-skill" or
  // "context-pack". Threaded through so consumers (review-consume, context-pack reload)
  // can tell which skill the latest run belongs to now that multiple skills land runs.
  skill: string;
  /**
   * The run's REAL start time (backend `skill_runs.created_at`, Postgres `now()` at
   * dispatch), or null when the backend has not been redeployed with the projection yet.
   *
   * THIS, not `triggered_at`, is what an elapsed clock must count from. It is a distinct
   * field ON PURPOSE — see the note on `triggered_at` below.
   */
  created_at: string | null;
  /**
   * LEGACY, SYNTHETIC, and deliberately left exactly as it was: `applied_at ?? completed_at
   * ?? now`. For a run that is still running BOTH markers are null, so this collapses to
   * wall-clock now — a value that changes on every re-map.
   *
   * ⛔ Do NOT "fix" this field by pointing it at `created_at`. It is also the input to the
   * optimistic-dispatch RELEASE GUARD in `routes/admin.pulse.intakes.$id.tsx` (~:293),
   * which compares it against `optimisticRunStartedAt` — a value taken from the BROWSER's
   * clock via `new Date()`. `created_at` comes from the Cloud SQL clock. If a browser
   * running ahead of the database were compared that way, a freshly dispatched run's
   * `created_at` would sort BEFORE the optimistic stamp, the guard would never release,
   * `skillLoading` would stay true, and the forced 5s poll plus the disabled dispatch CTAs
   * would stick for the full 10-minute poll cap. Keeping this field byte-for-byte as it was
   * keeps that guard's behaviour unchanged.
   */
  triggered_at: string;
  completed_at: string | null;
  applied_at: string | null;
  error: string | null;
};

/**
 * Reconcile the backend `SkillRunView` into the `ActiveSkillRun` contract this module
 * exposes to its callers.
 *
 * `created_at` is passed straight through — it is the run's real start and is STABLE for a
 * given run, which is what stops the elapsed clock from restarting on every SSE event and
 * lets it survive a refresh. `triggered_at` retains its original synthetic fallback chain
 * for the optimistic-release guard that consumes it (see the type above).
 */
function toActiveSkillRun(r: SkillRun | null): ActiveSkillRun | null {
  if (!r) return null;
  return {
    id: r.id,
    status: r.status,
    skill: r.skill,
    created_at: r.created_at ?? null,
    triggered_at: r.applied_at ?? r.completed_at ?? new Date().toISOString(),
    completed_at: r.completed_at,
    applied_at: r.applied_at,
    error: null,
  };
}

/**
 * Latest skill-run for an intake — SSE-first with the bounded 5s poll retained as the
 * silent fallback (Phase 8, API-04, D-09/D-07a).
 *
 * The live push (which the legacy Supabase Realtime subscription gave, then a 5s poll
 * stood in for in Phase 6/7) is now driven by `openSkillRunStream`. The 5s poll block
 * below is the safety net: it runs concurrently with the stream on mount so a run that
 * starts out-of-band, before the page mounts, or on a different instance the SSE
 * connection is not pinned to is not invisible until the 10-min cap (WR-01). The poll
 * self-stops as soon as `status` leaves `running`/`queued`, so the two racing briefly is
 * cheap and idempotent. It also runs when the stream fails (`onFallback`, i.e. no token /
 * 401·404 / backoff exhausted) so the UI never goes blind.
 *
 * `_forcePoll` is read through a ref (WR-06): toggling it must NOT tear down and reopen the
 * live SSE stream mid-run. The effect depends only on `intakeId`, so the connection is
 * opened once per intake and survives the caller's `skillLoading` flip.
 *
 * The external contract (`{ data: ActiveSkillRun | null }` and the second `_forcePoll`
 * arg) is intentionally UNCHANGED — the whole point of the Phase 6/7 prep — so callers
 * need zero edits. The terminal-event → detail-page refresh (load + loadSkillRuns) is
 * wired at the route (D-09), not here, so the hook contract stays frozen.
 */
export function useActiveSkillRun(
  intakeId: string | undefined,
  _forcePoll = false,
): { data: ActiveSkillRun | null } {
  const [data, setData] = useState<ActiveSkillRun | null>(null);

  // Read `_forcePoll` through a ref so toggling it does NOT re-run the effect and tear
  // down the live SSE stream mid-run (WR-06). The effect depends only on `intakeId`.
  const forcePollRef = useRef(_forcePoll);
  forcePollRef.current = _forcePoll;

  // Restart hook for a poll that already self-stopped: after a run finishes, the stream
  // closes itself (WR-02) and the poll halts on the terminal status — dispatching a NEW
  // run then left the page blind (stuck-timer UAT finding, 2026-07-16). Assigned inside
  // the main effect so it closes over that effect's fetch/schedule; the `_forcePoll`
  // watcher effect below kicks it without tearing down the stream (WR-06 intact).
  const restartPollRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    if (!intakeId) {
      setData(null);
      return;
    }
    let cancelled = false;
    let pollTimer: ReturnType<typeof setTimeout> | null = null;
    let stream: { close: () => void } | null = null;
    let pollStart = Date.now();
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
      // Keep polling while the run is in flight (status verbatim from backend) OR while
      // the caller signals an optimistic dispatch (`forcePollRef`) — the just-created run
      // may not surface as `latest` on the first fetch, and the terminal status of the
      // PREVIOUS run must not stop us from seeing the new one.
      if (status !== "running" && status !== "queued" && !forcePollRef.current) return;
      if (Date.now() - pollStart > MAX_POLL_MS) return;
      pollTimer = setTimeout(async () => {
        const next = await fetchLatest();
        schedulePoll(next?.status);
      }, 5000);
    };

    // The tested 5s poll — started on mount alongside SSE, and re-invoked as the SSE
    // fallback path. Idempotent: `schedulePoll` clears any pending timer first.
    const startPoll = () => {
      if (cancelled) return;
      void fetchLatest().then((next) => schedulePoll(next?.status));
    };

    // Always start the poll on mount — it self-stops once the run leaves running/queued,
    // and it covers the pre-run / out-of-band / cross-instance gap the SSE snapshot alone
    // cannot (WR-01). When the caller forces it (an optimistic run start pre-stream) this
    // is the only transport that matters until a run surfaces.
    startPoll();

    // Re-arm the safety poll for a NEW dispatch after the previous run went terminal:
    // reset the poll-cap window so MAX_POLL_MS is measured from the restart, not mount.
    restartPollRef.current = () => {
      if (cancelled) return;
      pollStart = Date.now();
      startPoll();
    };

    if (!forcePollRef.current) {
      // SSE is the primary live-push channel: map each event through `toActiveSkillRun`
      // (which guards null snapshots). On a terminal event, close our own side of the
      // connection deterministically rather than waiting for the server to close (WR-02);
      // the final snapshot was already delivered by the preceding `onEvent` and the route
      // refreshes (load + loadSkillRuns). On stream failure we lean on the poll started above.
      stream = openSkillRunStream(
        intakeId,
        (r) => {
          if (!cancelled) setData(toActiveSkillRun(r));
        },
        () => {
          stream?.close(); // terminal — release the connection now
        },
        () => {
          if (!cancelled) startPoll();
        },
      );
    }

    return () => {
      cancelled = true;
      restartPollRef.current = null;
      if (pollTimer) clearTimeout(pollTimer);
      if (stream) stream.close();
    };
    // `_forcePoll` is intentionally read via `forcePollRef` (not referenced in this effect
    // body) so toggling it does not tear down the live stream mid-run (WR-06).
  }, [intakeId]);

  // Kick the poll back to life the moment the caller flags an optimistic dispatch. A
  // separate effect (not a dep of the main one) so the SSE stream is never re-created.
  useEffect(() => {
    if (_forcePoll) restartPollRef.current?.();
  }, [_forcePoll]);

  return { data };
}

/**
 * The full skill-run row (heavy `output_parsed` + cost) produced by the Phase-7
 * apply-intake-skill backend. Phase 8 (D-08) un-stubs this against the new space-scoped
 * `GET /intakes/{intakeId}/skill-runs/{runId}` read so the terminal SSE event actually
 * feeds the AIReviewPanel review flow (dead until now).
 *
 * Gated on `enabled && intakeId && skillRunId` — the route only turns `enabled` true once
 * the phase machine reaches `awaiting_review`, so the heavy `output_parsed` is fetched
 * exactly once, on demand. Return-no-throw: on any failure `data` stays `null` (the
 * review panel simply does not enter review mode). The `{ data }` shape is preserved.
 */
export function useSkillRunFull(
  intakeId: string | undefined,
  skillRunId: string | undefined,
  enabled: boolean,
): {
  data: { id: string; output_parsed: unknown; cost_estimate_usd: number | null } | null;
} {
  const [data, setData] = useState<{
    id: string;
    output_parsed: unknown;
    cost_estimate_usd: number | null;
  } | null>(null);

  useEffect(() => {
    if (!enabled || !intakeId || !skillRunId) {
      setData(null);
      return;
    }
    let cancelled = false;
    void (async () => {
      const res = await getSkillRunFull(intakeId, skillRunId);
      if (cancelled) return;
      if (!res.success) {
        console.warn("[SkillRunProgress] full run fetch failed", res.error);
        return;
      }
      setData({
        id: res.data.id,
        output_parsed: res.data.output_parsed,
        cost_estimate_usd: res.data.cost_estimate_usd,
      });
    })();
    return () => {
      cancelled = true;
    };
  }, [intakeId, skillRunId, enabled]);

  return { data };
}

export function SkillRunProgress({ triggeredAt }: { triggeredAt: string }) {
  const { t } = useTranslation("intake");
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
          {t("skillRunProgress.title")}
        </div>
        <div className="font-sans text-[15px] leading-relaxed text-ink">
          {t("skillRunProgress.body")}
        </div>
      </div>
      <div className="font-mono text-2xl tabular-nums text-ink">
        {mm}:{ss}
      </div>
    </div>
  );
}
