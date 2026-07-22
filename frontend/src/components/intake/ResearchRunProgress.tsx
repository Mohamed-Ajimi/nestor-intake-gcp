import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  AlertTriangle,
  CheckCircle2,
  Circle,
  Download,
  Loader2,
  Lock,
  XCircle,
} from "lucide-react";
import { format } from "date-fns";
import { toast } from "sonner";
import i18n from "@/lib/i18n";
import { getDateLocale } from "@/lib/i18n/date-locale";
import {
  getBundleUrl,
  openResearchStream,
  reVerifyChain,
  triggerResearch,
  type ResearchRun,
} from "@/lib/api/research";

// frontend/src/components/intake/ResearchRunProgress.tsx — the admin's live window into a
// Tribunal deep-research run (Phase 16, RUN-01/D-07/D-09). It mirrors SkillRunProgress's
// SSE-first + bounded-poll hook mechanics and the intake design language, but renders the
// FULL stage list DYNAMICALLY from the run's `stage_detail` — so a future Phase-15 added
// pass costs this UI nothing (T-16-14; NO hardcoded stage count / no literal 9).
//
// SECURITY (T-16-12): this component lives ONLY on the admin detail route. No client route
// or component imports it — the client-facing UI is unchanged during in_research (D-08).

const RESEARCH_TERMINAL = new Set(["completed", "failed", "cancelled"]);

type StageRow = { key: string; name: string; status: string };

/**
 * Flatten the mirrored `stage_detail` JSONB (`{ stage_key: { items: [{ name, status }] } }`)
 * into an ordered, data-driven row list. The list length is whatever the run reports — a
 * run with 10 stages renders 10 rows. Object key order is preserved (insertion order for
 * string keys), which mirrors the engine's stage sequence.
 */
function toStageRows(run: ResearchRun | null): StageRow[] {
  if (!run?.stage_detail) return [];
  const rows: StageRow[] = [];
  for (const [stageKey, group] of Object.entries(run.stage_detail)) {
    const items = group?.items ?? [];
    if (items.length === 0) {
      // A stage with no sub-items still renders one row keyed on the stage itself.
      rows.push({ key: stageKey, name: stageKey, status: "pending" });
      continue;
    }
    for (const [idx, item] of items.entries()) {
      rows.push({
        key: `${stageKey}:${idx}`,
        name: item.name,
        status: item.status,
      });
    }
  }
  return rows;
}

/**
 * Latest research-run for an intake — SSE-first via `openResearchStream` with a bounded
 * poll fallback, cloned from `useActiveSkillRun`'s mechanics (cancelled-cleanup flag,
 * terminal → `stream.close()`, `onFallback` → poll). There is no dedicated poll read for
 * research yet, so the fallback re-opens the stream once after backoff; the terminal event
 * closes the connection deterministically (WR-02 discipline).
 */
function useActiveResearchRun(intakeId: string | undefined): {
  run: ResearchRun | null;
} {
  const [run, setRun] = useState<ResearchRun | null>(null);
  // Guard against a late terminal event re-opening after unmount.
  const streamRef = useRef<{ close: () => void } | null>(null);

  useEffect(() => {
    if (!intakeId) {
      setRun(null);
      return;
    }
    let cancelled = false;

    streamRef.current = openResearchStream(
      intakeId,
      (r) => {
        if (!cancelled) setRun(r);
      },
      () => {
        // Terminal — release the connection now; the final snapshot was already delivered
        // by the preceding onEvent.
        streamRef.current?.close();
      },
      () => {
        // Stream unavailable (no token / 401·404 / backoff exhausted). No separate poll
        // read exists for research; the panel simply keeps the last snapshot. The stream's
        // own bounded reconnect already ran before onFallback fired.
      },
    );

    return () => {
      cancelled = true;
      streamRef.current?.close();
      streamRef.current = null;
    };
  }, [intakeId]);

  return { run };
}

function fmtDate(d: string | null, fallback: string): string {
  if (!d) return fallback;
  try {
    return format(new Date(d), "d MMM yyyy HH:mm", {
      locale: getDateLocale(i18n.language),
    });
  } catch {
    return d;
  }
}

function fmtCost(cost: string | null, fallback: string): string {
  if (cost == null || cost === "") return fallback;
  const n = Number(cost);
  if (Number.isNaN(n)) return `$${cost}`;
  return `$${n.toFixed(2)}`;
}

/** Elapsed clock (mm:ss) counting up from `startedAt`; falls back to now if unset. */
function useElapsed(startedAt: string | null, active: boolean): string {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const start = startedAt ? new Date(startedAt).getTime() : Date.now();
    const tick = () => setElapsed(Math.max(0, Math.floor((Date.now() - start) / 1000)));
    tick();
    if (!active) return;
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [startedAt, active]);
  const mm = String(Math.floor(elapsed / 60)).padStart(2, "0");
  const ss = String(elapsed % 60).padStart(2, "0");
  return `${mm}:${ss}`;
}

/** Fixed duration between two timestamps (mm:ss), for the summary card. */
function fmtDuration(startedAt: string | null, completedAt: string | null): string {
  if (!startedAt || !completedAt) return "—";
  const s = new Date(startedAt).getTime();
  const e = new Date(completedAt).getTime();
  const secs = Math.max(0, Math.floor((e - s) / 1000));
  const mm = String(Math.floor(secs / 60)).padStart(2, "0");
  const ss = String(secs % 60).padStart(2, "0");
  return `${mm}:${ss}`;
}

function StageIcon({ status }: { status: string }) {
  if (status === "done") return <CheckCircle2 className="h-4 w-4 text-emerald-600" />;
  if (status === "running")
    return <Loader2 className="h-4 w-4 animate-spin text-ink" style={{ color: "#FF2D87" }} />;
  return <Circle className="h-4 w-4 text-ink/30" />;
}

/**
 * The raw-output affordance on the completed summary card (RUN-03 / D-06 / D-07).
 *
 * A VERIFIED chain renders a `[Download]` button: `getBundleUrl` mints a short-lived signed
 * URL server-side and the browser navigates to it (the seam forces `attachment` disposition,
 * so it downloads rather than renders — T-17-13). A BROKEN chain renders a distinct locked
 * state with a `[Re-verify]` button (`reVerifyChain`); on a now-passing re-verify the SSE
 * stream pushes the new `chain_status`, flipping this back to the download affordance. Every
 * error path is a toast — never a throw (CLAUDE.md return-no-throw). Admin-only by placement
 * (T-16-12 / T-17-15): this component is imported only by the admin intake detail route.
 */
function RawOutputControls({
  intakeId,
  run,
}: {
  intakeId: string;
  run: ResearchRun;
}) {
  const { t } = useTranslation("intake");
  const [busy, setBusy] = useState(false);

  const btnClass =
    "inline-flex items-center gap-2 bg-ink px-4 py-2 font-mono text-xs uppercase tracking-wider text-paper hover:bg-ink/85 disabled:opacity-60";

  const handleDownload = async () => {
    if (busy) return;
    setBusy(true);
    const res = await getBundleUrl(intakeId, run.id);
    setBusy(false);
    if (res.success && res.data?.url) {
      // The signed URL forces attachment disposition server-side → the browser downloads.
      window.location.href = res.data.url;
    } else {
      toast.error(t("research.downloadError"));
    }
  };

  const handleReverify = async () => {
    if (busy) return;
    setBusy(true);
    const res = await reVerifyChain(intakeId, run.id);
    setBusy(false);
    if (!res.success) {
      toast.error(t("research.reverifyError"));
      return;
    }
    if (res.data?.chain_status !== "verified") {
      // Still broken — the lock stays; the SSE stream keeps the locked card as-is.
      toast.error(t("research.reverifyStillBroken"));
    }
    // On success the SSE stream pushes the new chain_status → the card re-renders to the
    // download affordance; no local state to flip.
  };

  if (run.chain_status === "broken") {
    return (
      <div className="mt-4 border-l-4 bg-paper px-4 py-3" style={{ borderLeftColor: "#DC2626" }}>
        <div className="mb-1 flex items-center gap-2">
          <Lock className="h-4 w-4 text-red-600" />
          <span
            className="font-mono text-[11px] uppercase tracking-wider"
            style={{ color: "#DC2626" }}
          >
            {t("research.lockedTitle")}
          </span>
        </div>
        <div className="mb-3 font-sans text-[14px] leading-relaxed text-ink">
          {t("research.lockedBody")}
        </div>
        <button type="button" onClick={handleReverify} disabled={busy} className={btnClass}>
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <AlertTriangle className="h-4 w-4" />}
          {t("research.reverify")}
        </button>
      </div>
    );
  }

  if (run.chain_status === "verified") {
    return (
      <div className="mt-4">
        <button type="button" onClick={handleDownload} disabled={busy} className={btnClass}>
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
          {t("research.download")}
        </button>
      </div>
    );
  }

  // chain_status null (pre-Phase-17 row / not yet finalized): no affordance.
  return null;
}

/**
 * The live research-progress panel. While the run is active it renders the dynamic stage
 * list + running cost + elapsed clock. On a terminal status it collapses to a summary card
 * (completed → timestamp/cost/duration; failed/cancelled → error + a re-trigger affordance).
 *
 * `onRetry` re-invokes the trigger; the 3-attempt cap is enforced server-side, so the panel
 * always offers the affordance and lets the backend reject an over-cap retry.
 */
export function ResearchRunProgress({
  intakeId,
  onRetry,
}: {
  intakeId: string;
  onRetry?: () => void;
}) {
  const { t } = useTranslation("intake");
  const { run } = useActiveResearchRun(intakeId);

  const status = run?.status ?? "queued";
  // `needs_input` is the engine's parked clarification state. The intake side has
  // no answer surface (by design — briefs are pre-validated), so the panel renders
  // it as the failure card with the re-trigger affordance: a retry supersedes the
  // parked run with a repaired brief (allowed server-side since the 2026-07-21 fix).
  const isTerminal = RESEARCH_TERMINAL.has(status) || status === "needs_input";
  const stageRows = toStageRows(run);
  const elapsed = useElapsed(run?.started_at ?? null, !isTerminal);
  const costFallback = t("research.costFallback");
  const dateFallback = t("research.dateFallback");

  // ── Terminal: summary / failure card ─────────────────────────────────────────────
  if (isTerminal) {
    if (status === "completed") {
      return (
        <div
          className="mb-5 border border-ink/30 border-l-4 bg-paperLight px-6 py-5"
          style={{ borderLeftColor: "#DFF940" }}
          role="status"
          aria-live="polite"
        >
          <div className="mb-2 flex items-center gap-2">
            <CheckCircle2 className="h-5 w-5 text-emerald-600" />
            <span
              className="font-mono text-[11px] uppercase tracking-wider"
              style={{ color: "#7A8B00" }}
            >
              {t("research.completedTitle")}
            </span>
          </div>
          <div className="mb-3 font-sans text-[15px] leading-relaxed text-ink">
            {t("research.completedBody")}
          </div>
          <div className="flex flex-wrap gap-x-6 gap-y-1 font-mono text-[12px] text-ink/70">
            <span>{t("research.completedAt", { date: fmtDate(run?.completed_at ?? null, dateFallback) })}</span>
            <span>{t("research.totalCost", { cost: fmtCost(run?.cost_usd_total ?? null, costFallback) })}</span>
            <span>{t("research.duration", { duration: fmtDuration(run?.started_at ?? null, run?.completed_at ?? null) })}</span>
          </div>
          {/* Raw-output download (verified) or locked+re-verify (broken) — RUN-03. */}
          {run && <RawOutputControls intakeId={intakeId} run={run} />}
        </div>
      );
    }

    // failed | cancelled
    const isFailed = status === "failed";
    return (
      <div
        className="mb-5 border border-ink/30 border-l-4 bg-paperLight px-6 py-5"
        style={{ borderLeftColor: isFailed ? "#DC2626" : "#9CA3AF" }}
        role="status"
        aria-live="polite"
      >
        <div className="mb-2 flex items-center gap-2">
          {isFailed ? (
            <XCircle className="h-5 w-5 text-red-600" />
          ) : (
            <AlertTriangle className="h-5 w-5 text-ink/50" />
          )}
          <span
            className="font-mono text-[11px] uppercase tracking-wider"
            style={{ color: isFailed ? "#DC2626" : "#6B7280" }}
          >
            {isFailed ? t("research.failedTitle") : t("research.cancelledTitle")}
          </span>
        </div>
        <div className="mb-3 font-sans text-[15px] leading-relaxed text-ink">
          {isFailed ? t("research.failedBody") : t("research.cancelledBody")}
        </div>
        {run?.error_message && (
          <div className="mb-4">
            <div className="mb-1 font-mono text-[11px] uppercase tracking-wider text-ink/50">
              {t("research.errorLabel")}
            </div>
            <div className="whitespace-pre-wrap break-words font-mono text-[13px] text-red-700">
              {run.error_message}
            </div>
          </div>
        )}
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="inline-flex items-center gap-2 bg-ink px-4 py-2 font-mono text-xs uppercase tracking-wider text-paper hover:bg-ink/85"
          >
            {t("research.retry")}
          </button>
        )}
      </div>
    );
  }

  // ── Active: dynamic stage list + running cost + elapsed clock ─────────────────────
  return (
    <div
      className="mb-5 border border-ink/30 border-l-4 bg-paperLight px-6 py-5"
      style={{ borderLeftColor: "#FF2D87" }}
      role="status"
      aria-live="polite"
    >
      <div className="mb-3 flex items-center gap-3">
        <Loader2 className="h-5 w-5 animate-spin text-ink" />
        <div className="flex-1">
          <div
            className="mb-1 font-mono text-[11px] uppercase tracking-wider"
            style={{ color: "#FF2D87" }}
          >
            {t("research.panelTitle")}
          </div>
          <div className="font-sans text-[15px] leading-relaxed text-ink">
            {stageRows.length === 0 ? t("research.startingBody") : t("research.panelBody")}
          </div>
        </div>
        <div className="flex flex-col items-end gap-1 font-mono text-ink">
          <span className="text-2xl tabular-nums">{elapsed}</span>
          <span className="text-[11px] uppercase tracking-wider text-ink/60">
            {t("research.cost")}: {fmtCost(run?.cost_usd_total ?? null, costFallback)}
          </span>
        </div>
      </div>

      {run?.current_stage && (
        <div className="mb-3 font-mono text-[12px] text-ink/60">
          {t("research.currentStage", { stage: run.current_stage })}
        </div>
      )}

      {stageRows.length > 0 && (
        <div>
          <div className="mb-2 font-mono text-[11px] uppercase tracking-wider text-ink/50">
            {t("research.stagesTitle")}
          </div>
          <ul className="space-y-1">
            {stageRows.map((row) => (
              <li key={row.key} className="flex items-center gap-2 font-mono text-[13px]">
                <StageIcon status={row.status} />
                <span
                  className={
                    row.status === "done"
                      ? "text-ink/70"
                      : row.status === "running"
                        ? "text-ink"
                        : "text-ink/40"
                  }
                >
                  {row.name}
                </span>
                <span className="ml-auto text-[11px] uppercase tracking-wider text-ink/40">
                  {row.status === "done"
                    ? t("research.stageDone")
                    : row.status === "running"
                      ? t("research.stageRunning")
                      : t("research.stagePending")}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// Re-export the trigger so the detail route can wire the confirm dialog + re-trigger
// callback without importing two modules for one feature.
export { triggerResearch };
