import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Clipboard, Download, Check, Sparkles, Loader2 } from "lucide-react";
import ReactMarkdown from "react-markdown";
import { supabase } from "@/lib/supabase";
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
    if (!supabase) return;
    setLoadingPack(true);
    const { data } = await supabase
      .schema("nestor")
      .from("skill_runs")
      .select("id, output, cost_estimate_usd, completed_at, model")
      .eq("intake_id", intakeId)
      .eq("skill_name", "context-pack")
      .eq("status", "succeeded")
      .order("completed_at", { ascending: false })
      .limit(1)
      .maybeSingle();
    setPack((data as ContextPack | null) ?? null);
    setLoadingPack(false);
  };

  useEffect(() => {
    fetchPack();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intakeId]);

  const handleGenerate = async () => {
    if (!supabase) return;
    setGenerating(true);
    try {
      const { data, error } = await supabase.functions.invoke("generate-context-pack", {
        body: { intake_id: intakeId },
      });
      if (error) throw error;
      if (!data?.success) throw new Error(data?.error || "Synthese mislukt");
      toast.success("Context Pack gegenereerd");
      await fetchPack();
    } catch (e) {
      toast.error(`Synthese mislukt: ${(e as Error).message}`);
    } finally {
      setGenerating(false);
    }
  };

  const handleCopy = async () => {
    const projectName =
      (typeof answers.project_name === "string" && answers.project_name.trim()) ||
      intakeTitle;
    const lines: string[] = [];
    lines.push(`# Research-vragen — ${clientName} — ${projectName}`);
    lines.push("");

    // Main research questions
    const mainQuestions = Array.isArray(answers.questions)
      ? (answers.questions as Array<{ text: string; kind?: string }>)
      : [];
    if (mainQuestions.length > 0) {
      lines.push("## Onderzoeksvragen");
      lines.push("");
      mainQuestions.forEach((q, idx) => {
        lines.push(`### V${idx + 1}. ${q.text}`);
        if (q.kind) {
          const kindLabel =
            q.kind === "decision"
              ? "Beslissing"
              : q.kind === "exploration"
                ? "Verkenning"
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
      lines.push("## Extra vragen (klant-goedgekeurd)");
      lines.push("");
      extras.forEach((e, idx) => {
        lines.push(`### E${idx + 1}. ${e.text}`);
        if (e.rationale) lines.push(`*Waarom relevant:* ${e.rationale}`);
        lines.push("");
      });
    }

    try {
      await navigator.clipboard.writeText(lines.join("\n"));
      toast.success("Vragen gekopieerd — plak in Nestor");
    } catch {
      toast.error("Kopiëren mislukt");
    }
  };

  const handleDownload = async () => {
    if (!pack) return;
    setBusy(true);
    try {
      const blob = await generateContextPackBlob({
        clientName,
        intakeTitle,
        validatedAt,
        generatedAt: pack.completed_at,
        contextPackMarkdown: pack.output,
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
      toast.error(`PDF mislukt: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  const handleMarkDelivered = async () => {
    if (!supabase) return;
    setBusy(true);
    const { error } = await supabase
      .schema("nestor")
      .from("intakes")
      .update({ status: "decomposed" })
      .eq("id", intakeId);
    setBusy(false);
    setConfirming(false);
    if (error) {
      toast.error("Status niet bijgewerkt");
      return;
    }
    onStatusChange("decomposed");
    toast.success("Status: gedecomposeerd");
  };

  const fmtDate = (d: string | null) => {
    if (!d) return "—";
    try {
      return new Date(d).toLocaleDateString("nl-NL", {
        day: "numeric",
        month: "long",
        year: "numeric",
      });
    } catch {
      return d;
    }
  };

  const fmtEur = (usd: number | null) =>
    usd == null ? "—" : `€${(usd * 0.92).toFixed(2)}`;

  return (
    <div className="mb-6 border border-ink border-l-4 border-l-agenic-yellow bg-paperLight p-6">
      <div className="mb-3 font-mono text-xs uppercase tracking-wider text-ink">
        HANDOFF VOOR NESTOR
      </div>
      <p className="mb-5 text-ink font-sans text-sm">
        Intake gevalideerd. Genereer eerst het Context Pack (AI synthese), dan kan je downloaden.
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
            {generating ? "Bezig met synthese..." : "Genereer Context Pack"}
          </button>
        )}
        <button
          type="button"
          onClick={handleCopy}
          className="inline-flex items-center gap-2 border border-ink bg-paper px-4 py-2 font-mono text-xs uppercase tracking-wider text-ink hover:border-2"
        >
          <Clipboard className="h-3.5 w-3.5" />
          Kopieer alle vragen
        </button>
        {pack && (
          <button
            type="button"
            onClick={handleDownload}
            disabled={busy}
            className="inline-flex items-center gap-2 border border-ink bg-paper px-4 py-2 font-mono text-xs uppercase tracking-wider text-ink hover:border-2 disabled:opacity-50"
          >
            <Download className="h-3.5 w-3.5" />
            Download Context Pack PDF
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
            Regenereer
          </button>
        )}
        <button
          type="button"
          onClick={() => !delivered && setConfirming(true)}
          disabled={delivered || busy}
          className="inline-flex items-center gap-2 border border-ink bg-agenic-green px-4 py-2 font-mono text-xs uppercase tracking-wider text-ink disabled:opacity-60"
        >
          <Check className="h-3.5 w-3.5" />
          {delivered ? "Afgeleverd" : "Markeer als afgeleverd"}
        </button>
      </div>

      {pack && (
        <div className="mt-6 border border-ink bg-paper p-5">
          <div className="mb-3 font-mono text-xs uppercase tracking-wider text-ink/70">
            CONTEXT PACK — gegenereerd {fmtDate(pack.completed_at)} · cost{" "}
            {fmtEur(pack.cost_estimate_usd)} · model {pack.model ?? "—"}
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
              BEVESTIG
            </div>
            <p className="font-sans text-sm text-ink">
              Heb je de PDF + vragen naar Nestor doorgegeven?
            </p>
            <div className="mt-6 flex justify-end gap-2">
              <button
                onClick={() => setConfirming(false)}
                className="border border-ink bg-paper px-4 py-2 font-mono text-xs uppercase tracking-wider text-ink hover:border-2"
              >
                Annuleren
              </button>
              <button
                onClick={handleMarkDelivered}
                disabled={busy}
                className="border border-ink bg-agenic-green px-4 py-2 font-mono text-xs uppercase tracking-wider text-ink disabled:opacity-60"
              >
                Bevestig
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
