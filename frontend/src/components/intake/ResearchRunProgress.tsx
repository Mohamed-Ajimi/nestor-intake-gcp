import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "@tanstack/react-router";
import {
  AlertTriangle,
  ArrowDownToLine,
  CheckCircle2,
  ChevronDown,
  Circle,
  Download,
  ExternalLink,
  FileSearch,
  Loader2,
  Lock,
  RotateCw,
  StopCircle,
  XCircle,
} from "lucide-react";
import { toast } from "sonner";
// The clock and formatters now live in ONE place, shared with the dedicated run page
// (15.3-08). The bodies are unchanged by the move — in particular `useElapsed` still
// derives from the run's own `started_at`, which is the whole reason it is worth sharing.
import { fmtCost, fmtDate, fmtDuration, useElapsed } from "@/lib/research/runClock";
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
// The confirm gate for the Stop button. This is the SAME affordance the research
// TRIGGER already uses (NextStepBanner's `researchConfirm*` AlertDialog) — the existing
// house pattern for a destructive/paid research action. No new dialog component is
// introduced and `components/ui/**` is not modified (CLAUDE.md).
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";

// frontend/src/components/intake/ResearchRunProgress.tsx — the admin's live window into a
// Tribunal deep-research run (Phase 16, RUN-01/D-07/D-09). It mirrors SkillRunProgress's
// SSE-first + bounded-poll hook mechanics and the intake design language, but renders the
// FULL stage list DYNAMICALLY from the run's `stage_detail` — so a future Phase-15 added
// pass costs this UI nothing (T-16-14; NO hardcoded stage count / no literal 9).
//
// SECURITY (T-16-12): this component lives ONLY on the admin detail route. No client route
// or component imports it — the client-facing UI is unchanged during in_research (D-08).

// D-12: `completed_degraded` is terminal here AND must be handled by the success branch
// below — adding it to this set alone would route a degraded run into the cancelled card.
// `parked` IS terminal here (15.2-19 / DEC-3) now that the Resume affordance exists, and
// like `completed_degraded` it MUST be handled by its own branch below — adding it to this
// set alone would route a paused run into the cancelled card.
const RESEARCH_TERMINAL = new Set([
  "completed",
  "completed_degraded",
  "failed",
  "cancelled",
  "parked",
]);

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
 *
 * EXPORTED for the dedicated run page (`routes/admin.pulse.runs.$runId.tsx`, 15.3-08), which
 * needs exactly this — one connection that is the single authority on status, stage, cost,
 * `started_at` and the feed cursor. A second copy of these mechanics on the run page would be
 * a second opinion about when a run ended; there must be only one.
 *
 * `reopenKey` (15.3-09, OPTIONAL — omitting it is exactly the previous behaviour) exists for
 * ONE situation: a paused run's stream is already closed, because a pause waits on a human
 * click that may be hours away and holding the connection open would burn the handler to its
 * cap. When the operator then continues that run from the run page, no frame will ever arrive
 * on the closed connection and the page would sit on the paused card forever. Bumping this
 * value re-runs the effect and opens a fresh connection. It is NOT a poll and must never be
 * driven by a timer — it is bumped by a completed operator action and by nothing else.
 */
export function useActiveResearchRun(
  intakeId: string | undefined,
  reopenKey?: number,
): {
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
  }, [intakeId, reopenKey]);

  return { run };
}

/**
 * The way into the dedicated run page (15.3-08 / D-01). ONE definition rendered in ALL FOUR
 * card branches — active, completed/degraded, parked, and failed/cancelled.
 *
 * It is present on the failure branches DELIBERATELY. A failed or cancelled run is exactly
 * the run whose detail an operator needs, and those two cards are the ones that drop the feed
 * entirely today; sending them to a page that keeps the full event history is the point.
 *
 * Styled as the card's existing SECONDARY action (bordered, mono, uppercase, tracking-wider),
 * not as a new primary button — it must not compete with Resume, Retry or Stop, which are the
 * actions that change something.
 */
function OpenRunLink({ runId }: { runId: string }) {
  const { t } = useTranslation("intake");
  return (
    <Link
      to="/admin/pulse/runs/$runId"
      params={{ runId }}
      className="mt-4 inline-flex items-center gap-2 border border-ink/30 px-4 py-2 font-mono text-xs uppercase tracking-wider text-ink hover:bg-ink/5"
    >
      <ExternalLink className="h-3.5 w-3.5" />
      {t("research.openRun")}
    </Link>
  );
}

/**
 * The intake detail page's link-only research surface (D-22-5).
 *
 * WHY THIS EXISTS AT ALL. D-22-5 takes the embedded feed off the intake detail page — operator
 * verbatim: *"activity shouldnt show on the intake page, we already have a open run button that
 * opens it in a different page and it is exactly the same so no need to have it there."* But the
 * same ruling keeps the link and makes it THE way in. `OpenRunLink` above is defined here and was
 * rendered ONLY from this file's four card branches, so removing the `<ResearchRunProgress>`
 * element from the intake page WITHOUT this wrapper would leave the app with no navigation into
 * the run page at all — only a bookmarked URL. (`RunActions`' own `navigate` is not an entry
 * point: it fires once you are ALREADY on the run page.) This wrapper is the whole reason the
 * removal is not a capability loss.
 *
 * WHY IT USES THE HOOK. `useActiveResearchRun` is the only client-side way to learn an intake's
 * latest run id: `Intake` (`lib/api/intakes.ts`) carries no research-run field, and
 * `locateResearchRun` goes the OTHER way (run id → intake id). The hook stays inside this
 * component rather than being called from the route, which keeps the intake route free of a
 * research stream it does not own.
 *
 * NETWORK COST. This mounts ONE SSE connection — the very same connection the removed component
 * already opened on that page. Strictly less network than before, never more, and the stream
 * still closes itself on a terminal run (`onTerminal → stream.close()`).
 *
 * Renders nothing until a run id is known, so an intake with no run shows no dead link.
 */
export function IntakeOpenRunLink({ intakeId }: { intakeId: string }) {
  const { run } = useActiveResearchRun(intakeId);
  if (!run?.id) return null;
  return <OpenRunLink runId={run.id} />;
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
 *
 * `onResume` is the route-supplied handler that POSTs the resume for a PARKED run and then
 * re-loads. Distinct from `onRetry` on purpose: a retry starts a NEW attempt and re-charges
 * the engine, while a resume continues the SAME run from its checkpoints for free (F-02).
 *
 * `onCancel` (D-D, plan 15.2-25) is the route-supplied handler that POSTs the cancel for a
 * LIVE run and then re-loads. It is the operator's only stop path: before it existed, the
 * only way to stop a run was to pause the whole tribunal-worker service, which does not
 * stop the run and nearly caused a fresh worker to re-claim it at full cost.
 */
export function ResearchRunProgress({
  intakeId,
  runId: runIdProp,
  onRetry,
  onResume,
  onCancel,
}: {
  intakeId: string;
  // Optional: the route may lift the run id explicitly. When omitted (the default), the
  // run id is sourced from the SSE run (`run.id`) internally. Either way the audit
  // drill-down threads intakeId + runId + auditId into AuditBodyPanel.
  runId?: string;
  onRetry?: () => void;
  onResume?: () => void | Promise<void>;
  onCancel?: () => void | Promise<void>;
}) {
  const { t } = useTranslation("intake");
  const { run } = useActiveResearchRun(intakeId);
  // T-15.2-193: guards a double-click while a run-lifecycle request is in flight. The
  // backend is the authoritative state guard anyway; this only stops the operator firing
  // two requests at once. ONE flag deliberately serves BOTH resume and cancel — they can
  // never be on screen at the same time (resume is the parked card, cancel is the active
  // card), so a second flag would be two names for one condition.
  const [actionBusy, setActionBusy] = useState(false);
  // Open-state of the Stop confirmation. Not a second busy flag — the dialog's own
  // visibility, matching NextStepBanner's `researchConfirmOpen`.
  const [cancelConfirmOpen, setCancelConfirmOpen] = useState(false);
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
  //
  // `parked` (the D-17 wall, NOT `needs_input`) is different: it gets its OWN card
  // below. Routing it to the failure card would offer a re-trigger, which starts a
  // fresh attempt and throws away every checkpoint the engine already paid for.
  const isTerminal = RESEARCH_TERMINAL.has(status) || status === "needs_input";
  const stageRows = toStageRows(run);
  const elapsed = useElapsed(run?.started_at ?? null, !isTerminal);
  const costFallback = t("research.costFallback");
  const dateFallback = t("research.dateFallback");

  // ── Terminal: summary / failure card ─────────────────────────────────────────────
  if (isTerminal) {
    // D-09/D-12: a `completed_degraded` run deliberately renders the FINISHED card,
    // not the failure card. Reaching the failure card would strip the raw-output
    // download, the verification-report button and the frozen feed from a ~$45 run —
    // the exact opposite of D-09. Only the border, icon, title and body differ; every
    // affordance below stays unconditional. The degradation REASONS are not listed
    // here: 15.2-08 shapes them into the verification report, reached from the
    // "View verification report" button already in this card.
    if (status === "completed" || status === "completed_degraded") {
      const isDegraded = status === "completed_degraded";
      return (
        <div
          className="mb-5 border border-ink/30 border-l-4 bg-paperLight px-6 py-5"
          style={{ borderLeftColor: isDegraded ? "#D97706" : "#DFF940" }}
          role="status"
          aria-live="polite"
        >
          <div className="mb-2 flex items-center gap-2">
            {isDegraded ? (
              <AlertTriangle className="h-5 w-5 text-emerald-600" />
            ) : (
              <CheckCircle2 className="h-5 w-5 text-emerald-600" />
            )}
            <span
              className="font-mono text-[11px] uppercase tracking-wider"
              style={{ color: "#7A8B00" }}
            >
              {isDegraded ? t("research.degradedTitle") : t("research.completedTitle")}
            </span>
          </div>
          <div className="mb-3 font-sans text-[15px] leading-relaxed text-ink">
            {isDegraded ? t("research.degradedBody") : t("research.completedBody")}
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

          {/* Branch 1 of 4: the way into the dedicated run page. */}
          {runId && <OpenRunLink runId={runId} />}

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

    // ── parked: the F-01 Resume card ────────────────────────────────────────────
    // A parked run deliberately renders a RESUME card rather than the failure card.
    // Reaching the failure card would offer a full re-trigger, which discards the
    // run's paid checkpoints — the opposite of what a park is for. It also renders
    // no RawOutputControls and no verification toggle: a parked run has no report
    // and no bundle (`report_readable("parked")` is false and the intake-side
    // download gate would 409).
    if (status === "parked") {
      return (
        <div
          className="mb-5 border border-ink/30 border-l-4 bg-paperLight px-6 py-5"
          style={{ borderLeftColor: "#D97706" }}
          role="status"
          aria-live="polite"
        >
          <div className="mb-2 flex items-center gap-2">
            <AlertTriangle className="h-5 w-5 text-amber-600" />
            <span
              className="font-mono text-[11px] uppercase tracking-wider"
              style={{ color: "#B45309" }}
            >
              {t("research.parkedTitle")}
            </span>
          </div>
          <div className="mb-3 font-sans text-[15px] leading-relaxed text-ink">
            {t("research.parkedBody")}
          </div>
          {run?.error_message && (
            <div className="mb-4">
              <div className="mb-1 font-mono text-[11px] uppercase tracking-wider text-ink/50">
                {t("research.parkedReasonLabel")}
              </div>
              {/* The mirrored error_message carries the `[park#n]` marker. Rendered
                  AS-IS: it is the operator's evidence of whether the park mail was
                  already sent. Do not strip it and do not parse it. React renders
                  this as a text child, never as markup. */}
              <div className="whitespace-pre-wrap break-words font-mono text-[13px] text-amber-700">
                {run.error_message}
              </div>
            </div>
          )}
          {onResume && (
            <button
              type="button"
              disabled={actionBusy}
              onClick={async () => {
                setActionBusy(true);
                try {
                  await onResume?.();
                } finally {
                  setActionBusy(false);
                }
              }}
              className="inline-flex items-center gap-2 bg-ink px-4 py-2 font-mono text-xs uppercase tracking-wider text-paper hover:bg-ink/85 disabled:opacity-60"
            >
              {actionBusy && <Loader2 className="h-4 w-4 animate-spin" />}
              {t("research.resume")}
            </button>
          )}
          {/* Branch 2 of 4. A parked run is mid-flight — its feed is the evidence of where
              the wall is, so the deeper page matters here as much as the Resume button. */}
          {runId && <OpenRunLink runId={runId} />}
          {/* The frozen feed: exactly where the run stopped, still clickable. */}
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
        {/* Branch 3 of 4 — failed | cancelled. THIS is the branch the link exists for: these
            two cards drop the feed entirely, so today they show the word "failed" and nothing
            else. The run page keeps the whole event history for exactly these states. */}
        {runId && <OpenRunLink runId={runId} />}
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
          {/* D-D: the Stop control. Rendered ONLY when the route supplies `onCancel`, and
              only here — this whole block is the ACTIVE card, unreachable once the run is
              terminal, so a terminal run can never show it. It sits BENEATH the cost line
              in the right-hand column deliberately: the cost is the number that makes an
              operator want to stop, and placing it here keeps it out of competition with
              the stage feed for attention. Secondary (outline) styling, not the primary
              ink fill — stopping is a rare escape hatch, not the expected next action. */}
          {onCancel && (
            <button
              type="button"
              disabled={actionBusy}
              onClick={() => setCancelConfirmOpen(true)}
              className="mt-2 inline-flex items-center gap-2 border border-ink/40 px-3 py-1.5 font-mono text-[11px] uppercase tracking-wider text-ink hover:bg-ink/5 disabled:opacity-60"
            >
              {actionBusy ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <StopCircle className="h-3.5 w-3.5" />
              )}
              {actionBusy ? t("research.cancelling") : t("research.cancel")}
            </button>
          )}
        </div>
      </div>

      {/* The confirm gate — the same AlertDialog affordance the research TRIGGER uses.
          The POST fires ONLY on the confirm action; Cancel is a no-op. The body states
          that the cost so far is not refunded and that the run cannot be continued
          afterwards, only re-triggered — both are true and both are irreversible. */}
      {onCancel && (
        <AlertDialog open={cancelConfirmOpen} onOpenChange={setCancelConfirmOpen}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>{t("research.cancelConfirmTitle")}</AlertDialogTitle>
              <AlertDialogDescription>{t("research.cancelConfirm")}</AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>{t("nextStep.researchConfirmCancel")}</AlertDialogCancel>
              <AlertDialogAction
                onClick={async () => {
                  setActionBusy(true);
                  try {
                    await onCancel?.();
                  } finally {
                    setActionBusy(false);
                  }
                }}
              >
                {t("research.cancel")}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      )}

      {run?.current_stage && (
        <div className="mb-3 font-mono text-[12px] text-ink/60">
          {t("research.currentStage", { stage: run.current_stage })}
        </div>
      )}

      {/* Branch 4 of 4 — the ACTIVE card. The card stays the intake-page summary; the page
          is the depth behind it. Neither replaces the other (15.3 CONTEXT, out of scope). */}
      {runId && <OpenRunLink runId={runId} />}

      <AgentFeed rows={stageRows} intakeId={intakeId} runId={runId} />
    </div>
  );
}

// Re-export the trigger so the detail route can wire the confirm dialog + re-trigger
// callback without importing two modules for one feature.
export { triggerResearch };
