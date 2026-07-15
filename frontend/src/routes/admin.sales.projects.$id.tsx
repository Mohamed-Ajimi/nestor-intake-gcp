import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useState, type ReactNode } from "react";
import { formatDistanceToNow, format } from "date-fns";
import { nl } from "date-fns/locale";
import { Copy, Check, Pencil, Zap, ArrowRight, AlertCircle, Mail } from "lucide-react";
import { sendSalesMail } from "@/lib/salesMail";
import { supabase } from "@/lib/supabase";
import { BattlecardMarkdown } from "@/components/sales/BattlecardMarkdown";
import {
  BattlecardBlocks,
  BattlecardIntakeStrip,
} from "@/components/sales/BattlecardBlocks";
import { generateBattlecardPdf } from "@/utils/generateBattlecardPdf";
import { SalesStatusBadge } from "./admin.sales.projects.index";
import {
  SalesContextFields,
  type SalesContextValues,
} from "@/components/sales/SalesContextFields";

import {
  meetingTypeLabel,
  dealStageLabel,
  klantTypeLabel,
  type Stakeholder,
} from "@/lib/salesLabels";



export const Route = createFileRoute("/admin/sales/projects/$id")({
  component: SalesProjectDetailPage,
});

type Prep = {
  id: string;
  status: string;
  klant_name: string;
  klant_email: string;
  klant_company: string;
  klant_role: string | null;
  project_title: string | null;
  intake_token: string;
  validation_token: string;
  results_token: string;
  intake_sent_at: string | null;
  submitted_by_klant_at: string | null;
  validation_sent_at: string | null;
  validated_by_klant_at: string | null;
  research_started_at: string | null;
  delivered_at: string | null;
  created_at: string;
  prospect_company_name: string | null;
  prospect_company_url: string | null;
  prospect_sector: string | null;
  decision_maker_name: string | null;
  decision_maker_role: string | null;
  decision_maker_linkedin_url: string | null;
  meeting_datetime: string | null;
  meeting_location: string | null;
  meeting_agenda: string | null;
  sales_objective: string | null;
  relationship_status: string | null;
  hypotheses: string | null;
  sales_method: string | null;
  meeting_type: string | null;
  deal_stage: string | null;
  klant_type: string | null;
  industry_vertical: string | null;
  product_offering: string | null;
  competitors: string | null;
  meeting_deadline: string | null;
  biggest_concern: string | null;
  specific_question: string | null;
  prior_contact_summary: string | null;
  geography_culture: string | null;
  additional_stakeholders: Stakeholder[] | null;
};

type Battlecard = {
  status: string;
  raw_markdown: string | null;
  generation_error: string | null;
  blocks?: Record<string, { title?: string; content?: string; category?: string; subsections?: Array<{ title?: string; content?: string }> }> | null;
  pdf_storage_path?: string | null;
  pdf_byte_size?: number | null;
  pdf_generated_at?: string | null;
} | null;

function fmtDate(s: string | null | undefined) {
  if (!s) return "—";
  try {
    return format(new Date(s), "d MMM yyyy 'om' HH:mm", { locale: nl });
  } catch {
    return s;
  }
}

function fmtRel(s: string | null | undefined) {
  if (!s) return "";
  try {
    return formatDistanceToNow(new Date(s), { addSuffix: true, locale: nl });
  } catch {
    return "";
  }
}

function SalesProjectDetailPage() {
  const { id } = Route.useParams();
  const navigate = useNavigate();
  const [data, setData] = useState<{ prep: Prep | null; battlecard: Battlecard } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function loadProject() {
    if (!supabase) {
      setError("Supabase niet geconfigureerd.");
      setLoading(false);
      return;
    }
    setLoading(true);
    const { data: result, error: rpcErr } = await supabase
      .schema("sales" as never)
      .rpc("get_project", { p_id: id });
    if (rpcErr) {
      setError(rpcErr.message);
      setData(null);
    } else {
      setData(result as { prep: Prep | null; battlecard: Battlecard });
      setError(null);
    }
    setLoading(false);
  }

  useEffect(() => {
    loadProject();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  if (loading) {
    return <p className="font-mono text-xs uppercase tracking-wider text-ink/50">Laden…</p>;
  }
  if (error) {
    return (
      <div className="border border-red-500/40 bg-red-500/5 px-3 py-2 font-mono text-xs text-red-700">
        {error}
      </div>
    );
  }
  if (!data?.prep) {
    return (
      <div>
        <p className="text-sm text-ink/60">Project niet gevonden.</p>
        <button
          onClick={() => navigate({ to: "/admin/sales/projects" })}
          className="mt-4 font-mono text-xs uppercase tracking-wider text-ink/60 hover:text-ink"
        >
          ← Terug naar projecten
        </button>
      </div>
    );
  }

  const prep = data.prep;
  const battlecard = data.battlecard;

  return (
    <div>
      <Link
        to="/admin/sales/projects"
        className="mb-3 block font-mono text-xs uppercase tracking-wider text-ink/60 hover:text-ink"
      >
        ← Terug naar projecten
      </Link>

      <div className="mb-2 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="font-serif text-3xl font-normal lowercase tracking-tight text-ink">
            {prep.klant_name} — {prep.klant_company}
          </h1>
          {prep.project_title && (
            <p className="mt-1 text-sm text-ink/60">{prep.project_title}</p>
          )}
        </div>
        {battlecard && ["in_onderzoek", "geleverd"].includes(prep.status) && (
          <RegenerateBattlecardButton prepId={prep.id} onChange={loadProject} />
        )}
      </div>

      <SalesStatusTracker prep={prep} />

      <NextStepBanner prep={prep} battlecard={battlecard} onChange={loadProject} />

      <ProjectInfoSection prep={prep} />

      {prep.status !== "concept" && (
        <>
          <SalesContextSection prep={prep} onChange={loadProject} />
          <MeetingPrepSection prep={prep} onChange={loadProject} />
        </>
      )}


      {["in_onderzoek", "geleverd"].includes(prep.status) && (
        <BattlecardSection battlecard={battlecard} prep={prep} />
      )}

    </div>
  );
}

function fmtShort(d: string | null | undefined) {
  if (!d) return "";
  try {
    return new Date(d).toLocaleDateString("nl-BE", { day: "numeric", month: "short" });
  } catch {
    return "";
  }
}

function SalesStatusTracker({ prep }: { prep: Prep }) {
  const steps = [
    { key: "concept", label: "Aangemaakt", date: prep.created_at },
    { key: "intake_sent", label: "Intake verstuurd", date: prep.intake_sent_at },
    { key: "submitted", label: "Klant ingediend", date: prep.submitted_by_klant_at },
    { key: "reviewed", label: "Gereviewd", date: prep.validation_sent_at },
    { key: "validated", label: "Klant gevalideerd", date: prep.validated_by_klant_at },
    { key: "in_research", label: "In onderzoek", date: prep.research_started_at },
    { key: "delivered", label: "Geleverd", date: prep.delivered_at },
  ];
  let currentIdx = -1;
  steps.forEach((s, i) => {
    if (s.date) currentIdx = i;
  });
  return (
    <div className="my-6 border-y border-ink/15 bg-paperLight px-2 py-6">
      <div className="grid grid-cols-7 gap-2">
        {steps.map((s, i) => {
          const isCurrent = i === currentIdx;
          const isDone = !!s.date && !isCurrent;
          const isFuture = !s.date;
          return (
            <div key={s.key} className="flex flex-col items-center text-center">
              <div
                className={
                  "mb-3 h-4 w-4 " +
                  (isCurrent
                    ? "bg-agenic-green"
                    : isDone
                    ? "bg-ink"
                    : "border border-ink/30 bg-transparent")
                }
              />
              <div
                className={
                  "font-mono text-[10px] uppercase tracking-wider leading-tight " +
                  (isFuture ? "text-ink/35" : "text-ink/70")
                }
              >
                {s.label}
              </div>
              {s.date && (
                <div className="mt-1 font-mono text-[10px] text-ink/40">
                  {fmtShort(s.date)}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function InlineCopyLink({ url }: { url: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <code className="bg-ink/5 px-2 py-1 font-mono text-xs break-all">{url}</code>
      <button
        type="button"
        onClick={() => {
          navigator.clipboard.writeText(url);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        }}
        className="text-xs underline hover:text-ink"
      >
        {copied ? "Gekopieerd" : "Kopieer"}
      </button>
    </span>
  );
}

function ProjectInfoSection({ prep }: { prep: Prep }) {
  const baseUrl = typeof window !== "undefined" ? window.location.origin : "";
  const intakeLink = `${baseUrl}/sales/intake/${prep.intake_token}`;
  const validationLink = `${baseUrl}/sales/validate/${prep.validation_token}`;
  const resultsLink = `${baseUrl}/sales/results/${prep.results_token}`;

  const rows: Array<{ label: string; value: ReactNode; hint?: string }> = [
    {
      label: "Klant",
      value: (
        <>
          {prep.klant_name}
          {prep.klant_role && <span className="text-ink/60"> — {prep.klant_role}</span>}
        </>
      ),
    },
    {
      label: "Email",
      value: (
        <a href={`mailto:${prep.klant_email}`} className="underline">
          {prep.klant_email}
        </a>
      ),
    },
    { label: "Bedrijf", value: prep.klant_company },
    {
      label: "Product",
      value: (
        <>
          Nestor Sales <span className="text-ink/50">(Sales-prep)</span>
        </>
      ),
    },
    { label: "Status", value: <SalesStatusBadge status={prep.status} /> },
    { label: "Aangemaakt", value: fmtDate(prep.created_at) },
  ];

  if (prep.delivered_at) {
    rows.push({ label: "Geleverd op", value: fmtDate(prep.delivered_at) });
  }
  if (prep.intake_sent_at) {
    rows.push({
      label: "Intake-link",
      value: <InlineCopyLink url={intakeLink} />,
      hint: "Werkt zolang status = Concept of Ingediend",
    });
  }
  if (prep.validation_sent_at) {
    rows.push({
      label: "Validatie-link",
      value: <InlineCopyLink url={validationLink} />,
      hint: "Werkt nadat je 'Stuur voor klant-validatie' klikte",
    });
  }
  if (prep.status === "geleverd") {
    rows.push({
      label: "Klant-resultaten-link",
      value: <InlineCopyLink url={resultsLink} />,
      hint: "Werkt zodra status = Geleverd",
    });
  }

  return (
    <section className="mb-6 border border-ink/20 bg-paperLight">
      <div className="border-b border-ink/15 px-6 py-3 font-mono text-[10px] uppercase tracking-wider text-ink/60">
        Project-info
      </div>
      <dl>
        {rows.map((r, i) => (
          <div
            key={i}
            className={
              "grid grid-cols-[220px_1fr] gap-6 px-6 py-3 text-sm" +
              (i < rows.length - 1 ? " border-b border-ink/10" : "")
            }
          >
            <dt className="text-ink/60">{r.label}</dt>
            <dd>
              <div>{r.value}</div>
              {r.hint && (
                <div className="mt-1 font-mono text-[10px] uppercase tracking-wider text-ink/40">
                  {r.hint}
                </div>
              )}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function NextStepBanner({
  prep,
  battlecard,
  onChange,
}: {
  prep: Prep;
  battlecard: Battlecard;
  onChange: () => void;
}) {
  const [busy, setBusy] = useState(false);

  async function callRpc(name: string, confirmMsg?: string) {
    if (confirmMsg && !window.confirm(confirmMsg)) return;
    if (!supabase) return;
    setBusy(true);
    const { error } = await supabase.schema("sales" as never).rpc(name, { p_id: prep.id });
    setBusy(false);
    if (error) {
      alert(`Faalde: ${error.message}`);
      return;
    }
    onChange();
  }

  async function handleDeliverWithPdf() {
    if (!supabase) {
      alert("Supabase client niet beschikbaar");
      return;
    }
    if (!window.confirm("PDF genereren en project op GELEVERD zetten?")) return;
    setBusy(true);

    try {
      console.log("[PDF] Start generation for prep:", prep.id);

      const blob = await generateBattlecardPdf(
        prep as unknown as Record<string, unknown>,
        battlecard as { blocks?: Record<string, { title?: string; content?: string; category?: string }> },
      );
      console.log("[PDF] Generated blob:", blob.size, "bytes");

      const filename = `${prep.id}/battlecard-${Date.now()}.pdf`;
      const { error: uploadError } = await supabase.storage
        .from("sales-battlecards")
        .upload(filename, blob, {
          contentType: "application/pdf",
          upsert: true,
        });
      if (uploadError) {
        console.error("[PDF] Upload error:", uploadError);
        alert(`Upload faalde: ${uploadError.message}`);
        setBusy(false);
        return;
      }
      console.log("[PDF] Uploaded to:", filename);

      const { error: rpcError } = await supabase
        .schema("sales" as never)
        .rpc("admin_save_pdf", {
          p_id: prep.id,
          p_storage_path: filename,
          p_byte_size: blob.size,
          p_mark_delivered: true,
        });
      if (rpcError) {
        console.error("[PDF] RPC error:", rpcError);
        alert(`DB-save faalde: ${rpcError.message}`);
        setBusy(false);
        return;
      }
      console.log("[PDF] Saved to DB + marked delivered");

      alert("PDF opgeslagen ✓ — project staat nu op GELEVERD");
      onChange();
    } catch (err) {
      console.error("[PDF] Unexpected error:", err);
      alert(
        `Onverwachte fout: ${(err as Error).message}\n\nCheck browser console (F12) voor details.`,
      );
    } finally {
      setBusy(false);
    }
  }

  const baseUrl = typeof window !== "undefined" ? window.location.origin : "";

  let description: ReactNode = null;
  let actions: ReactNode = null;

  const btnPrimary =
    "inline-flex items-center gap-1.5 bg-ink px-4 py-2 font-mono text-xs uppercase tracking-wider text-paper hover:bg-ink/85 disabled:opacity-50";
  const btnSecondary =
    "inline-flex items-center gap-1.5 border border-ink bg-transparent px-4 py-2 font-mono text-xs uppercase tracking-wider text-ink hover:border-2 disabled:opacity-50";

  function copy(url: string) {
    navigator.clipboard.writeText(url);
  }

  async function sendMail(
    mailType: "intake" | "validation" | "results",
    confirmMsg: string,
    successMsg: string,
  ) {
    if (!window.confirm(confirmMsg)) return;
    setBusy(true);
    const result = await sendSalesMail(prep.id, mailType);
    setBusy(false);
    if (!result.success) {
      alert(`Mail-versturen faalde: ${result.error}`);
      return;
    }
    alert(successMsg);
    onChange();
  }

  switch (prep.status) {
    case "concept":
      description = (
        <>
          Stuur de intake-link naar <strong>{prep.klant_name}</strong> ({prep.klant_email}).
        </>
      );
      actions = (
        <>
          <button
            disabled={busy}
            onClick={() =>
              sendMail(
                "intake",
                `Verstuur intake-mail naar ${prep.klant_email}?`,
                "Intake-mail verstuurd ✓",
              )
            }
            className={btnPrimary}
          >
            <Mail className="h-3.5 w-3.5" />
            {busy
              ? "Bezig…"
              : prep.intake_sent_at
                ? "↻ Verstuur opnieuw"
                : "Verstuur intake-mail"}
          </button>
          <button
            onClick={() => copy(`${baseUrl}/sales/intake/${prep.intake_token}`)}
            className={btnSecondary}
          >
            <Copy className="h-3.5 w-3.5" />
            Kopieer link
          </button>
          {prep.intake_sent_at && (
            <span className="ml-1 font-mono text-[11px] text-ink/60">
              Laatst verstuurd op {fmtDate(prep.intake_sent_at)}
            </span>
          )}
        </>
      );
      break;
    case "ingediend":
      description = (
        <>
          {prep.klant_name} heeft de intake ingevuld op{" "}
          {fmtDate(prep.submitted_by_klant_at)}. Review onderaan en stuur dan voor
          validatie.
        </>
      );
      actions = (
        <button
          disabled={busy}
          onClick={() =>
            callRpc("send_for_validation", "Stuur intake naar klant voor validatie?")
          }
          className={btnPrimary}
        >
          <ArrowRight className="h-3.5 w-3.5" />
          Stuur voor klant-validatie
        </button>
      );
      break;
    case "gereviewd":
      description = (
        <>
          Wachten op klant-validatie. Stuur de validatie-link naar {prep.klant_name}.
        </>
      );
      actions = (
        <>
          <button
            disabled={busy}
            onClick={() =>
              sendMail(
                "validation",
                `Verstuur validatie-mail naar ${prep.klant_email}?`,
                "Validatie-mail verstuurd ✓",
              )
            }
            className={btnPrimary}
          >
            <Mail className="h-3.5 w-3.5" />
            {busy
              ? "Bezig…"
              : prep.validation_sent_at
                ? "↻ Verstuur opnieuw"
                : "Verstuur validatie-mail"}
          </button>
          <button
            onClick={() => copy(`${baseUrl}/sales/validate/${prep.validation_token}`)}
            className={btnSecondary}
          >
            <Copy className="h-3.5 w-3.5" />
            Kopieer link
          </button>
          {prep.validation_sent_at && (
            <span className="ml-1 font-mono text-[11px] text-ink/60">
              Laatst verstuurd op {fmtDate(prep.validation_sent_at)}
            </span>
          )}
        </>
      );
      break;
    case "gevalideerd":
      description = (
        <>
          {prep.klant_name} heeft gevalideerd op {fmtDate(prep.validated_by_klant_at)}.
          Tijd om de battlecard te genereren.
        </>
      );
      actions = (
        <button
          disabled={busy}
          onClick={async () => {
            if (!supabase) return;
            if (!window.confirm("Start de research voor deze battlecard?")) return;
            setBusy(true);
            const { error: rpcError } = await supabase
              .schema("sales" as never)
              .rpc("start_research", { p_id: prep.id });
            if (rpcError) {
              setBusy(false);
              alert(`Kon research niet starten: ${rpcError.message}`);
              return;
            }
            const { error: fnError } = await supabase.functions.invoke(
              "generate-battlecard",
              { body: { prep_id: prep.id } },
            );
            setBusy(false);
            if (fnError) {
              alert(
                `RPC OK maar Edge Function faalde: ${fnError.message}\n` +
                  `Status zit op in_onderzoek maar generatie is niet gestart. ` +
                  `Reset eventueel manueel of probeer opnieuw.`,
              );
              return;
            }
            alert(
              "Research gestart. Duurt ~90 seconden. Je krijgt een mail wanneer klaar.",
            );
            onChange();
          }}
          className={btnPrimary}
        >
          <Zap className="h-3.5 w-3.5" />
          Start research
        </button>
      );
      break;
    case "in_onderzoek": {
      const bcStatus = battlecard?.status || "queued";
      if (bcStatus === "ready") {
        description = (
          <>
            Battlecard is gegenereerd. Review onderaan en lever aan klant. Bij leveren
            wordt automatisch een PDF aangemaakt.
          </>
        );
        actions = (
          <button disabled={busy} onClick={handleDeliverWithPdf} className={btnPrimary}>
            <Check className="h-3.5 w-3.5" />
            {busy ? "Bezig met PDF + leveren…" : "Genereer PDF + lever aan klant"}
          </button>
        );
      } else if (bcStatus === "failed") {
        description = (
          <span className="inline-flex items-center gap-2 text-red-700">
            <AlertCircle className="h-4 w-4" />
            Research mislukt: {battlecard?.generation_error || "onbekende fout"}
          </span>
        );
      } else {
        description = (
          <>
            Research loopt — battlecard status:{" "}
            <strong>{bcStatus.toUpperCase()}</strong>
            {prep.research_started_at && <> · gestart {fmtRel(prep.research_started_at)}</>}
          </>
        );
      }
      break;
    }
    case "geleverd":
      description = (
        <>
          Klant heeft toegang tot de battlecard sinds {fmtDate(prep.delivered_at)}.
        </>
      );
      actions = (
        <>
          <button
            disabled={busy}
            onClick={() =>
              sendMail(
                "results",
                `Verstuur leverings-mail naar ${prep.klant_email}?`,
                "Leverings-mail verstuurd ✓",
              )
            }
            className={btnPrimary}
          >
            <Mail className="h-3.5 w-3.5" />
            {busy ? "Bezig…" : "Verstuur leverings-mail naar klant"}
          </button>
          <button
            onClick={() => copy(`${baseUrl}/sales/results/${prep.results_token}`)}
            className={btnSecondary}
          >
            <Copy className="h-3.5 w-3.5" />
            Kopieer link
          </button>
        </>
      );
      break;
    default:
      return null;
  }

  return (
    <section
      className="mb-5 border border-ink/30 border-l-4 bg-paperLight px-6 py-5"
      style={{ borderLeftColor: "#FF2D87" }}
    >
      <div
        className="mb-2 font-mono text-[11px] uppercase tracking-wider"
        style={{ color: "#FF2D87" }}
      >
        Volgende stap
      </div>
      <div className="mb-4 font-sans text-[15px] leading-relaxed text-ink">
        {description}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </section>
  );
}

const FIELDS: Array<{ key: keyof Prep; label: string; type?: "textarea" | "datetime-local" | "text" }> = [
  { key: "prospect_company_name", label: "Bedrijfsnaam prospect" },
  { key: "prospect_company_url", label: "Website prospect" },
  { key: "prospect_sector", label: "Sector" },
  { key: "decision_maker_name", label: "Decision-maker naam" },
  { key: "decision_maker_role", label: "Rol" },
  { key: "decision_maker_linkedin_url", label: "LinkedIn URL" },
  { key: "meeting_datetime", label: "Meeting datum/tijd", type: "datetime-local" },
  { key: "meeting_location", label: "Locatie" },
  { key: "meeting_agenda", label: "Agenda", type: "textarea" },
  { key: "meeting_deadline", label: "Tijdsdruk / deadline" },
  { key: "sales_objective", label: "Sales-doel", type: "textarea" },
  { key: "product_offering", label: "Wat verkoop je / aanbod", type: "textarea" },
  { key: "hypotheses", label: "Hypotheses", type: "textarea" },
  { key: "competitors", label: "Concurrenten / incumbents", type: "textarea" },
  { key: "prior_contact_summary", label: "Voorgaande contact-historiek", type: "textarea" },
  { key: "biggest_concern", label: "Grootste angst", type: "textarea" },
  { key: "specific_question", label: "Specifieke vraag", type: "textarea" },
  { key: "geography_culture", label: "Geografie / cultuur" },
  { key: "relationship_status", label: "Relatie-status" },
  { key: "sales_method", label: "Sales-methode" },
];

function MeetingPrepSection({ prep, onChange }: { prep: Prep; onChange: () => void }) {
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const editable = ["ingediend", "gereviewd"].includes(prep.status);

  const buildLocal = () => ({
    prospect_company_name: prep.prospect_company_name || "",
    prospect_company_url: prep.prospect_company_url || "",
    prospect_sector: prep.prospect_sector || "",
    decision_maker_name: prep.decision_maker_name || "",
    decision_maker_role: prep.decision_maker_role || "",
    decision_maker_linkedin_url: prep.decision_maker_linkedin_url || "",
    meeting_datetime: prep.meeting_datetime ? prep.meeting_datetime.slice(0, 16) : "",
    meeting_location: prep.meeting_location || "",
    meeting_agenda: prep.meeting_agenda || "",
    meeting_deadline: prep.meeting_deadline || "",
    sales_objective: prep.sales_objective || "",
    product_offering: prep.product_offering || "",
    hypotheses: prep.hypotheses || "",
    competitors: prep.competitors || "",
    prior_contact_summary: prep.prior_contact_summary || "",
    biggest_concern: prep.biggest_concern || "",
    specific_question: prep.specific_question || "",
    geography_culture: prep.geography_culture || "",
    relationship_status: prep.relationship_status || "",
    sales_method: prep.sales_method || "",
    additional_stakeholders: Array.isArray(prep.additional_stakeholders)
      ? prep.additional_stakeholders
      : ([] as Stakeholder[]),
  });

  const [local, setLocal] = useState(buildLocal());

  function startEdit() {
    setLocal(buildLocal());
    setEditing(true);
  }

  const addStakeholder = () =>
    setLocal((s) => ({
      ...s,
      additional_stakeholders: [
        ...s.additional_stakeholders,
        { name: "", role: "", linkedin_url: "" },
      ],
    }));
  const updateStakeholder = (
    idx: number,
    field: keyof Stakeholder,
    value: string,
  ) =>
    setLocal((s) => ({
      ...s,
      additional_stakeholders: s.additional_stakeholders.map((sh, i) =>
        i === idx ? { ...sh, [field]: value } : sh,
      ),
    }));
  const removeStakeholder = (idx: number) =>
    setLocal((s) => ({
      ...s,
      additional_stakeholders: s.additional_stakeholders.filter(
        (_, i) => i !== idx,
      ),
    }));

  async function save() {
    if (!supabase) return;
    setSaving(true);
    const cleanStakeholders = local.additional_stakeholders.filter(
      (s) => s.name.trim() || s.role.trim() || s.linkedin_url.trim(),
    );
    const { error } = await supabase.schema("sales" as never).rpc("admin_update_intake", {
      p_id: prep.id,
      p_prospect_company_name: local.prospect_company_name || null,
      p_prospect_company_url: local.prospect_company_url || null,
      p_prospect_sector: local.prospect_sector || null,
      p_decision_maker_name: local.decision_maker_name || null,
      p_decision_maker_role: local.decision_maker_role || null,
      p_decision_maker_linkedin_url: local.decision_maker_linkedin_url || null,
      p_meeting_datetime: local.meeting_datetime
        ? new Date(local.meeting_datetime).toISOString()
        : null,
      p_meeting_location: local.meeting_location || null,
      p_meeting_agenda: local.meeting_agenda || null,
      p_sales_objective: local.sales_objective || null,
      p_relationship_status: local.relationship_status || null,
      p_hypotheses: local.hypotheses || null,
      p_sales_method: local.sales_method || null,
      p_meeting_type: prep.meeting_type,
      p_deal_stage: prep.deal_stage,
      p_klant_type: prep.klant_type,
      p_industry_vertical: prep.industry_vertical,
      p_product_offering: local.product_offering || null,
      p_competitors: local.competitors || null,
      p_meeting_deadline: local.meeting_deadline || null,
      p_biggest_concern: local.biggest_concern || null,
      p_specific_question: local.specific_question || null,
      p_prior_contact_summary: local.prior_contact_summary || null,
      p_geography_culture: local.geography_culture || null,
      p_additional_stakeholders: cleanStakeholders,
    });
    setSaving(false);
    if (error) {
      alert(`Opslaan faalde: ${error.message}`);

      return;
    }
    setEditing(false);
    onChange();
  }

  return (
    <section className="mb-6 border border-ink/20 p-6">
      <div className="mb-4 flex items-center justify-between">
        <div className="font-mono text-[10px] uppercase tracking-wider text-ink/60">
          Meeting-prep details
        </div>
        {editable &&
          (editing ? (
            <div className="flex gap-2">
              <button
                onClick={() => setEditing(false)}
                className="font-mono text-xs uppercase tracking-wider text-ink/60 hover:text-ink"
              >
                Annuleer
              </button>
              <button
                onClick={save}
                disabled={saving}
                className="bg-ink px-3 py-1 font-mono text-xs uppercase tracking-wider text-paper hover:bg-ink/90 disabled:opacity-50"
              >
                {saving ? "Opslaan…" : "Opslaan"}
              </button>
            </div>
          ) : (
            <button
              onClick={startEdit}
              className="inline-flex items-center gap-1.5 border border-ink/30 px-3 py-1 font-mono text-xs uppercase tracking-wider hover:bg-ink hover:text-paper"
            >
              <Pencil className="h-3 w-3" />
              Bewerken
            </button>
          ))}
      </div>

      {!editing ? (
        <dl className="grid grid-cols-[200px_1fr] gap-y-3 text-sm">
          {FIELDS.map(({ key, label, type }) => {
            const v = prep[key] as string | null;
            let display: ReactNode = v || <span className="text-ink/30">—</span>;
            if (v && type === "datetime-local") display = fmtDate(v);
            if (v && key === "prospect_company_url") {
              display = (
                <a href={v} target="_blank" rel="noreferrer" className="underline">
                  {v}
                </a>
              );
            }
            if (v && key === "decision_maker_linkedin_url") {
              display = (
                <a href={v} target="_blank" rel="noreferrer" className="underline">
                  {v}
                </a>
              );
            }
            return (
              <div key={key} className="contents">
                <dt className="text-ink/60">{label}</dt>
                <dd className="whitespace-pre-wrap">{display}</dd>
              </div>
            );
          })}
        </dl>
      ) : (
        <div className="space-y-4">
          {FIELDS.map(({ key, label, type }) => (
            <label key={key} className="block">
              <span className="block font-mono text-[11px] uppercase tracking-wider text-ink/70">
                {label}
              </span>
              {type === "textarea" ? (
                <textarea
                  value={(local[key as keyof typeof local] as string) || ""}
                  onChange={(e) =>
                    setLocal((s) => ({ ...s, [key]: e.target.value }))
                  }
                  rows={3}
                  className="mt-1.5 w-full border border-ink/30 bg-paper px-3 py-2 font-mono text-sm"
                />
              ) : (
                <input
                  type={type || "text"}
                  value={(local[key as keyof typeof local] as string) || ""}
                  onChange={(e) =>
                    setLocal((s) => ({ ...s, [key]: e.target.value }))
                  }
                  className="mt-1.5 w-full border border-ink/30 bg-paper px-3 py-2 font-mono text-sm"
                />
              )}
            </label>
          ))}

          {/* Extra stakeholders editor */}
          <div className="pt-4 border-t border-ink/15">
            <div className="mb-3 font-mono text-[11px] uppercase tracking-wider text-ink/70">
              Extra stakeholders ({local.additional_stakeholders.length})
            </div>
            {local.additional_stakeholders.map((s, idx) => (
              <div
                key={idx}
                className="mb-3 border-l-2 border-ink/20 pl-4 space-y-2"
              >
                <div className="flex items-center justify-between">
                  <div className="font-mono text-[10px] uppercase tracking-wider text-ink/50">
                    Persoon {idx + 1}
                  </div>
                  <button
                    type="button"
                    onClick={() => removeStakeholder(idx)}
                    className="font-mono text-[10px] uppercase tracking-wider text-ink/50 hover:text-pink-500 underline"
                  >
                    Verwijder
                  </button>
                </div>
                <input
                  type="text"
                  placeholder="Naam"
                  value={s.name}
                  onChange={(e) =>
                    updateStakeholder(idx, "name", e.target.value)
                  }
                  className="w-full border border-ink/30 bg-paper px-3 py-2 font-mono text-sm"
                />
                <input
                  type="text"
                  placeholder="Functie"
                  value={s.role}
                  onChange={(e) =>
                    updateStakeholder(idx, "role", e.target.value)
                  }
                  className="w-full border border-ink/30 bg-paper px-3 py-2 font-mono text-sm"
                />
                <input
                  type="text"
                  placeholder="LinkedIn-URL"
                  value={s.linkedin_url}
                  onChange={(e) =>
                    updateStakeholder(idx, "linkedin_url", e.target.value)
                  }
                  className="w-full border border-ink/30 bg-paper px-3 py-2 font-mono text-sm"
                />
              </div>
            ))}
            <button
              type="button"
              onClick={addStakeholder}
              className="font-mono text-[10px] uppercase tracking-wider border border-ink/30 px-3 py-2 hover:border-ink/60"
            >
              + Voeg extra persoon toe
            </button>
          </div>
        </div>
      )}
    </section>
  );
}


function BattlecardSection({
  battlecard,
  prep,
}: {
  battlecard: Battlecard;
  prep: Prep;
}) {
  const extraCount = Array.isArray(prep.additional_stakeholders)
    ? prep.additional_stakeholders.length
    : 0;
  const totalPeople = extraCount + (prep.decision_maker_name || prep.decision_maker_linkedin_url ? 1 : 0);
  return (
    <section className="mb-6 border border-ink/20 bg-ink/[0.02] p-6">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="font-mono text-[10px] uppercase tracking-wider text-ink/60">
          Battlecard
        </div>
        {(totalPeople > 1 || prep.meeting_deadline) && (
          <div className="font-mono text-[10px] uppercase tracking-wider text-ink/50">
            {totalPeople > 1 && (
              <span className="mr-4">
                <strong className="text-ink/70">{totalPeople}</strong> personen aan tafel
              </span>
            )}
            {prep.meeting_deadline && (
              <span>Deadline: <strong className="text-ink/70">{prep.meeting_deadline}</strong></span>
            )}
          </div>
        )}
      </div>
      {!battlecard && <p className="text-sm text-ink/50">Nog niet gegenereerd.</p>}
      {battlecard && (
        <div>
          <p className="text-sm">
            Status: <strong>{battlecard.status.toUpperCase()}</strong>
          </p>
          {battlecard.pdf_storage_path && (
            <PdfActions
              prepId={prep.id}
              prep={prep}
              battlecard={battlecard}
            />
          )}
          {battlecard.blocks && Object.keys(battlecard.blocks).length > 0 ? (
            <div className="mt-4 border border-ink/20 bg-paper p-5">
              <BattlecardIntakeStrip prep={prep} />
              <BattlecardBlocks blocks={battlecard.blocks} />
            </div>
          ) : (
            battlecard.raw_markdown && (
              <div className="mt-4 border border-ink/20 bg-paper p-5">
                <BattlecardMarkdown>{battlecard.raw_markdown}</BattlecardMarkdown>
              </div>
            )
          )}
          {battlecard.status === "failed" && battlecard.generation_error && (
            <div className="mt-2 inline-flex items-center gap-2 text-sm text-red-700">
              <AlertCircle className="h-4 w-4" />
              Fout: {battlecard.generation_error}
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function PdfActions({
  prepId,
  prep,
  battlecard,
}: {
  prepId: string;
  prep: Prep;
  battlecard: NonNullable<Battlecard>;
}) {
  const [busy, setBusy] = useState(false);
  const [opening, setOpening] = useState(false);
  const path = battlecard.pdf_storage_path!;

  async function openPdf() {
    if (!supabase) return;
    setOpening(true);
    const { data, error } = await supabase.storage
      .from("sales-battlecards")
      .createSignedUrl(path, 60);
    setOpening(false);
    if (error || !data) {
      alert(error?.message || "Kon link niet maken");
      return;
    }
    window.open(data.signedUrl, "_blank");
  }

  async function regenerate() {
    if (!supabase) return;
    if (!window.confirm("Nieuwe PDF genereren? De oude versie wordt overschreven.")) return;
    setBusy(true);
    try {
      const blob = await generateBattlecardPdf(
        prep as unknown as Record<string, unknown>,
        battlecard as { blocks?: Record<string, { title?: string; content?: string; category?: string }> },
      );
      const filename = `${prepId}/battlecard-${Date.now()}.pdf`;
      const { error: upErr } = await supabase.storage
        .from("sales-battlecards")
        .upload(filename, blob, { contentType: "application/pdf", upsert: true });
      if (upErr) {
        alert(`Upload faalde: ${upErr.message}`);
        return;
      }
      const { error: rpcErr } = await supabase
        .schema("sales" as never)
        .rpc("admin_save_pdf", {
          p_id: prepId,
          p_storage_path: filename,
          p_byte_size: blob.size,
          p_mark_delivered: false,
        });
      if (rpcErr) {
        alert(`DB-save faalde: ${rpcErr.message}`);
        return;
      }
      alert("PDF vernieuwd ✓");
      window.location.reload();
    } catch (e) {
      alert(`Fout: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="mt-4 border border-ink/20 bg-paperLight p-4">
      <div className="mb-2 font-mono text-[10px] uppercase tracking-wider text-ink/60">
        PDF — opgeslagen battlecard
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <button
          onClick={openPdf}
          disabled={opening}
          className="bg-ink px-4 py-2 font-mono text-xs uppercase tracking-wider text-paper hover:bg-ink/85 disabled:opacity-50"
        >
          {opening ? "Bezig…" : "↓ Open PDF"}
        </button>
        <button
          onClick={regenerate}
          disabled={busy}
          className="border border-ink/30 px-3 py-2 font-mono text-xs uppercase tracking-wider hover:border-ink disabled:opacity-50"
        >
          {busy ? "Bezig…" : "↻ Regenereer PDF"}
        </button>
        <span className="text-xs text-ink/60">
          {battlecard.pdf_byte_size != null && (
            <>{Math.round((battlecard.pdf_byte_size || 0) / 1024)} KB</>
          )}
          {battlecard.pdf_generated_at && (
            <> · gegenereerd {fmtDate(battlecard.pdf_generated_at)}</>
          )}
        </span>
      </div>
    </section>
  );
}

function RegenerateBattlecardButton({
  prepId,
  onChange,
}: {
  prepId: string;
  onChange: () => void;
}) {
  const [busy, setBusy] = useState(false);
  async function handle() {
    if (!supabase) return;
    if (
      !window.confirm(
        "Regenereer de complete battlecard? Dit overschrijft de huidige content " +
          "(web-searches worden opnieuw uitgevoerd, ~3 min). De opgeslagen PDF " +
          "blijft behouden tot je hem ook regenereert.",
      )
    )
      return;
    setBusy(true);
    const { error: rpcErr } = await supabase
      .schema("sales" as never)
      .rpc("admin_regenerate_battlecard", { p_id: prepId });
    if (rpcErr) {
      setBusy(false);
      alert(`Reset faalde: ${rpcErr.message}`);
      return;
    }
    const { error: fnErr } = await supabase.functions.invoke("generate-battlecard", {
      body: { prep_id: prepId },
    });
    setBusy(false);
    if (fnErr) {
      alert(
        `Edge Function faalde: ${fnErr.message}\nReset is gedaan, probeer manueel opnieuw.`,
      );
      return;
    }
    alert(
      "Battlecard regenereert in achtergrond (~3 min). Je krijgt een mail wanneer klaar.",
    );
    onChange();
  }
  return (
    <button
      onClick={handle}
      disabled={busy}
      className="border-2 border-fluoPink px-3 py-2 font-mono text-xs uppercase tracking-wider text-fluoPink hover:bg-fluoPink hover:text-paper disabled:opacity-50"
    >
      {busy ? "Bezig…" : "↻ Regenereer battlecard"}
    </button>
  );
}


function SalesContextSection({
  prep,
  onChange,
}: {
  prep: Prep;
  onChange: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const editable = ["ingediend", "gereviewd"].includes(prep.status);

  const buildLocal = (): SalesContextValues => ({
    meeting_type: prep.meeting_type || "",
    deal_stage: prep.deal_stage || "",
    klant_type: prep.klant_type || "",
    industry_vertical: prep.industry_vertical || "",
  });

  const [local, setLocal] = useState<SalesContextValues>(buildLocal());

  function startEdit() {
    setLocal(buildLocal());
    setEditing(true);
  }

  async function save() {
    if (!supabase) return;
    setSaving(true);
    const { error } = await supabase
      .schema("sales" as never)
      .rpc("admin_update_intake", {
        p_id: prep.id,
        p_prospect_company_name: prep.prospect_company_name,
        p_prospect_company_url: prep.prospect_company_url,
        p_prospect_sector: prep.prospect_sector,
        p_decision_maker_name: prep.decision_maker_name,
        p_decision_maker_role: prep.decision_maker_role,
        p_decision_maker_linkedin_url: prep.decision_maker_linkedin_url,
        p_meeting_datetime: prep.meeting_datetime,
        p_meeting_location: prep.meeting_location,
        p_meeting_agenda: prep.meeting_agenda,
        p_sales_objective: prep.sales_objective,
        p_relationship_status: prep.relationship_status,
        p_hypotheses: prep.hypotheses,
        p_sales_method: prep.sales_method,
        p_meeting_type: local.meeting_type || null,
        p_deal_stage: local.deal_stage || null,
        p_klant_type: local.klant_type || null,
        p_industry_vertical: local.industry_vertical.trim() || null,
        p_product_offering: prep.product_offering,
        p_competitors: prep.competitors,
        p_meeting_deadline: prep.meeting_deadline,
        p_biggest_concern: prep.biggest_concern,
        p_specific_question: prep.specific_question,
        p_prior_contact_summary: prep.prior_contact_summary,
        p_geography_culture: prep.geography_culture,
        p_additional_stakeholders: prep.additional_stakeholders ?? [],
      });

    setSaving(false);
    if (error) {
      alert(`Opslaan faalde: ${error.message}`);
      return;
    }
    setEditing(false);
    onChange();
  }

  const niet = <em className="text-ink/40">Niet ingevuld</em>;

  return (
    <section className="mb-6 border border-ink/20 p-6">
      <div className="mb-4 flex items-center justify-between">
        <div className="font-mono text-[10px] uppercase tracking-wider text-ink/60">
          Context & nadruk
        </div>
        {editable &&
          (editing ? (
            <div className="flex gap-2">
              <button
                onClick={() => setEditing(false)}
                className="font-mono text-xs uppercase tracking-wider text-ink/60 hover:text-ink"
              >
                Annuleer
              </button>
              <button
                onClick={save}
                disabled={saving}
                className="bg-ink px-3 py-1 font-mono text-xs uppercase tracking-wider text-paper hover:bg-ink/90 disabled:opacity-50"
              >
                {saving ? "Opslaan…" : "Opslaan"}
              </button>
            </div>
          ) : (
            <button
              onClick={startEdit}
              className="inline-flex items-center gap-1.5 border border-ink/30 px-3 py-1 font-mono text-xs uppercase tracking-wider hover:bg-ink hover:text-paper"
            >
              <Pencil className="h-3 w-3" />
              Bewerken
            </button>
          ))}
      </div>

      {!editing ? (
        <dl className="grid grid-cols-[200px_1fr] gap-y-3 text-sm">
          <dt className="text-ink/60">Type meeting</dt>
          <dd>{meetingTypeLabel(prep.meeting_type) || niet}</dd>
          <dt className="text-ink/60">Deal stage</dt>
          <dd>{dealStageLabel(prep.deal_stage) || niet}</dd>
          <dt className="text-ink/60">Klantsoort</dt>
          <dd>{klantTypeLabel(prep.klant_type) || niet}</dd>
          <dt className="text-ink/60">Industry vertical</dt>
          <dd>{prep.industry_vertical || niet}</dd>
        </dl>
      ) : (
        <SalesContextFields
          values={local}
          onChange={setLocal}
          variant="admin"
        />
      )}
    </section>
  );
}




