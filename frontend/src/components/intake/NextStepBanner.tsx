import { useEffect, useState } from "react";
import { Trans, useTranslation } from "react-i18next";
import { Clock, Loader2 } from "lucide-react";
import { format } from "date-fns";
import i18n from "@/lib/i18n";
import { getDateLocale } from "@/lib/i18n/date-locale";
import type { Phase } from "@/lib/intake-phase";
import type { ActiveSkillRun } from "./SkillRunProgress";
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

type Props = {
  phase: Phase;
  validationLinkSentAt: string | null;
  resultsLinkSentAt: string | null;
  deliveredAt: string | null;
  activeRun?: ActiveSkillRun | null;
  busy: Partial<Record<BusyKey, boolean>>;
  onRunSkill: () => void;
  onSendIntakeMail: () => void;
  onCopyIntakeLink: () => void;
  onOpenAIReview: () => void;
  onSendValidationMail: () => void;
  onCopyValidationLink: () => void;
  onSendValidationReminder: () => void;
  onGenerateContextPack: () => void;
  onStartAutoResearch: () => void;
  onDownloadContextPack: () => void;
  onUploadFinalReport: () => void;
  onSendResultsMail: () => void;
  onCopyResultsLink: () => void;
  onArchive: () => void;
};

export type BusyKey =
  | "runSkill"
  | "sendIntake"
  | "sendValidation"
  | "sendReminder"
  | "generateContextPack"
  | "startResearch"
  | "uploadReport"
  | "sendResults"
  | "archive";

function fmtDate(d: string | null, at: string, fallback: string): string {
  if (!d) return fallback;
  try {
    return format(new Date(d), `d MMM yyyy '${at}' HH:mm`, {
      locale: getDateLocale(i18n.language),
    });
  } catch {
    return d;
  }
}

const primaryCls =
  "inline-flex items-center gap-2 bg-ink px-4 py-2 font-mono text-xs uppercase tracking-wider text-paper hover:bg-ink/85 disabled:opacity-50";
const secondaryCls =
  "inline-flex items-center gap-2 border border-ink bg-transparent px-4 py-2 font-mono text-xs uppercase tracking-wider text-ink hover:border-2 disabled:opacity-50";

function PrimaryBtn({
  onClick,
  busy,
  children,
}: {
  onClick: () => void;
  busy?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button type="button" onClick={onClick} disabled={busy} className={primaryCls}>
      {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
      {children}
    </button>
  );
}

function SecondaryBtn({
  onClick,
  busy,
  children,
}: {
  onClick: () => void;
  busy?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button type="button" onClick={onClick} disabled={busy} className={secondaryCls}>
      {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
      {children}
    </button>
  );
}

function Tooltip({ text }: { text: string }) {
  return (
    <span
      className="ml-1 cursor-help text-ink/40"
      title={text}
      aria-label={text}
    >
      ⓘ
    </span>
  );
}

/**
 * Elapsed clock for an in-flight AI skill run.
 *
 * `startedAt` MUST be the run's real start (`ActiveSkillRun.created_at`, i.e. backend
 * `skill_runs.created_at`) — a value that is STABLE for the lifetime of the run. It used
 * to be fed `ActiveSkillRun.triggered_at`, which for a still-running run is synthesised as
 * wall-clock `new Date()`; because that produced a NEW value on every re-map, the effect's
 * dependency changed on every SSE event and every 5s poll and the clock restarted from
 * 00:00 roughly every 5 seconds — as well as on every mount, so it never survived a
 * refresh. Nothing about the counting method changed; only the value it counts from.
 *
 * This is NOT a second clock definition: the deep-research run page has its own,
 * `lib/research/runClock.ts::useElapsed`, which is correct and is deliberately untouched.
 * This one is the intake page's skill-run banner clock.
 */
function RunningClock({ startedAt }: { startedAt: string }) {
  const { t } = useTranslation("intake");
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const start = new Date(startedAt).getTime();
    const tick = () => setElapsed(Math.max(0, Math.floor((Date.now() - start) / 1000)));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [startedAt]);
  const mm = String(Math.floor(elapsed / 60)).padStart(2, "0");
  const ss = String(elapsed % 60).padStart(2, "0");
  return (
    <button
      type="button"
      disabled
      aria-live="polite"
      className="inline-flex items-center gap-2 border border-ink/40 bg-paper px-4 py-2 font-mono text-xs uppercase tracking-wider text-ink/70 cursor-not-allowed"
    >
      <Clock className="h-4 w-4 animate-pulse" />
      <span className="tabular-nums">{mm}:{ss}</span>
      <span>{t("nextStep.analyzing")}</span>
    </button>
  );
}

export function NextStepBanner(props: Props) {
  const { t } = useTranslation("intake");
  // Phase 16 (D-03): the Start-research CTA opens a confirm dialog; the trigger fires ONLY
  // on the AlertDialogAction (confirm), never on the initial click.
  const [researchConfirmOpen, setResearchConfirmOpen] = useState(false);
  const {
    phase,
    validationLinkSentAt,
    resultsLinkSentAt,
    deliveredAt,
    activeRun,
    busy,
  } = props;

  const at = t("nextStep.at");
  const dateFallback = t("nextStep.dateFallback");

  const isArchived = phase === "archived";
  const isWaiting = phase === "awaiting_client_validation" || phase === "completed";
  const accentColor = isArchived ? "#9CA3AF" : isWaiting ? "#DFF940" : "#FF2D87";

  let title = t("nextStep.defaultTitle");
  let body: React.ReactNode = null;
  let actions: React.ReactNode = null;

  switch (phase) {
    case "awaiting_client_submission":
      body = t("nextStep.awaitingSubmissionBody");
      actions = (
        <>
          <PrimaryBtn onClick={props.onSendIntakeMail} busy={busy.sendIntake}>
            {t("nextStep.sendIntakeMail")}
          </PrimaryBtn>
          <SecondaryBtn onClick={props.onCopyIntakeLink}>
            {t("nextStep.copyIntakeLink")}
          </SecondaryBtn>
        </>
      );
      break;

    case "awaiting_skill_run":
      if (activeRun?.status === "running") {
        body = t("nextStep.analyzingBody");
        actions = <RunningClock startedAt={activeRun.created_at ?? activeRun.triggered_at} />;
      } else {
        body = t("nextStep.runSkillBody");
        actions = (
          <PrimaryBtn onClick={props.onRunSkill} busy={busy.runSkill}>
            {t("nextStep.runSkill")}
          </PrimaryBtn>
        );
      }
      break;

    case "awaiting_review":
      if (activeRun?.status === "running") {
        // A manual re-run is in flight — same running treatment as awaiting_skill_run.
        body = t("nextStep.analyzingBody");
        actions = <RunningClock startedAt={activeRun.created_at ?? activeRun.triggered_at} />;
      } else {
        body = t("nextStep.reviewBody");
        actions = (
          <>
            <PrimaryBtn onClick={props.onOpenAIReview}>
              {t("nextStep.openAIReview")}
            </PrimaryBtn>
            {/* Manual redo without a new intake: POST /skills/apply has no status gate —
                the new run becomes latest and its output replaces the review. */}
            <SecondaryBtn onClick={props.onRunSkill} busy={busy.runSkill}>
              {t("nextStep.rerunSkill")}
            </SecondaryBtn>
          </>
        );
      }
      break;

    case "awaiting_validation_send":
      body = t("nextStep.validationSendBody");
      actions = (
        <>
          <PrimaryBtn onClick={props.onSendValidationMail} busy={busy.sendValidation}>
            {t("nextStep.sendValidationMail")}
          </PrimaryBtn>
          <SecondaryBtn onClick={props.onCopyValidationLink}>
            {t("nextStep.copyValidationLink")}
          </SecondaryBtn>
        </>
      );
      break;

    case "awaiting_client_validation":
      title = t("nextStep.waitingClientTitle");
      body = (
        <Trans
          i18nKey="nextStep.waitingClientBody"
          ns="intake"
          values={{ date: fmtDate(validationLinkSentAt, at, dateFallback) }}
          components={[<strong />]}
        />
      );
      actions = (
        <SecondaryBtn onClick={props.onSendValidationReminder} busy={busy.sendReminder}>
          {t("nextStep.sendReminder")}
        </SecondaryBtn>
      );
      break;

    case "awaiting_context_pack":
      if (activeRun?.status === "running") {
        body = t("nextStep.contextPackRunningBody");
        actions = <RunningClock startedAt={activeRun.created_at ?? activeRun.triggered_at} />;
      } else {
        body = (
          <>
            {t("nextStep.contextPackBody")}
            <Tooltip text={t("nextStep.contextPackTooltip")} />
          </>
        );
        actions = (
          <PrimaryBtn onClick={props.onGenerateContextPack} busy={busy.generateContextPack}>
            {busy.generateContextPack
              ? t("nextStep.generatingContextPack")
              : t("nextStep.generateContextPack")}
          </PrimaryBtn>
        );
      }
      break;

    case "awaiting_research_start":
      body = (
        <>
          <div className="mb-3 font-semibold">{t("nextStep.researchStartTitle")}</div>
          <p className="max-w-[640px] text-[14px] font-normal leading-[1.5] text-ink/60">
            <Trans
              i18nKey="nextStep.researchStartBody"
              ns="intake"
              components={[<strong />]}
            />
          </p>
        </>
      );
      actions = (
        <PrimaryBtn onClick={() => setResearchConfirmOpen(true)} busy={busy.startResearch}>
          {busy.startResearch
            ? t("nextStep.researchRunning")
            : t("nextStep.startAutoResearch")}
        </PrimaryBtn>
      );
      break;

    case "in_research":
      title = t("nextStep.workPhaseTitle");
      body = t("nextStep.inResearchBody");
      break;

    case "awaiting_report_upload":
      body = t("nextStep.reportUploadBody");
      actions = (
        <PrimaryBtn onClick={props.onUploadFinalReport} busy={busy.uploadReport}>
          {t("nextStep.uploadReport")}
        </PrimaryBtn>
      );
      break;

    case "awaiting_results_send":
      body = t("nextStep.resultsSendBody");
      actions = (
        <>
          <PrimaryBtn onClick={props.onSendResultsMail} busy={busy.sendResults}>
            {t("nextStep.sendResultsMail")}
          </PrimaryBtn>
          <SecondaryBtn onClick={props.onCopyResultsLink}>
            {t("nextStep.copyResultsLink")}
          </SecondaryBtn>
        </>
      );
      break;

    case "completed":
      title = t("nextStep.completedTitle");
      body = (
        <Trans
          i18nKey="nextStep.completedBody"
          ns="intake"
          values={{ date: fmtDate(resultsLinkSentAt, at, dateFallback) }}
          components={[<strong />]}
        />
      );
      actions = (
        <SecondaryBtn onClick={props.onArchive} busy={busy.archive}>
          {t("nextStep.archiveProject")}
        </SecondaryBtn>
      );
      break;

    case "archived":
      title = t("nextStep.archivedTitle");
      body = t("nextStep.archivedBody", {
        suffix: deliveredAt
          ? t("nextStep.archivedOn", { date: fmtDate(deliveredAt, at, dateFallback) })
          : "",
      });
      break;

    default:
      return null;
  }

  return (
    <div
      className="border-t border-ink/10 border-l-4 bg-paperLight px-6 py-5"
      style={{ borderLeftColor: accentColor }}
    >
      <div
        className="mb-2 font-mono text-[11px] uppercase tracking-wider"
        style={{ color: accentColor }}
      >
        {title}
      </div>
      <div
        className={
          "mb-4 font-sans text-[15px] leading-relaxed " +
          (isArchived ? "text-ink/60" : "text-ink")
        }
      >
        {body}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}

      {/* Phase 16 (D-03): confirm gate for the deep-research trigger. The 202 fires ONLY
          when the operator clicks the confirm action — Cancel is a no-op. */}
      <AlertDialog open={researchConfirmOpen} onOpenChange={setResearchConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("nextStep.researchConfirmTitle")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("nextStep.researchConfirmBody")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("nextStep.researchConfirmCancel")}</AlertDialogCancel>
            <AlertDialogAction onClick={props.onStartAutoResearch}>
              {t("nextStep.researchConfirmConfirm")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
