import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, X } from "lucide-react";
import { toast } from "sonner";
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card";
import { getSource, type Citation, type CitationSource } from "@/lib/api/research";

// frontend/src/components/intake/CitationPanel.tsx — the D13 client-quality numbered-citation
// surface (Plan 15-06 / ENGINE-09). A clickable `[n]` marker (rendered by
// `renderCitationMarker`) opens this panel, which fetches the citation's stored source
// snapshot through the Plan 15-04 superadmin proxy and renders the number, title, publication
// date, quality tier (1 official / 2 serious press / 3 blog), a single-source badge, an
// inline outdated-fact temporal caveat, and — crucially — the STORED snapshot text.
//
// The `[n]` numbering itself is GENERATED from the DB (Plan 15-03 numbering.py), never the
// model (T-15-16), so every number is guaranteed to resolve against `getSource`.
//
// SECURITY (T-15-14 / T-15-15 / T-15-16b): superadmin-only BY PLACEMENT — no client route
// imports this (enforced by the 16-D-08 route-import grep guard). The panel renders the
// STORED `snapshot_text` DIRECTLY and NEVER re-fetches the live `source.url` — so a dead link
// still resolves and no arbitrary live URL is requested (SSRF + dead-link survival, the
// renderer.py contract). The source read goes through the space-scoped superadmin proxy
// (Plan 15-04) + tribunal RLS 404 — never `sources.ts` (that is intake-UPLOAD sources).
//
// RETURN-NO-THROW (CLAUDE.md): the fetch surfaces failure via a sonner toast + inline error,
// never a throw.

const TIER_KEY: Record<1 | 2 | 3, string> = {
  1: "citation.tierOfficial",
  2: "citation.tierPress",
  3: "citation.tierBlog",
};

/** The `[n]` marker's classes. Shared so the trigger button is byte-identical to the original.
 *  NOTE `mx-0.5` (2px) is deliberate optical alignment of an inline element inside running
 *  text — it is inherited from the 15-06 marker and must NOT be "corrected" to 4px. */
const MARKER_CLASS =
  "mx-0.5 inline-flex items-baseline align-baseline font-mono text-[11px] text-[#FF2D87] hover:underline";

/**
 * The quality-tier glyph: tier 1 = ■■■, tier 2 = ■■□, tier 3 = ■□□ — filled marks count DOWN
 * as tier quality drops (1 official / 2 serious press / 3 blog).
 *
 * ACCESSIBILITY CONTRACT: the tier is NEVER carried by the glyph alone and NEVER by colour —
 * both marks are ink. The text label ships INSIDE this component, beside the marks, so the
 * glyph can only ever be redundant reinforcement. Rendering it here (rather than leaving the
 * label to each call site) is what keeps the hover card and the expanded citation list from
 * drifting into disagreeing about what a tier looks like (22-UI-SPEC §3.3).
 *
 * Exported for reuse by the citation-list rows.
 */
export function CitationTierGlyph({ quality_tier }: { quality_tier: 1 | 2 | 3 }) {
  const { t } = useTranslation("intake");
  // tier 1 → 3 filled, tier 2 → 2 filled, tier 3 → 1 filled.
  const filled = 4 - quality_tier;

  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        role="img"
        aria-label={t("verification.hoverTierLabel", { tier: quality_tier })}
        className="inline-flex items-center gap-0.5"
      >
        {[0, 1, 2].map((i) => (
          <span key={i} className={i < filled ? "mark-ink" : "mark-outline"} />
        ))}
      </span>
      <span>{t(TIER_KEY[quality_tier])}</span>
    </span>
  );
}

/**
 * A clickable `[n]` citation marker that previews its citation on hover. `onOpen` is called
 * with the citation on click, opening the CitationPanel.
 *
 * NO NETWORK CALL: every field in the preview comes off the in-memory `Citation`. `getSource`
 * is the panel's job, never the marker's.
 *
 * SECURITY (T-22-06): `citation.title` is engine-authored from remote page metadata and is
 * rendered as a PLAIN TEXT CHILD. It must never be routed through `MdText` / `ReactMarkdown` —
 * `rehype-raw` is a project dependency, which would turn a hostile page title into stored XSS.
 *
 * The HoverCard is CONTROLLED on purpose: a click while the card is open would otherwise leave
 * a floating preview sitting on top of the panel it just opened. `setOpen(false)` before
 * `onOpen` makes the ordering deterministic instead of relying on Radix pointer-down heuristics.
 */
export function CitationMarker({
  citation,
  onOpen,
}: {
  citation: Citation;
  onOpen: (c: Citation) => void;
}) {
  const { t } = useTranslation("intake");
  const [open, setOpen] = useState(false);

  return (
    <HoverCard open={open} onOpenChange={setOpen} openDelay={120} closeDelay={80}>
      <HoverCardTrigger asChild>
        <button
          type="button"
          onClick={() => {
            setOpen(false);
            onOpen(citation);
          }}
          className={MARKER_CLASS}
          aria-label={`citation ${citation.n}`}
        >
          [{citation.n}]
        </button>
      </HoverCardTrigger>

      {/* A CLOSED LIST of exactly four lines: number + title, retrieved date, tier, hint.
          Everything else the record carries — the corroboration badge, the outdated-fact
          caveat, the stored page text, the link and where it came from — is deliberately
          EXCLUDED: it belongs to the click and lives in the panel below.
          `shadow-none` overrides the primitive's `shadow-md`: this design system is 0px radii
          and hard borders, so a drop shadow is the wrong dialect. */}
      <HoverCardContent
        side="top"
        align="start"
        sideOffset={6}
        collisionPadding={16}
        className="w-72 border border-ink/30 border-l-4 bg-paperLight p-4 shadow-none"
        style={{ borderLeftColor: "#FF2D87" }}
      >
        <div className="flex items-baseline gap-1.5">
          <span className="font-mono text-[11px] text-[#FF2D87]">[{citation.n}]</span>
          <span className="font-sans text-[13px] font-semibold text-ink">
            {citation.title ?? t("citation.untitled")}
          </span>
        </div>

        <div className="mt-1 font-mono text-[11px] text-ink/60">
          {t("citation.retrieved", {
            date: citation.publication_date ?? t("citation.dateUnknown"),
          })}
        </div>

        <div className="mt-2">
          <span className="inline-flex bg-paper2 px-2 py-0.5 font-mono text-[11px] text-ink/70">
            <CitationTierGlyph quality_tier={citation.quality_tier} />
          </span>
        </div>

        <p className="mt-2 border-t border-ink/10 pt-2 font-mono text-[10px] text-ink/45">
          {t("verification.hoverClickHint")}
        </p>
      </HoverCardContent>
    </HoverCard>
  );
}

/**
 * Render a clickable `[n]` citation marker for the report body. Kept as an exported function
 * with an UNCHANGED signature — a thin wrapper over `CitationMarker` — so the three existing
 * call sites in `VerificationReport.tsx` compile without an edit.
 */
export function renderCitationMarker(citation: Citation, onOpen: (c: Citation) => void) {
  return <CitationMarker key={`cite-${citation.n}`} citation={citation} onOpen={onOpen} />;
}

/**
 * The D13 citation panel. Given a clicked `[n]` (a `Citation`), fetches
 * `getSource(intakeId, citation.source_id)` on mount and renders the number, title,
 * publication date, quality tier, single-source badge, inline temporal note, and the stored
 * `snapshot_text` — rendered DIRECTLY (never a live-URL re-fetch). `onClose` collapses it.
 * Superadmin-only by placement (imported only on the admin intake detail route beside the
 * report body — never a client route).
 */
export function CitationPanel({
  intakeId,
  citation,
  onClose,
}: {
  intakeId: string;
  citation: Citation;
  onClose?: () => void;
}) {
  const { t } = useTranslation("intake");
  const [source, setSource] = useState<CitationSource | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    void getSource(intakeId, citation.source_id).then((res) => {
      if (cancelled) return;
      setLoading(false);
      if (res.success && res.data) {
        setSource(res.data);
      } else {
        setError(t("citation.loadError"));
        toast.error(t("citation.loadError"));
      }
    });
    return () => {
      cancelled = true;
    };
  }, [intakeId, citation.source_id, t]);

  const title = citation.title ?? source?.title ?? t("citation.untitled");

  return (
    <div
      className="mt-2 border border-ink/20 border-l-4 bg-paperLight px-4 py-3"
      style={{ borderLeftColor: "#FF2D87" }}
      role="region"
      aria-label={t("citation.regionLabel")}
    >
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="font-mono text-[11px] uppercase tracking-wider text-ink/60">
          {t("citation.title", { n: citation.n })}
        </span>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            className="inline-flex items-center gap-1 font-mono text-[11px] uppercase tracking-wider text-ink/50 hover:text-ink"
          >
            <X className="h-3.5 w-3.5" />
            {t("citation.close")}
          </button>
        )}
      </div>

      {/* ── Header metadata: title, publication date, tier, single-source, temporal note ── */}
      <div className="mb-2">
        <div className="font-sans text-[14px] font-medium text-ink">{title}</div>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[11px] text-ink/60">
          {/* "retrieved", NEVER "published". `publication_date` carries `source.fetched_at` —
              the moment the crawler pulled the page, which says nothing about when the page
              was published. `citations/numbering.py:29-31` states the field is a retrieval-date
              proxy and requires downstream renderers label it "retrieved". This line said
              "Published:" until Phase 22; presenting a proxy as a fact is precisely what the
              "NO ESTIMATES — facts only" bar forbids. The hover card reads the SAME key, so
              the two surfaces cannot drift about what the date means. */}
          <span>
            {t("citation.retrieved", {
              date: citation.publication_date ?? t("citation.dateUnknown"),
            })}
          </span>
          <span className="bg-paper px-2 py-0.5 text-ink/70">
            {t(TIER_KEY[citation.quality_tier])}
          </span>
          {citation.single_source && (
            <span className="bg-amber-50 px-2 py-0.5 text-amber-700">
              {t("citation.singleSource")}
            </span>
          )}
        </div>
        {citation.temporal_note && (
          <p className="mt-2 bg-amber-50 px-3 py-1.5 font-sans text-[12px] text-amber-800">
            {citation.temporal_note}
          </p>
        )}
      </div>

      {/* ── Stored snapshot (rendered DIRECTLY — the live url is NEVER re-fetched) ──────── */}
      <p className="mb-1 font-mono text-[10px] uppercase tracking-wider text-ink/45">
        {t("citation.snapshotLabel")}
      </p>

      {loading && (
        <div className="flex items-center gap-2 font-mono text-[12px] text-ink/60">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t("citation.loading")}
        </div>
      )}

      {!loading && error && <p className="font-sans text-[13px] text-red-600">{error}</p>}

      {!loading && !error && source && (
        <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words bg-paper px-3 py-2 font-sans text-[13px] leading-relaxed text-ink/80">
          {source.snapshot_text ?? t("citation.snapshotEmpty")}
        </pre>
      )}
    </div>
  );
}
