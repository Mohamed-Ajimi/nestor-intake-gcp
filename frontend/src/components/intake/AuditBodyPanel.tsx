import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, X } from "lucide-react";
import { toast } from "sonner";
import { getAuditBody, type AuditBody } from "@/lib/api/research";

// frontend/src/components/intake/AuditBodyPanel.tsx — the D15 feed drill-down panel
// (Plan 15-05 / ENGINE-09). When the operator clicks an agent card's audit_id, this
// panel fetches the ALREADY-REDACTED audit body (request/response) from the Plan 15-04
// superadmin proxy and renders it read-only.
//
// SECURITY (T-15-12 / T-15-13b): superadmin-only BY PLACEMENT — no client route imports
// this. The body is redacted server-side (Plan 15-03) and there is NO live-URL fetch and
// NO key re-exposure here; it renders the GCS-sourced body verbatim. getAuditBody is called
// with ALL THREE ids (intakeId, runId, auditId) — the runId is required to scope the read,
// so the caller HIDES the drill-down affordance when a runId is not available.
//
// RETURN-NO-THROW (CLAUDE.md): the fetch surfaces failure via a sonner toast + inline error,
// never a throw.

/** Render an opaque JSON blob (request/response) as pretty-printed, read-only text. */
function BlobView({ value }: { value: unknown }) {
  let text: string;
  if (value == null) {
    text = "";
  } else if (typeof value === "string") {
    text = value;
  } else {
    try {
      text = JSON.stringify(value, null, 2);
    } catch {
      text = String(value);
    }
  }
  return (
    <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words bg-paper px-3 py-2 font-mono text-[12px] leading-relaxed text-ink/80">
      {text}
    </pre>
  );
}

/**
 * The audit-body drill-down. Fetches `getAuditBody(intakeId, runId, auditId)` on mount and
 * renders the redacted request/response body in a side panel. `onClose` collapses it back
 * into the feed. Superadmin-only by placement (imported only from ResearchRunProgress, which
 * mounts only on the admin intake detail route).
 */
export function AuditBodyPanel({
  intakeId,
  runId,
  auditId,
  onClose,
}: {
  intakeId: string;
  runId: string;
  auditId: string;
  onClose?: () => void;
}) {
  const { t } = useTranslation("intake");
  const [body, setBody] = useState<AuditBody | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    void getAuditBody(intakeId, runId, auditId).then((res) => {
      if (cancelled) return;
      setLoading(false);
      if (res.success && res.data) {
        setBody(res.data);
      } else {
        setError(t("audit.loadError"));
        toast.error(t("audit.loadError"));
      }
    });
    return () => {
      cancelled = true;
    };
  }, [intakeId, runId, auditId, t]);

  return (
    <div
      className="mt-2 border border-ink/20 border-l-4 bg-paperLight px-4 py-3"
      style={{ borderLeftColor: "#FF2D87" }}
      role="region"
      aria-label={t("audit.regionLabel")}
    >
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="font-mono text-[11px] uppercase tracking-wider text-ink/60">
          {t("audit.title")}
        </span>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            className="inline-flex items-center gap-1 font-mono text-[11px] uppercase tracking-wider text-ink/50 hover:text-ink"
          >
            <X className="h-3.5 w-3.5" />
            {t("audit.close")}
          </button>
        )}
      </div>

      {loading && (
        <div className="flex items-center gap-2 font-mono text-[12px] text-ink/60">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t("audit.loading")}
        </div>
      )}

      {!loading && error && (
        <p className="font-sans text-[13px] text-red-600">{error}</p>
      )}

      {!loading && !error && body && (
        <div className="space-y-3">
          <div className="flex flex-wrap gap-x-4 gap-y-1 font-mono text-[11px] text-ink/60">
            <span>{t("audit.provider", { provider: body.provider ?? t("audit.unknown") })}</span>
            <span>{t("audit.model", { model: body.model ?? t("audit.unknown") })}</span>
          </div>
          <div>
            <div className="mb-1 font-mono text-[11px] uppercase tracking-wider text-ink/50">
              {t("audit.request")}
            </div>
            <BlobView value={body.request} />
          </div>
          <div>
            <div className="mb-1 font-mono text-[11px] uppercase tracking-wider text-ink/50">
              {t("audit.response")}
            </div>
            <BlobView value={body.response} />
          </div>
        </div>
      )}
    </div>
  );
}
