import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
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
//
// ── D-22-2: WHAT THIS COMPONENT IS, AND WHAT IT IS NOT ALLOWED TO BECOME ─────────────────
// The operator's verdict on this report was "very good information, so style it better, like a
// dashboard". The CONTENT is endorsed; only its PRESENTATION was at fault. So the restyle is an
// INSTRUMENTED DOCUMENT (22-UI-SPEC "Visual Direction — RESOLVED", direction A): the trust
// question lifted above the fold as a stat strip, the funnel made legible as proportion, and
// then the same document underneath as anchored, headed blocks.
//
// ⛔ NOT ONE SECTION IS DROPPED, TRUNCATED, REORDERED, MERGED OR SUMMARISED. The sections below
// are in the exact order they have always rendered, and `VerdictItemRow` — the actual row
// rendering, the evidence list, the effect block and the amber caveat — is untouched. A restyle
// that hides a section is solving the wrong problem and reverses the ruling. The tile/card grid
// (direction B) was shown to the operator and REJECTED, because multi-column cards are hostile
// to the long markdown evidence blocks `MdText` renders; proposing one here reverses a ruling.
//
// ⛔ NO DERIVED FIGURES. No percentage, no ratio, no "N% verified", no trend, no comparison to a
// previous run, and no duplicates-removed or corroboration figure. `total_claims` can be 0, so a
// rate is one division-by-zero away from printing `NaN%` as though it were a measurement — and
// this project's bar is "facts and correct calculations only".
//
// ── PAGE CHROME LIVES ON THE PAGE, NOT HERE (D-22-1) ─────────────────────────────────────
// `routes/admin.pulse.runs.$runId.verification.tsx` owns the header, the pink accent identity
// rule, the breadcrumb and the back link, and it is this component's ONE mount in the app. This
// component therefore renders no container border, no title and no close affordance — it used to
// render all three plus a close-callback prop, and every one of them was a second copy of
// something the page already says. It also declares NO announcing region: the run page owns the
// product's single one (T-15.3-82) and a second would double-announce.

/** 22-UI-SPEC Typography: section heading — 13px/600 mono uppercase. The ONE typographic change
 *  that makes this document scannable. It used to be 11px/400, the same weight as the metadata
 *  inside it, which is a large part of why the report read as an undifferentiated wall. */
const SECTION_HEADING_CLASS =
  "flex items-baseline gap-2 font-mono text-[13px] font-semibold uppercase tracking-[0.1em] text-ink";

/** 22-UI-SPEC Color: the one neutral, for a figure that is zero or absent. */
const FIGURE_NEUTRAL = "#6B7280";

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

/**
 * One document section: the block, its heading and its anchor (22-UI-SPEC §1.9).
 *
 * `id` is the anchor plan 22-08's nav rail links to, and `scroll-mt-6` keeps the heading clear
 * of the sticky header when it does. The heading is a real `<h2>` carrying its own id, which
 * the section then uses to name itself via `aria-labelledby` — so a screen-reader user reaches
 * every section by heading AND by landmark. On a document this long that is most of what makes
 * it usable, and it costs nothing.
 *
 * `leftRuleColor` is the section's semantic rule. Exactly one section in this document has one.
 */
function ReportSection({
  id,
  title,
  count,
  leftRuleColor,
  children,
}: {
  id: string;
  title: string;
  count?: number;
  leftRuleColor?: string;
  children: ReactNode;
}) {
  return (
    <section
      id={id}
      aria-labelledby={`${id}-heading`}
      className={cn("mb-8 scroll-mt-6 bg-paperLight px-6 py-5", leftRuleColor && "border-l-4")}
      style={leftRuleColor ? { borderLeftColor: leftRuleColor } : undefined}
    >
      <h2 id={`${id}-heading`} className={SECTION_HEADING_CLASS}>
        <span>{title}</span>
        {typeof count === "number" && (
          <span className="font-normal tabular-nums text-ink/50">{count}</span>
        )}
      </h2>
      {children}
    </section>
  );
}

/** A titled section that only renders when it has rows. */
function VerdictSection({
  id,
  title,
  items,
  leftRuleColor,
  showEffect,
  citationsByClaim,
  onOpenCitation,
}: {
  id: string;
  title: string;
  items?: VerificationVerdictItem[];
  leftRuleColor?: string;
  showEffect?: boolean;
  citationsByClaim?: Map<string, Citation[]>;
  onOpenCitation?: (c: Citation) => void;
}) {
  // Unchanged behaviour: an empty list renders nothing. Omitting an empty section is not
  // hiding information, and it is what this component has always done.
  if (!items || items.length === 0) return null;
  return (
    <ReportSection id={id} title={title} count={items.length} leftRuleColor={leftRuleColor}>
      <ul className="mt-3 space-y-2">
        {items.map((item, idx) => (
          <VerdictItemRow
            key={idx}
            item={item}
            showEffect={showEffect}
            citations={
              typeof item.claim_id === "string" ? citationsByClaim?.get(item.claim_id) : undefined
            }
            onOpenCitation={onOpenCitation}
          />
        ))}
      </ul>
    </ReportSection>
  );
}

/**
 * A stat figure and the colour it takes.
 *
 * A measured number renders as itself in ink. A zero renders as `0` in the neutral grey — it is
 * a MEASURED FACT, and swapping it for a dash would hide one. Only a genuinely ABSENT field
 * gets the em dash. No thousands separator: `toLocaleString()` reads the runtime locale, which
 * differs between the server render and the browser's, and a hydration mismatch is not worth a
 * comma.
 */
function statFigure(n: number | null | undefined): { value: string; color?: string } {
  if (typeof n !== "number" || !Number.isFinite(n)) return { value: "—", color: FIGURE_NEUTRAL };
  if (n === 0) return { value: "0", color: FIGURE_NEUTRAL };
  return { value: String(n) };
}

/**
 * One stat tile (22-UI-SPEC §1.6): an 11px mono label over a 24px mono tabular figure. No
 * border — the paper/paperLight contrast is the division between tiles.
 *
 * FACTS ONLY. A tile shows a number the report measured, an em dash when the field is absent,
 * or a LABEL for a class that is not yet itemized — never a derived rate, and never a numeric
 * placeholder standing in for something unknown. `color` is used by exactly one tile, whose
 * label also carries the meaning, so colour is never the sole carrier of anything.
 */
function StatTile({
  label,
  value,
  color,
  chip,
}: {
  label: string;
  value: string;
  color?: string;
  chip?: string;
}) {
  return (
    <div className="bg-paperLight px-6 py-5">
      <div className="font-mono text-[11px] uppercase tracking-wider text-ink/50">{label}</div>
      <div
        className="mt-2 font-mono text-[24px] leading-none tabular-nums text-ink"
        style={{ color }}
      >
        {value}
      </div>
      {chip && (
        <span className="mt-2 inline-block bg-amber-50 px-2 py-0.5 font-mono text-[11px] text-amber-700">
          {chip}
        </span>
      )}
    </div>
  );
}

/**
 * The superadmin verification report, rendered as an instrumented document: a stat strip, a
 * proportional gate funnel, then every section this report has always had, in the order it has
 * always had them, as anchored and headed blocks. Fetches `getVerification(intakeId, runId)` on
 * mount. Its single mount is `routes/admin.pulse.runs.$runId.verification.tsx`, which owns the
 * page's header, identity rule and back link (superadmin-only by placement).
 */
export function VerificationReport({ intakeId, runId }: { intakeId: string; runId: string }) {
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
  // ONE computed source count. Stat tile 5 reads it here, and plan 22-08's collapsed citation
  // list must read this same const rather than make a second `.length` call of its own: two
  // independent counts of one thing are two numbers that can drift (22-UI-SPEC §3.2).
  const sourcesCited = citations.length;
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

  const refutedCount = report?.verdicts?.refute?.length ?? 0;
  const costTotal = report?.true_cost?.cost_usd_total ?? null;

  // The funnel's VALUES cross the same trust boundary as its engine-authored keys (T-22-20):
  // the wire type says number, but anything else would reach the bar as `width: NaN%`. Coerced
  // once, here, so the bar geometry can never be fed a non-number.
  const funnelEntries: Array<[string, number]> = Object.entries(report?.funnel ?? {}).map(
    ([stage, count]) => [stage, Number.isFinite(Number(count)) ? Number(count) : 0],
  );
  // A funnel of all zeros must not divide by zero, and an empty funnel must not produce
  // -Infinity — which is exactly what a bare `Math.max(...[])` returns.
  const funnelMax = Math.max(...funnelEntries.map(([, count]) => count), 1);

  // "Every verdict list is empty" is a FINDING, not a blank page: the funnel, the unverified
  // accounting and the cost still render beneath the message.
  const verdictRowCount =
    (report?.verdicts?.refute?.length ?? 0) +
    (report?.verdicts?.support?.length ?? 0) +
    (report?.verdicts?.insufficient?.length ?? 0) +
    (report?.verdicts?.superseded?.length ?? 0) +
    (report?.superseded?.length ?? 0) +
    (report?.reconciled?.length ?? 0);

  // The fetch lives in a callback so that BOTH the mount effect and the error state's "Try
  // again" button drive one code path. `reqRef` does what the old effect's `cancelled` flag
  // did, and more precisely: only the NEWEST request may write state. When intakeId/runId
  // change, the effect re-runs, the sequence is bumped, and the previous run's in-flight
  // response is dropped — so run A's report can never render under run B's id. React 19 no
  // longer warns about a setState after unmount and it is a no-op, so no cleanup is needed for
  // that case. RETURN-NO-THROW: failure surfaces as an inline message AND a toast.
  const reqRef = useRef(0);
  const loadReport = useCallback(() => {
    const seq = ++reqRef.current;
    setLoading(true);
    setError(null);
    void getVerification(intakeId, runId).then((res) => {
      if (seq !== reqRef.current) return;
      setLoading(false);
      if (res.success && res.data) {
        setReport(res.data);
      } else {
        setError(t("verification.loadError"));
        toast.error(t("verification.loadError"));
      }
    });
  }, [intakeId, runId, t]);

  useEffect(() => {
    loadReport();
  }, [loadReport]);

  return (
    <div role="region" aria-label={t("verification.regionLabel")}>
      {/* A full page showing a single spinner reads as broken. The skeleton has the shape of
          what is arriving: the stat strip, then section blocks. */}
      {loading && (
        <div>
          <div className="mb-8 grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-6">
            {[0, 1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="bg-paperLight px-6 py-5">
                <Skeleton className="h-3 w-20" />
                <Skeleton className="mt-3 h-6 w-14" />
              </div>
            ))}
          </div>
          {[0, 1, 2].map((i) => (
            <div key={i} className="mb-8 bg-paperLight px-6 py-5">
              <Skeleton className="h-3.5 w-48" />
              <Skeleton className="mt-4 h-16 w-full" />
            </div>
          ))}
        </div>
      )}

      {!loading && error && (
        <div className="bg-paperLight px-6 py-5">
          <p className="font-sans text-[13px] text-red-600">{error}</p>
          <button
            type="button"
            onClick={loadReport}
            className="mt-3 inline-flex items-center gap-2 border border-ink/30 px-4 py-2 font-mono text-xs uppercase tracking-wider text-ink hover:bg-ink/5"
          >
            {t("verification.retry")}
          </button>
        </div>
      )}

      {!loading && !error && report && (
        <div>
          {/* ── B. Stat strip — the trust question above the fold ─────────────────────
                 "How much was checked, and how much of it broke." Today that answer was
                 scattered across a raw funnel line and a sentence hundreds of lines down.
                 Six tiles, every one a figure the report measured. NO percentages, NO
                 ratios, NO trend, NO duplicates-removed count and NO corroboration claim:
                 read-time collapsing changes DISPLAY only, while cost and corroboration
                 still count the absorbed rows until the write-side fix lands (D-22-4).
                 Tile 5 is therefore "Sources cited" — the count of distinct sources SHOWN —
                 and deliberately not "Sources fetched". */}
          <div className="mb-8 grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-6">
            <StatTile
              label={t("verification.statClaims")}
              {...statFigure(report.unverified?.total_claims)}
            />
            <StatTile
              label={t("verification.statWithVerdict")}
              {...statFigure(report.unverified?.claims_with_verdict)}
            />
            {/* The one tile that ever takes a colour, and only when something actually
                broke. Its label reads "Refuted", so the colour is reinforcement. */}
            <StatTile
              label={t("verification.statRefuted")}
              {...statFigure(refutedCount)}
              color={refutedCount > 0 ? "#DC2626" : FIGURE_NEUTRAL}
            />
            <StatTile
              label={t("verification.statUnverified")}
              {...statFigure(report.unverified?.count)}
            />
            <StatTile label={t("verification.statSources")} {...statFigure(sourcesCited)} />
            {/* C1 facts-only: an open tool fee shows the total SO FAR plus a label. Never a
                numeric placeholder for the class that is not yet itemized. */}
            <StatTile
              label={t("research.cost")}
              value={costTotal ?? "—"}
              color={costTotal ? undefined : FIGURE_NEUTRAL}
              chip={report.true_cost?.cost_pending ? t("verification.costPending") : undefined}
            />
          </div>

          {/* ── C. Gate funnel as proportion ──────────────────────────────────────────
                 A bar per stage, so "3,000 in, 40 out" is legible at a glance where a
                 comma-separated list of numbers is not. The stage key is rendered RAW: it is
                 an engine identifier, and inventing a friendly label for a key this build has
                 never seen is precisely the fabrication this project bars. NO CHART LIBRARY —
                 one is already installed and it is deliberately not used here, because a
                 proportional div matches the house language, costs no bundle weight and needs
                 no responsive container.
                 The funnel gets no anchor id: it sits above the document, beside the stat
                 strip, and is not one of the nav rail's entries. */}
          {funnelEntries.length > 0 && (
            <section aria-labelledby="funnel-heading" className="mb-8 bg-paperLight px-6 py-5">
              <h2 id="funnel-heading" className={SECTION_HEADING_CLASS}>
                <span>{t("verification.funnelTitle")}</span>
              </h2>
              <div className="mt-3 space-y-1.5">
                {funnelEntries.map(([stage, count]) => (
                  <div
                    key={stage}
                    className="flex items-center gap-3"
                    aria-label={t("verification.funnelStage", { stage, count })}
                  >
                    <span className="w-44 shrink-0 truncate font-mono text-[11px] text-ink/70">
                      {stage}
                    </span>
                    <div className="h-2 flex-1 bg-paper2" aria-hidden="true">
                      <div
                        className="h-2 bg-ink"
                        style={{ width: `${(count / funnelMax) * 100}%` }}
                      />
                    </div>
                    <span className="w-16 shrink-0 text-right font-mono text-[11px] tabular-nums text-ink/70">
                      {count}
                    </span>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* ── E. THE DOCUMENT ───────────────────────────────────────────────────────
                 E1–E9 below are in the EXACT order this component has always rendered
                 them. Not one has moved, and not one is dropped, truncated, merged or
                 collapsed (D-22-2). What changed is that each is now a block with a real
                 heading and an anchor. */}

          {/* A report that loaded but recorded no verdicts at all is a FINDING. Say so, and
              still render the funnel above and the accounting and cost below. */}
          {verdictRowCount === 0 && (
            <div className="mb-8 bg-paperLight px-6 py-5">
              <p className="font-sans text-[13px] leading-relaxed text-ink/60">
                {t("verification.emptyReport")}
              </p>
            </div>
          )}

          {/* E1. Refuted — the one section carrying a semantic rule, because it is the one
                  that answers "what broke". Colour is not the sole carrier: the heading
                  says "Refuted". */}
          <VerdictSection
            id="refuted"
            title={t("verification.refutedTitle")}
            items={report.verdicts?.refute}
            leftRuleColor="#DC2626"
            showEffect
            citationsByClaim={citationsByClaim}
            onOpenCitation={openCitationPanel}
          />
          <VerdictSection
            id="support"
            title={t("verification.supportTitle")}
            items={report.verdicts?.support}
            citationsByClaim={citationsByClaim}
            onOpenCitation={openCitationPanel}
          />
          <VerdictSection
            id="insufficient"
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
            id="superseded-verdicts"
            title={t("verification.supersededVerdictsTitle")}
            items={report.verdicts?.superseded}
            showEffect
            citationsByClaim={citationsByClaim}
            onOpenCitation={openCitationPanel}
          />

          {/* ── Superseded / scoped findings (canonical value + caveat inline) ──── */}
          <VerdictSection
            id="superseded"
            title={t("verification.supersededTitle")}
            items={report.superseded}
            showEffect
            citationsByClaim={citationsByClaim}
            onOpenCitation={openCitationPanel}
          />

          {/* ── Reconciled contradictions (chosen canonical value) ─────────────── */}
          <VerdictSection
            id="reconciled"
            title={t("verification.reconciledTitle")}
            items={report.reconciled}
            showEffect
            citationsByClaim={citationsByClaim}
            onOpenCitation={openCitationPanel}
          />

          {/* ── Honest unverified accounting (count-only — the backend emits no
                 per-claim items: {count, claims_with_verdict, total_claims}) ──────── */}
          <ReportSection
            id="unverified"
            title={t("verification.unverifiedTitle", { count: report.unverified?.count ?? 0 })}
          >
            {(report.unverified?.count ?? 0) > 0 ? (
              <p className="mt-3 font-sans text-[13px] leading-relaxed text-ink/60">
                {t("verification.unverifiedSummary", {
                  withVerdict: report.unverified?.claims_with_verdict ?? 0,
                  total: report.unverified?.total_claims ?? 0,
                })}
              </p>
            ) : (
              <p className="mt-3 font-sans text-[13px] leading-relaxed text-ink/60">
                {t("verification.unverifiedNone")}
              </p>
            )}
          </ReportSection>

          {/* ── Numbered citations (SC4 / D13 — every [n] clickable + resolving) ──
                 A flat list in this plan; plan 22-08 makes it collapsible and moves the
                 panel below out to a page-level sheet. */}
          {citations.length > 0 && (
            <ReportSection id="citations" title={t("verification.citationsTitle")}>
              <ul className="mt-3 space-y-1">
                {citations.map((c) => (
                  <li
                    key={c.n}
                    className="flex items-baseline gap-1 font-sans text-[13px] leading-relaxed text-ink/80"
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
            </ReportSection>
          )}

          {/* ── True itemized cost (facts-only; pending → LABEL, never a number) ── */}
          <ReportSection id="cost" title={t("verification.costTitle")}>
            <div className="mt-3 border-t border-ink/10 pt-3">
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
          </ReportSection>
        </div>
      )}
    </div>
  );
}
