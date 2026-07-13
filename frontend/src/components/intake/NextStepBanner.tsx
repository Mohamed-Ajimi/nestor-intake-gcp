import { useEffect, useState } from "react";
import { Clock, Loader2 } from "lucide-react";
import { format } from "date-fns";
import { nl } from "date-fns/locale";
import type { Phase } from "@/lib/intake-phase";
import type { ActiveSkillRun } from "./SkillRunProgress";

type Props = {
  phase: Phase;
  validationLinkSentAt: string | null;
  resultsLinkSentAt: string | null;
  deliveredAt: string | null;
  activeRun?: ActiveSkillRun | null;
  busy: Partial<Record<BusyKey, boolean>>;
  onRunSkill: () => void;
  onCopyIntakeLink: () => void;
  onOpenAIReview: () => void;
  onSendValidationMail: () => void;
  onCopyValidationLink: () => void;
  onSendValidationReminder: () => void;
  onGenerateContextPack: () => void;
  onStartAutoResearch: () => void;
  onStartManualResearch: () => void;
  onDownloadContextPack: () => void;
  onUploadFinalReport: () => void;
  onSendResultsMail: () => void;
  onCopyResultsLink: () => void;
  onArchive: () => void;
};

export type BusyKey =
  | "runSkill"
  | "sendValidation"
  | "sendReminder"
  | "generateContextPack"
  | "startResearch"
  | "uploadReport"
  | "sendResults"
  | "archive";

function fmtDate(d: string | null): string {
  if (!d) return "—";
  try {
    return format(new Date(d), "d MMM yyyy 'om' HH:mm", { locale: nl });
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

function RunningClock({ triggeredAt }: { triggeredAt: string }) {
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
    <button
      type="button"
      disabled
      aria-live="polite"
      className="inline-flex items-center gap-2 border border-ink/40 bg-paper px-4 py-2 font-mono text-xs uppercase tracking-wider text-ink/70 cursor-not-allowed"
    >
      <Clock className="h-4 w-4 animate-pulse" />
      <span className="tabular-nums">{mm}:{ss}</span>
      <span>— Nestor analyseert…</span>
    </button>
  );
}

export function NextStepBanner(props: Props) {
  const {
    phase,
    validationLinkSentAt,
    resultsLinkSentAt,
    deliveredAt,
    activeRun,
    busy,
  } = props;

  const isArchived = phase === "archived";
  const isWaiting = phase === "awaiting_client_validation" || phase === "completed";
  const accentColor = isArchived ? "#9CA3AF" : isWaiting ? "#DFF940" : "#FF2D87";

  let title = "Volgende stap";
  let body: React.ReactNode = null;
  let actions: React.ReactNode = null;

  switch (phase) {
    case "awaiting_client_submission":
      body = "Klant moet de intake invullen. Stuur de intake-link.";
      actions = (
        <SecondaryBtn onClick={props.onCopyIntakeLink}>Kopieer intake-link</SecondaryBtn>
      );
      break;

    case "awaiting_skill_run":
      if (activeRun?.status === "running") {
        body =
          "Nestor analyseert je intake. Dit duurt gemiddeld 90–120 seconden. Je mag deze tab open laten.";
        actions = <RunningClock triggeredAt={activeRun.triggered_at} />;
      } else {
        body =
          "De klant heeft de intake ingediend. Run de intake-skill om Nestor's analyse en suggesties te krijgen.";
        actions = (
          <PrimaryBtn onClick={props.onRunSkill} busy={busy.runSkill}>
            Run intake-skill
          </PrimaryBtn>
        );
      }
      break;

    case "awaiting_review":
      body =
        "Nestor's analyse is klaar. Review hieronder en stuur ter validatie naar de klant.";
      actions = (
        <PrimaryBtn onClick={props.onOpenAIReview}>
          Open AI review hieronder
        </PrimaryBtn>
      );
      break;

    case "awaiting_validation_send":
      body =
        "Suggesties toegepast. Stuur de validatie-link naar de klant via mail.";
      actions = (
        <>
          <PrimaryBtn onClick={props.onSendValidationMail} busy={busy.sendValidation}>
            Verstuur validatie-link via mail
          </PrimaryBtn>
          <SecondaryBtn onClick={props.onCopyValidationLink}>
            Kopieer validatie-link
          </SecondaryBtn>
        </>
      );
      break;

    case "awaiting_client_validation":
      title = "Wachten op klant";
      body = (
        <>
          Validatie-link verstuurd op <strong>{fmtDate(validationLinkSentAt)}</strong>.
          Wachten op klant-bevestiging.
        </>
      );
      actions = (
        <SecondaryBtn onClick={props.onSendValidationReminder} busy={busy.sendReminder}>
          Stuur herinnering
        </SecondaryBtn>
      );
      break;

    case "awaiting_context_pack":
      if (activeRun?.status === "running") {
        body =
          "Context Pack wordt gegenereerd — Nestor bundelt de gevalideerde intake tot de briefing. Dit duurt ± 60–120 seconden. Je mag deze tab open laten.";
        actions = <RunningClock triggeredAt={activeRun.triggered_at} />;
      } else {
        body = (
          <>
            Klant heeft gevalideerd. Genereer de Context Pack — de briefing-PDF voor Nestor's
            onderzoeker.
            <Tooltip text="Bundelt de gevalideerde intake, gevoeligheden, blinde vlekken en onderzoeksvragen in één PDF die de research-fase voedt." />
          </>
        );
        actions = (
          <PrimaryBtn onClick={props.onGenerateContextPack} busy={busy.generateContextPack}>
            {busy.generateContextPack ? "Bezig met genereren… (60–120s)" : "Genereer Context Pack"}
          </PrimaryBtn>
        );
      }
      break;

    case "awaiting_research_start":
      body = (
        <>
          <div className="mb-3 font-semibold">
            Context Pack klaar. Start de research voor deze intake.
          </div>
          <p className="max-w-[640px] text-[14px] font-normal leading-[1.5] text-ink/60">
            Dit lanceert <strong>SerpAPI + SearchAPI + Apify</strong> (rag-web-browser
            + website-content-crawler) voor élke onderzoeksvraag. Levert 2–5 artifacts
            per vraag, klaar binnen 2–5 minuten. Daarna kan je per vraag manueel extra
            artifacts toevoegen.
          </p>
        </>
      );
      actions = (
        <PrimaryBtn onClick={props.onStartAutoResearch} busy={busy.startResearch}>
          {busy.startResearch ? "Research loopt…" : "Start automatische research"}
        </PrimaryBtn>
      );
      break;

    case "in_research":
      title = "Werkfase";
      body =
        "Research loopt. Upload artifacts per onderzoeksvraag of laat run-research lopen.";
      break;

    case "awaiting_report_upload":
      body =
        "Research klaar. Upload het volledige klant-rapport (DOCX of PDF).";
      actions = (
        <PrimaryBtn onClick={props.onUploadFinalReport} busy={busy.uploadReport}>
          Upload rapport
        </PrimaryBtn>
      );
      break;

    case "awaiting_results_send":
      body = "Rapport geladen. Stuur de resultaten-link naar de klant.";
      actions = (
        <>
          <PrimaryBtn onClick={props.onSendResultsMail} busy={busy.sendResults}>
            Verstuur resultaten-link via mail
          </PrimaryBtn>
          <SecondaryBtn onClick={props.onCopyResultsLink}>
            Kopieer resultaten-link
          </SecondaryBtn>
        </>
      );
      break;

    case "completed":
      title = "Voltooid";
      body = (
        <>
          Resultaten-link verstuurd op <strong>{fmtDate(resultsLinkSentAt)}</strong>.
          Klant kan downloaden via de portal.
        </>
      );
      actions = (
        <SecondaryBtn onClick={props.onArchive} busy={busy.archive}>
          Archiveer project
        </SecondaryBtn>
      );
      break;

    case "archived":
      title = "Gearchiveerd";
      body = (
        <>Project gearchiveerd{deliveredAt ? ` op ${fmtDate(deliveredAt)}` : ""}.</>
      );
      break;

    default:
      return null;
  }

  return (
    <div
      className="mb-5 border border-ink/30 border-l-4 bg-paperLight px-6 py-5"
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
    </div>
  );
}
