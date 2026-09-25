import { useCallback, useEffect, useId, useState } from "react";
import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { ArrowRight, Check, Download, ExternalLink, Loader2, RotateCw } from "lucide-react";
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
import { Skeleton } from "@/components/ui/skeleton";
import { IntakeOpenRunLink } from "@/components/intake/ResearchRunProgress";
import {
  chooseResearchRun,
  getBundleUrl,
  getResearchRuns,
  triggerResearch,
  type ResearchRun,
  type ResearchRunHistory as ResearchRunHistoryData,
  type ResearchRunHistoryItem,
} from "@/lib/api/research";
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
  type ChosenRun,
  type RerunLoadState,
} from "@/lib/research/runHistory";
import { statusLabel } from "@/lib/research/statusLabel";
import { fmtCost, fmtDate, fmtDuration, useElapsed } from "@/lib/research/runClock";
import { classifyTriggerOutcome } from "@/lib/research/triggerOutcome";
import { canHaveVerificationReport } from "@/lib/research/verificationGate";
import { resolveErrorKey } from "@/lib/i18n/error-codes";
import { cn } from "@/lib/utils";

// frontend/src/components/intake/ResearchRunHistory.tsx — Phase 23.6 (D-23.6-01/02/03/04).
//
// The superadmin's research-run history on the intake page: every run newest first, the
// internal "chosen run" label, and the Rerun button. Layout, copy and states follow the
// approved 23.6-UI-SPEC exactly; every DECISION (badge row, Rerun visible/disabled, which row
// actions show, what a failed rerun may claim about money) comes from the pure, tested
// `lib/research/runHistory.ts` — this file only renders them.
//
// ONE STREAM PER PAGE. This component opens NO research stream. The intake route owns the
// page's single `useActiveResearchRun` connection and hands its latest frame down as
// `liveRun`; the newest row's status/cost/clock are overlaid from it (`mergeLiveRun`). The list
// is refetched once when that frame's run id or status changes — never on a timer.
//
// SPEND ONLY FROM THE CONFIRM. The ~$40 trigger fires only from the rerun dialog's
// AlertDialogAction (Phase 16 D-03); the backend's 409 on an in-flight run stays the authority.
//
// The page renders this only for superadmins; `rerunState` still receives `isSuperadmin: true`
// so the rule keeps one input list.

const PRIMARY_BTN =
  "inline-flex items-center gap-2 bg-ink px-4 py-2 font-mono text-xs uppercase tracking-wider text-paper hover:bg-ink/85 disabled:opacity-50";
const SECONDARY_BTN =
  "inline-flex items-center gap-2 border border-ink bg-paper px-4 py-2 font-mono text-xs uppercase tracking-wider text-ink hover:border-2 disabled:opacity-50";
const LINK_BTN =
  "inline-flex items-center gap-2 border border-ink/30 px-4 py-2 font-mono text-xs uppercase tracking-wider text-ink hover:bg-ink/5 disabled:opacity-50";
const LABEL = "font-mono text-[11px] uppercase tracking-wider text-ink/60";
const TH =
  "px-4 py-2 text-left font-mono text-[11px] font-normal uppercase tracking-wider text-ink/60";

/** Awaited by the rerun flow; the page reloads the intake and reopens its one stream. */
type MaybePromise = Promise<void> | void;
type RerunStartedHandler = () => MaybePromise;

type Props = {
  intakeId: string;
  intakeStatus: string;
  liveRun: ResearchRun | null;
  onRerunStarted: RerunStartedHandler;
};

export function ResearchRunHistory({ intakeId, intakeStatus, liveRun, onRerunStarted }: Props) {
  const { t } = useTranslation("admin");
  const { t: tIntake } = useTranslation("intake");
  const reasonId = useId();

  const [history, setHistory] = useState<ResearchRunHistoryData | null>(null);
  const [loadState, setLoadState] = useState<RerunLoadState>("loading");
  const [rerunOpen, setRerunOpen] = useState(false);
  const [rerunBusy, setRerunBusy] = useState(false);
  const [chooseTarget, setChooseTarget] = useState<ResearchRunHistoryItem | null>(null);
  const [choosingId, setChoosingId] = useState<string | null>(null);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);

  /**
   * Load the run list. `isCancelled` is the effect's `let cancelled` flag, so a response that
   * lands after unmount (or after a newer refetch was keyed) is dropped. Returns the fetched
   * runs, or `null` when the fetch failed — the rerun failure path needs that distinction.
   */
  const fetchHistory = useCallback(
    async (isCancelled: () => boolean = () => false): Promise<ResearchRunHistoryItem[] | null> => {
      const res = await getResearchRuns(intakeId);
      if (isCancelled()) return res.success ? res.data.runs : null;
      if (res.success) {
        setHistory(res.data);
        setLoadState("ready");
        return res.data.runs;
      }
      setLoadState((prev) => (prev === "ready" ? prev : "error"));
      return null;
    },
    [intakeId],
  );

  const liveId = liveRun?.id ?? null;
  const liveStatus = liveRun?.status ?? null;
  // Refetch ONCE per change of the live run's id or status (and on mount). Keyed on the two
  // primitives only — a frame that changes nothing but cost/clock does not refetch.
  useEffect(() => {
    let cancelled = false;
    void fetchHistory(() => cancelled);
    return () => {
      cancelled = true;
    };
  }, [fetchHistory, liveId, liveStatus]);

  const runs = sortRunsNewestFirst(mergeLiveRun(history?.runs ?? [], liveRun));
  const chosen = resolveChosenRun(runs, history?.chosen_research_run_id ?? null);
  const rerun = rerunState({ isSuperadmin: true, intakeStatus, runs, loadState });
  const showRerun = rerun.visible;
  const rerunDisabled = rerun.disabled || rerunBusy;
  const blockedInFlight = rerun.reason === "in_flight";

  const handleRetry = () => {
    setLoadState("loading");
    void fetchHistory();
  };

  const handleRerunConfirm = async () => {
    if (rerunBusy) return;
    const beforeIds = new Set(runs.map((r) => r.id));
    setRerunBusy(true);
    try {
      const res = await triggerResearch(intakeId);
      switch (classifyTriggerOutcome(res)) {
        case "started":
          toast.success(t("intakeDetail.runs.toast.rerunStarted"));
          await onRerunStarted();
          await fetchHistory();
          break;
        case "needs_investigation":
          toast.warning(t("intakeDetail.toast.researchNeedsInvestigation"));
          await fetchHistory();
          break;
        case "error": {
          // Copy truth: the trigger's 409 carries no machine code, so what the toast may claim
          // about money is decided from a list refetched AFTER the failure. A failed refetch is
          // `null` and classifies as maybe_started — never the "nothing charged" copy.
          const freshRuns = await fetchHistory();
          const failure = classifyRerunFailure(beforeIds, freshRuns);
          if (failure === "in_flight") {
            toast.error(t("intakeDetail.runs.toast.rerunInFlight"));
          } else if (failure === "maybe_started") {
            toast.error(t("intakeDetail.toast.researchStartFailed"));
            await onRerunStarted();
          } else {
            const codeKey = res.success ? undefined : resolveErrorKey(res.code);
            toast.error(codeKey ? t(codeKey) : t("intakeDetail.runs.toast.rerunFailed"));
          }
          break;
        }
      }
    } finally {
      setRerunBusy(false);
    }
  };

  const handleChooseConfirm = async () => {
    const target = chooseTarget;
    if (!target || choosingId) return;
    setChoosingId(target.id);
    try {
      const res = await chooseResearchRun(intakeId, target.id);
      if (res.success && res.data?.chosen_research_run_id) {
        const newId = res.data.chosen_research_run_id;
        // The badge moves locally — no page reload. Internal label only (D-23.6-02 revised).
        setHistory((prev) => (prev ? { ...prev, chosen_research_run_id: newId } : prev));
        toast.success(t("intakeDetail.runs.toast.chooseDone", { number: target.attempt }));
      } else {
        toast.error(t("intakeDetail.runs.toast.chooseFailed"));
      }
    } finally {
      setChoosingId(null);
      setChooseTarget(null);
    }
  };

  const handleDownload = async (run: ResearchRunHistoryItem) => {
    if (downloadingId) return;
    setDownloadingId(run.id);
    const res = await getBundleUrl(intakeId, run.id);
    setDownloadingId(null);
    if (res.success && res.data?.url) {
      // The signed URL forces attachment disposition server-side -> the browser downloads.
      window.location.href = res.data.url;
    } else {
      toast.error(tIntake("research.downloadError"));
    }
  };

  const rowActionProps = {
    chosen,
    intakeStatus,
    choosingId,
    downloadingId,
    onChoose: (run: ResearchRunHistoryItem) => setChooseTarget(run),
    onDownload: (run: ResearchRunHistoryItem) => void handleDownload(run),
  };

  return (
    <div className="border-t border-ink/10 bg-paperLight px-6 py-5">
      {/* Header row */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className={LABEL}>
          {t("intakeDetail.runs.title")}{" "}
          {loadState === "ready" && (
            <span className="tabular-nums text-ink/40">({runs.length})</span>
          )}
        </h3>
        {showRerun && (
          <button
            type="button"
            className={cn(PRIMARY_BTN, "w-full justify-center sm:w-auto")}
            disabled={rerunDisabled}
            onClick={() => setRerunOpen(true)}
            aria-describedby={blockedInFlight ? reasonId : undefined}
            title={blockedInFlight ? t("intakeDetail.runs.rerunBlockedInFlight") : undefined}
          >
            {rerunBusy ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <RotateCw className="h-3.5 w-3.5" />
            )}
            {rerunBusy ? t("intakeDetail.runs.rerunStarting") : t("intakeDetail.runs.rerun")}
          </button>
        )}
      </div>
      {showRerun && blockedInFlight && (
        <p id={reasonId} className="mt-2 font-sans text-[14px] text-ink/60">
          {t("intakeDetail.runs.rerunBlockedInFlight")}
        </p>
      )}

      {loadState === "loading" && (
        <div className="mt-4 flex flex-col gap-2">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      )}

      {loadState === "error" && (
        <div className="mt-4 space-y-3">
          <p className="text-sm text-red-600">{t("intakeDetail.runs.loadFailed")}</p>
          <button type="button" className={SECONDARY_BTN} onClick={handleRetry}>
            {t("intakeDetail.runs.retry")}
          </button>
          {/* A failed list never removes the way into the run page. */}
          <div>
            <IntakeOpenRunLink runId={liveRun?.id ?? null} />
          </div>
        </div>
      )}

      {loadState === "ready" && runs.length === 0 && (
        <p className="mt-4 font-sans text-[14px] text-ink/60">{t("intakeDetail.runs.empty")}</p>
      )}

      {loadState === "ready" && runs.length > 0 && (
        <>
          {chosen.runId === null && (
            <p className="mt-2 font-sans text-[14px] text-ink/60">
              {t("intakeDetail.runs.noChosenRun")}
            </p>
          )}

          {/* Desktop (md+) */}
          <table className="mt-4 hidden w-full md:table">
            <caption className="sr-only">{t("intakeDetail.runs.title")}</caption>
            <thead className="bg-paper2">
              <tr>
                <th scope="col" className={TH}>
                  {t("intakeDetail.runs.col.attempt")}
                </th>
                <th scope="col" className={TH}>
                  {t("intakeDetail.runs.col.status")}
                </th>
                <th scope="col" className={TH}>
                  {t("intakeDetail.runs.col.started")}
                </th>
                <th scope="col" className={TH}>
                  {t("intakeDetail.runs.col.duration")}
                </th>
                <th scope="col" className={TH}>
                  {t("intakeDetail.runs.col.cost")}
                </th>
                <th scope="col" className={TH}>
                  <span className="sr-only">{t("intakeDetail.runs.col.actions")}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.id} className="border-t border-ink/10">
                  <td className="px-4 py-3 align-top font-mono text-[11px] uppercase tracking-wider text-ink">
                    {tIntake("research.runPage.trace.attempt", { number: run.attempt })}
                  </td>
                  <td className="px-4 py-3 align-top">
                    <StatusBadge status={run.status} />
                  </td>
                  <td className="px-4 py-3 align-top font-mono text-xs tabular-nums text-ink">
                    {fmtDate(run.started_at, "—")}
                  </td>
                  <td className="px-4 py-3 align-top font-mono text-xs tabular-nums text-ink">
                    <RunDuration run={run} />
                  </td>
                  <td className="px-4 py-3 align-top font-mono text-xs tabular-nums text-ink">
                    {fmtCost(run.cost_usd_total, "—")}
                  </td>
                  <td className="px-4 py-3 align-top">
                    <div className="flex flex-col items-end gap-2">
                      <ChosenBadge run={run} chosen={chosen} />
                      <RowActions run={run} mobile={false} {...rowActionProps} />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {/* Mobile (below md) */}
          <ol className="mt-4 divide-y divide-ink/10 md:hidden">
            {runs.map((run) => (
              <li key={run.id} className="space-y-2 py-4">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-[11px] uppercase tracking-wider text-ink">
                    {tIntake("research.runPage.trace.attempt", { number: run.attempt })}
                  </span>
                  <StatusBadge status={run.status} />
                </div>
                <p className="font-mono text-xs tabular-nums text-ink/60">
                  {t("intakeDetail.runs.startedMobile", { date: fmtDate(run.started_at, "—") })}
                  {" · "}
                  <RunDuration run={run} />
                  {" · "}
                  {fmtCost(run.cost_usd_total, "—")}
                </p>
                <ChosenBadge run={run} chosen={chosen} />
                <RowActions run={run} mobile {...rowActionProps} />
              </li>
            ))}
          </ol>
        </>
      )}

      {/* Rerun confirm — the ONLY place a (~$40) rerun is triggered. */}
      <AlertDialog open={rerunOpen} onOpenChange={setRerunOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("intakeDetail.runs.rerunConfirmTitle")}</AlertDialogTitle>
            <AlertDialogDescription asChild>
              <div className="space-y-2 font-sans text-[14px]">
                <p>{t("intakeDetail.runs.rerunConfirmBody")}</p>
                {rerun.parkedNote && <p>{t("intakeDetail.runs.rerunConfirmParkedNote")}</p>}
              </div>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("intakeDetail.runs.rerunConfirmCancel")}</AlertDialogCancel>
            <AlertDialogAction disabled={rerunDisabled} onClick={() => void handleRerunConfirm()}>
              {t("intakeDetail.runs.rerunConfirmConfirm")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Choose confirm — internal label only, no client effect. */}
      <AlertDialog
        open={chooseTarget !== null}
        onOpenChange={(open) => {
          if (!open && !choosingId) setChooseTarget(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t("intakeDetail.runs.chooseConfirmTitle", { number: chooseTarget?.attempt ?? "" })}
            </AlertDialogTitle>
            <AlertDialogDescription className="font-sans text-[14px]">
              {t("intakeDetail.runs.chooseConfirmBody")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={choosingId !== null}>
              {t("intakeDetail.runs.chooseConfirmCancel")}
            </AlertDialogCancel>
            <AlertDialogAction
              disabled={choosingId !== null}
              onClick={(e) => {
                // Keep the dialog open while the request is in flight; it closes in `finally`.
                e.preventDefault();
                void handleChooseConfirm();
              }}
            >
              {choosingId !== null && <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />}
              {t("intakeDetail.runs.chooseConfirmConfirm")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

/** Status badge per the UI-SPEC mapping (`runStatusBadge` decides; this only renders). */
function StatusBadge({ status }: { status: string }) {
  const { t: tIntake } = useTranslation("intake");
  const badge = runStatusBadge(status);
  return (
    <span className={badge.className}>
      {badge.mark === "green" && <span className="mark-green" aria-hidden="true" />}
      {badge.mark === "ink" && <span className="mark-ink" aria-hidden="true" />}
      {badge.spinner && <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />}
      {statusLabel(badge.labelStatus, tIntake)}
    </span>
  );
}

/** Fixed duration for a terminal run; the ONE live clock (`useElapsed`) for an in-flight run. */
function RunDuration({ run }: { run: ResearchRunHistoryItem }) {
  if (RESEARCH_IN_FLIGHT_STATUSES.has(run.status)) {
    return <RunningClock startedAt={run.started_at} />;
  }
  return <>{fmtDuration(run.started_at, run.completed_at)}</>;
}

/** A subcomponent so each in-flight row calls the clock hook once (hooks cannot loop). */
function RunningClock({ startedAt }: { startedAt: string | null }) {
  const elapsed = useElapsed(startedAt, true);
  if (!startedAt) return <>—</>;
  return <>{elapsed}</>;
}

/** The yellow "chosen run" badge + its sub-line, on exactly the one chosen row. */
function ChosenBadge({ run, chosen }: { run: ResearchRunHistoryItem; chosen: ChosenRun }) {
  const { t } = useTranslation("admin");
  if (chosen.runId !== run.id) return null;
  const sub =
    chosen.source === "marked"
      ? t("intakeDetail.runs.chosenBadgeMarked")
      : t("intakeDetail.runs.chosenBadgeDefault");
  const label = t("intakeDetail.runs.chosenBadge");
  return (
    <div className="flex flex-col gap-1 md:items-end">
      <span className="badge-highlight" aria-label={`${label}. ${sub}`}>
        <Check className="h-3 w-3" aria-hidden="true" />
        {label}
      </span>
      <span className="font-sans text-[14px] text-ink/60 md:text-right" aria-hidden="true">
        {sub}
      </span>
    </div>
  );
}

function RowActions({
  run,
  mobile,
  chosen,
  intakeStatus,
  choosingId,
  downloadingId,
  onChoose,
  onDownload,
}: {
  run: ResearchRunHistoryItem;
  mobile: boolean;
  chosen: ChosenRun;
  intakeStatus: string;
  choosingId: string | null;
  downloadingId: string | null;
  onChoose: (run: ResearchRunHistoryItem) => void;
  onDownload: (run: ResearchRunHistoryItem) => void;
}) {
  const { t } = useTranslation("admin");
  const { t: tIntake } = useTranslation("intake");
  const touch = mobile ? "min-h-[44px]" : undefined;
  const finished = RESEARCH_SUCCESS_STATUSES.has(run.status);
  const canZip = canDownloadRunZip(run);
  return (
    <div className={cn("flex flex-col gap-1", !mobile && "items-end")}>
      <div className={cn("flex flex-wrap gap-2", !mobile && "justify-end")}>
        {canChooseRun(run, chosen, intakeStatus) && (
          <button
            type="button"
            className={cn(SECONDARY_BTN, touch)}
            disabled={choosingId !== null}
            onClick={() => onChoose(run)}
          >
            {choosingId === run.id && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
            {t("intakeDetail.runs.choose")}
          </button>
        )}
        <Link
          to="/admin/pulse/runs/$runId"
          params={{ runId: run.id }}
          className={cn(LINK_BTN, touch)}
        >
          <ExternalLink className="h-3.5 w-3.5" />
          {tIntake("research.openRun")}
        </Link>
        {canHaveVerificationReport(run.status) && (
          <Link
            to="/admin/pulse/runs/$runId/verification"
            params={{ runId: run.id }}
            className={cn(LINK_BTN, touch)}
          >
            {tIntake("verification.viewAction")}
            <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        )}
        {canZip && (
          <button
            type="button"
            className={cn(LINK_BTN, touch)}
            disabled={downloadingId !== null}
            onClick={() => onDownload(run)}
          >
            {downloadingId === run.id ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Download className="h-3.5 w-3.5" />
            )}
            {tIntake("research.download")}
          </button>
        )}
      </div>
      {finished && !canZip && (
        <p className={cn("font-sans text-[14px] text-ink/60", !mobile && "text-right")}>
          {t("intakeDetail.runs.zipOnRunPage")}
        </p>
      )}
    </div>
  );
}
