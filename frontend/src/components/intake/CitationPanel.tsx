import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, X } from "lucide-react";
import { toast } from "sonner";
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

/**
 * Render a clickable `[n]` citation marker for the report body. `onOpen` is called with the
 * citation when the marker is clicked, opening the CitationPanel. Kept tiny + presentational
 * so the report body can interleave markers inline with prose.
 */
export function renderCitationMarker(citation: Citation, onOpen: (c: Citation) => void) {
  return (
    <button
      key={`cite-${citation.n}`}
      type="button"
      onClick={() => onOpen(citation)}
      className="mx-0.5 inline-flex items-baseline align-baseline font-mono text-[11px] text-[#FF2D87] hover:underline"
      aria-label={`citation ${citation.n}`}
    >
      [{citation.n}]
    </button>
  );
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
          <span>
            {t("citation.published", {
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
