import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { search as runSearch, refreshSearch, type SearchHit } from "@/lib/api/search";

export const Route = createFileRoute("/admin/pulse/search")({
  component: SearchPage,
});

const SUGGESTIONS = [
  "tankstations en EV-charging",
  "merk strategie",
  "B2B fleet contracten",
  "consumer sentiment",
  "concurrenten benchmarken",
];

const RECENT_KEY = "nestor:recent-global-queries";

function simColor(s: number) {
  if (s >= 0.7) return "text-emerald-700";
  if (s >= 0.55) return "text-amber-700";
  return "text-ink/50";
}

function SearchPage() {
  const { t } = useTranslation("admin");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchHit[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [reindexing, setReindexing] = useState(false);
  const [latency, setLatency] = useState<number | null>(null);
  const [lastQuery, setLastQuery] = useState("");

  useEffect(() => {
    if (typeof window !== "undefined") {
      localStorage.removeItem(RECENT_KEY);
      localStorage.removeItem("nestor:recent_searches");
      localStorage.removeItem("recent_searches");
      localStorage.removeItem("ai_search_history");
    }
  }, []);

  async function handleSearch(queryText?: string) {
    const q = (queryText ?? query).trim();
    if (!q) return;
    setLoading(true);
    setLastQuery(q);
    const start = Date.now();
    // The semantic-search backend lands in Phase 7; the seam shape is fixed now, so a
    // not-yet-available response surfaces as a graceful toast rather than a crash.
    const res = await runSearch(q);
    setLoading(false);
    if (!res.success) {
      toast.error(res.error);
      setResults([]);
      return;
    }
    setResults(res.data);
    setLatency(Date.now() - start);
  }

  async function reindex() {
    if (!confirm(t("search.reindexConfirm"))) return;
    setReindexing(true);
    const res = await refreshSearch();
    setReindexing(false);
    if (!res.success) {
      toast.error(res.error);
      return;
    }
    toast.success(t("search.reindexStarted"));
  }

  return (
    <div className="max-w-4xl">
      <p className="font-mono text-xs uppercase tracking-wider text-ink/60">
        {t("search.eyebrow")}
      </p>
      <p className="mt-3 font-sans text-base text-ink/70">{t("search.subtitle")}</p>

      <div className="mt-6 flex border border-ink/30 border-l-4 border-l-pink-500 bg-paperLight">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              handleSearch();
            }
          }}
          placeholder={t("search.inputPlaceholder")}
          className="flex-1 min-w-0 bg-transparent px-5 py-4 text-base text-ink placeholder:text-ink/40 placeholder:font-mono placeholder:text-sm focus:outline-none"
          autoFocus
        />
        <button
          type="button"
          onClick={() => handleSearch()}
          disabled={loading || !query.trim()}
          className="bg-ink text-paper font-mono text-sm uppercase tracking-wider px-5 disabled:opacity-40"
        >
          {loading ? t("search.searching") : t("search.searchButton")}
        </button>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <span className="font-mono text-[11px] uppercase tracking-wider text-ink/60">
          {t("search.examples")}
        </span>
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => {
              setQuery(s);
              void handleSearch(s);
            }}
            className="border border-ink/30 px-3 py-1 text-sm hover:bg-ink/5"
          >
            {s}
          </button>
        ))}
      </div>

      <div className="mt-6 flex items-center justify-end border-t border-ink/15 pt-3">
        <button
          type="button"
          onClick={reindex}
          disabled={reindexing}
          className="font-mono text-[11px] uppercase tracking-wider text-ink underline-offset-4 hover:underline disabled:opacity-40"
        >
          {reindexing ? t("search.reindexing") : t("search.reindex")}
        </button>
      </div>

      {results !== null && (
        <div className="mt-8">
          <p className="font-mono text-[11px] uppercase tracking-wider text-ink/60">
            {t("search.resultsSummary", { query: lastQuery, count: results.length })}
            {latency !== null ? ` · ${latency}ms` : ""}
          </p>

          {results.length === 0 && !loading && (
            <p className="mt-4 font-sans text-sm text-ink/60">{t("search.noResults")}</p>
          )}

          <div className="mt-4 space-y-3">
            {results.map((r) => (
              <div key={r.id} className="border border-ink/30 bg-paperLight p-4">
                <div className="flex items-start justify-between gap-3">
                  <p className="min-w-0 font-sans text-sm text-ink/80 line-clamp-4">
                    {r.content ?? "—"}
                  </p>
                  <span className={cn("font-mono text-[11px] tabular-nums", simColor(r.score))}>
                    {Math.round(r.score * 100)}%
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
