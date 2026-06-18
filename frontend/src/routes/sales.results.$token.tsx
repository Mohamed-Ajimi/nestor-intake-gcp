import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import { BattlecardMarkdown } from "@/components/sales/BattlecardMarkdown";
import {
  BattlecardBlocks as BattlecardBlocksShared,
  BattlecardIntakeStrip,
} from "@/components/sales/BattlecardBlocks";


export const Route = createFileRoute("/sales/results/$token")({
  component: SalesKlantResultsPage,
});

type Source = { url: string; title?: string | null };
type Block = {
  title?: string;
  content?: string;
  sources?: Source[];
};
type Battlecard = {
  status: "queued" | "researching" | "writing" | "ready" | "failed" | string;
  blocks?: Record<string, Block> | null;
  sources?: Source[] | null;
  pdf_storage_path?: string | null;
  pdf_byte_size?: number | null;
  completed_at?: string | null;
};
type Stakeholder = { name: string; role: string; linkedin_url: string };
type Results = {
  prep_id: string;
  klant_name: string;
  klant_company: string;
  project_title?: string | null;
  prospect_company_name?: string | null;
  decision_maker_name?: string | null;
  meeting_datetime?: string | null;
  meeting_location?: string | null;
  meeting_deadline?: string | null;
  meeting_type?: string | null;
  deal_stage?: string | null;
  klant_type?: string | null;
  industry_vertical?: string | null;
  delivered_at?: string | null;
  status: string;
  additional_stakeholders?: Stakeholder[] | null;
  battlecard: Battlecard | null;
};


function fmtDateTime(s?: string | null) {
  if (!s) return "";
  try {
    return new Date(s).toLocaleString("nl-BE", {
      day: "numeric",
      month: "long",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return s;
  }
}
function fmtDate(s?: string | null) {
  if (!s) return "";
  try {
    return new Date(s).toLocaleDateString("nl-BE", {
      day: "numeric",
      month: "long",
      year: "numeric",
    });
  } catch {
    return s;
  }
}

function CenteredLoading() {
  return (
    <div className="min-h-screen flex items-center justify-center text-ink/50 font-mono text-xs bg-paper">
      Laden...
    </div>
  );
}
function CenteredError({ text }: { text: string }) {
  return (
    <div className="min-h-screen flex items-center justify-center bg-paper">
      <div className="text-center max-w-md px-8">
        <div className="font-serif text-4xl mb-4">⌀</div>
        <p className="text-ink/70">{text}</p>
      </div>
    </div>
  );
}

function InProgressBlock({
  battlecardStatus,
  onRefresh,
}: {
  battlecardStatus?: string;
  onRefresh: () => void;
}) {
  const stageLabels: Record<string, string> = {
    queued: "In wachtrij",
    researching: "Research aan de gang",
    writing: "Battlecard wordt geschreven",
    failed: "Iets ging mis",
    pending: "Nog niet gestart",
  };
  const stage = stageLabels[battlecardStatus || "pending"] || "Bezig...";

  return (
    <section className="border-l-4 border-amber-500 bg-amber-50 p-6 mb-8">
      <div className="font-mono text-[10px] uppercase tracking-wider text-amber-700 mb-2">
        Research loopt
      </div>
      <p className="text-lg mb-3">{stage}</p>
      <p className="text-sm text-ink/70 mb-4">
        Je battlecard wordt voor je voorbereid. Dit duurt typisch enkele uren
        tot een dag. Je krijgt een mail zodra hij klaar is.
      </p>
      <button
        onClick={onRefresh}
        className="font-mono text-xs uppercase tracking-wider border border-ink/30 px-3 py-2 hover:bg-ink hover:text-paper"
      >
        ↻ Status verversen
      </button>
    </section>
  );
}

function DownloadBlock({
  bc,
  downloading,
  onDownload,
}: {
  bc: Battlecard;
  downloading: boolean;
  onDownload: () => void;
}) {
  const sizeKb = bc.pdf_byte_size ? Math.round(bc.pdf_byte_size / 1024) : null;
  return (
    <section
      className="border border-ink/30 border-l-4 bg-paperLight p-6 mb-8"
      style={{ borderLeftColor: "#FF2D87" }}
    >
      <div
        className="font-mono text-[10px] uppercase tracking-wider mb-2"
        style={{ color: "#FF2D87" }}
      >
        Battlecard klaar
      </div>
      <p className="text-sm mb-4">
        Download het complete document: 10 strategische blokken,
        decision-maker profiel, talking points en risk-flags.
      </p>
      {bc.pdf_storage_path ? (
        <button
          onClick={onDownload}
          disabled={downloading}
          className="bg-ink text-paper font-mono text-xs uppercase tracking-wider px-6 py-3 disabled:opacity-50 hover:bg-ink/90"
        >
          {downloading
            ? "Bezig..."
            : `↓ Download battlecard${sizeKb ? ` (${sizeKb} KB)` : ""}`}
        </button>
      ) : (
        <p className="text-xs text-ink/50 italic">
          PDF wordt nog gegenereerd. Probeer over enkele minuten opnieuw.
        </p>
      )}
    </section>
  );
}

// Local BattlecardBlocks removed — using shared BattlecardBlocksShared from components/sales.

function SourcesBlock({ sources }: { sources: Source[] }) {
  return (
    <section className="border-t border-ink/20 pt-6 mt-8">
      <div className="font-mono text-[10px] uppercase tracking-wider text-ink/60 mb-3">
        Geraadpleegde bronnen ({sources.length})
      </div>
      <ul className="text-xs space-y-1">
        {sources.map((s, i) => (
          <li key={i}>
            <a
              href={s.url}
              target="_blank"
              rel="noopener noreferrer"
              className="underline text-ink/70 hover:text-ink break-all"
            >
              {s.title || s.url}
            </a>
          </li>
        ))}
      </ul>
    </section>
  );
}

function SalesKlantResultsPage() {
  const { token } = Route.useParams();
  const [data, setData] = useState<Results | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);

  async function loadResults() {
    if (!supabase) {
      setError("Supabase niet geconfigureerd.");
      setLoading(false);
      return;
    }
    setLoading(true);
    const { data: result, error: err } = await supabase
      .schema("sales" as never)
      .rpc("get_results_by_token", { p_token: token });
    if (err || !result) {
      setError("Deze link is niet meer geldig.");
      setData(null);
      setLoading(false);
      return;
    }
    setData(result as Results);
    setError(null);
    setLoading(false);
  }

  useEffect(() => {
    loadResults();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  async function handleDownload() {
    if (!supabase || !data?.battlecard?.pdf_storage_path) return;
    setDownloading(true);
    try {
      const { data: signed, error: signErr } = await supabase.storage
        .from("sales-battlecards")
        .createSignedUrl(data.battlecard.pdf_storage_path, 300);
      if (signErr || !signed?.signedUrl) {
        alert("Download faalde — probeer opnieuw");
        return;
      }
      const response = await fetch(signed.signedUrl);
      const blob = await response.blob();
      const blobUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = blobUrl;
      a.download = `Battlecard — ${data.prospect_company_name || "prospect"}.pdf`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(blobUrl);
    } finally {
      setDownloading(false);
    }
  }

  if (loading) return <CenteredLoading />;
  if (error && !data) return <CenteredError text={error} />;
  if (!data) return <CenteredError text="Onbekende fout." />;

  const bc = data.battlecard;
  const ready = data.status === "geleverd" && bc?.status === "ready";

  return (
    <div className="min-h-screen bg-paper text-ink">
      <div className="border-b border-ink/20 px-8 py-4">
        <div className="font-mono text-[10px] uppercase tracking-wider text-pink-500">
          Nestor Sales — Battlecard
        </div>
        <div className="font-serif text-xl">AGENIC</div>
      </div>

      <div className="max-w-4xl mx-auto px-8 py-10">
        <h1 className="font-serif text-4xl mb-2 lowercase">
          dag {data.klant_name}
        </h1>
        <p className="text-ink/70 mb-8">
          Je battlecard voor de meeting met{" "}
          <strong>{data.prospect_company_name}</strong>
          {data.decision_maker_name && <> ({data.decision_maker_name})</>}.
        </p>

        <section className="border border-ink/20 bg-paperLight p-6 mb-8">
          <div className="font-mono text-[10px] uppercase tracking-wider text-ink/60 mb-3">
            Project-info
          </div>
          <dl className="grid grid-cols-[160px_1fr] gap-y-2 text-sm">
            <dt className="text-ink/60">Prospect</dt>
            <dd>{data.prospect_company_name || "—"}</dd>
            {data.decision_maker_name && (
              <>
                <dt className="text-ink/60">Decision maker</dt>
                <dd>{data.decision_maker_name}</dd>
              </>
            )}
            {data.meeting_datetime && (
              <>
                <dt className="text-ink/60">Meeting</dt>
                <dd>{fmtDateTime(data.meeting_datetime)}</dd>
              </>
            )}
            {data.delivered_at && (
              <>
                <dt className="text-ink/60">Geleverd</dt>
                <dd>{fmtDate(data.delivered_at)}</dd>
              </>
            )}
          </dl>
          {((data.additional_stakeholders?.length ?? 0) > 0 ||
            data.meeting_deadline) && (
            <div className="mt-3 pt-3 border-t border-ink/10 text-xs text-ink/60">
              {(data.additional_stakeholders?.length ?? 0) > 0 && (
                <span className="mr-4">
                  <strong>
                    {(data.additional_stakeholders?.length ?? 0) + 1}
                  </strong>{" "}
                  personen aan tafel
                </span>
              )}
              {data.meeting_deadline && (
                <span>Deadline: {data.meeting_deadline}</span>
              )}
            </div>
          )}
        </section>



        {!ready && (
          <InProgressBlock
            battlecardStatus={bc?.status}
            onRefresh={loadResults}
          />
        )}

        {ready && bc && (
          <>
            <DownloadBlock
              bc={bc}
              downloading={downloading}
              onDownload={handleDownload}
            />
            {bc.blocks && (
              <>
                <BattlecardIntakeStrip prep={data} />
                <BattlecardBlocksShared blocks={bc.blocks} />
              </>
            )}
            {bc.sources && bc.sources.length > 0 && (
              <SourcesBlock sources={bc.sources} />
            )}
          </>
        )}
      </div>
    </div>
  );
}
