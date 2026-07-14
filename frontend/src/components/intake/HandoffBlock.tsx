import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Clipboard, Download, Check, Sparkles, Loader2 } from "lucide-react";
import ReactMarkdown from "react-markdown";
import i18n from "@/lib/i18n";
import { derivePhase, phaseShowsResearch } from "@/lib/intake-phase";
import { generateContextPackBlob } from "./ContextPackPDF";

function slug(s: string) {
  return s
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

type ContextPack = {
  id: string;
  output: string;
  cost_estimate_usd: number | null;
  completed_at: string | null;
  model: string | null;
};

type Props = {
  intakeId: string;
  intakeTitle: string;
  intakeStatus: string | null;
  productName: string;
  clientName: string;
  validatedAt: string | null;
  answers: Record<string, unknown>;
  onStatusChange: (status: string) => void;
};

export function HandoffBlock({
  intakeId,
  intakeTitle,
  intakeStatus,
  clientName,
  validatedAt,
  answers,
  onStatusChange,
}: Props) {
  const { t } = useTranslation("intake");
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [pack, setPack] = useState<ContextPack | null>(null);
  const [loadingPack, setLoadingPack] = useState(true);

  const delivered =
    intakeStatus === "decomposed" ||
    intakeStatus === "in_research" ||
    intakeStatus === "delivered";

  const fetchPack = async () => {
    // Context-pack skill-run data is served via the API seam (other Phase-6
    // plans). This block is gated-off dead UI this milestone — render inert.
    void intakeId;
    setPack(null);
    setLoadingPack(false);
  };

  useEffect(() => {
    fetchPack();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intakeId]);

  const handleGenerate = async () => {
    // Context-pack synthesis runs through the backend skill seam (Phase 6/7),
    // not invoked from this gated-off block.
    toast.error(t("handoff.packUnavailable"));
  };

  const handleCopy = async () => {
    const projectName =
      (typeof answers.project_name === "string" && answers.project_name.trim()) ||
      intakeTitle;
    const lines: string[] = [];
    lines.push(
      t("handoff.researchQuestionsHeader", { client: clientName, project: projectName }),
    );
    lines.push("");

    // Main research questions
    const mainQuestions = Array.isArray(answers.questions)
      ? (answers.questions as Array<{ text: string; kind?: string }>)
      : [];
    if (mainQuestions.length > 0) {
      lines.push(t("handoff.questionsSection"));
      lines.push("");
      mainQuestions.forEach((q, idx) => {
        lines.push(`### V${idx + 1}. ${q.text}`);
        if (q.kind) {
          const kindLabel =
            q.kind === "decision"
              ? t("handoff.kindDecision")
              : q.kind === "exploration"
                ? t("handoff.kindExploration")
                : q.kind;
          lines.push(`Type: ${kindLabel}`);
        }
        lines.push("");
      });
    }

    // Approved extra questions
    const extras = Array.isArray(answers.extra_questions_proposed)
      ? (answers.extra_questions_proposed as Array<{
          text: string;
          rationale?: string;
          approved?: boolean;
        }>).filter((e) => e.approved === true)
      : [];
    if (extras.length > 0) {
      lines.push(t("handoff.extraSection"));
      lines.push("");
      extras.forEach((e, idx) => {
        lines.push(`### E${idx + 1}. ${e.text}`);
        if (e.rationale) lines.push(`${t("handoff.whyRelevant")} ${e.rationale}`);
        lines.push("");
      });
    }

    try {
      await navigator.clipboard.writeText(lines.join("\n"));
      toast.success(t("handoff.questionsCopied"));
    } catch {
      toast.error(t("handoff.copyFailed"));
    }
  };

  const handleDownload = async () => {
    if (!pack) return;
    setBusy(true);
    try {
      // Pitfall 3: resolve the PDF's display strings HERE (inside the provider) and
      // pass them as a `labels` object — the PDF renders outside the I18nextProvider.
      const blob = await generateContextPackBlob({
        clientName,
        intakeTitle,
        contextPackMarkdown: pack.output,
        labels: {
          footer: t("pdf.contextPack.footer"),
          validated: t("pdf.contextPack.validated", { date: fmtDate(validatedAt) }),
          generated: t("pdf.contextPack.generated", { date: fmtDate(pack.completed_at) }),
        },
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      const date = new Date().toISOString().slice(0, 10);
      a.href = url;
      a.download = `context-pack-${slug(clientName)}-${date}.pdf`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e) {
      toast.error(t("handoff.pdfFailed", { error: (e as Error).message }));
    } finally {
      setBusy(false);
    }
  };

  const handleMarkDelivered = async () => {
    // Status transitions are mediated by backend transition verbs (intakes.ts);
    // not wired from this gated-off block.
    void onStatusChange;
    setConfirming(false);
    toast.error(t("handoff.statusBackend"));
  };

  const fmtDate = (d: string | null) => {
    if (!d) return t("handoff.dateFallback");
    try {
      return new Date(d).toLocaleDateString(i18n.language, {
        day: "numeric",
        month: "long",
        year: "numeric",
      });
    } catch {
      return d;
    }
  };

  const fmtEur = (usd: number | null) =>
    usd == null ? t("handoff.dateFallback") : `€${(usd * 0.92).toFixed(2)}`;

  // Phase-gate: this handoff block is post-decomposed dead UI this milestone.
  // The re-platform scope ceiling stops at `decomposed`, so phaseShowsResearch()
  // is effectively false and the block never renders.
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

  return (
    <div className="mb-6 border border-ink border-l-4 border-l-agenic-yellow bg-paperLight p-6">
      <div className="mb-3 font-mono text-xs uppercase tracking-wider text-ink">
        {t("handoff.title")}
      </div>
      <p className="mb-5 text-ink font-sans text-sm">
        {t("handoff.intro")}
      </p>
      <div className="flex flex-wrap items-center gap-3">
        {!pack && !loadingPack && (
          <button
            type="button"
            onClick={handleGenerate}
            disabled={generating}
            className="inline-flex items-center gap-2 border border-ink bg-ink px-4 py-2 font-mono text-xs uppercase tracking-wider text-paper hover:bg-ink/90 disabled:opacity-60"
          >
            {generating ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Sparkles className="h-3.5 w-3.5" />
            )}
            {generating ? t("handoff.synthesizing") : t("handoff.generateContextPack")}
          </button>
        )}
        <button
          type="button"
          onClick={handleCopy}
          className="inline-flex items-center gap-2 border border-ink bg-paper px-4 py-2 font-mono text-xs uppercase tracking-wider text-ink hover:border-2"
        >
          <Clipboard className="h-3.5 w-3.5" />
          {t("handoff.copyAllQuestions")}
        </button>
        {pack && (
          <button
            type="button"
            onClick={handleDownload}
            disabled={busy}
            className="inline-flex items-center gap-2 border border-ink bg-paper px-4 py-2 font-mono text-xs uppercase tracking-wider text-ink hover:border-2 disabled:opacity-50"
          >
            <Download className="h-3.5 w-3.5" />
            {t("handoff.downloadPdf")}
          </button>
        )}
        {pack && (
          <button
            type="button"
            onClick={handleGenerate}
            disabled={generating}
            className="inline-flex items-center gap-2 border border-ink bg-paper px-4 py-2 font-mono text-xs uppercase tracking-wider text-ink hover:border-2 disabled:opacity-60"
          >
            {generating ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Sparkles className="h-3.5 w-3.5" />
            )}
            {t("handoff.regenerate")}
          </button>
        )}
        <button
          type="button"
          onClick={() => !delivered && setConfirming(true)}
          disabled={delivered || busy}
          className="inline-flex items-center gap-2 border border-ink bg-agenic-green px-4 py-2 font-mono text-xs uppercase tracking-wider text-ink disabled:opacity-60"
        >
          <Check className="h-3.5 w-3.5" />
          {delivered ? t("handoff.delivered") : t("handoff.markDelivered")}
        </button>
      </div>

      {pack && (
        <div className="mt-6 border border-ink bg-paper p-5">
          <div className="mb-3 font-mono text-xs uppercase tracking-wider text-ink/70">
            {t("handoff.packGenerated", {
              date: fmtDate(pack.completed_at),
              cost: fmtEur(pack.cost_estimate_usd),
              model: pack.model ?? t("handoff.modelFallback"),
            })}
          </div>
          <div className="prose prose-sm max-w-none text-ink prose-headings:font-serif prose-headings:text-ink prose-strong:text-ink prose-strong:font-semibold prose-a:text-ink">
            <ReactMarkdown>{pack.output}</ReactMarkdown>
          </div>
        </div>
      )}

      {confirming && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4">
          <div className="max-w-md border border-ink bg-paper p-6">
            <div className="mb-2 font-mono text-xs uppercase tracking-wider text-ink">
              {t("handoff.confirm")}
            </div>
            <p className="font-sans text-sm text-ink">
              {t("handoff.confirmBody")}
            </p>
            <div className="mt-6 flex justify-end gap-2">
              <button
                onClick={() => setConfirming(false)}
                className="border border-ink bg-paper px-4 py-2 font-mono text-xs uppercase tracking-wider text-ink hover:border-2"
              >
                {t("handoff.cancel")}
              </button>
              <button
                onClick={handleMarkDelivered}
                disabled={busy}
                className="border border-ink bg-agenic-green px-4 py-2 font-mono text-xs uppercase tracking-wider text-ink disabled:opacity-60"
              >
                {t("handoff.confirmBtn")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
