import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Loader2, Upload, Download, Send } from "lucide-react";
import * as storage from "@/lib/api/storage";
import { deliverReport, getReport, replaceReport } from "@/lib/api/intakes";
import { derivePhase, phaseShowsFinalReport } from "@/lib/intake-phase";
import { RecipientPicker } from "@/components/intake/RecipientPicker";

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
  const { t } = useTranslation("intake");
  const [artifact, setArtifact] = useState<Artifact | null>(null);
  const [busy, setBusy] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  // Staged (uploaded-but-not-yet-delivered) file — D-01: staging is client-invisible,
  // the status stays in_research until the explicit Deliver act.
  const [stagedPath, setStagedPath] = useState<string | null>(null);
  const [stagedMeta, setStagedMeta] = useState<{ filename: string; size: number } | null>(null);
  const [delivering, setDelivering] = useState(false);
  const [deliverOpen, setDeliverOpen] = useState(false);
  const [replaceOpen, setReplaceOpen] = useState(false);

  // hasResultsToken is retained on the prop surface (admin route wires it) but the
  // delivered state now comes from the backend status, never a client-side token check.
  void hasResultsToken;

  const isDelivered = intakeStatus === "delivered";

  useEffect(() => {
    // The delivered report metadata is served by GET /intakes/{id}/report (18-01).
    // Fetch it once the intake carries a linked report artifact; clear otherwise.
    let cancelled = false;
    if (!finalReportArtifactId) {
      setArtifact(null);
      return;
    }
    (async () => {
      const res = await getReport(intakeId);
      if (cancelled) return;
      if (!res.success) {
        // 404 pre-delivery (REPORT-02) or a read error — surface nothing here, the
        // block still renders its staged/upload affordances.
        setArtifact(null);
        return;
      }
      setArtifact({
        id: finalReportArtifactId,
        filename: res.data.filename ?? "",
        byte_size: res.data.byte_size,
        mime_type: res.data.mime_type,
        storage_path: res.data.storage_path,
      });
    })();
    return () => {
      cancelled = true;
    };
  }, [intakeId, finalReportArtifactId]);

  const onPick = async (file: File) => {
    setBusy(true);
    try {
      // The server authors the stored key (D-05); we tag the file with its category and
      // send the original filename. sanitizeFilenameForStorage is retained for display-side
      // name normalization only. Uploading only STAGES the file (D-01) — nothing is
      // client-visible and the status is untouched until the explicit Deliver/Replace act.
      const res = await storage.uploadFile({
        intakeId,
        file,
        filename: file.name,
        category: "reports",
        contentType: file.type || undefined,
      });
      if (!res.success) throw new Error(res.error);
      // Stage the uploaded key locally; re-uploading over an existing staged file simply
      // replaces the staged key (D-06 — the staged object may be swapped freely pre-deliver).
      setStagedPath(res.data.path);
      setStagedMeta({ filename: res.data.filename, size: res.data.size });
      toast.success(t("finalReport.reportUploaded"));
    } catch (e) {
      toast.error(t("finalReport.uploadFailed", { error: (e as Error).message }));
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  // Pre-delivery swap/remove — clears the staged file locally. Before delivery the staged
  // object is not linked server-side, so there is no backend delete: the operator just
  // re-uploads (D-06).
  const onClearStaged = () => {
    setStagedPath(null);
    setStagedMeta(null);
  };

  const onDeliverConfirm = async (membershipIds: string[]) => {
    if (!stagedPath) return;
    setDelivering(true);
    try {
      const res = await deliverReport(intakeId, {
        storagePath: stagedPath,
        recipients: membershipIds,
      });
      if (!res.success) {
        toast.error(t("finalReport.deliverFailed", { error: res.error }));
        return;
      }
      toast.success(t("finalReport.delivered"));
      onClearStaged();
      // The backend view is the source of truth — the admin route reloads the intake
      // (getIntake) from this callback; the artifact id is advisory.
      await onChange(res.data.final_report_artifact_id);
    } finally {
      setDelivering(false);
      setDeliverOpen(false);
    }
  };

  const onReplaceConfirm = async (membershipIds: string[]) => {
    if (!stagedPath) return;
    setDelivering(true);
    try {
      // recipients=[] → silent replace (no re-notify, D-05); a non-empty list re-notifies.
      const res = await replaceReport(intakeId, {
        storagePath: stagedPath,
        recipients: membershipIds,
      });
      if (!res.success) {
        toast.error(t("finalReport.deliverFailed", { error: res.error }));
        return;
      }
      toast.success(t("finalReport.delivered"));
      onClearStaged();
      await onChange(res.data.final_report_artifact_id);
    } finally {
      setDelivering(false);
      setReplaceOpen(false);
    }
  };

  const onSilentReplace = async () => {
    if (!stagedPath) return;
    setDelivering(true);
    try {
      const res = await replaceReport(intakeId, { storagePath: stagedPath, recipients: [] });
      if (!res.success) {
        toast.error(t("finalReport.deliverFailed", { error: res.error }));
        return;
      }
      toast.success(t("finalReport.delivered"));
      onClearStaged();
      await onChange(res.data.final_report_artifact_id);
    } finally {
      setDelivering(false);
    }
  };

  const onDownload = async () => {
    if (!artifact?.storage_path) return;
    const signed = await storage.signedDownloadUrl({
      intakeId,
      path: artifact.storage_path,
      expiresIn: 300,
    });
    if (!signed.success) {
      toast.error(t("finalReport.linkCreateFailed"));
      return;
    }
    try {
      const response = await fetch(signed.data.url);
      if (!response.ok) throw new Error(t("finalReport.downloadFailed"));
      const blob = await response.blob();
      const blobUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = blobUrl;
      a.download = artifact.filename || sanitizeFilenameForStorage("report.pdf");
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(blobUrl);
    } catch (e) {
      toast.error(t("finalReport.downloadFailedError", { error: (e as Error).message }));
    }
  };

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragActive(false);
    const file = e.dataTransfer?.files?.[0];
    if (file) onPick(file);
  };

  // Phase-gate: the final report is delivered during in_research (Phase 18, REPORT-01) and
  // stays visible through delivered/completed. phaseShowsFinalReport now includes in_research.
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

  // Red when nothing delivered AND nothing staged (active blocker) — yellow once a report
  // exists (staged or delivered).
  const hasStaged = !!stagedPath;
  const isMissing = !artifact && !hasStaged;
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
          {isMissing ? t("finalReport.labelMissing") : t("finalReport.label")}
        </span>
      </div>

      <p className="mb-3 font-sans text-[15px] leading-relaxed text-ink">
        {t("finalReport.intro")}
      </p>

      {artifact && (
        <div className="mb-3 font-sans text-sm text-ink">
          {t("finalReport.current")} <strong>{artifact.filename}</strong>
          {artifact.byte_size != null && (
            <span className="text-ink/60"> · {bytesLabel(artifact.byte_size)}</span>
          )}
        </div>
      )}

      {hasStaged && stagedMeta && (
        <div className="mb-3 border border-dashed border-ink/40 bg-paper2/40 px-3 py-2">
          <div className="font-mono text-[11px] uppercase tracking-wider text-ink/70">
            {t("finalReport.staged")}
          </div>
          <div className="mt-1 font-sans text-sm text-ink">
            <strong>{stagedMeta.filename}</strong>
            <span className="text-ink/60"> · {bytesLabel(stagedMeta.size)}</span>
          </div>
          <div className="mt-1 font-sans text-[13px] text-ink/60">
            {t("finalReport.stagedHint")}
          </div>
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
          accept=".pdf"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) onPick(f);
          }}
        />
        {dragActive ? (
          <div className="py-2 font-mono text-xs uppercase tracking-wider" style={{ color: "#FF2D87" }}>
            {t("finalReport.dropToUpload")}
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                inputRef.current?.click();
              }}
              disabled={busy || delivering}
              className="inline-flex items-center gap-1.5 bg-ink px-3 py-2 font-mono text-xs uppercase tracking-wider text-paper hover:bg-ink/80 disabled:opacity-50"
            >
              {busy ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Upload className="h-3.5 w-3.5" />
              )}
              {artifact || hasStaged ? t("finalReport.replaceReport") : t("finalReport.uploadReport")}
            </button>

            {/* Deliver — only pre-delivery, once a file is staged (D-01: explicit act). */}
            {!isDelivered && hasStaged && (
              <button
                type="button"
                disabled={busy || delivering}
                onClick={(e) => { e.stopPropagation(); setDeliverOpen(true); }}
                className="inline-flex items-center gap-1.5 bg-[#DFF940] px-3 py-2 font-mono text-xs uppercase tracking-wider text-ink hover:bg-[#DFF940]/80 disabled:opacity-50"
              >
                {delivering ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Send className="h-3.5 w-3.5" />
                )}
                {delivering ? t("finalReport.delivering") : t("finalReport.deliver")}
              </button>
            )}

            {/* Post-delivery Replace — a staged file may be re-notified or silently swapped (D-04/D-05). */}
            {isDelivered && hasStaged && (
              <>
                <button
                  type="button"
                  disabled={busy || delivering}
                  onClick={(e) => { e.stopPropagation(); setReplaceOpen(true); }}
                  className="inline-flex items-center gap-1.5 bg-[#DFF940] px-3 py-2 font-mono text-xs uppercase tracking-wider text-ink hover:bg-[#DFF940]/80 disabled:opacity-50"
                >
                  {delivering ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Send className="h-3.5 w-3.5" />
                  )}
                  {t("finalReport.reNotify")}
                </button>
                <button
                  type="button"
                  disabled={busy || delivering}
                  onClick={(e) => { e.stopPropagation(); onSilentReplace(); }}
                  className="inline-flex items-center gap-1.5 border border-ink bg-paperLight px-3 py-2 font-mono text-xs uppercase tracking-wider text-ink hover:bg-ink/5 disabled:opacity-50"
                >
                  {t("finalReport.silentReplace")}
                </button>
              </>
            )}

            {hasStaged && (
              <button
                type="button"
                disabled={busy || delivering}
                onClick={(e) => { e.stopPropagation(); onClearStaged(); }}
                className="inline-flex items-center gap-1.5 border border-ink bg-paperLight px-3 py-2 font-mono text-xs uppercase tracking-wider text-ink hover:bg-ink/5 disabled:opacity-50"
              >
                {t("finalReport.remove")}
              </button>
            )}

            {artifact && !hasStaged && (
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); onDownload(); }}
                className="inline-flex items-center gap-1.5 border border-ink bg-paperLight px-3 py-2 font-mono text-xs uppercase tracking-wider text-ink hover:bg-ink/5"
              >
                <Download className="h-3.5 w-3.5" /> {t("finalReport.view")}
              </button>
            )}

            <span className="ml-1 font-mono text-xs uppercase tracking-wider text-ink/40">
              {t("finalReport.dragDrop")}
            </span>
          </div>
        )}
      </div>

      {!artifact && !hasStaged && (
        <div className="mt-2 font-mono text-xs uppercase tracking-wider text-ink/40">
          {t("finalReport.noReport")}
        </div>
      )}

      {/* Deliver dialog — reuses RecipientPicker (type="results" copy family, D-02). */}
      <RecipientPicker
        open={deliverOpen}
        onOpenChange={setDeliverOpen}
        intakeId={intakeId}
        type="results"
        busy={delivering}
        onConfirm={onDeliverConfirm}
      />

      {/* Replace re-notify dialog — reuses RecipientPicker (D-05). */}
      <RecipientPicker
        open={replaceOpen}
        onOpenChange={setReplaceOpen}
        intakeId={intakeId}
        type="results"
        busy={delivering}
        onConfirm={onReplaceConfirm}
      />
    </section>
  );
}
