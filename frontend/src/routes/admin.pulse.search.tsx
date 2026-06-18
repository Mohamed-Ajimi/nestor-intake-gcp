import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { format } from "date-fns";
import { nl } from "date-fns/locale";
import { supabase } from "@/lib/supabase";
import { ProductPill } from "@/components/admin/clientPills";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/admin/pulse/search")({
  component: SearchPage,
});

const SUPABASE_URL = import.meta.env.VITE_SUPABASE_URL as string;
const SUPABASE_ANON_KEY = import.meta.env.VITE_SUPABASE_ANON_KEY as string;

const SUGGESTIONS = [
  "tankstations en EV-charging",
  "merk strategie",
  "B2B fleet contracten",
  "consumer sentiment",
  "concurrenten benchmarken",
];

const RECENT_KEY = "nestor:recent-global-queries";

const ANSWER_LABELS: Record<string, string> = {
  decision_or_goal: "DOEL",
  company_intro: "BEDRIJF",
  audience_description: "DOELGROEP",
  context: "CONTEXT",
  constraints: "CONSTRAINTS",
  success_criteria: "SUCCES",
};

type SearchResult = {
  entity_type: string;
  context_label?: string | null;
  text_content: string;
  similarity: number;
  intake_id?: string | null;
  intake_title?: string | null;
  product_slug?: string | null;
  product_name?: string | null;
  client_id?: string | null;
  client_name?: string | null;
  client_industry?: string | null;
};

function typeBadge(r: SearchResult) {
  switch (r.entity_type) {
    case "question":
      return "VRAAG";
    case "intake_title":
      return "PROJECT";
    case "client_name":
      return "KLANT";
    case "intake_answer":
      return ANSWER_LABELS[r.context_label ?? ""] ?? (r.context_label ?? "ANTWOORD").toUpperCase();
    default:
      return r.entity_type.toUpperCase();
  }
}

function simColor(s: number) {
  if (s >= 0.7) return "text-emerald-700";
  if (s >= 0.55) return "text-amber-700";
  return "text-ink/50";
}


function SearchPage() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [reindexing, setReindexing] = useState(false);
  const [latency, setLatency] = useState<number | null>(null);
  const [lastQuery, setLastQuery] = useState("");
  const [stats, setStats] = useState<{ total: number; lastUpdate: string | null }>({
    total: 0,
    lastUpdate: null,
  });
  const navigate = useNavigate();

  useEffect(() => {
    if (typeof window !== "undefined") {
      localStorage.removeItem(RECENT_KEY);
      localStorage.removeItem("nestor:recent_searches");
      localStorage.removeItem("recent_searches");
      localStorage.removeItem("ai_search_history");
    }
    void fetchStats();
  }, []);

  async function fetchStats() {
    if (!supabase) return;
    const { data } = await supabase
      .schema("nestor" as never)
      .from("search_index")
      .select("updated_at")
      .order("updated_at", { ascending: false });
    setStats({
      total: data?.length ?? 0,
      lastUpdate: data?.[0]?.updated_at ?? null,
    });
  }

  async function handleSearch(queryText?: string) {
    const q = (queryText ?? query).trim();
    if (!q) return;
    setLoading(true);
    setLastQuery(q);
    const start = Date.now();
    try {
      const res = await fetch(`${SUPABASE_URL}/functions/v1/search-global`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${SUPABASE_ANON_KEY}`,
          apikey: SUPABASE_ANON_KEY,
        },
        body: JSON.stringify({ query: q, top_k: 15 }),
      });
      if (!res.ok) throw new Error(`Search failed (${res.status})`);
      const data = await res.json();
      setResults(data.results || []);
      setLatency(Date.now() - start);
      
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Zoeken mislukt");
      setResults([]);
    } finally {
      setLoading(false);
    }
  }

  async function reindex() {
    if (!supabase) return;
    if (!confirm("Reindex alle klanten/vragen? Duurt ~30 sec.")) return;
    setReindexing(true);
    try {
      const { error } = await supabase.schema("nestor" as never).rpc("refresh_search_index");
      if (error) throw error;
      const res = await fetch(`${SUPABASE_URL}/functions/v1/embed-pending-search`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${SUPABASE_ANON_KEY}`,
          apikey: SUPABASE_ANON_KEY,
        },
        body: "{}",
      });
      const data = await res.json();
      toast.success(`${data.embedded ?? 0} items geïndexeerd`);
      await fetchStats();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Reindex mislukt");
    } finally {
      setReindexing(false);
    }
  }


  function openResult(r: SearchResult) {
    if (r.entity_type === "client_name" && r.client_id) {
      navigate({ to: "/admin/pulse/clients", search: { client: r.client_id } as never });
    } else if (r.intake_id) {
      navigate({ to: "/admin/pulse/intakes/$id", params: { id: r.intake_id } });
    } else if (r.client_id) {
      navigate({ to: "/admin/pulse/clients", search: { client: r.client_id } as never });
    }
  }

  return (
    <div className="max-w-4xl">
      <p className="font-mono text-xs uppercase tracking-wider text-ink/60">AI-zoek alles</p>
      <p className="mt-3 font-sans text-base text-ink/70">
        Doorzoek alle klanten, projecten en research-vragen op betekenis.
      </p>

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
          placeholder="stel je vraag in natuurlijke taal..."
          className="flex-1 min-w-0 bg-transparent px-5 py-4 text-base text-ink placeholder:text-ink/40 placeholder:font-mono placeholder:text-sm focus:outline-none"
          autoFocus
        />
        <button
          type="button"
          onClick={() => handleSearch()}
          disabled={loading || !query.trim()}
          className="bg-ink text-paper font-mono text-sm uppercase tracking-wider px-5 disabled:opacity-40"
        >
          {loading ? "Bezig…" : "Zoek →"}
        </button>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <span className="font-mono text-[11px] uppercase tracking-wider text-ink/60">Voorbeelden:</span>
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


      <div className="mt-6 flex items-center justify-between border-t border-ink/15 pt-3">
        <p className="font-mono text-[11px] uppercase tracking-wider text-ink/60">
          Geïndexeerd: {stats.total} items
          {stats.lastUpdate
            ? ` · Laatst: ${format(new Date(stats.lastUpdate), "d MMM HH:mm", { locale: nl })}`
            : ""}
        </p>
        <button
          type="button"
          onClick={reindex}
          disabled={reindexing}
          className="font-mono text-[11px] uppercase tracking-wider text-ink underline-offset-4 hover:underline disabled:opacity-40"
        >
          {reindexing ? "reindexeren…" : "Reindex"}
        </button>
      </div>

      {results !== null && (
        <div className="mt-8">
          <p className="font-mono text-[11px] uppercase tracking-wider text-ink/60">
            "{lastQuery}" — {results.length} resultaten
            {latency !== null ? ` · ${latency}ms` : ""}
          </p>

          {results.length === 0 && !loading && (
            <p className="mt-4 font-sans text-sm text-ink/60">
              Geen resultaten boven 0% similarity. Probeer een andere formulering of klik Reindex.
            </p>
          )}

          <div className="mt-4 space-y-3">
            {results.map((r, i) => (
              <div key={i} className="border border-ink/30 bg-paperLight p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex flex-wrap items-center gap-1.5 min-w-0">
                    <span className="inline-block whitespace-nowrap font-mono text-[10px] uppercase tracking-wider px-1.5 py-0.5 bg-ink text-paper">
                      {typeBadge(r)}
                    </span>
                    {r.product_slug && <ProductPill slug={r.product_slug} name={r.product_slug} />}
                    {r.intake_title && (
                      <span className="font-sans text-sm font-medium text-ink truncate">
                        {r.intake_title}
                      </span>
                    )}
                  </div>
                  <span className={cn("font-mono text-[11px] tabular-nums", simColor(r.similarity))}>
                    {Math.round(r.similarity * 100)}%
                  </span>
                </div>
                {(r.client_name || r.client_industry) && (
                  <div className="mt-1 font-mono text-[10px] uppercase tracking-wider text-ink/60">
                    {[r.client_name, r.client_industry].filter(Boolean).join(" · ")}
                  </div>
                )}
                <p className="mt-2 font-sans text-sm text-ink/80 line-clamp-4">{r.text_content}</p>
                <div className="mt-3">
                  <button
                    type="button"
                    onClick={() => openResult(r)}
                    className="font-mono text-[11px] uppercase tracking-wider text-ink underline-offset-4 hover:underline"
                  >
                    {r.entity_type === "client_name" ? "Open klant →" : "Open intake →"}
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
