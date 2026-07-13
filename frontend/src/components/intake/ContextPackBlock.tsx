import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Loader2, ChevronDown, ChevronRight, X, Copy } from "lucide-react";
import { jsPDF } from "jspdf";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { format } from "date-fns";
import { nl } from "date-fns/locale";
import { displayQuestionText, isAnchorQuestion } from "@/lib/research-question";
import * as skills from "@/lib/api/skills";
import { getContextPack, type ContextPackView } from "@/lib/api/contextPack";

type Pack = {
  id: string;
  output: string | null;
  cost_estimate_usd: number | null;
  completed_at: string | null;
  model: string | null;
};

// Map the backend `ContextPackView` (text_content/created_at, no cost/model) onto the
// UI `Pack` shape the modal/PDF/history consumers already key off. The markdown
// (`output`) is what renders; cost/model are cosmetic metadata already null-tolerant.
function toPack(v: ContextPackView): Pack {
  return {
    id: v.id,
    output: v.text_content,
    cost_estimate_usd: null,
    completed_at: v.created_at,
    model: null,
  };
}

type Props = {
  intakeId: string;
  intakeStatus: string | null;
  intakeTitle: string;
  clientName: string;
  // A one-shot terminal signal (e.g. `${status}:${runId}`) that changes when a
  // context-pack run terminates. The load effect re-reads the pack when it changes so a
  // re-generate on an already-`decomposed` intake (status unchanged) still refreshes.
  reloadSignal?: string | null;
};

const VISIBLE_STATUSES = new Set([
  "validated_by_client",
  "decomposed",
  "in_research",
  "delivered",
]);

function fmtDate(d: string | null) {
  if (!d) return "—";
  try {
    return format(new Date(d), "d MMM yyyy 'om' HH:mm", { locale: nl });
  } catch {
    return d;
  }
}

function downloadContextPackPDF(markdown: string, clientName: string, intakeTitle: string) {
  const doc = new jsPDF({ unit: "mm", format: "a4" });
  const margin = 20;
  const pageW = doc.internal.pageSize.getWidth();
  const pageH = doc.internal.pageSize.getHeight();
  const usableW = pageW - 2 * margin;
  let y = margin;

  function addPageIfNeeded(neededHeight: number) {
    if (y + neededHeight > pageH - margin - 8) {
      doc.addPage();
      y = margin;
    }
  }

  doc.setFont("helvetica", "normal");
  doc.setFontSize(8);
  doc.setTextColor(120);
  doc.text("AGENIC × NESTOR", margin, 12);
  doc.text("Context Pack — Intern werkdocument", pageW - margin, 12, { align: "right" });
  y = 24;

  doc.setFont("helvetica", "bold");
  doc.setFontSize(22);
  doc.setTextColor(0);
  doc.text(`Context Pack — ${clientName}`, margin, y);
  y += 10;

  doc.setFont("helvetica", "normal");
  doc.setFontSize(11);
  doc.setTextColor(80);
  doc.text(intakeTitle || "", margin, y);
  y += 6;
  doc.setFontSize(9);
  doc.setTextColor(140);
  doc.text(
    `Gegenereerd op ${new Date().toLocaleDateString("nl-BE", { day: "numeric", month: "long", year: "numeric" })}`,
    margin,
    y,
  );
  y += 10;

  doc.setDrawColor(0);
  doc.setLineWidth(0.2);
  doc.line(margin, y, pageW - margin, y);
  y += 8;

  const body = markdown.replace(/^#\s+Context Pack[^\n]*\n+/i, "");
  const lines = body.split("\n");

  for (const rawLine of lines) {
    const line = rawLine.trimEnd();
    if (line === "") {
      y += 3;
      continue;
    }

    if (line.startsWith("## ")) {
      const text = line.replace(/^##\s+/, "");
      addPageIfNeeded(14);
      y += 4;
      doc.setFont("helvetica", "bold");
      doc.setFontSize(14);
      doc.setTextColor(0);
      doc.text(text, margin, y);
      y += 7;
      doc.setDrawColor(200);
      doc.line(margin, y - 2, pageW - margin, y - 2);
      continue;
    }

    if (line.startsWith("### ")) {
      const text = line.replace(/^###\s+/, "");
      addPageIfNeeded(10);
      y += 2;
      doc.setFont("helvetica", "bold");
      doc.setFontSize(11);
      doc.setTextColor(0);
      doc.text(text, margin, y);
      y += 6;
      continue;
    }

    if (line.startsWith("> ")) {
      const text = line.replace(/^>\s+/, "");
      const wrapped = doc.splitTextToSize(text, usableW - 6) as string[];
      doc.setFont("helvetica", "italic");
      doc.setFontSize(9);
      doc.setTextColor(100);
      for (const w of wrapped) {
        addPageIfNeeded(5);
        doc.text(w, margin + 4, y);
        y += 5;
      }
      y += 1;
      continue;
    }

    if (/^[-*]\s+/.test(line)) {
      const text = line.replace(/^[-*]\s+/, "").replace(/\*\*/g, "");
      const wrapped = doc.splitTextToSize(text, usableW - 6) as string[];
      doc.setFont("helvetica", "normal");
      doc.setFontSize(10);
      doc.setTextColor(0);
      for (let i = 0; i < wrapped.length; i++) {
        addPageIfNeeded(5);
        const prefix = i === 0 ? "•  " : "   ";
        doc.text(prefix + wrapped[i], margin + 2, y);
        y += 5;
      }
      continue;
    }

    const cleanLine = line.replace(/\*\*/g, "");
    const wrapped = doc.splitTextToSize(cleanLine, usableW) as string[];
    doc.setFont("helvetica", "normal");
    doc.setFontSize(10);
    doc.setTextColor(20);
    for (const w of wrapped) {
      addPageIfNeeded(5);
      doc.text(w, margin, y);
      y += 5;
    }
    y += 1;
  }

  const pageCount = doc.getNumberOfPages();
  for (let i = 1; i <= pageCount; i++) {
    doc.setPage(i);
    doc.setFontSize(7);
    doc.setTextColor(150);
    doc.text(`pagina ${i} / ${pageCount}`, pageW - margin, pageH - 8, { align: "right" });
    doc.text("AGENIC × NESTOR — Context Pack — confidentieel", margin, pageH - 8);
  }

  const slug = `context-pack-${clientName}-${new Date().toISOString().slice(0, 10)}`
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
  doc.save(`${slug}.pdf`);
}

export function ContextPackBlock({
  intakeId,
  intakeStatus,
  intakeTitle,
  clientName,
  reloadSignal,
}: Props) {
  const [latestPack, setLatestPack] = useState<Pack | null>(null);
  const [loadingPack, setLoadingPack] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [viewingPack, setViewingPack] = useState<Pack | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [history, setHistory] = useState<Pack[] | null>(null);
  const [questions, setQuestions] = useState<
    Array<{ id: string; priority: number | null; question_type: string | null; question_text: string }>
  >([]);
  const [questionsOpen, setQuestionsOpen] = useState(true);

  const loadLatest = useCallback(async () => {
    // Read the generated pack from the 07-09 backend surface
    // (`GET /intakes/{id}/context-pack`). Existence-hidden empty read → `latest: null`.
    setLoadingPack(true);
    const res = await getContextPack(intakeId);
    if (!res.success) {
      setLatestPack(null);
      setError(res.error);
      setLoadingPack(false);
      return;
    }
    setLatestPack(res.data.latest ? toPack(res.data.latest) : null);
    setLoadingPack(false);
  }, [intakeId]);

  const loadHistory = useCallback(async () => {
    // History comes from the same 07-09 read surface (`{ latest, history }`).
    const res = await getContextPack(intakeId);
    if (!res.success) {
      setHistory([]);
      return;
    }
    setHistory(res.data.history.map(toPack));
  }, [intakeId]);

  useEffect(() => {
    if (!VISIBLE_STATUSES.has(intakeStatus ?? "")) return;
    loadLatest();
    // A terminal context-pack run bumps `reloadSignal`; re-reading here refreshes the pack
    // even when the status was already `decomposed` (a re-generate). The history is also
    // re-fetched when it's already been opened, so it stays in sync.
    if (history !== null) loadHistory();
    // research_questions are written post-`decomposed` (Bucket E) and never render in
    // this milestone, so there is no read here.
    setQuestions([]);
    // history is intentionally omitted from deps: it must not re-trigger on its own state
    // change (that would loop). loadHistory is stable (useCallback on intakeId).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intakeStatus, loadLatest, loadHistory, intakeId, reloadSignal]);

  const toggleHistory = () => {
    const next = !historyOpen;
    setHistoryOpen(next);
    if (next && history === null) loadHistory();
  };

  async function generateContextPack() {
    // Dispatch the Phase-7 context-pack run. NOTE: the pack DISPLAY (loadLatest /
    // loadHistory above) still has no backend read surface — the run succeeds and the
    // intake advances to `decomposed`, but the markdown render stays empty until an
    // artifacts-read endpoint exists (logged as an integration gap, 2026-07-13 UAT).
    setGenerating(true);
    try {
      const res = await skills.generateContextPack(intakeId);
      if (!res.success) {
        toast.error(`Context Pack starten mislukt: ${res.error}`);
        return;
      }
      toast.success("Context Pack-generatie gestart — dit duurt ± 1–2 minuten.");
    } finally {
      setGenerating(false);
    }
  }

  if (!VISIBLE_STATUSES.has(intakeStatus ?? "")) return null;

  const wrapperCls =
    "mb-6 border border-ink/30 border-l-4 bg-paperLight px-6 py-5";
  const primaryBtnCls =
    "inline-flex items-center gap-2 bg-ink px-4 py-2 font-mono text-xs uppercase tracking-wider text-paper hover:bg-ink/85 disabled:opacity-60";
  const secondaryBtnCls =
    "inline-flex items-center gap-2 border border-ink bg-transparent px-4 py-2 font-mono text-xs uppercase tracking-wider text-ink hover:border-2 disabled:opacity-60";

  const isDone = !!latestPack;
  const accentColor = isDone ? "#DFF940" : "#FF2D87";
  const labelColor = isDone ? undefined : "#FF2D87";

  return (
    <>
      <div className={wrapperCls} style={{ borderLeftColor: accentColor }}>
        <div
          className={`mb-2 font-mono text-[11px] uppercase tracking-wider ${isDone ? "text-ink/60" : ""}`}
          style={labelColor ? { color: labelColor } : undefined}
        >
          Context Pack
        </div>

        <div className="mb-4 font-sans text-[15px] leading-relaxed text-ink">
          Briefingdocument voor Nestor — destillaat van de gevalideerde intake in 11 secties
          (klant, beslissing, ankers, scope, concurrenten, hypotheses, …).
        </div>
        <div className="flex flex-wrap gap-2">
          {latestPack ? (
            <>
              <button
                type="button"
                className={secondaryBtnCls}
                onClick={() => setViewingPack(latestPack)}
                disabled={generating}
              >
                Bekijk laatste
              </button>
              <button
                type="button"
                className={secondaryBtnCls}
                onClick={() =>
                  latestPack.output &&
                  downloadContextPackPDF(latestPack.output, clientName, intakeTitle)
                }
                disabled={generating || !latestPack.output}
              >
                Download PDF
              </button>
              <button
                type="button"
                className={secondaryBtnCls}
                onClick={generateContextPack}
                disabled={generating || loadingPack}
                title="Pack opnieuw genereren — admin escape-hatch"
              >
                {generating ? (
                  <>
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    Bezig…
                  </>
                ) : (
                  "↻ Genereer opnieuw"
                )}
              </button>
            </>
          ) : (
            <p className="font-sans text-xs italic text-ink/50">
              Nog geen Context Pack — gebruik de actie in het Volgende-stap-blok hierboven.
            </p>
          )}
        </div>
        {latestPack && (
          <div className="mt-3 font-mono text-[11px] uppercase tracking-wide text-ink/40">
            Laatst gegenereerd: {fmtDate(latestPack.completed_at)}
            {latestPack.cost_estimate_usd != null && ` · €${latestPack.cost_estimate_usd}`}
            {latestPack.model && ` · ${latestPack.model}`}
          </div>
        )}
        {error && <div className="mt-3 text-xs text-red-600">{error}</div>}

        {questions.length > 0 && (
          <div className="mt-5 border-t border-ink/15 pt-4">
            <div className="flex items-center justify-between gap-2">
              <button
                type="button"
                onClick={() => setQuestionsOpen((v) => !v)}
                className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-wider text-ink/70 hover:text-ink"
              >
                {questionsOpen ? (
                  <ChevronDown className="h-3.5 w-3.5" />
                ) : (
                  <ChevronRight className="h-3.5 w-3.5" />
                )}
                Onderzoeksvragen ({questions.length})
              </button>
              <button
                type="button"
                onClick={() => {
                  const header = `Onderzoeksvragen — ${intakeTitle}`;
                  const body = questions
                    .map((q, i) => `V${i + 1} — ${displayQuestionText(q)}`)
                    .join("\n\n");
                  navigator.clipboard
                    .writeText(`${header}\n\n${body}`)
                    .then(() =>
                      toast.success(`${questions.length} vragen gekopieerd naar klembord`),
                    )
                    .catch(() => toast.error("Kopiëren mislukt"));
                }}
                className={secondaryBtnCls}
              >
                <Copy className="h-3.5 w-3.5" />
                Kopieer alle
              </button>
            </div>

            {questionsOpen && (
              <ul className="mt-3 divide-y divide-ink/10 border border-ink/10 bg-paper">
                {questions.map((q, i) => {
                  const label = `V${i + 1}`;
                  const anchor = isAnchorQuestion(q);
                  const text = displayQuestionText(q);
                  return (
                    <li key={q.id} className="flex items-start gap-3 px-4 py-3">
                      <div className="flex-1">
                        <div className="flex flex-wrap items-center gap-2 font-mono text-[11px] uppercase tracking-wider text-ink/50">
                          {anchor && (
                            <span className="inline-flex items-center border border-ink bg-agenic-yellow px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-ink">
                              Ankervraag
                            </span>
                          )}
                          <span>
                            {label}
                            {q.question_type ? ` · ${q.question_type}` : ""}
                          </span>
                        </div>
                        <div className="mt-1 font-sans text-sm text-ink">{text}</div>
                      </div>
                      <button
                        type="button"
                        onClick={() => {
                          navigator.clipboard
                            .writeText(`${label} — ${text}`)
                            .then(() => toast.success(`Vraag ${label} gekopieerd`))
                            .catch(() => toast.error("Kopiëren mislukt"));
                        }}
                        className="shrink-0 border border-ink/20 p-1.5 text-ink/60 hover:bg-ink/5 hover:text-ink"
                        title={`Kopieer ${label}`}
                        aria-label={`Kopieer ${label}`}
                      >
                        <Copy className="h-3.5 w-3.5" />
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        )}
      </div>

      {latestPack && (
        <section className="mb-6 border border-ink/10 bg-paper">
          <button
            type="button"
            onClick={toggleHistory}
            className="flex w-full items-center justify-between px-6 py-3 text-left text-sm font-medium text-ink/70 hover:bg-ink/5"
          >
            <span className="flex items-center gap-2">
              {historyOpen ? (
                <ChevronDown className="h-4 w-4" />
              ) : (
                <ChevronRight className="h-4 w-4" />
              )}
              Eerdere context pack runs
              {history && <span className="text-xs text-ink/60">({history.length})</span>}
            </span>
          </button>
          {historyOpen && (
            <div className="border-t border-ink/5 px-6 py-3">
              {history === null ? (
                <p className="text-sm text-ink/60">Laden…</p>
              ) : history.length === 0 ? (
                <p className="text-sm text-ink/60">Geen runs.</p>
              ) : (
                <ul className="divide-y divide-ink/5">
                  {history.map((r) => (
                    <li
                      key={r.id}
                      className="flex flex-wrap items-center gap-2 py-2 text-sm"
                    >
                      <span>✓</span>
                      <span className="text-ink/70">{fmtDate(r.completed_at)}</span>
                      {r.cost_estimate_usd != null && (
                        <span className="text-ink/60">· €{r.cost_estimate_usd}</span>
                      )}
                      {r.model && <span className="text-ink/60">· {r.model}</span>}
                      <span className="ml-auto flex gap-2">
                        <button
                          type="button"
                          onClick={() => setViewingPack(r)}
                          className="border border-ink/20 px-2 py-1 font-mono text-[11px] uppercase tracking-wider text-ink hover:bg-ink/5"
                        >
                          Bekijk
                        </button>
                        <button
                          type="button"
                          onClick={() =>
                            r.output && downloadContextPackPDF(r.output, clientName, intakeTitle)
                          }
                          disabled={!r.output}
                          className="border border-ink/20 px-2 py-1 font-mono text-[11px] uppercase tracking-wider text-ink hover:bg-ink/5 disabled:opacity-40"
                        >
                          Download PDF
                        </button>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </section>
      )}

      {viewingPack && (
        <div
          className="fixed inset-0 z-50 flex items-start justify-center bg-ink/50 p-4 overflow-y-auto"
          onClick={() => setViewingPack(null)}
        >
          <div
            className="my-8 w-full max-w-4xl border-2 border-ink bg-paper"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between border-b border-ink/20 px-6 py-4">
              <div>
                <div
                  className="font-mono text-[11px] uppercase tracking-wider"
                  style={{ color: "#FF2D87" }}
                >
                  Context Pack
                </div>
                <h2 className="mt-1 font-serif text-2xl text-ink">Briefing voor Nestor</h2>
                <p className="mt-1 font-mono text-[11px] uppercase tracking-wide text-ink/40">
                  {fmtDate(viewingPack.completed_at)}
                  {viewingPack.cost_estimate_usd != null &&
                    ` · €${viewingPack.cost_estimate_usd}`}
                  {viewingPack.model && ` · ${viewingPack.model}`}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setViewingPack(null)}
                className="p-1 text-ink/60 hover:text-ink"
                aria-label="Sluiten"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="prose prose-sm max-w-none px-6 py-6 prose-headings:font-serif prose-headings:text-ink prose-p:text-ink prose-li:text-ink prose-strong:text-ink">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {viewingPack.output ?? ""}
              </ReactMarkdown>
            </div>

            <div className="flex flex-wrap justify-end gap-2 border-t border-ink/20 px-6 py-4">
              <button
                type="button"
                onClick={() => {
                  if (!viewingPack.output) return;
                  navigator.clipboard
                    .writeText(viewingPack.output)
                    .then(() => toast.success("Markdown gekopieerd"))
                    .catch(() => toast.error("Kopiëren mislukt"));
                }}
                className={secondaryBtnCls}
              >
                Kopieer markdown
              </button>
              <button
                type="button"
                onClick={() =>
                  viewingPack.output &&
                  downloadContextPackPDF(viewingPack.output, clientName, intakeTitle)
                }
                className={primaryBtnCls}
              >
                Download PDF
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
