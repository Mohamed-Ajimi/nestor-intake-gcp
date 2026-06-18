import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { format } from "date-fns";
import { nl } from "date-fns/locale";
import { toast } from "sonner";
import { Download, Loader2 } from "lucide-react";
import { supabase } from "@/lib/supabase";
import {
  ResearchResultsPanel,
  type RRPArtifact,
  type RRPClient,
  type RRPIntake,
  type RRPQuestion,
} from "@/components/intake/ResearchResultsPanel";

export const Route = createFileRoute("/results/$token")({
  component: ResultsPage,
});

type FinalReport = {
  available: boolean;
  artifact_id?: string;
  filename?: string;
  byte_size?: number;
  mime_type?: string;
};

type RpcResult = {
  success?: boolean;
  error?: string;
  message?: string;
  intake?: RRPIntake & { created_at?: string; delivered_at?: string | null; title?: string | null };
  client?: RRPClient;
  questions?: RRPQuestion[];
  artifacts?: RRPArtifact[];
  final_report?: FinalReport;
  search_available?: boolean;
};


function bytesLabel(n: number | null | undefined) {
  if (n == null) return "";
  if (n > 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  if (n > 1024) return `${Math.round(n / 1024)} KB`;
  return `${n} B`;
}

function FinalReportDownload({
  token,
  finalReport,
}: {
  token: string;
  finalReport?: FinalReport;
}) {
  const [busy, setBusy] = useState(false);

  if (!finalReport?.available) {
    return (
      <div className="mb-8 border border-ink/30 bg-paperLight px-6 py-5">
        <p className="font-sans text-sm text-ink/70">
          Het complete rapport wordt momenteel afgewerkt. Je krijgt automatisch
          een mail zodra het beschikbaar is.
        </p>
      </div>
    );
  }

  const download = async () => {
    if (!supabase) return;
    setBusy(true);
    try {
      const { data, error } = await supabase
        .schema("nestor" as never)
        .rpc("get_final_report_by_token", { p_token: token });
      const r = data as
        | {
            success?: boolean;
            error?: string;
            message?: string;
            storage_bucket?: string;
            storage_path?: string;
            filename?: string;
          }
        | null;
      if (error || !r || r.error || r.success === false || !r.storage_path || !r.storage_bucket) {
        toast.error(r?.message || "Kon rapport niet ophalen");
        return;
      }
      const { data: signed, error: signErr } = await supabase.storage
        .from(r.storage_bucket)
        .createSignedUrl(r.storage_path, 300);
      if (signErr || !signed) {
        toast.error("Kon download-link niet maken");
        return;
      }
      const response = await fetch(signed.signedUrl);
      if (!response.ok) throw new Error("Download faalde");
      const blob = await response.blob();
      const blobUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = blobUrl;
      a.download = r.filename || "rapport";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(blobUrl);
    } catch (e) {
      toast.error(`Download mislukt: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="mb-8 border border-ink/30 border-l-4 bg-paperLight px-6 py-5"
      style={{ borderLeftColor: "#FF2D87" }}
    >
      <div
        className="mb-2 font-mono text-[11px] uppercase tracking-wider"
        style={{ color: "#FF2D87" }}
      >
        Volledig rapport
      </div>
      <p className="mb-4 font-sans text-[15px] leading-relaxed text-ink">
        Het complete onderzoeksrapport: alle vragen samengevat in één document.
      </p>
      <button
        type="button"
        onClick={download}
        disabled={busy}
        className="inline-flex items-center gap-2 bg-ink px-4 py-2 font-mono text-xs uppercase tracking-wider text-paper hover:bg-ink/85 disabled:opacity-50"
      >
        {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
        Download rapport
        {finalReport.byte_size != null && (
          <span className="opacity-70">({bytesLabel(finalReport.byte_size)})</span>
        )}
      </button>
    </div>
  );
}

function ResultsPage() {
  const { token } = Route.useParams();
  const [data, setData] = useState<RpcResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!supabase) {
        setError("Configuratie ontbreekt.");
        setLoading(false);
        return;
      }
      const { data: rpcData, error: rpcErr } = await supabase
        .schema("nestor" as never)
        .rpc("get_results_by_token", { p_token: token });
      if (cancelled) return;
      if (rpcErr) {
        setError("Ongeldige link of resultaten zijn nog niet beschikbaar.");
      } else {
        const r = rpcData as RpcResult | null;
        if (!r || r.error || r.success === false) {
          setError(r?.message || "Ongeldige link of resultaten zijn nog niet beschikbaar.");
        } else {
          setData(r);
        }
      }
      setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  if (loading) {
    return (
      <div className="min-h-screen bg-paper px-6 py-12">
        <div className="mx-auto max-w-4xl text-center font-mono text-xs uppercase tracking-wider text-ink/60">
          Laden…
        </div>
      </div>
    );
  }

  if (error || !data || !data.intake || !data.client) {
    return (
      <div className="min-h-screen bg-paper px-6 py-16">
        <div className="mx-auto max-w-xl border border-ink bg-paperLight p-8 text-center">
          <div className="font-mono text-xs uppercase tracking-wider text-ink/60">
            AGENIC × NESTOR
          </div>
          <h1 className="mt-4 font-serif text-2xl lowercase text-ink">
            Resultaten niet beschikbaar
          </h1>
          <p className="mt-3 font-sans text-sm text-ink/70">
            {error ?? "Ongeldige link of resultaten zijn nog niet beschikbaar."}
          </p>
        </div>
      </div>
    );
  }

  const intake = data.intake;
  const created = (intake as { created_at?: string }).created_at;

  return (
    <div className="min-h-screen bg-paper">
      <header className="border-b border-ink/20 px-6 py-5">
        <div className="mx-auto max-w-5xl">
          <div className="font-mono text-xs uppercase tracking-wider text-ink">
            AGENIC × NESTOR
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-5xl px-6 py-10">
        <h1 className="font-serif text-3xl lowercase text-ink">
          Research voor {data.client.name}
        </h1>
        {intake.title && (
          <p className="mt-2 font-serif text-lg italic text-ink/80">{intake.title}</p>
        )}
        {(() => {
          const delivered = (intake as { delivered_at?: string | null }).delivered_at;
          const dateStr = delivered || created;
          if (!dateStr) return null;
          return (
            <p className="mt-2 font-mono text-xs uppercase tracking-wider text-ink/50">
              Geleverd op {(() => {
                try {
                  return format(new Date(dateStr), "d MMMM yyyy", { locale: nl });
                } catch {
                  return dateStr;
                }
              })()}
            </p>
          );
        })()}

        <div className="mt-8">
          <FinalReportDownload token={token} finalReport={data.final_report} />

          <ResearchResultsPanel
            mode="klant"
            intake={intake}
            client={data.client}
            questions={data.questions ?? []}
            artifacts={[]}
            token={token}
            searchAvailable={data.search_available === true}
          />

        </div>
      </div>

      <footer className="mt-16 border-t border-ink/20 px-6 py-6">
        <div className="mx-auto max-w-5xl text-center font-mono text-xs uppercase tracking-wider text-ink/50">
          AGENIC × NESTOR — confidentieel · vragen?{" "}
          <a className="hover:text-ink" href="mailto:nestor@agenic.be">
            nestor@agenic.be
          </a>
        </div>
      </footer>
    </div>
  );
}
