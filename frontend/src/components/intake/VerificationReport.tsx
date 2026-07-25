import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  getVerification,
  type Citation,
  type VerificationReport as VerificationReportData,
  type VerificationVerdictItem,
} from "@/lib/api/research";
import { CitationPanel, renderCitationMarker } from "@/components/intake/CitationPanel";

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

/**
 * Render one backend `evidence_refs` entry as display text. The refs are opaque JSON
 * (skeptic-emitted): usually strings, sometimes objects carrying a quote/text/url field.
 * Never throws — an unrecognised shape degrades to its JSON string.
 */
function refToText(ref: unknown): string {
  if (typeof ref === "string") return ref;
  if (ref && typeof ref === "object") {
    const r = ref as Record<string, unknown>;
    for (const key of ["quote", "text", "evidence", "claim", "title", "url", "source"]) {
      const v = r[key];
      if (typeof v === "string" && v) return v;
    }
    try {
      return JSON.stringify(ref);
    } catch {
      return "";
    }
  }
  return ref == null ? "" : String(ref);
}

/**
 * A verdict/contradiction row rendering the REAL backend `_verdict_dto` fields
 * (claim_id / verdict / confidence / evidence_refs / reconciliation) — never the
 * pre-CR-01 imaginary `claim`/`evidence`/`effect` keys the backend does not emit.
 * The evidence block lists `evidence_refs`; the effect/canonical block renders
 * `reconciliation.canonical`, with `reconciliation.note` as an inline caveat.
 *
 * CAVEAT FALLBACK (G-07 / 15.1): the amber caveat renders `reconciliation.note` OR, when
 * there is none, `superseded_note`. A `superseded` verdict on a SINGLE-member group is the
 * ordinary shape — `relation` defaults to "single" and `canonical` to "", so the group emits
 * no reconciliation note at all. Without this fallback the skeptic's G-07 caveat ("was true,
 * changed on <date>") would reach the browser on every such row and be displayed nowhere.
 */
function VerdictItemRow({
  item,
  showEffect,
  citations,
  onOpenCitation,
}: {
  item: VerificationVerdictItem;
  showEffect?: boolean;
  /** The [n] citations introduced by this row's claim (SC4 — markers inline). */
  citations?: Citation[];
  onOpenCitation?: (c: Citation) => void;
}) {
  const { t } = useTranslation("intake");
  const verdict = typeof item.verdict === "string" ? item.verdict : "";
  const confidence = typeof item.confidence === "string" ? item.confidence : "";
  const refs = Array.isArray(item.evidence_refs) ? item.evidence_refs : [];
  const recon =
    item.reconciliation && typeof item.reconciliation === "object" ? item.reconciliation : null;
  const canonical = typeof recon?.canonical === "string" ? recon.canonical : "";
  const reconNote = typeof recon?.note === "string" ? recon.note : "";
  const supersededNote = typeof item.superseded_note === "string" ? item.superseded_note : "";
  // Reconciliation note first (it describes the whole group); otherwise the row's own G-07
  // superseded caveat, which is all a single-member superseded group ever carries.
  const note = reconNote || supersededNote;
  return (
    <li className="border-l-2 border-ink/15 pl-3">
      <div className="flex flex-wrap items-center gap-2 font-mono text-[11px] text-ink/60">
        {verdict && <span className="uppercase tracking-wider">{verdict}</span>}
        {confidence && (
          <span className="bg-paper px-2 py-0.5">
            {t("verification.confidenceLabel")}: {confidence}
          </span>
        )}
        {onOpenCitation &&
          citations &&
          citations.length > 0 &&
          citations.map((c) => renderCitationMarker(c, onOpenCitation))}
      </div>
      {refs.length > 0 && (
        <div className="mt-1">
          <span className="font-mono text-[10px] uppercase tracking-wider text-ink/45">
            {t("verification.evidenceLabel")}
          </span>
          <ul className="space-y-1">
            {refs.map((ref, idx) => {
              const text = refToText(ref);
              return text ? (
                <li key={idx}>
                  <MdText value={text} />
                </li>
              ) : null;
            })}
          </ul>
        </div>
      )}
      {showEffect && canonical && (
        <div className="mt-1">
          <span className="font-mono text-[10px] uppercase tracking-wider text-ink/45">
            {t("verification.effectLabel")}
          </span>
          <MdText value={canonical} />
        </div>
      )}
      {note && (
        <p className="mt-1 bg-amber-50 px-2 py-1 font-sans text-[12px] text-amber-800">{note}</p>
      )}
    </li>
  );
}

/** A titled section that only renders when it has rows. */
function VerdictSection({
  title,
  items,
  showEffect,
  citationsByClaim,
  onOpenCitation,
}: {
  title: string;
  items?: VerificationVerdictItem[];
  showEffect?: boolean;
  citationsByClaim?: Map<string, Citation[]>;
  onOpenCitation?: (c: Citation) => void;
}) {
  if (!items || items.length === 0) return null;
  return (
    <div className="mb-4">
      <div className="mb-2 font-mono text-[11px] uppercase tracking-wider text-ink/50">
        {title}
      </div>
      <ul className="space-y-2">
        {items.map((item, idx) => (
          <VerdictItemRow
            key={idx}
            item={item}
            showEffect={showEffect}
            citations={
              typeof item.claim_id === "string"
                ? citationsByClaim?.get(item.claim_id)
                : undefined
            }
            onOpenCitation={onOpenCitation}
          />
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
  // SC4: the clicked [n] citation whose CitationPanel is open (null = closed).
  const [openCitation, setOpenCitation] = useState<Citation | null>(null);

  // SC4 / D13: markers are rendered from EXACTLY the backend citations list, so
  // every [n] resolves. Group by the claim that introduced the source so verdict
  // rows carry their own markers inline (claim-linked runs; the recorded run's
  // rows predate claim linkage and surface via the numbered list below instead).
  const citations = report?.citations ?? [];
  const citationsByClaim = new Map<string, Citation[]>();
  for (const c of citations) {
    const cid = typeof c.first_claim_id === "string" && c.first_claim_id ? c.first_claim_id : null;
    if (!cid) continue;
    const list = citationsByClaim.get(cid);
    if (list) {
      list.push(c);
    } else {
      citationsByClaim.set(cid, [c]);
    }
  }
  const openCitationPanel = (c: Citation) => setOpenCitation(c);

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
            citationsByClaim={citationsByClaim}
            onOpenCitation={openCitationPanel}
          />
          <VerdictSection
            title={t("verification.supportTitle")}
            items={report.verdicts?.support}
            citationsByClaim={citationsByClaim}
            onOpenCitation={openCitationPanel}
          />
          <VerdictSection
            title={t("verification.insufficientTitle")}
            items={report.verdicts?.insufficient}
            citationsByClaim={citationsByClaim}
            onOpenCitation={openCitationPanel}
          />

          {/* ── Superseded VERDICTS (G-06 verdict class: "was true, has since changed") ──
                 ⚠ DISTINCT from the superseded/scoped section directly below: this one lists
                 rows the skeptic CLASSED as superseded (report.verdicts.superseded), while
                 that one lists reconciliation-derived scoped findings carrying a canonical
                 value (report.superseded). Same word, different question — the backend
                 documents the deliberate collision in verification/report.py. Do NOT merge
                 them, and do NOT give them one shared heading. */}
          <VerdictSection
            title={t("verification.supersededVerdictsTitle")}
            items={report.verdicts?.superseded}
            showEffect
            citationsByClaim={citationsByClaim}
            onOpenCitation={openCitationPanel}
          />

          {/* ── Superseded / scoped findings (canonical value + caveat inline) ──── */}
          <VerdictSection
            title={t("verification.supersededTitle")}
            items={report.superseded}
            showEffect
            citationsByClaim={citationsByClaim}
            onOpenCitation={openCitationPanel}
          />

          {/* ── Reconciled contradictions (chosen canonical value) ─────────────── */}
          <VerdictSection
            title={t("verification.reconciledTitle")}
            items={report.reconciled}
            showEffect
            citationsByClaim={citationsByClaim}
            onOpenCitation={openCitationPanel}
          />

          {/* ── Honest unverified accounting (count-only — the backend emits no
                 per-claim items: {count, claims_with_verdict, total_claims}) ──────── */}
          <div className="mb-5">
            <div className="mb-2 font-mono text-[11px] uppercase tracking-wider text-ink/50">
              {t("verification.unverifiedTitle", { count: report.unverified?.count ?? 0 })}
            </div>
            {(report.unverified?.count ?? 0) > 0 ? (
              <p className="font-sans text-[13px] text-ink/60">
                {t("verification.unverifiedSummary", {
                  withVerdict: report.unverified?.claims_with_verdict ?? 0,
                  total: report.unverified?.total_claims ?? 0,
                })}
              </p>
            ) : (
              <p className="font-sans text-[13px] text-ink/60">
                {t("verification.unverifiedNone")}
              </p>
            )}
          </div>

          {/* ── Numbered citations (SC4 / D13 — every [n] clickable + resolving) ── */}
          {citations.length > 0 && (
            <div className="mb-5">
              <div className="mb-2 font-mono text-[11px] uppercase tracking-wider text-ink/50">
                {t("verification.citationsTitle")}
              </div>
              <ul className="space-y-1">
                {citations.map((c) => (
                  <li
                    key={c.n}
                    className="flex items-baseline gap-1 font-sans text-[13px] text-ink/80"
                  >
                    {renderCitationMarker(c, openCitationPanel)}
                    <span>{c.title ?? t("citation.untitled")}</span>
                  </li>
                ))}
              </ul>
              {openCitation && (
                <CitationPanel
                  intakeId={intakeId}
                  citation={openCitation}
                  onClose={() => setOpenCitation(null)}
                />
              )}
            </div>
          )}

          {/* ── True itemized cost (facts-only; pending → LABEL, never a number) ── */}
          <div className="border-t border-ink/10 pt-3">
            <div className="mb-1 font-mono text-[11px] uppercase tracking-wider text-ink/50">
              {t("verification.costTitle")}
            </div>
            {report.true_cost?.cost_pending ? (
              <div className="font-mono text-[13px] text-ink/70">
                {t("verification.costTotalWithPending", {
                  total: report.true_cost?.cost_usd_total ?? "—",
                })}
                <span className="ml-2 bg-amber-50 px-2 py-0.5 text-[11px] text-amber-700">
                  {t("verification.costPending")}
                </span>
              </div>
            ) : (
              <div className="font-mono text-[13px] text-ink/70">
                {t("verification.costTotal", {
                  total: report.true_cost?.cost_usd_total ?? "—",
                })}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
