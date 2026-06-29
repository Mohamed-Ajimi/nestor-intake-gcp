import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Loader2, Upload, Download } from "lucide-react";
import * as storage from "@/lib/api/storage";
import { derivePhase, phaseShowsFinalReport } from "@/lib/intake-phase";

const BUCKET = "nestor-uploads";

type Artifact = {
  id: string;
  filename: string;
  byte_size: number | null;
  mime_type: string | null;
  storage_path: string | null;
};

function bytesLabel(n: number | null | undefined) {
  if (n == null) return "";
  if (n > 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  if (n > 1024) return `${Math.round(n / 1024)} KB`;
  return `${n} B`;
}

function sanitizeFilenameForStorage(name: string): string {
  return name
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[—–]/g, '-')
    .replace(/\s+/g, '_')
    .replace(/[^a-zA-Z0-9._-]/g, '')
    .replace(/_+/g, '_')
    .replace(/-+/g, '-')
    .replace(/^[_.-]+|[_.-]+$/g, '');
}

export function FinalReportBlock({
  intakeId,
  finalReportArtifactId,
  intakeStatus,
  hasResultsToken,
  onChange,
}: {
  intakeId: string;
  finalReportArtifactId: string | null;
  intakeStatus: string | null;
  hasResultsToken: boolean;
  onChange: (artifactId: string | null) => void | Promise<void>;
}) {
  const [artifact, setArtifact] = useState<Artifact | null>(null);
  const [busy, setBusy] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    // The final-report artifact record is served by the research backend
    // (Phase 7+). Not fetched this milestone — the block is gated off.
    void finalReportArtifactId;
    setArtifact(null);
  }, [finalReportArtifactId]);

  const maybeAutoDeliver = async () => {
    // Status transitions are mediated by the backend transition verbs
    // (intakes.ts); the auto-deliver bump is out of scope here.
    void intakeStatus;
    void hasResultsToken;
  };

  const onPick = async (file: File) => {
    setBusy(true);
    try {
      const safeName = sanitizeFilenameForStorage(file.name);
      const path = `intakes/${intakeId}/final-report/${crypto.randomUUID()}-${safeName}`;
      const res = await storage.uploadFile({
        intakeId,
        bucket: BUCKET,
        path,
        file,
        filename: file.name,
        contentType: file.type || undefined,
      });
      if (!res.success) throw new Error(res.error);
      // Linking the uploaded report to the intake (set_final_report) and the
      // research-artifact record are research-backend operations (Phase 7+),
      // not wired this milestone.
      toast.success("Rapport geüpload");
      await maybeAutoDeliver();
      await onChange(null);
    } catch (e) {
      toast.error(`Upload mislukt: ${(e as Error).message}`);
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  const onRemove = async () => {
    if (!confirm("Verwijder het volledig rapport voor deze klant?")) return;
    setBusy(true);
    try {
      // Unlinking the final report (set_final_report) is a research-backend
      // operation (Phase 7+); here we only clear local UI state.
      setArtifact(null);
      toast.success("Rapport ontkoppeld");
      await onChange(null);
    } catch (e) {
      toast.error(`Mislukt: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  const onDownload = async () => {
    if (!artifact?.storage_path) return;
    const signed = await storage.signedDownloadUrl({
      bucket: BUCKET,
      path: artifact.storage_path,
      expiresIn: 300,
    });
    if (!signed.success) {
      toast.error("Kon link niet maken");
      return;
    }
    try {
      const response = await fetch(signed.data.url);
      if (!response.ok) throw new Error("Download faalde");
      const blob = await response.blob();
      const blobUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = blobUrl;
      a.download = artifact.filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(blobUrl);
    } catch (e) {
      toast.error(`Download faalde: ${(e as Error).message}`);
    }
  };

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragActive(false);
    const file = e.dataTransfer?.files?.[0];
    if (file) onPick(file);
  };

  // Phase-gate: the final report belongs to the post-decomposed flow. The
  // re-platform scope ceiling stops at `decomposed`, so phaseShowsFinalReport()
  // is effectively false this milestone and the block never renders.
  const phase = derivePhase(
    {
      status: intakeStatus,
      validation_link_sent_at: null,
      results_link_sent_at: null,
      context_pack_artifact_id: null,
      final_report_artifact_id: finalReportArtifactId,
    },
    null,
    false,
  );
  if (!phaseShowsFinalReport(phase)) return null;

  // Red when missing (active blocker) — yellow when uploaded (done).
  // The block is only rendered for in_research/decomposed/delivered, so a
  // missing report is always a blocker for delivery.
  const isMissing = !artifact;
  const accentColor = isMissing ? "#FF2D3A" : "#DFF940";

  return (
    <section
      className="mb-5 border border-ink/30 border-l-4 bg-paperLight px-6 py-5"
      style={{ borderLeftColor: accentColor }}
    >
      <div
        className="mb-2 font-mono text-[11px] uppercase tracking-wider"
        style={isMissing ? { color: "#FF2D3A" } : undefined}
      >
        <span className={isMissing ? "" : "text-ink/60"}>
          Volledig klant-rapport{isMissing ? " — ontbreekt" : ""}
        </span>
      </div>

      <p className="mb-3 font-sans text-[15px] leading-relaxed text-ink">
        Eén samengevat rapport dat de klant downloadt via de portal. Upload de
        finale PDF (alle vragen in één document).
      </p>

      {artifact && (
        <div className="mb-3 font-sans text-sm text-ink">
          Huidig rapport: <strong>{artifact.filename}</strong>
          {artifact.byte_size != null && (
            <span className="text-ink/60"> · {bytesLabel(artifact.byte_size)}</span>
          )}
        </div>
      )}

      <div
        onDragEnter={(e) => { e.preventDefault(); setDragActive(true); }}
        onDragLeave={(e) => { e.preventDefault(); setDragActive(false); }}
        onDragOver={(e) => e.preventDefault()}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
        className={`border border-dashed p-3 transition-colors ${
          dragActive
            ? "border-[#FF2D87] bg-[#FFF0F5]/40"
            : "border-ink/30 bg-transparent hover:bg-ink/5"
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.docx,.md,.txt"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) onPick(f);
          }}
        />
        {dragActive ? (
          <div className="py-2 font-mono text-xs uppercase tracking-wider" style={{ color: "#FF2D87" }}>
            Laat los om te uploaden
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                inputRef.current?.click();
              }}
              disabled={busy}
              className="inline-flex items-center gap-1.5 bg-ink px-3 py-2 font-mono text-xs uppercase tracking-wider text-paper hover:bg-ink/80 disabled:opacity-50"
            >
              {busy ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Upload className="h-3.5 w-3.5" />
              )}
              {artifact ? "Vervang rapport" : "Upload rapport"}
            </button>

            {artifact && (
              <>
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); onDownload(); }}
                  className="inline-flex items-center gap-1.5 border border-ink bg-paperLight px-3 py-2 font-mono text-xs uppercase tracking-wider text-ink hover:bg-ink/5"
                >
                  <Download className="h-3.5 w-3.5" /> Bekijk
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={(e) => { e.stopPropagation(); onRemove(); }}
                  className="inline-flex items-center gap-1.5 border border-ink bg-paperLight px-3 py-2 font-mono text-xs uppercase tracking-wider text-ink hover:bg-ink/5 disabled:opacity-50"
                >
                  Verwijder
                </button>
              </>
            )}

            <span className="ml-1 font-mono text-xs uppercase tracking-wider text-ink/40">
              of sleep &amp; drop hier
            </span>
          </div>
        )}
      </div>

      {!artifact && (
        <div className="mt-2 font-mono text-xs uppercase tracking-wider text-ink/40">
          Nog geen rapport geüpload
        </div>
      )}
    </section>
  );
}
