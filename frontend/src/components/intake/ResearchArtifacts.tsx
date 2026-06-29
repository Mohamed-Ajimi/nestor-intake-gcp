import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { format } from "date-fns";
import { nl } from "date-fns/locale";
import { toast } from "sonner";
import { Loader2, Upload, FileText, Download, X, StickyNote } from "lucide-react";
import * as storage from "@/lib/api/storage";
import { derivePhase, phaseShowsResearch } from "@/lib/intake-phase";
import { displayQuestionText, isAnchorQuestion } from "@/lib/research-question";

const BUCKET = "nestor-uploads";

const SOURCES = [
  { value: "claude", label: "Claude" },
  { value: "gemini", label: "Gemini" },
  { value: "openai", label: "OpenAI" },
  { value: "serp_api", label: "SerpAPI" },
  { value: "search_api", label: "SearchAPI" },
  { value: "manual", label: "Manueel" },
  { value: "other", label: "Andere" },
];

const TYPES = [
  { value: "deliverable", label: "KLANT-RAPPORT (deliverable)" },
  { value: "deep_research", label: "Deep research" },
  { value: "search_result", label: "Search result" },
  { value: "synthesis", label: "Synthese" },
  { value: "note", label: "Notitie" },
  { value: "transcript", label: "Transcript" },
  { value: "data", label: "Data" },
  { value: "other", label: "Andere" },
];

type ResearchQuestion = {
  id: string;
  question_text: string;
  question_type: string | null;
  priority: number | null;
  rationale: string | null;
  status: string | null;
  client_answer_artifact_id?: string | null;
};

type Artifact = {
  id: string;
  research_question_id: string | null;
  source: string;
  artifact_type: string;
  filename: string;
  storage_path: string | null;
  byte_size: number | null;
  mime_type: string | null;
  created_at: string;
  embed_status: string | null;
  notes: string | null;
};

const RESEARCH_STATUSES = ["validated_by_client", "decomposed", "in_research", "delivered"];

export function ResearchArtifactsBlock({
  intakeId,
  intakeStatus,
  onStartResearch,
}: {
  intakeId: string;
  intakeStatus: string | null;
  onStartResearch?: () => Promise<void> | void;
}) {
  // Phase-gate: this block is post-decomposed UI (research phase only). The
  // re-platform flow stops at `decomposed`, so phaseShowsResearch() is
  // effectively false this milestone and the block never renders (scope ceiling).
  const phase = derivePhase(
    {
      status: intakeStatus,
      validation_link_sent_at: null,
      results_link_sent_at: null,
      context_pack_artifact_id: null,
      final_report_artifact_id: null,
    },
    null,
    false,
  );
  if (!phaseShowsResearch(phase)) return null;
  // onStartResearch prop is no longer used by this block (banner handles it).
  void onStartResearch;

  return <ResearchArtifactsInner intakeId={intakeId} intakeStatus={intakeStatus!} />;
}

// RunResearchPanel removed — research start/progress lives in NextStepBanner.


function ResearchArtifactsInner({
  intakeId,
  intakeStatus,
}: {
  intakeId: string;
  intakeStatus: string;
}) {
  const [questions, setQuestions] = useState<ResearchQuestion[]>([]);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    // Post-decomposed research data is out of scope this milestone (research
    // backend lands Phase 7+). The block is gated off, so render inert with
    // no data rather than fetching.
    void intakeId;
    setQuestions([]);
    setArtifacts([]);
    setLoading(false);
  }, [intakeId]);

  useEffect(() => {
    reload();
  }, [reload]);

  const visibleQuestions = useMemo(
    () => (questions || []).filter((q) => q.question_text && q.question_text.trim().length > 0),
    [questions],
  );

  const grouped = useMemo(() => {
    const m = new Map<string, Artifact[]>();
    visibleQuestions.forEach((q) => m.set(q.id, []));
    artifacts.forEach((a) => {
      if (!a.research_question_id) return;
      if (!m.has(a.research_question_id)) m.set(a.research_question_id, []);
      m.get(a.research_question_id)!.push(a);
    });
    return m;
  }, [artifacts, visibleQuestions]);

  const generalArtifacts = useMemo(
    () => artifacts.filter((a) => !a.research_question_id),
    [artifacts],
  );

  return (
    <div>


      <section className="border border-ink bg-paperLight p-6">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-mono text-xs uppercase tracking-wider text-ink">Research artifacts</h2>
          {loading && <Loader2 className="h-4 w-4 animate-spin text-ink/40" />}
        </div>

        <div className="space-y-6">
          {visibleQuestions.length === 0 && !loading && (
            <p className="border border-ink/30 bg-paper p-3 font-sans text-sm text-ink/60">
              Nog geen onderzoeksvragen — die verschijnen zodra de intake is gedecomposeerd.
            </p>
          )}

          {visibleQuestions.map((q, i) => (
            <div key={q.id} className={i === 0 ? "" : "border-t border-ink/20 pt-6"}>
              <QuestionBlock
                intakeId={intakeId}
                question={q}
                index={i + 1}
                artifacts={grouped.get(q.id) ?? []}
                onChanged={reload}
              />
            </div>
          ))}

          {generalArtifacts.length > 0 || visibleQuestions.length > 0 ? (
            <div className="mt-6 border-t-2 border-ink/20 pt-6">
              <div className="mb-2">
                <span className="font-mono text-xs uppercase tracking-wider text-ink/60">
                  Algemeen
                </span>
                <p className="mt-1 max-w-3xl text-sm text-ink/60">
                  Research die niet aan één specifieke vraag hoort — API-zoekresultaten,
                  brede marktrapporten, geo-data, bronnen die over meerdere vragen heen
                  relevant zijn.
                </p>
              </div>
              <QuestionBlock
                intakeId={intakeId}
                question={null}
                artifacts={generalArtifacts}
                onChanged={reload}
              />
            </div>
          ) : null}
        </div>
      </section>
    </div>
  );
}

function QuestionBlock({
  intakeId,
  question,
  index,
  artifacts,
  onChanged,
}: {
  intakeId: string;
  question: ResearchQuestion | null;
  index?: number;
  artifacts: Artifact[];
  onChanged: () => void | Promise<void>;
}) {
  const [noteOpen, setNoteOpen] = useState(false);
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  const displayText = question ? displayQuestionText(question) : "";
  const anchor = question ? isAnchorQuestion(question) : false;
  const label = question
    ? `V${index}. ${displayText}`
    : "Algemeen (niet per vraag)";

  const onPick = (files: FileList | null) => {
    if (!files || !files.length) return;
    setPendingFiles(Array.from(files));
  };

  return (
    <div>
      <div className="mb-2 font-sans text-sm text-ink">
        <span className="inline-flex items-center gap-2 font-mono text-xs uppercase tracking-wider text-ink/60">
          {anchor && (
            <span className="inline-flex items-center border border-ink bg-agenic-yellow px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-ink">
              Ankervraag
            </span>
          )}
          {question ? `V${index}` : "Algemeen"}
        </span>
        {question && <p className="mt-1 font-sans text-ink">{displayText}</p>}
        {!question && <p className="mt-1 text-ink/60">Voor intake-brede uploads.</p>}
      </div>

      {question && (
        <ResearchArtifactsPerSource
          intakeId={intakeId}
          questionPriority={question.priority ?? index ?? 0}
          artifacts={artifacts}
        />
      )}







      <div
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          onPick(e.dataTransfer.files);
        }}
        className="border border-dashed border-ink/40 bg-paper p-3"
      >
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            className="inline-flex items-center gap-1.5 border border-ink bg-paper px-2.5 py-1 font-mono text-xs uppercase tracking-wider text-ink hover:bg-ink/5"
          >
            <Upload className="h-3.5 w-3.5" /> Upload bestanden
          </button>
          <button
            type="button"
            onClick={() => setNoteOpen(true)}
            className="inline-flex items-center gap-1.5 border border-ink bg-paper px-2.5 py-1 font-mono text-xs uppercase tracking-wider text-ink hover:bg-ink/5"
          >
            <StickyNote className="h-3.5 w-3.5" /> Manuele notitie
          </button>
          <span className="font-mono text-[10px] uppercase tracking-wider text-ink/40">
            of sleep & drop hier
          </span>
        </div>
        <input
          ref={inputRef}
          type="file"
          multiple
          className="hidden"
          onChange={(e) => onPick(e.target.files)}
        />
      </div>

      {pendingFiles.length > 0 && (
        <PendingUploadForm
          intakeId={intakeId}
          questionId={question?.id ?? null}
          files={pendingFiles}
          onClose={() => setPendingFiles([])}
          onDone={async () => {
            setPendingFiles([]);
            await onChanged();
          }}
        />
      )}

      {noteOpen && (
        <NoteModal
          intakeId={intakeId}
          questionId={question?.id ?? null}
          onClose={() => setNoteOpen(false)}
          onDone={async () => {
            setNoteOpen(false);
            await onChanged();
          }}
        />
      )}

      {(() => {
        const AUTO_GENERATED_SOURCES = ["serpapi", "searchapi", "apify-crawler", "apify-maps-reviews", "apify-rag-web-browser", "apify-website-content-crawler", "serp_api", "search_api"];
        const uploadedArtifacts = artifacts.filter((a) => !AUTO_GENERATED_SOURCES.includes(a.source));
        if (uploadedArtifacts.length === 0) return null;
        return (
          <ul className="mt-3 divide-y divide-ink/10 border border-ink/20 bg-paper">
            {uploadedArtifacts.map((a) => (
              <ArtifactRow
                key={a.id}
                artifact={a}
                isClientChoice={question?.client_answer_artifact_id === a.id}
                onDeleted={onChanged}
              />
            ))}
          </ul>
        );
      })()}
    </div>
  );
}





function PendingUploadForm({
  intakeId,
  questionId,
  files,
  onClose,
  onDone,
}: {
  intakeId: string;
  questionId: string | null;
  files: File[];
  onClose: () => void;
  onDone: () => Promise<void>;
}) {
  const [source, setSource] = useState("manual");
  const [otherSource, setOtherSource] = useState("");
  const [type, setType] = useState("deep_research");
  const [busy, setBusy] = useState(false);

  const upload = async () => {
    setBusy(true);
    // Artifact metadata (source/type) is persisted by the research backend
    // (Phase 7+), which is out of scope here. Files route through the storage
    // seam only; the DB-indexing insert is intentionally not wired this milestone.
    const finalSource = source === "other" && otherSource.trim() ? otherSource.trim() : source;
    void finalSource;
    void type;
    try {
      for (const file of files) {
        const path = `intakes/${intakeId}/research/${questionId ?? "general"}/${crypto.randomUUID()}-${file.name}`;
        const res = await storage.uploadFile({
          intakeId,
          bucket: BUCKET,
          path,
          file,
          filename: file.name,
          contentType: file.type || undefined,
        });
        if (!res.success) throw new Error(res.error);
        toast.success(`${file.name} geüpload.`);
      }
      await onDone();
    } catch (e) {
      toast.error(`Upload mislukt: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-2 border border-ink bg-paper p-3">
      <div className="mb-2 font-mono text-xs uppercase tracking-wider text-ink">
        {files.length} bestand{files.length > 1 ? "en" : ""} klaar
      </div>
      <ul className="mb-3 space-y-0.5 font-sans text-sm text-ink/70">
        {files.map((f) => (
          <li key={f.name}>📄 {f.name} <span className="text-ink/40">({Math.round(f.size / 1024)} KB)</span></li>
        ))}
      </ul>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block">
          <span className="font-mono text-[10px] uppercase tracking-wider text-ink/60">Bron</span>
          <select
            value={source}
            onChange={(e) => setSource(e.target.value)}
            className="mt-1 block w-full border border-ink bg-paper px-2 py-1 text-sm text-ink"
          >
            {SOURCES.map((s) => (
              <option key={s.value} value={s.value}>{s.label}</option>
            ))}
          </select>
          {source === "other" && (
            <input
              type="text"
              placeholder="Bron (vrije tekst)"
              value={otherSource}
              onChange={(e) => setOtherSource(e.target.value)}
              className="mt-1 block w-full border border-ink bg-paper px-2 py-1 text-sm text-ink"
            />
          )}
        </label>
        <label className="block">
          <span className="font-mono text-[10px] uppercase tracking-wider text-ink/60">Type</span>
          <select
            value={type}
            onChange={(e) => setType(e.target.value)}
            className="mt-1 block w-full border border-ink bg-paper px-2 py-1 text-sm text-ink"
          >
            {TYPES.map((t) => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </select>
        </label>
      </div>
      <div className="mt-3 flex justify-end gap-2">
        <button
          type="button"
          onClick={onClose}
          disabled={busy}
          className="border border-ink bg-paper px-3 py-1 font-mono text-xs uppercase tracking-wider text-ink hover:bg-ink/5"
        >
          Annuleren
        </button>
        <button
          type="button"
          onClick={upload}
          disabled={busy}
          className="inline-flex items-center gap-1.5 bg-ink px-3 py-1 font-mono text-xs uppercase tracking-wider text-paper hover:bg-ink/80 disabled:opacity-50"
        >
          {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          Uploaden
        </button>
      </div>
    </div>
  );
}

function NoteModal({
  intakeId,
  questionId,
  onClose,
  onDone,
}: {
  intakeId: string;
  questionId: string | null;
  onClose: () => void;
  onDone: () => Promise<void>;
}) {
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);

  const save = async () => {
    if (!text.trim()) {
      toast.error("Schrijf een notitie");
      return;
    }
    setBusy(true);
    try {
      const ts = Date.now();
      const filename = (title.trim() ? title.trim().replace(/[^\w-]+/g, "_") : `note-${ts}`) + ".txt";
      const path = `intakes/${intakeId}/research/${questionId ?? "general"}/${crypto.randomUUID()}-${filename}`;
      const blob = new Blob([text], { type: "text/plain" });
      // Note content routes through the storage seam; the research-artifact
      // DB record + embedding belong to the research backend (Phase 7+).
      const res = await storage.uploadFile({
        intakeId,
        bucket: BUCKET,
        path,
        file: blob,
        filename,
        contentType: "text/plain",
      });
      if (!res.success) throw new Error(res.error);
      toast.success("Notitie opgeslagen");
      await onDone();
    } catch (e) {
      toast.error(`Opslaan mislukt: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4">
      <div className="w-full max-w-xl border border-ink bg-paper p-6">
        <h3 className="font-serif text-xl lowercase">Manuele notitie</h3>
        <label className="mt-4 block">
          <span className="font-mono text-[10px] uppercase tracking-wider text-ink/60">Titel</span>
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Optioneel"
            className="mt-1 block w-full border border-ink bg-paper px-2 py-1 text-sm text-ink"
          />
        </label>
        <label className="mt-3 block">
          <span className="font-mono text-[10px] uppercase tracking-wider text-ink/60">Tekst</span>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={10}
            className="mt-1 block w-full border border-ink bg-paper px-2 py-1 font-sans text-sm text-ink"
          />
        </label>
        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="border border-ink bg-paper px-3 py-1 font-mono text-xs uppercase tracking-wider text-ink hover:bg-ink/5"
          >
            Annuleren
          </button>
          <button
            type="button"
            onClick={save}
            disabled={busy}
            className="inline-flex items-center gap-1.5 bg-ink px-3 py-1 font-mono text-xs uppercase tracking-wider text-paper hover:bg-ink/80 disabled:opacity-50"
          >
            {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
            Opslaan
          </button>
        </div>
      </div>
    </div>
  );
}

function ArtifactRow({ artifact, isClientChoice, onDeleted }: { artifact: Artifact; isClientChoice?: boolean; onDeleted: () => void | Promise<void> }) {
  const [busy, setBusy] = useState(false);

  const open = async () => {
    if (!artifact.storage_path) return;
    const res = await storage.signedDownloadUrl({
      bucket: BUCKET,
      path: artifact.storage_path,
      expiresIn: 300,
    });
    if (!res.success) {
      toast.error("Kon link niet maken");
      return;
    }
    window.open(res.data.url, "_blank");
  };

  const remove = async () => {
    if (!confirm(`Verwijder ${artifact.filename}?`)) return;
    setBusy(true);
    try {
      // The research-artifact DB record is owned by the research backend
      // (Phase 7+); here we only remove the stored object via the seam.
      if (artifact.storage_path) {
        const res = await storage.removeFile({ bucket: BUCKET, paths: [artifact.storage_path] });
        if (!res.success) throw new Error(res.error);
      }
      toast.success("Verwijderd");
      await onDeleted();
    } catch (e) {
      toast.error(`Verwijderen mislukt: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  const sizeLabel = artifact.byte_size != null
    ? artifact.byte_size > 1024
      ? `${Math.round(artifact.byte_size / 1024)} KB`
      : `${artifact.byte_size} B`
    : "";

  const date = (() => {
    try {
      return format(new Date(artifact.created_at), "d MMM HH:mm", { locale: nl });
    } catch {
      return artifact.created_at;
    }
  })();

  const status = artifact.embed_status;

  return (
    <li className="flex flex-wrap items-center gap-2 px-3 py-2 text-sm">
      <FileText className="h-4 w-4 text-ink/60" />
      <span className="font-sans text-ink">{artifact.filename}</span>
      <span className="font-mono text-[10px] uppercase tracking-wider text-ink/60">
        · {artifact.source}
      </span>
      <span className="font-mono text-[10px] uppercase tracking-wider text-ink/40">
        · {artifact.artifact_type}
      </span>
      <span className="text-xs text-ink/60">· {date}</span>
      {sizeLabel && <span className="text-xs text-ink/40">· {sizeLabel}</span>}
      {isClientChoice && (
        <span
          className="inline-flex items-center gap-1 border px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider"
          style={{ color: "#FF2D87", borderColor: "#FF2D87" }}
        >
          ✓ Klant-versie
        </span>
      )}
      {status === "pending" && (
        <span className="inline-flex items-center gap-1 font-mono text-[10px] uppercase tracking-wider text-ink/60">
          <Loader2 className="h-3 w-3 animate-spin" /> Indexeren…
        </span>
      )}
      {status === "embedded" && (
        <span className="font-mono text-[10px] uppercase tracking-wider text-ink">Geïndexeerd</span>
      )}
      {status === "failed" && (
        <span className="font-mono text-[10px] uppercase tracking-wider text-ink/40">Indexering mislukt</span>
      )}
      <span className="ml-auto flex items-center gap-1">
        {artifact.storage_path && (
          <button
            type="button"
            onClick={open}
            className="inline-flex items-center gap-1 border border-ink/30 bg-paper px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-ink hover:bg-ink/5"
          >
            <Download className="h-3 w-3" /> Open
          </button>
        )}
        <button
          type="button"
          onClick={remove}
          disabled={busy}
          className="inline-flex items-center gap-1 border border-ink/30 bg-paper px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-ink hover:bg-ink/5 disabled:opacity-50"
        >
          <X className="h-3 w-3" /> Verwijder
        </button>
      </span>
    </li>
  );
}

/* -------------------- Per-source artifact cards (downloadable .md) -------------------- */

const SOURCE_LABELS: Record<string, { label: string; color: string }> = {
  serpapi: { label: "SerpAPI · Google", color: "text-ink/60" },
  searchapi: { label: "SearchAPI · Google", color: "text-ink/60" },
  "apify-crawler": { label: "Apify · Website crawl", color: "text-ink/60" },
  "apify-maps-reviews": { label: "Apify · Maps reviews", color: "text-ink/60" },
  "apify-rag-web-browser": { label: "Apify · RAG web browser", color: "text-ink/60" },
  "apify-website-content-crawler": { label: "Apify · Website content crawler", color: "text-ink/60" },
  serp_api: { label: "SerpAPI · Google", color: "text-ink/60" },
  search_api: { label: "SearchAPI · Google", color: "text-ink/60" },
};


function ResearchArtifactsPerSource({
  intakeId,
  questionPriority,
  artifacts,
}: {
  intakeId: string;
  questionPriority: number;
  artifacts: Artifact[];
}) {
  const autoArtifacts = useMemo(
    () =>
      [...artifacts]
        .filter((a) => SOURCE_LABELS[a.source] !== undefined)
        .sort((a, b) => a.source.localeCompare(b.source)),
    [artifacts],
  );

  if (autoArtifacts.length === 0) {
    return (
      <div className="mt-4 mb-4">
        <div className="mb-2 font-mono text-[10px] uppercase tracking-wider text-ink/60">
          Research artifacts
        </div>
        <p className="mb-3 text-xs italic text-ink/40">
          Nog geen automatische artifacts. Start de research via de knop bovenaan.
        </p>
      </div>
    );
  }

  return (
    <div className="mt-4 mb-4">
      <div className="mb-3 font-mono text-[10px] uppercase tracking-wider text-ink/60">
        Research artifacts ({autoArtifacts.length})
      </div>
      <div className="space-y-2">
        {autoArtifacts.map((a) => (
          <PerSourceRow
            key={a.id}
            artifact={a}
            intakeId={intakeId}
            questionPriority={questionPriority}
          />
        ))}
      </div>
    </div>
  );
}

function PerSourceRow({
  artifact,
  intakeId,
  questionPriority,
}: {
  artifact: Artifact;
  intakeId: string;
  questionPriority: number;
}) {
  const [text, setText] = useState<string | null>(null);
  const [loadingText, setLoadingText] = useState(false);
  const [showPreview, setShowPreview] = useState(false);
  const meta = SOURCE_LABELS[artifact.source] ?? {
    label: artifact.source,
    color: "text-ink/60",
  };

  const queryLabel = (artifact.filename || "").replace(/\.json$/, "").replace(/\.md$/, "");
  const displayName = `q${questionPriority}-${queryLabel}.md`;

  const ensureText = useCallback(async (): Promise<string | null> => {
    if (text !== null) return text;
    // Artifact text content is served by the research backend (Phase 7+);
    // not available this milestone, so previews/downloads have no body.
    void artifact.id;
    void setLoadingText;
    return null;
  }, [artifact.id, text]);

  const resultsMatch = (text || "").match(/Results?:\s*(\d+)/i);
  const resultsCount = resultsMatch ? parseInt(resultsMatch[1]) : 0;
  const hasError = (text || "").includes("**ERROR**");
  const queryMatch = (text || "").match(/Query:\s*`(.+?)`/);
  const queryText = queryMatch ? queryMatch[1].slice(0, 80) : "";

  const downloadAsMarkdown = async () => {
    const content = (await ensureText()) || "(geen content)";
    const blob = new Blob([content], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = displayName;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const togglePreview = async () => {
    if (!showPreview) await ensureText();
    setShowPreview((s) => !s);
  };

  // Suppress unused warning
  void intakeId;

  return (
    <div className="border border-ink/20 bg-paperLight p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="mb-0.5 truncate font-mono text-sm font-bold">
            📄 {displayName}
          </div>
          <div
            className={`font-mono text-[10px] uppercase tracking-wider ${meta.color}`}
          >
            {meta.label}
            {resultsCount > 0 && ` · ${resultsCount} results`}
            {artifact.byte_size != null && ` · ${(artifact.byte_size / 1024).toFixed(1)} KB`}
            {" · "}
            {hasError && <span className="text-fluoRed">⚠ error</span>}
            {!hasError && artifact.embed_status === "embedded" && (
              <span className="text-ink/60">✓ embedded</span>
            )}
            {!hasError && artifact.embed_status === "pending" && (
              <span className="text-amber-600">⏳ embedding</span>
            )}
            {!hasError && artifact.embed_status === "failed" && (
              <span className="text-fluoRed">⚠ embed failed</span>
            )}
            {!hasError && !artifact.embed_status && (
              <span className="text-ink/40">—</span>
            )}
          </div>
          {queryText && (
            <div className="mt-1 truncate text-xs text-ink/55">
              Query: <span className="font-mono">{queryText}</span>
            </div>
          )}
        </div>
        <div className="flex shrink-0 gap-2">
          <button
            type="button"
            onClick={downloadAsMarkdown}
            disabled={loadingText}
            className="inline-flex items-center gap-1 border border-ink/30 bg-paper px-2 py-1 font-mono text-[10px] uppercase tracking-wider text-ink hover:bg-ink/5 disabled:opacity-50"
          >
            {loadingText ? <Loader2 className="h-3 w-3 animate-spin" /> : "↓"} .md
          </button>
          <button
            type="button"
            onClick={togglePreview}
            className="inline-flex items-center gap-1 border border-ink/30 bg-paper px-2 py-1 font-mono text-[10px] uppercase tracking-wider text-ink hover:bg-ink/5"
          >
            👁
          </button>
        </div>
      </div>

      {showPreview && (
        <pre className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap border border-ink/15 bg-paper p-3 font-mono text-xs">
          {text === null
            ? "Laden…"
            : text.slice(0, 6000) +
              (text.length > 6000
                ? "\n\n[...truncated, klik download voor volledige inhoud]"
                : "")}
        </pre>
      )}
    </div>
  );
}

