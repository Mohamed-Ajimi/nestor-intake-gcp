import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { jsPDF } from "jspdf";
import {
  Loader2,
  FileText,
  Download,
  Eye,
  EyeOff,
  Search as SearchIcon,
  ExternalLink,
  Copy,
  RefreshCw,
  ChevronDown,
  ChevronRight,
  X,
} from "lucide-react";
import * as storage from "@/lib/api/storage";
import { cn } from "@/lib/utils";
import { displayQuestionText, isAnchorQuestion } from "@/lib/research-question";

const BUCKET = "nestor-uploads";
const RECENT_MAX = 5;

export type RRPQuestion = {
  id: string;
  question_text: string;
  question_type: string | null;
  priority: number | null;
  rationale?: string | null;
  status?: string | null;
  /** klant-mode: from get_results_by_token */
  has_answer?: boolean;
  source_count?: number;
};

export type RRPArtifact = {
  id: string;
  research_question_id: string | null;
  source: string;
  artifact_type: string;
  filename: string;
  storage_path: string | null;
  byte_size: number | null;
  mime_type: string | null;
  created_at: string;
  text_content?: string | null;
};

export type RRPIntake = {
  id: string;
  title: string | null;
  client_results_token?: string | null;
  final_report_artifact_id?: string | null;
};

export type RRPClient = { id: string; name: string };

type SearchResult = {
  chunk_id: string;
  artifact_id: string;
  research_question_id: string | null;
  chunk_index: number;
  chunk_text: string;
  similarity: number;
  filename: string;
  source: string;
  artifact_type: string;
  created_at: string;
};

type Props = {
  mode: "admin" | "klant";
  intake: RRPIntake;
  client: RRPClient;
  questions: RRPQuestion[];
  artifacts: RRPArtifact[];
  /** klant-token, only required in mode="klant" */
  token?: string;
  /** klant-mode: whether AI-zoek is available (>=1 embedded artifact) */
  searchAvailable?: boolean;
  /** notify parent that token changed (admin only) */
  onTokenChange?: (token: string) => void;
};


function bytesLabel(n: number | null | undefined) {
  if (n == null) return "";
  if (n > 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  if (n > 1024) return `${Math.round(n / 1024)} KB`;
  return `${n} B`;
}

function slugify(s: string) {
  return s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

export function ResearchResultsPanel({
  mode,
  intake,
  client,
  questions,
  artifacts,
  token,
  searchAvailable,
  onTokenChange,
}: Props) {

  const visibleQuestions = useMemo(
    () =>
      (questions || [])
        .filter((q) => q.question_text && q.question_text.trim().length > 0)
        .sort((a, b) => {
          const pa = a.priority ?? 0;
          const pb = b.priority ?? 0;
          if (pa !== pb) return pa - pb;
          return 0;
        }),
    [questions],
  );

  const artifactsByQuestion = useMemo(() => {
    const m = new Map<string, RRPArtifact[]>();
    visibleQuestions.forEach((q) => m.set(q.id, []));
    artifacts.forEach((a) => {
      if (!a.research_question_id) return;
      if (!m.has(a.research_question_id)) m.set(a.research_question_id, []);
      m.get(a.research_question_id)!.push(a);
    });
    return m;
  }, [artifacts, visibleQuestions]);

  // Get signed URL — mode-aware
  const getSignedUrl = useCallback(
    async (artifactId: string, storagePath: string | null): Promise<string | null> => {
      // Admin downloads route through the backend storage seam. The klant
      // token-scoped path resolution is a research-backend op (Phase 7+) and is
      // inert this milestone.
      void artifactId;
      void token;
      if (mode !== "admin" || !storagePath) return null;
      const res = await storage.signedDownloadUrl({
        bucket: BUCKET,
        path: storagePath,
        expiresIn: 300,
      });
      return res.success ? res.data.url : null;
    },
    [mode, token],
  );

  const openArtifact = useCallback(
    async (a: RRPArtifact) => {
      const url = await getSignedUrl(a.id, a.storage_path);
      if (!url) {
        toast.error("Kon link niet maken");
        return;
      }
      window.open(url, "_blank", "noopener,noreferrer");
    },
    [getSignedUrl],
  );

  // Fetch text content of an artifact (for PDF)
  const getArtifactText = useCallback(
    async (a: RRPArtifact): Promise<string | null> => {
      // Artifact text bodies are served by the research backend (Phase 7+);
      // the admin DB read is out of scope. Where a signed URL is available
      // (admin seam), the text is fetched from it.
      const url = await getSignedUrl(a.id, a.storage_path);
      if (!url) return null;
      try {
        const res = await fetch(url);
        if (!res.ok) return null;
        return await res.text();
      } catch {
        return null;
      }
    },
    [mode, getSignedUrl],
  );

  return (
    <section className="border border-ink bg-paperLight p-6">
      <h2 className="mb-4 font-mono text-xs uppercase tracking-wider text-ink">
        Research resultaten
      </h2>

      {mode === "admin" && onTokenChange && (
        <KlantToegangBlock
          intake={intake}
          onTokenChange={onTokenChange}
        />
      )}

      {mode === "klant" && visibleQuestions.length === 0 && (
        <p className="border border-ink/30 bg-paper p-3 font-sans text-sm text-ink/60">
          Nog geen onderzoeksvragen beschikbaar.
        </p>
      )}

      {mode === "klant" && (
        <div className="space-y-6">
          {visibleQuestions.map((q, i) => (
            <QuestionResultBlock
              key={q.id}
              mode={mode}
              token={token}
              index={i + 1}
              question={q}
              artifacts={artifactsByQuestion.get(q.id) ?? []}
              client={client}
              openArtifact={openArtifact}
              getArtifactText={getArtifactText}
            />
          ))}
        </div>
      )}

      {(() => {
        const hasAnswers =
          mode === "klant"
            ? searchAvailable === true
            : artifacts.length > 0;
        if (!hasAnswers) {
          if (visibleQuestions.length === 0) return null;

          return (
            <div className="mt-8 border border-ink/30 border-l-4 bg-paperLight px-6 py-5" style={{ borderLeftColor: "#FF2D87" }}>
              <div className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-wider" style={{ color: "#FF2D87" }}>
                <SearchIcon className="h-4 w-4" /> AI-zoek in alle research
              </div>
              <p className="mt-1 font-sans text-sm text-ink/60">
                Beschikbaar zodra de research-antwoorden zijn geüpload.
              </p>
            </div>
          );
        }
        return (
          <div className="mt-8">
            <AISearchPanel
              mode={mode}
              intakeId={intake.id}
              token={token}
              visibleQuestions={visibleQuestions}
              openArtifact={openArtifact}
              artifacts={artifacts}
            />
          </div>
        );
      })()}
    </section>
  );
}

/* -------------------- Klant-toegang (admin only) -------------------- */

function KlantToegangBlock({
  intake,
  onTokenChange,
}: {
  intake: RRPIntake;
  onTokenChange: (t: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const token = intake.client_results_token ?? null;
  const url =
    token && typeof window !== "undefined"
      ? `${window.location.origin}/results/${token}`
      : null;

  const generate = async (regen: boolean) => {
    if (regen && !confirm("De oude link wordt ongeldig — doorgaan?")) return;
    // Klant-link generation (and the auto-deliver status bump) is mediated by
    // the backend (Phase 7+); not wired from this gated-off panel.
    void intake.final_report_artifact_id;
    void onTokenChange;
    void setBusy;
    toast.error("Klant-link genereren verloopt via de backend.");
  };

  const copy = async () => {
    if (!url) return;
    try {
      await navigator.clipboard.writeText(url);
      toast.success("Link gekopieerd");
    } catch {
      toast.error("Kopiëren mislukt");
    }
  };

  return (
    <div
      className="mb-6 border border-ink/30 border-l-4 bg-paperLight px-6 py-5"
      style={{ borderLeftColor: "#FF2D87" }}
    >
      <div
        className="font-mono text-[11px] uppercase tracking-wider"
        style={{ color: "#FF2D87" }}
      >
        Klant-toegang
      </div>
      <p className="mt-1 font-sans text-sm text-ink/70">
        Klant kan deze resultaten zelf bekijken via een unieke link.
      </p>
      {url ? (
        <div className="mt-3 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <code
              title={url}
              className="max-w-full truncate bg-paper2 px-2 py-1 font-mono text-xs text-ink/70"
            >
              {url}
            </code>
            <button
              type="button"
              onClick={copy}
              className="inline-flex items-center gap-1 border border-ink bg-paper px-2.5 py-1 font-mono text-xs uppercase tracking-wider text-ink hover:bg-ink/5"
            >
              <Copy className="h-3.5 w-3.5" /> Kopieer link
            </button>
            <button
              type="button"
              onClick={() => generate(true)}
              disabled={busy}
              className="inline-flex items-center gap-1 border border-ink bg-paper px-2.5 py-1 font-mono text-xs uppercase tracking-wider text-ink hover:bg-ink/5 disabled:opacity-50"
            >
              <RefreshCw className="h-3.5 w-3.5" /> Genereer nieuwe link
            </button>
          </div>
          <p className="font-mono text-[10px] uppercase tracking-wider text-ink/50">
            ℹ️ Wat de klant ziet: één samengevat rapport (download) + vragen-overzicht + AI-zoek.
            GEEN toegang tot raw research files of filenames.
          </p>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => generate(false)}
          disabled={busy}
          className="mt-3 inline-flex items-center gap-1.5 bg-ink px-3 py-1.5 font-mono text-xs uppercase tracking-wider text-paper hover:bg-ink/80 disabled:opacity-50"
        >
          {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          Genereer klant-link
        </button>
      )}
    </div>
  );
}

/* -------------------- Per-question block -------------------- */

function QuestionResultBlock({
  mode,
  token,
  index,
  question,
  artifacts,
  client,
  openArtifact,
  getArtifactText,
}: {
  mode: "admin" | "klant";
  token?: string;
  index: number;
  question: RRPQuestion;
  artifacts: RRPArtifact[];
  client: RRPClient;
  openArtifact: (a: RRPArtifact) => Promise<void>;
  getArtifactText: (a: RRPArtifact) => Promise<string | null>;
}) {
  const [showSources, setShowSources] = useState(false);
  const [generating, setGenerating] = useState(false);

  const answerArtifact = useMemo<RRPArtifact | null>(() => {
    if (!artifacts.length) return null;
    const synthesis = artifacts.find((a) =>
      a.filename.toLowerCase().includes("synthesis"),
    );
    if (synthesis) return synthesis;
    const sorted = [...artifacts].sort(
      (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
    );
    return sorted[0] ?? null;
  }, [artifacts]);

  // klant-mode: rely on question.has_answer / source_count from RPC
  const hasAnswer =
    mode === "klant" ? question.has_answer === true : answerArtifact !== null;
  const sourceCount =
    mode === "klant" ? (question.source_count ?? 0) : artifacts.length;

  const buildPdf = (text: string, clientName: string) => {
    const doc = new jsPDF({ unit: "mm", format: "a4" });
    const margin = 20;
    const pageW = doc.internal.pageSize.getWidth();
    const pageH = doc.internal.pageSize.getHeight();
    const usableW = pageW - 2 * margin;

    doc.setFont("helvetica", "normal");
    doc.setFontSize(8);
    doc.setTextColor(120);
    doc.text("AGENIC × NESTOR", margin, 12);
    doc.text(clientName.toUpperCase(), pageW - margin, 12, { align: "right" });

    let y = 28;
    doc.setFont("helvetica", "bold");
    doc.setFontSize(18);
    doc.setTextColor(0);
    const titleLines = doc.splitTextToSize(
      `V${index}. ${displayQuestionText(question)}`,
      usableW,
    );
    doc.text(titleLines, margin, y);
    y += titleLines.length * 7 + 4;

    doc.setFont("helvetica", "normal");
    doc.setFontSize(9);
    doc.setTextColor(100);
    doc.text(
      `Type: ${question.question_type ?? "—"} · Onderzoek: ${clientName} · ${new Date().toLocaleDateString("nl-BE")}`,
      margin,
      y,
    );
    y += 8;

    doc.setDrawColor(0);
    doc.setLineWidth(0.2);
    doc.line(margin, y, pageW - margin, y);
    y += 8;

    doc.setFont("helvetica", "normal");
    doc.setFontSize(10);
    doc.setTextColor(0);
    const bodyLines = doc.splitTextToSize(text, usableW);
    const lh = 5;
    for (const line of bodyLines) {
      if (y + lh > pageH - margin) {
        doc.addPage();
        y = margin;
      }
      doc.text(line, margin, y);
      y += lh;
    }

    const total = doc.getNumberOfPages();
    for (let i = 1; i <= total; i++) {
      doc.setPage(i);
      doc.setFontSize(7);
      doc.setTextColor(150);
      doc.text(`pagina ${i} / ${total}`, pageW - margin, pageH - 8, {
        align: "right",
      });
      doc.text("AGENIC × NESTOR — confidentieel", margin, pageH - 8);
    }

    const slug = slugify(
      `${clientName}-V${index}-antwoord-${new Date().toISOString().slice(0, 10)}`,
    );
    doc.save(`nestor-${slug}.pdf`);
  };

  const downloadPdf = async () => {
    setGenerating(true);
    try {
      let text: string | null = null;
      let clientName = client.name;

      if (mode === "klant") {
        // Klant synthesis text is served by the research backend (Phase 7+);
        // not available this milestone.
        void token;
        toast.error("Antwoord niet beschikbaar in deze fase.");
        return;
      } else {
        if (!answerArtifact) return;
        text = await getArtifactText(answerArtifact);
      }

      if (!text || !text.trim()) {
        toast.error("Geen tekst beschikbaar voor deze vraag");
        return;
      }
      buildPdf(text, clientName);
      toast.success("PDF gedownload.");
    } catch (e) {
      toast.error(`PDF mislukt: ${(e as Error).message}`);
    } finally {
      setGenerating(false);
    }
  };

  const isMain = (question.priority ?? 0) >= 4;
  const anchor = isAnchorQuestion(question);

  return (
    <div className="border-t border-ink/20 pt-6 first:border-t-0 first:pt-0">
      <div>
        <div className="flex flex-wrap items-center gap-2 font-mono text-xs uppercase tracking-wider text-ink/60">
          {anchor && (
            <span className="inline-flex items-center border border-ink bg-agenic-yellow px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-ink">
              Ankervraag
            </span>
          )}
          <span>V{index}</span>
        </div>
        <p className="mt-1 font-sans text-base text-ink">{displayQuestionText(question)}</p>
        <p className="mt-1 font-mono text-[10px] uppercase tracking-wider text-ink/50">
          Type: {question.question_type ?? "—"} · Prioriteit: {isMain ? "hoofd" : "extra"}
        </p>

      </div>

      {mode === "admin" && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button
            type="button"
            disabled={!hasAnswer || generating}
            onClick={downloadPdf}
            className="inline-flex items-center gap-1.5 bg-ink px-3 py-1.5 font-mono text-xs uppercase tracking-wider text-paper hover:bg-ink/80 disabled:opacity-40"
          >
            {generating ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Download className="h-3.5 w-3.5" />
            )}
            {hasAnswer ? "Download antwoord (PDF)" : "Antwoord nog niet beschikbaar"}
          </button>
          {artifacts.length > 0 && (
            <button
              type="button"
              onClick={() => setShowSources((s) => !s)}
              className="inline-flex items-center gap-1.5 border border-ink bg-paper px-3 py-1.5 font-mono text-xs uppercase tracking-wider text-ink hover:bg-ink/5"
            >
              {showSources ? (
                <EyeOff className="h-3.5 w-3.5" />
              ) : (
                <Eye className="h-3.5 w-3.5" />
              )}
              Bekijk bronnen ({artifacts.length})
            </button>
          )}
        </div>
      )}

      {mode === "admin" && showSources && artifacts.length > 0 && (
        <div className="mt-3 border border-ink/20 bg-paper">
          <div className="px-3 py-2 font-mono text-[10px] uppercase tracking-wider text-ink/60">
            Bronnen ({artifacts.length})
          </div>
          <ul className="divide-y divide-ink/10">
            {artifacts.map((a) => (
              <li
                key={a.id}
                className="flex flex-wrap items-center gap-2 px-3 py-2 text-sm"
              >
                <FileText className="h-4 w-4 text-ink/60" />
                <span className="font-sans text-ink">{a.filename}</span>
                <span className="font-mono text-[10px] uppercase tracking-wider text-ink/50">
                  · {bytesLabel(a.byte_size)}
                </span>
                <span className="font-mono text-[10px] uppercase tracking-wider text-ink/60">
                  · {a.source}
                </span>
                <button
                  type="button"
                  onClick={() => openArtifact(a)}
                  className="ml-auto inline-flex items-center gap-1 border border-ink/30 bg-paper px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-ink hover:bg-ink/5"
                >
                  <ExternalLink className="h-3 w-3" /> Open
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/* -------------------- AI Search Panel -------------------- */

function AISearchPanel({
  mode,
  intakeId,
  token,
  visibleQuestions,
  openArtifact,
  artifacts,
}: {
  mode: "admin" | "klant";
  intakeId: string;
  token?: string;
  visibleQuestions: RRPQuestion[];
  openArtifact: (a: RRPArtifact) => Promise<void>;
  artifacts: RRPArtifact[];
}) {
  const recentKey = `nestor:recent-queries:${intakeId}`;
  const [query, setQuery] = useState("");
  const [submittedQuery, setSubmittedQuery] = useState("");
  const [answer, setAnswer] = useState<string | null>(null);
  const [sourcesUsed, setSourcesUsed] = useState(0);
  const [fragments, setFragments] = useState<SearchResult[] | null>(null);
  const [showFragments, setShowFragments] = useState(false);
  const [searching, setSearching] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      localStorage.removeItem(recentKey);
      localStorage.removeItem("nestor:recent_searches");
      localStorage.removeItem("recent_searches");
      localStorage.removeItem("ai_search_history");
    } catch {
      /* ignore */
    }
  }, [recentKey]);

  const submit = useCallback(
    async (q: string) => {
      const text = q.trim();
      if (!text) return;
      setSearching(true);
      setSubmittedQuery(text);
      setAnswer(null);
      setFragments(null);
      setShowFragments(false);
      // AI-zoek (ask-research / embeddings) runs on the research backend
      // (Phase 7+) and is not available this milestone.
      void intakeId;
      void mode;
      void token;
      void setSourcesUsed;
      toast.error("AI-zoek is nog niet beschikbaar in deze fase.");
      setAnswer("");
      setSearching(false);
    },
    [intakeId, mode, token],
  );

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    submit(query);
  };

  const close = () => {
    setAnswer(null);
    setFragments(null);
    setShowFragments(false);
    setSubmittedQuery("");
  };

  const copyAnswer = async () => {
    if (!answer) return;
    try {
      await navigator.clipboard.writeText(answer);
      toast.success("Antwoord gekopieerd");
    } catch {
      toast.error("Kopiëren mislukt");
    }
  };

  const questionMap = useMemo(() => {
    const m = new Map<string, { index: number; text: string }>();
    visibleQuestions.forEach((q, i) => m.set(q.id, { index: i + 1, text: displayQuestionText(q) }));
    return m;
  }, [visibleQuestions]);

  const artifactMap = useMemo(() => {
    const m = new Map<string, RRPArtifact>();
    artifacts.forEach((a) => m.set(a.id, a));
    return m;
  }, [artifacts]);

  const paragraphs = useMemo(
    () => (answer ? answer.split(/\n\n+/).map((p) => p.trim()).filter(Boolean) : []),
    [answer],
  );

  return (
    <div
      className="border border-ink/30 border-l-4 bg-paperLight px-6 py-5"
      style={{ borderLeftColor: "#FF2D87" }}
    >
      <div
        className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-wider"
        style={{ color: "#FF2D87" }}
      >
        <SearchIcon className="h-4 w-4" /> AI-zoek in alle research
      </div>
      <p className="mt-1 font-sans text-sm text-ink/70">
        Stel vragen in natuurlijke taal — Nestor schrijft een coherent antwoord op basis van
        het onderzoeksdossier.
      </p>

      <form onSubmit={onSubmit} className="mt-3 flex flex-wrap gap-2">
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="stel je vraag hier…"
          className="min-w-[260px] flex-1 border border-ink bg-paper px-3 py-2 font-sans text-sm text-ink focus:outline-none"
        />
        <button
          type="submit"
          disabled={!query.trim()}
          className="inline-flex items-center gap-1.5 bg-ink px-4 py-2 font-mono text-xs uppercase tracking-wider text-paper hover:bg-ink/80 disabled:opacity-50"
        >
          {searching && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          Zoek →
        </button>
      </form>


      {searching && (
        <div className="mt-5 flex items-center gap-2 border border-ink/20 bg-paperLight p-4 font-mono text-xs uppercase tracking-wider text-ink/70">
          <Loader2 className="h-4 w-4 animate-spin" /> Bezig met antwoord schrijven…
        </div>
      )}

      {!searching && answer !== null && (
        <div
          className="mt-5 border border-ink/30 border-l-4 bg-paperLight p-5"
          style={{ borderLeftColor: "#FF2D87" }}
        >
          <div
            className="font-mono text-[11px] uppercase tracking-wider"
            style={{ color: "#FF2D87" }}
          >
            Antwoord op: "{submittedQuery}"
          </div>
          <p className="mt-1 font-sans text-sm text-ink/60">
            {sourcesUsed > 0
              ? `Gebaseerd op ${sourcesUsed} fragment${sourcesUsed === 1 ? "" : "en"} uit het onderzoeksdossier.`
              : "Geen fragmenten gebruikt."}
          </p>

          <div className="mt-4 max-w-[72ch] space-y-3 font-serif text-[15px] leading-[1.6] text-ink">
            {paragraphs.length > 0 ? (
              paragraphs.map((p, i) => <p key={i}>{p}</p>)
            ) : (
              <p className="italic text-ink/60">Geen antwoord ontvangen.</p>
            )}
          </div>

          <div className="mt-5 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={copyAnswer}
              className="inline-flex items-center gap-1.5 border border-ink bg-paper px-3 py-1.5 font-mono text-[11px] uppercase tracking-wider text-ink hover:bg-ink/5"
            >
              <Copy className="h-3.5 w-3.5" /> Kopieer antwoord
            </button>
            <button
              type="button"
              onClick={close}
              className="inline-flex items-center gap-1.5 border border-ink/30 bg-paper px-3 py-1.5 font-mono text-[11px] uppercase tracking-wider text-ink/70 hover:bg-ink/5"
            >
              <X className="h-3.5 w-3.5" /> Sluiten
            </button>
          </div>

          {mode === "admin" && fragments && fragments.length > 0 && (
            <div className="mt-5 border-t border-ink/20 pt-4">
              <button
                type="button"
                onClick={() => setShowFragments((s) => !s)}
                className="inline-flex items-center gap-1.5 font-mono text-[11px] uppercase tracking-wider text-ink/70 hover:text-ink"
              >
                {showFragments ? (
                  <ChevronDown className="h-3.5 w-3.5" />
                ) : (
                  <ChevronRight className="h-3.5 w-3.5" />
                )}
                Bekijk de {fragments.length} bron-fragment
                {fragments.length === 1 ? "" : "en"} waarop dit antwoord is gebaseerd
              </button>

              {showFragments && (
                <div className="mt-3 space-y-3">
                  {fragments.map((r, i) => {
                    const q = r.research_question_id
                      ? questionMap.get(r.research_question_id)
                      : null;
                    const pct = Math.round(r.similarity * 100);
                    const pctColor =
                      pct >= 70
                        ? "text-emerald-700"
                        : pct >= 50
                          ? "text-ink"
                          : "text-ink/40";
                    const ar = artifactMap.get(r.artifact_id);
                    return (
                      <div
                        key={r.chunk_id}
                        className="border border-ink/20 bg-paper p-3"
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div className="font-mono text-[10px] uppercase tracking-wider text-ink/70">
                            Fragment {i + 1} ·{" "}
                            {q
                              ? `V${q.index}. ${q.text.slice(0, 60)}${q.text.length > 60 ? "…" : ""}`
                              : "ALGEMEEN"}
                          </div>
                          <div className={cn("font-mono text-xs font-bold", pctColor)}>
                            {pct}%
                          </div>
                        </div>
                        <div className="mt-1 font-mono text-[10px] uppercase tracking-wider text-ink/50">
                          Bron: {r.filename} · {r.source}
                        </div>
                        <div className="mt-2 max-h-[200px] overflow-y-auto whitespace-pre-wrap border border-ink/10 bg-paperLight p-2 font-sans text-sm text-ink">
                          {r.chunk_text}
                        </div>
                        {ar && (
                          <div className="mt-2 flex justify-end">
                            <button
                              type="button"
                              onClick={() => openArtifact(ar)}
                              className="inline-flex items-center gap-1 border border-ink/30 bg-paper px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-ink hover:bg-ink/5"
                            >
                              <ExternalLink className="h-3 w-3" /> Open bron
                            </button>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
