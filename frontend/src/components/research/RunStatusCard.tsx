import type React from "react";
import { useTranslation } from "react-i18next";
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  HelpCircle,
  Loader2,
  MessageSquare,
  XCircle,
} from "lucide-react";
import { fmtDate } from "@/lib/research/runClock";
import type { ResearchRun } from "@/lib/api/research";

// frontend/src/components/research/RunStatusCard.tsx — the run page's one card, exhaustively
// mapped over every status a run can actually reach (D-11).
//
// WHY EIGHT AND NOT THREE. The operator's design of record models idle / running / done.
// Production has eight, and two of them carry traps that were learned the expensive way and
// are already encoded in the embedded card (`components/intake/ResearchRunProgress.tsx`):
//
//   * A DEGRADED run renders the SUCCESS card. It still cost around forty-five dollars and it
//     keeps everything a clean run keeps — its raw output, its verification report and its
//     frozen feed. Routing it anywhere near the failure card strips all three from a run the
//     operator has already paid for in full. Inside that branch the ONLY thing the degraded
//     test is allowed to change is the border colour, the icon, the title and the sentence.
//     Nothing else in it may be conditional, because a condition there is how the loss creeps
//     back in.
//   * A PAUSED run renders its OWN card. Sending it to the failure card would offer a fresh
//     attempt, and a fresh attempt throws away every checkpoint the engine has already paid
//     for. That branch therefore carries no output affordance and no chain control of any
//     kind: the engine reports no readable report for a paused run and the seam would refuse
//     the request anyway.
//
// THE FEED IS NOT PART OF THIS COMPONENT AND THIS COMPONENT NEVER HIDES IT. The page renders
// the card and the feed as SIBLINGS. That is deliberate and it is the whole fix: in the
// embedded card the failed and cancelled branches drop the activity history entirely, so the
// two states whose evidence matters most are the only two that discard it. Because the feed
// is not reachable from inside this file, no branch added here later can take it away.
//
// ACCESSIBILITY. This card is the status-and-phase live region for the page (T-15.3-82). The
// feed declares none — a region announcing every one of a thousand rows is worse than none —
// and the page header no longer declares one either, so a single status change is announced
// exactly once.
//
// SECURITY (T-15.3-90). Engine-authored failure text and pause reasons are rendered as React
// TEXT CHILDREN inside a pre-wrapped block. They are never parsed, never interpreted as
// markup, and the pause marker they carry is never stripped — it is the operator's evidence
// of whether the pause mail was already sent.

/** The eight statuses a research run can reach (D-11), verbatim from the Tribunal contract. */
export type RunStatusKey =
  | "queued"
  | "running"
  | "completed"
  | "completed_degraded"
  | "failed"
  | "cancelled"
  | "parked"
  | "needs_input";

/** Left-border accents, kept together so two branches cannot drift onto the same colour. */
const ACCENT = {
  queued: "#9CA3AF",
  running: "#FF2D87",
  success: "#DFF940",
  degraded: "#D97706",
  failed: "#DC2626",
  cancelled: "#9CA3AF",
  parked: "#D97706",
  needsInput: "#2563EB",
  unknown: "#9CA3AF",
} as const;

function Shell({
  accent,
  labelColor,
  icon,
  title,
  children,
}: {
  accent: string;
  labelColor: string;
  icon: React.ReactNode;
  title: string;
  children?: React.ReactNode;
}) {
  return (
    <div
      className="mb-5 border border-ink/30 border-l-4 bg-paperLight px-6 py-5"
      style={{ borderLeftColor: accent }}
      role="status"
      aria-live="polite"
    >
      <div className="mb-2 flex items-center gap-2">
        {icon}
        <span
          className="font-mono text-[11px] uppercase tracking-wider"
          style={{ color: labelColor }}
        >
          {title}
        </span>
      </div>
      {children}
    </div>
  );
}

function Body({ children }: { children: React.ReactNode }) {
  return <div className="mb-3 font-sans text-[15px] leading-relaxed text-ink">{children}</div>;
}

/**
 * A block of engine-authored text under its own label. `text` is a React text child, so React
 * escapes it; it is shown exactly as the engine wrote it, markers included.
 */
function EngineText({ label, text, tone }: { label: string; text: string; tone: string }) {
  return (
    <div className="mb-4">
      <div className="mb-1 font-mono text-[11px] uppercase tracking-wider text-ink/50">{label}</div>
      <div className={`whitespace-pre-wrap break-words font-mono text-[13px] ${tone}`}>{text}</div>
    </div>
  );
}

/**
 * The card above the feed on the dedicated run page.
 *
 * `run` is nullable because the page has a real cold-open window: an operator who clicks
 * through the moment a run is triggered lands here before the first stream frame arrives, and
 * that window must read as "accepted, not started" rather than as a blank page.
 *
 * `elapsed` is part of the declared contract and is deliberately NOT rendered here. The page
 * header owns the elapsed and cost figures — one number, one place — and the same rule is why
 * this card carries no cost line either. The card's job is to name the state, show the
 * evidence that belongs to that state, and hold the actions.
 *
 * `actions` is the slot the page fills with the affordances legal for this run.
 */
export function RunStatusCard({
  run,
  elapsed,
  actions,
}: {
  run: ResearchRun | null;
  elapsed: string;
  actions?: React.ReactNode;
}): React.JSX.Element {
  const { t } = useTranslation("intake");
  const status = run?.status ?? "queued";
  const engineText = run?.error_message ?? null;
  const slot = actions ? <div className="flex flex-wrap items-center gap-3">{actions}</div> : null;

  switch (status) {
    // The run is accepted and waiting for a worker to claim it. It has started nothing and
    // charged nothing, and saying so beats showing an active panel that claims otherwise.
    case "queued":
      return (
        <Shell
          accent={ACCENT.queued}
          labelColor="#6B7280"
          icon={<Clock className="h-5 w-5 text-ink/50" />}
          title={t("research.runPage.card.queuedTitle")}
        >
          <Body>{t("research.runPage.card.queuedBody")}</Body>
          {slot}
        </Shell>
      );

    case "running":
      return (
        <Shell
          accent={ACCENT.running}
          labelColor="#FF2D87"
          icon={<Loader2 className="h-5 w-5 animate-spin text-ink" />}
          title={t("research.panelTitle")}
        >
          <Body>{t("research.panelBody")}</Body>
          {slot}
        </Shell>
      );

    // ── The success branch, shared by both success statuses. ─────────────────────────────
    // Read the module note before adding anything conditional in here.
    case "completed":
    case "completed_degraded": {
      const isDegraded = status === "completed_degraded";
      return (
        <Shell
          accent={isDegraded ? ACCENT.degraded : ACCENT.success}
          labelColor="#7A8B00"
          icon={
            isDegraded ? (
              <AlertTriangle className="h-5 w-5 text-emerald-600" />
            ) : (
              <CheckCircle2 className="h-5 w-5 text-emerald-600" />
            )
          }
          title={isDegraded ? t("research.degradedTitle") : t("research.completedTitle")}
        >
          <Body>{isDegraded ? t("research.degradedBody") : t("research.completedBody")}</Body>
          <div className="mb-4 font-mono text-[12px] text-ink/70">
            {t("research.completedAt", {
              date: fmtDate(run?.completed_at ?? null, t("research.dateFallback")),
            })}
          </div>
          {slot}
        </Shell>
      );
    }

    case "failed":
      return (
        <Shell
          accent={ACCENT.failed}
          labelColor="#DC2626"
          icon={<XCircle className="h-5 w-5 text-red-600" />}
          title={t("research.failedTitle")}
        >
          <Body>{t("research.failedBody")}</Body>
          {engineText && (
            <EngineText
              label={t("research.errorLabel")}
              text={engineText}
              tone="text-red-700"
            />
          )}
          {slot}
        </Shell>
      );

    // Its own card, distinct from the failure card. The operator stopped this run on purpose,
    // and calling a deliberate stop a failure is a lie the operator will not trust twice.
    case "cancelled":
      return (
        <Shell
          accent={ACCENT.cancelled}
          labelColor="#6B7280"
          icon={<AlertTriangle className="h-5 w-5 text-ink/50" />}
          title={t("research.cancelledTitle")}
        >
          <Body>{t("research.cancelledBody")}</Body>
          {engineText && (
            <EngineText label={t("research.errorLabel")} text={engineText} tone="text-ink/70" />
          )}
          {slot}
        </Shell>
      );

    case "parked":
      return (
        <Shell
          accent={ACCENT.parked}
          labelColor="#B45309"
          icon={<AlertTriangle className="h-5 w-5 text-amber-600" />}
          title={t("research.parkedTitle")}
        >
          <Body>{t("research.parkedBody")}</Body>
          {engineText && (
            <EngineText
              label={t("research.parkedReasonLabel")}
              text={engineText}
              tone="text-amber-700"
            />
          )}
          {slot}
        </Shell>
      );

    // The engine's clarification pause. It is NOT the same thing as the branch above and must
    // never be folded into it: the two look alike and mean opposite things about what the next
    // click costs. This side has no answer surface by design, so the card says so in words and
    // its slot carries a fresh attempt rather than a continuation.
    case "needs_input":
      return (
        <Shell
          accent={ACCENT.needsInput}
          labelColor="#1D4ED8"
          icon={<MessageSquare className="h-5 w-5 text-blue-600" />}
          title={t("research.runPage.card.needsInputTitle")}
        >
          <Body>{t("research.runPage.card.needsInputBody")}</Body>
          {engineText && (
            <EngineText
              label={t("research.runPage.card.needsInputReasonLabel")}
              text={engineText}
              tone="text-ink/70"
            />
          )}
          {slot}
        </Shell>
      );

    // A status this build has never heard of. A rolling deploy makes that the normal state of
    // the world, not an edge case, so it degrades to "we have no copy for this yet" and names
    // the raw value — never to a blank page.
    default:
      return (
        <Shell
          accent={ACCENT.unknown}
          labelColor="#6B7280"
          icon={<HelpCircle className="h-5 w-5 text-ink/50" />}
          title={t("research.runPage.card.unknownTitle")}
        >
          <Body>{t("research.runPage.card.unknownBody", { status })}</Body>
          {slot}
        </Shell>
      );
  }
}
