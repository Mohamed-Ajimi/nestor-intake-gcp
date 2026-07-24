import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  AlertTriangle,
  ArrowDownToLine,
  CheckCircle2,
  ChevronDown,
  Circle,
  Download,
  FileSearch,
  Loader2,
  Lock,
  RotateCw,
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
  type ResearchStageSummary,
} from "@/lib/api/research";
import { AuditBodyPanel } from "@/components/intake/AuditBodyPanel";
import { VerificationReport } from "@/components/intake/VerificationReport";

// frontend/src/components/intake/ResearchRunProgress.tsx — the admin's live window into a
// Tribunal deep-research run (Phase 16, RUN-01/D-07/D-09). It mirrors SkillRunProgress's
// SSE-first + bounded-poll hook mechanics and the intake design language, but renders the
// FULL stage list DYNAMICALLY from the run's `stage_detail` — so a future Phase-15 added
// pass costs this UI nothing (T-16-14; NO hardcoded stage count / no literal 9).
//
// SECURITY (T-16-12): this component lives ONLY on the admin detail route. No client route
// or component imports it — the client-facing UI is unchanged during in_research (D-08).

const RESEARCH_TERMINAL = new Set(["completed", "failed", "cancelled"]);

/**
 * One row of the D15 activity feed. An `item` row is an agent card (task title, expandable
 * prompt, status line with facts/cost, retry state, drill-down); a `summary` row is a
 * per-block "Worked for X · N actions · $Y" card that closes out a stage. The enriched
 * fields are all optional (D-07): a legacy flat `{name,status}` item renders as an agent
 * card with no cost/prompt/retry/audit affordance — exactly as before.
 */
type StageRow =
  | {
      kind: "item";
      key: string;
      stageKey: string;
      name: string;
      status: string;
      task_prompt?: string;
      cost_usd?: string;
      facts?: number;
      retry?: { attempt: number; max: number; wait_s: number };
      audit_id?: string;
    }
  | {
      kind: "summary";
      key: string;
      stageKey: string;
      summary: ResearchStageSummary;
    };

/**
 * Flatten the mirrored `stage_detail` JSONB into an ordered, data-driven feed. The list
 * length is whatever the run reports — a run with 10 stages renders 10 blocks. Object key
 * order is preserved (insertion order for string keys), mirroring the engine's stage
 * sequence. Enriched item fields (cost_usd, task_prompt, retry, facts, audit_id) ride onto
 * each `item` row ADDITIVELY, and a stage's optional `summary` becomes a trailing summary
 * row — a row missing any of these renders as it did before (D-07 contract preserved).
 */
function toStageRows(run: ResearchRun | null): StageRow[] {
  if (!run?.stage_detail) return [];
  const rows: StageRow[] = [];
  for (const [stageKey, group] of Object.entries(run.stage_detail)) {
    const items = group?.items ?? [];
    if (items.length === 0) {
      // A stage with no sub-items still renders one row keyed on the stage itself.
      rows.push({ kind: "item", key: stageKey, stageKey, name: stageKey, status: "pending" });
    } else {
      for (const [idx, item] of items.entries()) {
        rows.push({
          kind: "item",
          key: `${stageKey}:${idx}`,
          stageKey,
          name: item.name,
          status: item.status,
          task_prompt: item.task_prompt,
          cost_usd: item.cost_usd,
          facts: item.facts,
          retry: item.retry,
          audit_id: item.audit_id,
        });
      }
    }
    // Trailing per-block summary card (D15 "Worked for X · N actions · $Y").
    if (group?.summary) {
      rows.push({ kind: "summary", key: `${stageKey}:__summary`, stageKey, summary: group.summary });
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
  if (status === "retry") return <RotateCw className="h-4 w-4 text-amber-600" />;
  if (status === "failed") return <AlertTriangle className="h-4 w-4 text-red-600" />;
  return <Circle className="h-4 w-4 text-ink/30" />;
}

/** Format a duration in seconds as "Xm Ys" (D15 summary-card style). */
function fmtDurationSecs(secs: number): string {
  const s = Math.max(0, Math.floor(secs));
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return m > 0 ? `${m}m ${rem}s` : `${rem}s`;
}

/**
 * A D15 per-block summary card — the professionalism signal that closes out a stage:
 * "Worked for {duration} · {actions} actions · {items_read} items read · ${cost}".
 * `items_read` is optional (only shown when the engine reports it).
 */
function StageSummaryCard({ summary }: { summary: ResearchStageSummary }) {
  const { t } = useTranslation("intake");
  const base = t("research.feed.summaryCard", {
    duration: fmtDurationSecs(summary.duration_s),
    actions: summary.actions,
    cost: fmtCost(summary.cost_usd, "—"),
  });
  return (
    <div className="my-2 border-l-2 border-ink/20 bg-paper px-3 py-1.5 font-mono text-[12px] text-ink/70">
      {base}
      {summary.items_read != null && (
        <span>{t("research.feed.summaryItemsRead", { count: summary.items_read })}</span>
      )}
    </div>
  );
}

/**
 * A single D15 agent card. Renders the task title, an expandable task prompt ("Show more"/
 * "Show less"), a status line mapping status → icon + a `done · N facts · $X` result, a
 * visible retry state ("retry {attempt}/{max} — waiting {wait_s}s"), and — when the item
 * carries an `audit_id` AND the run has an id — a drill-down affordance that opens the
 * redacted audit body. The card renders identically for a legacy item that lacks all the
 * enriched fields (D-07). `onDrillDown` is only wired when a real drill-down is possible;
 * there is NO no-op stub handler.
 */
function AgentCard({
  row,
  onDrillDown,
  drilldownOpen,
}: {
  row: Extract<StageRow, { kind: "item" }>;
  onDrillDown?: (auditId: string) => void;
  drilldownOpen?: boolean;
}) {
  const { t } = useTranslation("intake");
  const [promptOpen, setPromptOpen] = useState(false);

  const canDrill = !!row.audit_id && !!onDrillDown;

  const statusLabel =
    row.status === "done"
      ? t("research.stageDone")
      : row.status === "running"
        ? t("research.stageRunning")
        : row.status === "retry"
          ? t("research.feed.statusRetrying")
          : row.status === "failed"
            ? t("research.feed.statusFailed")
            : t("research.stagePending");

  // "done · 14 facts · $0.12" — only the parts the item actually carries.
  const resultParts: string[] = [statusLabel];
  if (row.facts != null) resultParts.push(t("research.feed.factsCount", { count: row.facts }));
  if (row.cost_usd != null && row.cost_usd !== "") resultParts.push(fmtCost(row.cost_usd, "—"));
  const resultLine = resultParts.join(" · ");

  return (
    <li className="border-l-2 border-ink/10 pl-3">
      <div className="flex items-start gap-2 font-mono text-[13px]">
        <span className="mt-0.5">
          <StageIcon status={row.status} />
        </span>
        <div className="min-w-0 flex-1">
          <div
            className={
              row.status === "done"
                ? "text-ink/80"
                : row.status === "running" || row.status === "retry"
                  ? "text-ink"
                  : row.status === "failed"
                    ? "text-red-700"
                    : "text-ink/40"
            }
          >
            {row.name}
          </div>
          <div className="mt-0.5 text-[11px] uppercase tracking-wider text-ink/40">
            {resultLine}
          </div>

          {/* Retries shown in the open (R5), never hidden. */}
          {row.retry && (
            <div className="mt-1 inline-flex items-center gap-1 bg-amber-50 px-2 py-0.5 text-[11px] text-amber-700">
              <RotateCw className="h-3 w-3" />
              {t("research.feed.retryState", {
                attempt: row.retry.attempt,
                max: row.retry.max,
                wait: row.retry.wait_s,
              })}
            </div>
          )}

          {/* Expandable subagent task prompt (Replit-style block). */}
          {row.task_prompt && (
            <div className="mt-1">
              <button
                type="button"
                onClick={() => setPromptOpen((v) => !v)}
                className="inline-flex items-center gap-1 text-[11px] uppercase tracking-wider text-ink/50 hover:text-ink"
              >
                <ChevronDown
                  className={`h-3 w-3 transition-transform ${promptOpen ? "rotate-180" : ""}`}
                />
                {promptOpen ? t("research.feed.showLess") : t("research.feed.showPrompt")}
              </button>
              {promptOpen && (
                <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap break-words bg-paper px-3 py-2 text-[12px] leading-relaxed text-ink/70">
                  {row.task_prompt}
                </pre>
              )}
            </div>
          )}

          {/* Audit-body drill-down affordance — hidden when audit_id OR run.id absent. */}
          {canDrill && (
            <button
              type="button"
              onClick={() => onDrillDown!(row.audit_id!)}
              className="mt-1 inline-flex items-center gap-1 text-[11px] uppercase tracking-wider text-ink/50 hover:text-ink"
            >
              <FileSearch className="h-3 w-3" />
              {drilldownOpen ? t("research.feed.hideAudit") : t("research.feed.viewAudit")}
            </button>
          )}
        </div>
      </div>
    </li>
  );
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
  // Local override so a successful (re-)verify flips the card immediately — on an old
  // terminal run the SSE stream may already be closed and would never push the new state.
  const [localChain, setLocalChain] = useState<"verified" | "broken" | null>(null);
  const chainStatus = localChain ?? run.chain_status;

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
      // Still broken — the lock stays.
      setLocalChain("broken");
      toast.error(t("research.reverifyStillBroken"));
      return;
    }
    // Flip to the download affordance locally — don't rely on the SSE stream, which is
    // closed for a run that reached terminal state before this page was opened.
    setLocalChain("verified");
  };

  if (chainStatus === "broken") {
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

  if (chainStatus === "verified") {
    return (
      <div className="mt-4">
        <button type="button" onClick={handleDownload} disabled={busy} className={btnClass}>
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
          {t("research.download")}
        </button>
      </div>
    );
  }

  // chain_status null: the chain was simply never checked for this run (pre-Phase-17 row,
  // or the driver died before stamping). Offer the verify action — the same re-verify
  // endpoint runs the D-06 gate and stamps verified/broken, after which the card flips.
  return (
    <div className="mt-4 border-l-4 bg-paper px-4 py-3" style={{ borderLeftColor: "#FF2D87" }}>
      <div className="mb-1 flex items-center gap-2">
        <span className="font-mono text-[11px] uppercase tracking-wider text-ink/70">
          {t("research.unverifiedTitle")}
        </span>
      </div>
      <div className="mb-3 font-sans text-[14px] leading-relaxed text-ink">
        {t("research.unverifiedBody")}
      </div>
      <button type="button" onClick={handleReverify} disabled={busy} className={btnClass}>
        {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <AlertTriangle className="h-4 w-4" />}
        {t("research.verifyChain")}
      </button>
    </div>
  );
}

/**
 * The D15 agent feed — the ordered list of agent cards + per-block summary cards, with the
 * audit-body drill-down wired. Shared by the ACTIVE panel and the COMPLETED summary card so
 * that after the run the feed "stays frozen and clickable" (D15). Owns the drill-down open
 * state + scroll-to-latest. When `runId` is null (no run id available) the drill-down
 * affordance is hidden for every row (guards against calling getAuditBody without a runId).
 */
function AgentFeed({
  rows,
  intakeId,
  runId,
}: {
  rows: StageRow[];
  intakeId: string;
  runId: string | null;
}) {
  const { t } = useTranslation("intake");
  const [openAuditId, setOpenAuditId] = useState<string | null>(null);
  const feedEndRef = useRef<HTMLDivElement | null>(null);
  const scrollToLatest = () => feedEndRef.current?.scrollIntoView({ behavior: "smooth" });

  if (rows.length === 0) return null;

  return (
    <div>
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="font-mono text-[11px] uppercase tracking-wider text-ink/50">
          {t("research.feed.title")}
        </span>
        <button
          type="button"
          onClick={scrollToLatest}
          className="inline-flex items-center gap-1 font-mono text-[11px] uppercase tracking-wider text-ink/50 hover:text-ink"
        >
          <ArrowDownToLine className="h-3 w-3" />
          {t("research.feed.scrollToLatest")}
        </button>
      </div>
      <ul className="max-h-[28rem] space-y-2 overflow-auto">
        {rows.map((row) =>
          row.kind === "summary" ? (
            <StageSummaryCard key={row.key} summary={row.summary} />
          ) : (
            <div key={row.key}>
              <AgentCard
                row={row}
                drilldownOpen={!!row.audit_id && openAuditId === row.audit_id}
                onDrillDown={
                  row.audit_id && runId
                    ? (auditId) => setOpenAuditId((cur) => (cur === auditId ? null : auditId))
                    : undefined
                }
              />
              {/* Real audit-body drill-down — intakeId + runId + auditId threaded. */}
              {row.audit_id && runId && openAuditId === row.audit_id && (
                <AuditBodyPanel
                  intakeId={intakeId}
                  runId={runId}
                  auditId={row.audit_id}
                  onClose={() => setOpenAuditId(null)}
                />
              )}
            </div>
          ),
        )}
      </ul>
      <div ref={feedEndRef} />
    </div>
  );
}

/**
 * The live research-progress panel. While the run is active it renders the dynamic D15
 * agent feed + running cost + elapsed clock. On a terminal status it collapses to a summary
 * card (completed → timestamp/cost/duration + the frozen, clickable feed; failed/cancelled →
 * error + a re-trigger affordance).
 *
 * `onRetry` re-invokes the trigger; the 3-attempt cap is enforced server-side, so the panel
 * always offers the affordance and lets the backend reject an over-cap retry.
 */
export function ResearchRunProgress({
  intakeId,
  runId: runIdProp,
  onRetry,
}: {
  intakeId: string;
  // Optional: the route may lift the run id explicitly. When omitted (the default), the
  // run id is sourced from the SSE run (`run.id`) internally. Either way the audit
  // drill-down threads intakeId + runId + auditId into AuditBodyPanel.
  runId?: string;
  onRetry?: () => void;
}) {
  const { t } = useTranslation("intake");
  const { run } = useActiveResearchRun(intakeId);
  // The run id used to scope the audit drill-down: prefer an explicit route prop, else the
  // SSE run's id. When neither exists, the drill-down affordance is hidden by AgentFeed.
  const runId = runIdProp ?? run?.id ?? null;
  // The D-09 summary card's "View verification report" toggle (superadmin-only surface).
  const [showVerification, setShowVerification] = useState(false);

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

          {/* D-09 summary-card action: open the superadmin verification report (funnel +
              verdicts + superseded + reconciled + unverified + true cost). Only reachable
              when a run id is available. Superadmin-only by placement. */}
          {runId && (
            <div className="mt-4">
              <button
                type="button"
                onClick={() => setShowVerification((v) => !v)}
                className="inline-flex items-center gap-2 border border-ink/30 px-4 py-2 font-mono text-xs uppercase tracking-wider text-ink hover:bg-ink/5"
              >
                {showVerification
                  ? t("verification.hideAction")
                  : t("verification.viewAction")}
              </button>
            </div>
          )}
          {runId && showVerification && (
            <div className="mt-4">
              <VerificationReport
                intakeId={intakeId}
                runId={runId}
                onClose={() => setShowVerification(false)}
              />
            </div>
          )}

          {/* D15: after the run the feed stays frozen + clickable — a replay of what
              happened, with the audit-body drill-down still reachable (superadmin-only). */}
          {stageRows.length > 0 && (
            <div className="mt-5 border-t border-ink/10 pt-4">
              <AgentFeed rows={stageRows} intakeId={intakeId} runId={runId} />
            </div>
          )}
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

      <AgentFeed rows={stageRows} intakeId={intakeId} runId={runId} />
    </div>
  );
}

// Re-export the trigger so the detail route can wire the confirm dialog + re-trigger
// callback without importing two modules for one feature.
export { triggerResearch };
