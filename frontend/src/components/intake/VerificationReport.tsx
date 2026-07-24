import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  getVerification,
  type VerificationReport as VerificationReportData,
  type VerificationVerdictItem,
} from "@/lib/api/research";

// frontend/src/components/intake/VerificationReport.tsx — the superadmin-only verification
// report surface (Plan 15-05 / ENGINE-09). It fetches the recorded run's verification report
// through the Plan 15-04 superadmin proxy and renders the gate funnel, verdict sections
// (refuted with skeptic evidence + effect / support / insufficient), superseded/scoped
// findings with their temporal caveat, reconciled contradictions with the chosen canonical
// value, the HONEST unverified list, and true itemized cost — with a "pending" state that
// renders a LABEL, never a number, when tool fees are not yet reconciled (C1 facts-only).
//
// SECURITY (T-15-12 / T-15-13): superadmin-only BY PLACEMENT — no client route imports this
// (enforced by the 16-D-08 route-import grep guard). Cost is facts-only: when cost.pending is
// true, no numeric placeholder is shown for the pending class.
//
// RETURN-NO-THROW (CLAUDE.md): the fetch surfaces failure via a sonner toast + inline error.

/** Render a possibly-markdown string field read-only (mirrors the admin-panel markdown use). */
function MdText({ value }: { value: string | null | undefined }) {
  if (!value) return null;
  return (
    <div className="prose prose-sm max-w-none font-sans text-[13px] leading-relaxed text-ink/80">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{value}</ReactMarkdown>
    </div>
  );
}

/** A verdict/contradiction row: claim + optional evidence + optional effect/canonical. */
function VerdictItemRow({
  item,
  showEffect,
}: {
  item: VerificationVerdictItem;
  showEffect?: boolean;
}) {
  const { t } = useTranslation("intake");
  const claim = typeof item.claim === "string" ? item.claim : "";
  const evidence = typeof item.evidence === "string" ? item.evidence : "";
  const effect = typeof item.effect === "string" ? item.effect : "";
  return (
    <li className="border-l-2 border-ink/15 pl-3">
      {claim && <MdText value={claim} />}
      {evidence && (
        <div className="mt-1">
          <span className="font-mono text-[10px] uppercase tracking-wider text-ink/45">
            {t("verification.evidenceLabel")}
          </span>
          <MdText value={evidence} />
        </div>
      )}
      {showEffect && effect && (
        <div className="mt-1">
          <span className="font-mono text-[10px] uppercase tracking-wider text-ink/45">
            {t("verification.effectLabel")}
          </span>
          <MdText value={effect} />
        </div>
      )}
    </li>
  );
}

/** A titled section that only renders when it has rows. */
function VerdictSection({
  title,
  items,
  showEffect,
}: {
  title: string;
  items?: VerificationVerdictItem[];
  showEffect?: boolean;
}) {
  if (!items || items.length === 0) return null;
  return (
    <div className="mb-4">
      <div className="mb-2 font-mono text-[11px] uppercase tracking-wider text-ink/50">
        {title}
      </div>
      <ul className="space-y-2">
        {items.map((item, idx) => (
          <VerdictItemRow key={idx} item={item} showEffect={showEffect} />
        ))}
      </ul>
    </div>
  );
}

/**
 * The superadmin verification report. Fetches `getVerification(intakeId, runId)` on mount and
 * renders every required section from the recorded run. Mounted behind the D-09 summary card's
 * "View verification report" action on the admin intake detail route (superadmin-only by
 * placement). `onClose` collapses it back.
 */
export function VerificationReport({
  intakeId,
  runId,
  onClose,
}: {
  intakeId: string;
  runId: string;
  onClose?: () => void;
}) {
  const { t } = useTranslation("intake");
  const [report, setReport] = useState<VerificationReportData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    void getVerification(intakeId, runId).then((res) => {
      if (cancelled) return;
      setLoading(false);
      if (res.success && res.data) {
        setReport(res.data);
      } else {
        setError(t("verification.loadError"));
        toast.error(t("verification.loadError"));
      }
    });
    return () => {
      cancelled = true;
    };
  }, [intakeId, runId, t]);

  return (
    <div
      className="mb-5 border border-ink/30 border-l-4 bg-paperLight px-6 py-5"
      style={{ borderLeftColor: "#FF2D87" }}
      role="region"
      aria-label={t("verification.regionLabel")}
    >
      <div className="mb-3 flex items-center justify-between gap-2">
        <span className="font-mono text-[11px] uppercase tracking-wider text-ink/70">
          {t("verification.title")}
        </span>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            className="font-mono text-[11px] uppercase tracking-wider text-ink/50 hover:text-ink"
          >
            {t("verification.close")}
          </button>
        )}
      </div>

      {loading && (
        <div className="flex items-center gap-2 font-mono text-[12px] text-ink/60">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t("verification.loading")}
        </div>
      )}

      {!loading && error && <p className="font-sans text-[13px] text-red-600">{error}</p>}

      {!loading && !error && report && (
        <div>
          {/* ── Gate funnel ─────────────────────────────────────────────────────── */}
          <div className="mb-5">
            <div className="mb-2 font-mono text-[11px] uppercase tracking-wider text-ink/50">
              {t("verification.funnelTitle")}
            </div>
            <div className="flex flex-wrap gap-x-6 gap-y-1 font-mono text-[12px] text-ink/70">
              {Object.entries(report.funnel ?? {}).map(([stage, count]) => (
                <span key={stage}>
                  {t("verification.funnelStage", { stage, count })}
                </span>
              ))}
            </div>
          </div>

          {/* ── Verdicts ────────────────────────────────────────────────────────── */}
          <VerdictSection
            title={t("verification.refutedTitle")}
            items={report.verdicts?.refute}
            showEffect
          />
          <VerdictSection
            title={t("verification.supportTitle")}
            items={report.verdicts?.support}
          />
          <VerdictSection
            title={t("verification.insufficientTitle")}
            items={report.verdicts?.insufficient}
          />

          {/* ── Superseded / scoped findings (temporal caveat inline) ───────────── */}
          <VerdictSection
            title={t("verification.supersededTitle")}
            items={report.superseded}
          />

          {/* ── Reconciled contradictions (chosen canonical value) ─────────────── */}
          <VerdictSection
            title={t("verification.reconciledTitle")}
            items={report.reconciled}
          />

          {/* ── Honest unverified list ──────────────────────────────────────────── */}
          <div className="mb-5">
            <div className="mb-2 font-mono text-[11px] uppercase tracking-wider text-ink/50">
              {t("verification.unverifiedTitle", { count: report.unverified?.count ?? 0 })}
            </div>
            {report.unverified?.items && report.unverified.items.length > 0 ? (
              <ul className="space-y-2">
                {report.unverified.items.map((item, idx) => (
                  <VerdictItemRow key={idx} item={item} />
                ))}
              </ul>
            ) : (
              <p className="font-sans text-[13px] text-ink/60">
                {t("verification.unverifiedNone")}
              </p>
            )}
          </div>

          {/* ── True itemized cost (facts-only; pending → LABEL, never a number) ── */}
          <div className="border-t border-ink/10 pt-3">
            <div className="mb-1 font-mono text-[11px] uppercase tracking-wider text-ink/50">
              {t("verification.costTitle")}
            </div>
            {report.cost?.pending ? (
              <div className="font-mono text-[13px] text-ink/70">
                {t("verification.costTotalWithPending", { total: report.cost?.total ?? "—" })}
                <span className="ml-2 bg-amber-50 px-2 py-0.5 text-[11px] text-amber-700">
                  {t("verification.costPending")}
                </span>
              </div>
            ) : (
              <div className="font-mono text-[13px] text-ink/70">
                {t("verification.costTotal", { total: report.cost?.total ?? "—" })}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
