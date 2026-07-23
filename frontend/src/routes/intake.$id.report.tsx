import { createFileRoute, redirect, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Download, Loader2 } from "lucide-react";
import { onAuthStateChanged, signOut, type User } from "firebase/auth";
import { auth, MOCK_AUTH } from "@/lib/firebase";
import { useAuth } from "@/lib/auth-context";
import { getIntake, getReport, type ReportView } from "@/lib/api/intakes";
import * as storage from "@/lib/api/storage";
import { StatusPill } from "@/components/intake/_status";

// frontend/src/routes/intake.$id.report.tsx — the authenticated USER report-delivery
// view (`/intake/$id/report`). Phase 18 (REPORT-02). Renders ONLY when the intake status
// is EXACTLY `delivered`; any other status (or a GET /report 404) redirects to /intake —
// nothing research-related is client-visible before delivery.
//
// D-08: download-only via a backend-minted signed URL — NO iframe/embed/PDF viewer.
// D-07: a static placeholder reserves layout space for the future Phase-19 Q&A chat; no
// chat UI is built here (label only, no input, no message list, no data fetch).

function authReady(): Promise<User | null> {
  if (auth.currentUser) return Promise.resolve(auth.currentUser);
  return new Promise((resolve) => {
    const unsubscribe = onAuthStateChanged(auth, (user) => {
      unsubscribe();
      resolve(user);
    });
  });
}

export const Route = createFileRoute("/intake/$id/report")({
  beforeLoad: async () => {
    if (MOCK_AUTH) return; // mock mode: bypass Firebase auth check
    const user = await authReady();
    if (!user) {
      throw redirect({ to: "/auth/login" });
    }
  },
  component: UserIntakeReportPage,
});

// Local byte formatter (copied from FinalReportBlock :18-23 — display-only helper).
function bytesLabel(n: number | null | undefined) {
  if (n == null) return "";
  if (n > 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  if (n > 1024) return `${Math.round(n / 1024)} KB`;
  return `${n} B`;
}

function UserIntakeReportPage() {
  const { t, i18n } = useTranslation("intake");
  const { id } = Route.useParams();
  const { session } = useAuth();
  const navigate = useNavigate();
  const [report, setReport] = useState<ReportView | null>(null);
  const [title, setTitle] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      const intakeRes = await getIntake(id);
      if (cancelled) return;
      if (!intakeRes.success) {
        setError(t("reportPage.loadFailed"));
        setLoading(false);
        return;
      }

      // Delivered-only gate (REPORT-02) — EXACT equality, not a rank/>= comparison
      // (Pitfall 2). Any non-delivered status is structurally invisible: redirect away.
      if (intakeRes.data.status !== "delivered") {
        navigate({ to: "/intake" });
        return;
      }

      const reportRes = await getReport(id);
      if (cancelled) return;
      if (!reportRes.success) {
        // A delivered intake with no readable report view (or a race 404) — nothing to
        // show; surface a load error rather than leaking any research-side content.
        setError(t("reportPage.loadFailed"));
        setLoading(false);
        return;
      }

      setReport(reportRes.data);
      setTitle(intakeRes.data.client_name ?? "");
      setError(null);
      setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [id, navigate, t]);

  const handleLogout = async () => {
    try {
      await signOut(auth);
    } finally {
      navigate({ to: "/auth/login" });
    }
  };

  // Download-only (D-08): mint a short-lived signed URL, fetch the blob, and click a
  // synthetic anchor with the attachment filename — no inline viewer. Mirrors
  // FinalReportBlock.onDownload (:198-224).
  const handleDownload = async () => {
    if (!report?.storage_path) return;
    setDownloading(true);
    try {
      const signed = await storage.signedDownloadUrl({
        intakeId: id,
        path: report.storage_path,
        expiresIn: 300,
      });
      if (!signed.success) {
        toast.error(t("reportPage.loadFailed"));
        return;
      }
      const response = await fetch(signed.data.url);
      if (!response.ok) throw new Error(t("reportPage.loadFailed"));
      const blob = await response.blob();
      const blobUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = blobUrl;
      a.download = report.filename || "report.pdf";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(blobUrl);
    } catch {
      toast.error(t("reportPage.loadFailed"));
    } finally {
      setDownloading(false);
    }
  };

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-paper px-6">
        <p className="font-mono text-xs uppercase tracking-wider text-ink/40">
          {t("reportPage.loading")}
        </p>
      </div>
    );
  }

  if (error || !report) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-6 bg-paper px-6 text-center">
        <p className="max-w-md text-sm text-red-600">
          {error ?? t("reportPage.notAvailable")}
        </p>
        <button
          type="button"
          onClick={() => navigate({ to: "/intake" })}
          className="font-mono text-xs uppercase tracking-wider text-ink/60 underline-offset-2 hover:text-ink hover:underline"
        >
          {t("reportPage.backToOverview")}
        </button>
      </div>
    );
  }

  const deliveredLabel = report.delivered_at
    ? t("reportPage.deliveredOn", {
        date: new Date(report.delivered_at).toLocaleDateString(i18n.language),
      })
    : null;

  return (
    <div className="min-h-screen bg-paper text-ink">
      <div className="mx-auto max-w-4xl px-6 py-12">
        {/* Minimal authenticated chrome — no admin nav, no space switcher */}
        <div className="mb-10 flex items-center justify-between">
          <p className="font-mono text-xs uppercase tracking-widest text-ink/60">
            {t("reportPage.brand")}
          </p>
          <div className="flex items-center gap-4 font-mono text-xs uppercase tracking-wider text-ink/60">
            {session?.email && <span className="font-medium text-ink/70">{session.email}</span>}
            <button
              type="button"
              onClick={handleLogout}
              className="underline-offset-2 hover:text-ink hover:underline"
            >
              {t("reportPage.logout")}
            </button>
          </div>
        </div>

        <header className="mb-8 flex flex-wrap items-center justify-between gap-4">
          <div>
            <button
              type="button"
              onClick={() => navigate({ to: "/intake" })}
              className="font-mono text-xs uppercase tracking-wider text-ink/40 underline-offset-2 hover:text-ink hover:underline"
            >
              {t("reportPage.backToOverview")}
            </button>
            <h1 className="mt-2 font-serif text-3xl font-normal lowercase tracking-tight text-ink">
              {title || t("reportPage.heading")}
            </h1>
          </div>
          <StatusPill status="delivered" />
        </header>

        {/* Report metadata card — download-only (D-08), no embedded viewer. */}
        <section className="border border-ink bg-paper p-6 md:p-10">
          <h2 className="mb-6 font-serif text-2xl font-normal lowercase tracking-tight text-ink">
            {t("reportPage.heading")}
          </h2>

          <dl className="space-y-4">
            {report.filename && (
              <div>
                <dt className="font-mono text-[11px] uppercase tracking-wider text-ink/60">
                  {t("reportPage.download")}
                </dt>
                <dd className="mt-1 font-sans text-[15px] text-ink">{report.filename}</dd>
              </div>
            )}
            {deliveredLabel && (
              <div>
                <dd className="font-sans text-[15px] text-ink">{deliveredLabel}</dd>
              </div>
            )}
            {report.byte_size != null && (
              <div>
                <dt className="font-mono text-[11px] uppercase tracking-wider text-ink/60">
                  {t("reportPage.size")}
                </dt>
                <dd className="mt-1 font-sans text-[15px] text-ink">
                  {bytesLabel(report.byte_size)}
                </dd>
              </div>
            )}
          </dl>

          <div className="mt-8">
            <button
              type="button"
              onClick={handleDownload}
              disabled={downloading || !report.storage_path}
              className="inline-flex items-center gap-2 bg-ink px-4 py-2.5 font-mono text-xs uppercase tracking-wider text-paper hover:bg-ink/80 disabled:opacity-50"
            >
              {downloading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Download className="h-4 w-4" />
              )}
              {downloading ? t("reportPage.downloading") : t("reportPage.download")}
            </button>
          </div>
        </section>

        {/* Phase-19 Q&A chat reservation (D-07) — a static placeholder ONLY. No input,
            no message list, no chat logic, no data fetch. Layout reservation, not a feature. */}
        <section className="mt-8 border border-dashed border-ink/30 bg-paperLight p-6 md:p-8">
          <p className="font-mono text-xs uppercase tracking-wider text-ink/40">
            {t("reportPage.chatComingSoon")}
          </p>
        </section>
      </div>
    </div>
  );
}
