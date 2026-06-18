import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { supabase } from "@/lib/supabase";
import { RotateCcw } from "lucide-react";
import {
  SalesContextFields,
  EMPTY_SALES_CONTEXT,
  type SalesContextValues,
} from "@/components/sales/SalesContextFields";
import { GEOGRAPHY_OPTIONS, type Stakeholder } from "@/lib/salesLabels";
import agenicLogo from "@/assets/agenic-logo.png";

export const Route = createFileRoute("/sales/validate/$token")({
  component: SalesKlantValidatePage,
});

type ProjectValidation = {
  klant_name: string;
  klant_company: string;
  status?: string;
  reviewed_at?: string | null;
  prospect_company_name?: string | null;
  prospect_company_url?: string | null;
  prospect_sector?: string | null;
  decision_maker_name?: string | null;
  decision_maker_role?: string | null;
  decision_maker_linkedin_url?: string | null;
  meeting_datetime?: string | null;
  meeting_location?: string | null;
  meeting_agenda?: string | null;
  meeting_deadline?: string | null;
  sales_objective?: string | null;
  product_offering?: string | null;
  hypotheses?: string | null;
  competitors?: string | null;
  relationship_status?: string | null;
  sales_method?: string | null;
  meeting_type?: string | null;
  deal_stage?: string | null;
  klant_type?: string | null;
  industry_vertical?: string | null;
  biggest_concern?: string | null;
  specific_question?: string | null;
  prior_contact_summary?: string | null;
  geography_culture?: string | null;
  additional_stakeholders?: Stakeholder[] | null;
  submitted_snapshot?: Record<string, any> | null;
};

const inputBase =
  "w-full border px-3 py-2 font-mono text-sm focus:outline-none focus:border-ink";
const inputDefault = `${inputBase} border-ink/30 bg-paperLight`;
const inputChanged = `${inputBase} border-l-4 border-l-fluoYellow border-ink/30 bg-fluoYellow/10`;

const SALES_METHODS = [
  { v: "", label: "Geen voorkeur" },
  { v: "meddpicc", label: "MEDDPICC" },
  { v: "spin", label: "SPIN" },
  { v: "challenger", label: "Challenger" },
  { v: "voss", label: "Voss (Tactical Empathy)" },
  { v: "pre_suasion", label: "Pre-Suasion" },
];

const RELATIONSHIP_LABELS: Record<string, string> = {
  first_contact: "Eerste contact",
  ongoing: "Lopend gesprek",
  re_engagement: "Re-engagement",
  close: "Close-meeting",
};

function fmtDateTime(s: string | null | undefined) {
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

function normalizeUrl(raw: string): string {
  const t = (raw || "").trim();
  if (!t) return "";
  if (/^https?:\/\//i.test(t)) return t;
  return `https://${t}`;
}

function validateUrl(url: string): boolean {
  try {
    const u = new URL(normalizeUrl(url));
    return ["http:", "https:"].includes(u.protocol) && u.hostname.includes(".");
  } catch {
    return false;
  }
}

function validateLinkedIn(url: string): boolean {
  return /^https?:\/\/(www\.)?linkedin\.com\/in\/[a-zA-Z0-9_\-%.]+\/?/i.test(
    normalizeUrl(url),
  );
}

function eqValue(a: any, b: any) {
  const na = a == null || a === "" ? null : a;
  const nb = b == null || b === "" ? null : b;
  return na === nb;
}

function stakeKey(s: Stakeholder): string {
  const li = (s.linkedin_url || "").trim().toLowerCase();
  if (li) return `li:${li}`;
  return `nm:${(s.name || "").trim().toLowerCase()}|${(s.role || "").trim().toLowerCase()}`;
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

function ValidationThankYou({ project }: { project: ProjectValidation }) {
  return (
    <div className="min-h-screen bg-paper flex items-center justify-center">
      <div className="text-center max-w-md px-8">
        <div className="font-mono text-[10px] uppercase tracking-wider text-pink-500 mb-2">
          Nestor Sales
        </div>
        <h1 className="font-serif text-4xl mb-4 lowercase">
          gevalideerd, bedankt {project.klant_name}
        </h1>
        <p className="text-ink/70 mb-6">
          Bedankt voor je akkoord. We doen nog een laatste review en starten
          dan de research voor je battlecard. Je krijgt binnen enkele uren tot
          dagen een mail met de download-link.
        </p>
        <p className="text-xs text-ink/50">Je mag dit venster sluiten.</p>
      </div>
    </div>
  );
}

function ChangedHint({
  original,
  onRevert,
}: {
  original: ReactNode;
  onRevert: () => void;
}) {
  return (
    <div className="mt-1 flex flex-wrap items-center gap-2 text-xs">
      <span className="inline-flex items-center gap-1 border border-fluoYellow bg-fluoYellow/15 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-ink">
        Aangepast door Agenic
      </span>
      <span className="text-ink/50">
        origineel: <span className="text-ink/70">{original}</span>
      </span>
      <button
        type="button"
        onClick={onRevert}
        className="inline-flex items-center gap-1 text-ink/60 underline hover:text-ink"
      >
        <RotateCcw className="h-3 w-3" />
        zet terug
      </button>
    </div>
  );
}

function Field({
  label,
  required,
  children,
  hint,
}: {
  label: string;
  required?: boolean;
  children: ReactNode;
  hint?: ReactNode;
}) {
  return (
    <div className="mb-4">
      <label className="font-mono text-[10px] uppercase tracking-wider text-ink/60 mb-1 block">
        {label}
        {required && <span className="ml-1 text-pink-500">*</span>}
      </label>
      {children}
      {hint && <p className="text-xs text-ink/50 mt-1">{hint}</p>}
    </div>
  );
}

function SectionHeader({
  title,
  subtitle,
  changed,
}: {
  title: string;
  subtitle?: string;
  changed?: boolean;
}) {
  return (
    <div className="mb-4 flex items-start justify-between gap-3">
      <div>
        <h2 className="font-serif text-2xl lowercase">{title}</h2>
        {subtitle && <p className="text-sm text-ink/60 mt-1">{subtitle}</p>}
      </div>
      {changed && (
        <span className="mt-1 inline-block border border-fluoYellow bg-fluoYellow/20 px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-ink">
          Aangepast door Agenic
        </span>
      )}
    </div>
  );
}

function SalesKlantValidatePage() {
  const { token } = Route.useParams();
  const [project, setProject] = useState<ProjectValidation | null>(null);
  const [snapshot, setSnapshot] = useState<Record<string, any> | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [validated, setValidated] = useState(false);

  const [form, setForm] = useState({
    prospect_company_name: "",
    prospect_company_url: "",
    prospect_sector: "",
    decision_maker_name: "",
    decision_maker_role: "",
    decision_maker_linkedin_url: "",
    meeting_datetime: "",
    meeting_location: "",
    meeting_agenda: "",
    meeting_deadline: "",
    sales_objective: "",
    product_offering: "",
    hypotheses: "",
    competitors: "",
    prior_contact_summary: "",
    biggest_concern: "",
    specific_question: "",
    geography_culture: "",
    relationship_status: "",
    sales_method: "",
    additional_stakeholders: [] as Stakeholder[],
  });
  const [context, setContext] = useState<SalesContextValues>(EMPTY_SALES_CONTEXT);
  const [showExtra, setShowExtra] = useState(false);

  useEffect(() => {
    async function load() {
      if (!supabase) {
        setError("Supabase niet geconfigureerd.");
        setLoading(false);
        return;
      }
      const { data, error: err } = await supabase
        .schema("sales" as never)
        .rpc("get_validation_by_token", { p_token: token });
      if (err || !data) {
        setError(
          "Deze link is niet meer geldig of de validatie is al verwerkt.",
        );
        setLoading(false);
        return;
      }
      const p = data as ProjectValidation;
      setProject(p);
      setSnapshot(p.submitted_snapshot ?? null);
      setForm({
        prospect_company_name: p.prospect_company_name || "",
        prospect_company_url: p.prospect_company_url || "",
        prospect_sector: p.prospect_sector || "",
        decision_maker_name: p.decision_maker_name || "",
        decision_maker_role: p.decision_maker_role || "",
        decision_maker_linkedin_url: p.decision_maker_linkedin_url || "",
        meeting_datetime: p.meeting_datetime ? p.meeting_datetime.slice(0, 16) : "",
        meeting_location: p.meeting_location || "",
        meeting_agenda: p.meeting_agenda || "",
        meeting_deadline: p.meeting_deadline || "",
        sales_objective: p.sales_objective || "",
        product_offering: p.product_offering || "",
        hypotheses: p.hypotheses || "",
        competitors: p.competitors || "",
        prior_contact_summary: p.prior_contact_summary || "",
        biggest_concern: p.biggest_concern || "",
        specific_question: p.specific_question || "",
        geography_culture: p.geography_culture || "",
        relationship_status: p.relationship_status || "",
        sales_method: p.sales_method || "",
        additional_stakeholders: Array.isArray(p.additional_stakeholders)
          ? p.additional_stakeholders
          : [],
      });
      setContext({
        meeting_type: p.meeting_type || "",
        deal_stage: p.deal_stage || "",
        klant_type: p.klant_type || "",
        industry_vertical: p.industry_vertical || "",
      });
      if (
        p.relationship_status ||
        p.sales_method ||
        p.prior_contact_summary ||
        p.biggest_concern ||
        p.specific_question ||
        p.geography_culture
      ) {
        setShowExtra(true);
      }
      if (p.status === "gevalideerd") setValidated(true);
      setLoading(false);
    }
    load();
  }, [token]);

  function set<K extends keyof typeof form>(key: K, value: (typeof form)[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  // ---- diff helpers ----
  function origOf(key: string): any {
    if (!snapshot) return undefined;
    return snapshot[key];
  }
  function isChanged(key: string, current: any): boolean {
    if (!snapshot) return false;
    if (!(key in snapshot)) return false;
    let orig = snapshot[key];
    let cur = current;
    if (key === "meeting_datetime") {
      orig = orig ? new Date(orig).toISOString() : null;
      cur = cur ? new Date(cur).toISOString() : null;
    }
    return !eqValue(orig, cur);
  }
  function origDisplay(key: string): string {
    const v = origOf(key);
    if (v == null || v === "") return "leeg";
    if (key === "meeting_datetime") return fmtDateTime(v) || String(v);
    return String(v);
  }
  function revert<K extends keyof typeof form>(key: K, fallback: any = "") {
    let val: any = origOf(key as string) ?? fallback;
    if (key === "meeting_datetime" && val) val = String(val).slice(0, 16);
    setForm((f) => ({ ...f, [key]: val }));
  }
  function revertContext(key: keyof SalesContextValues) {
    setContext((c) => ({ ...c, [key]: (origOf(key as string) ?? "") as string }));
  }

  // ---- stakeholders diff ----
  const stakeDiff = useMemo(() => {
    const origArr: Stakeholder[] = Array.isArray(snapshot?.additional_stakeholders)
      ? snapshot!.additional_stakeholders
      : [];
    const origKeys = new Set(origArr.map(stakeKey));
    const curKeys = new Set(form.additional_stakeholders.map(stakeKey));
    const added = (s: Stakeholder) => !!snapshot && !origKeys.has(stakeKey(s));
    const removedItems = snapshot
      ? origArr.filter((s) => !curKeys.has(stakeKey(s)))
      : [];
    return { added, removedItems };
  }, [snapshot, form.additional_stakeholders]);

  // section change indicators
  const sectionChanged = useMemo(() => {
    return {
      prospect: ["prospect_company_name", "prospect_company_url", "prospect_sector"].some(
        (k) => isChanged(k, (form as any)[k]),
      ),
      people:
        ["decision_maker_linkedin_url", "decision_maker_name", "decision_maker_role"].some(
          (k) => isChanged(k, (form as any)[k]),
        ) ||
        form.additional_stakeholders.some((s) => stakeDiff.added(s)) ||
        stakeDiff.removedItems.length > 0,
      meeting: ["meeting_datetime", "meeting_location", "meeting_agenda", "meeting_deadline"].some(
        (k) => isChanged(k, (form as any)[k]),
      ),
      context: (["meeting_type", "deal_stage", "klant_type", "industry_vertical"] as const).some(
        (k) => isChanged(k, context[k]),
      ),
      sales: ["sales_objective", "product_offering", "hypotheses", "competitors"].some(
        (k) => isChanged(k, (form as any)[k]),
      ),
      extra: [
        "prior_contact_summary",
        "biggest_concern",
        "specific_question",
        "geography_culture",
        "relationship_status",
        "sales_method",
      ].some((k) => isChanged(k, (form as any)[k])),
    };
  }, [snapshot, form, context, stakeDiff]);

  // stakeholders edit
  const addStake = () =>
    setForm((f) => ({
      ...f,
      additional_stakeholders: [
        ...f.additional_stakeholders,
        { name: "", role: "", linkedin_url: "" },
      ],
    }));
  const updateStake = (idx: number, field: keyof Stakeholder, value: string) =>
    setForm((f) => ({
      ...f,
      additional_stakeholders: f.additional_stakeholders.map((s, i) =>
        i === idx ? { ...s, [field]: value } : s,
      ),
    }));
  const removeStake = (idx: number) =>
    setForm((f) => ({
      ...f,
      additional_stakeholders: f.additional_stakeholders.filter((_, i) => i !== idx),
    }));
  const restoreStake = (s: Stakeholder) =>
    setForm((f) => ({
      ...f,
      additional_stakeholders: [...f.additional_stakeholders, s],
    }));

  async function handleValidate() {
    setError(null);
    if (!form.prospect_company_name.trim()) {
      setError("Bedrijfsnaam van de prospect is verplicht");
      return;
    }
    if (!validateUrl(form.prospect_company_url)) {
      setError("Bedrijfs-URL moet een geldige website zijn");
      return;
    }
    if (!validateLinkedIn(form.decision_maker_linkedin_url)) {
      setError("LinkedIn-URL van de decision-maker is verplicht");
      return;
    }
    if (!form.sales_objective.trim()) {
      setError("Sales-objectief is verplicht");
      return;
    }
    if (!form.product_offering.trim()) {
      setError(
        "Wat verkoop je / aanbod is verplicht — zonder dit blijft de battlecard generiek",
      );
      return;
    }
    if (
      !window.confirm(
        "Ben je akkoord met de intake zoals weergegeven? Daarna volgt nog een laatste review.",
      )
    )
      return;
    if (!supabase) return;
    setSubmitting(true);

    const cleanStakeholders = form.additional_stakeholders.filter(
      (s) => s.name.trim() || s.role.trim() || s.linkedin_url.trim(),
    );

    const { error: rpcErr } = await supabase
      .schema("sales" as never)
      .rpc("validate_by_token", {
        p_token: token,
        p_prospect_company_name: form.prospect_company_name.trim(),
        p_prospect_company_url: normalizeUrl(form.prospect_company_url),
        p_decision_maker_linkedin_url: normalizeUrl(form.decision_maker_linkedin_url),
        p_sales_objective: form.sales_objective.trim(),
        p_prospect_sector: form.prospect_sector || null,
        p_decision_maker_name: form.decision_maker_name || null,
        p_decision_maker_role: form.decision_maker_role || null,
        p_meeting_datetime: form.meeting_datetime
          ? new Date(form.meeting_datetime).toISOString()
          : null,
        p_meeting_location: form.meeting_location || null,
        p_meeting_agenda: form.meeting_agenda || null,
        p_hypotheses: form.hypotheses || null,
        p_relationship_status: form.relationship_status || null,
        p_sales_method: form.sales_method || null,
        p_meeting_type: context.meeting_type || null,
        p_deal_stage: context.deal_stage || null,
        p_klant_type: context.klant_type || null,
        p_industry_vertical: context.industry_vertical.trim() || null,
        p_product_offering: form.product_offering.trim() || null,
        p_competitors: form.competitors || null,
        p_meeting_deadline: form.meeting_deadline || null,
        p_biggest_concern: form.biggest_concern || null,
        p_specific_question: form.specific_question || null,
        p_prior_contact_summary: form.prior_contact_summary || null,
        p_geography_culture: form.geography_culture || null,
        p_additional_stakeholders: cleanStakeholders,
      });

    setSubmitting(false);
    if (rpcErr) {
      setError(`Validatie faalde: ${rpcErr.message}`);
      return;
    }
    setValidated(true);
  }

  if (loading) return <CenteredLoading />;
  if (error && !project) return <CenteredError text={error} />;
  if (validated && project) return <ValidationThankYou project={project} />;
  if (!project) return <CenteredError text="Onbekende fout." />;

  const clsFor = (key: string, current: any) =>
    isChanged(key, current) ? inputChanged : inputDefault;

  return (
    <div className="min-h-screen bg-paper text-ink">
      <div className="border-b border-ink/20 px-8 py-4">
        <div className="font-mono text-[10px] uppercase tracking-wider text-pink-500">
          Nestor Sales — Validatie
        </div>
        <img src={agenicLogo} alt="Agenic" className="h-8 mt-1" />
      </div>

      <div className="max-w-3xl mx-auto px-8 py-10">
        <h1 className="font-serif text-4xl mb-2 lowercase">
          dag {project.klant_name}
        </h1>
        <p className="text-ink/70 mb-6 max-w-2xl">
          Agenic heeft je intake gereviewd en, waar nodig, aangevuld of
          aangescherpt. Velden met een gele rand zijn door ons aangepast — je
          kan ze gewoon overschrijven of terugzetten naar je originele invoer.
        </p>

        {project.reviewed_at && (
          <p className="text-xs text-ink/50 mb-4 font-mono">
            Gereviewd door Agenic op {fmtDateTime(project.reviewed_at)}
          </p>
        )}

        <div className="mb-8 border border-ink border-l-4 border-l-fluoYellow bg-paperLight p-4 text-ink">
          <div className="mb-2 font-mono text-xs uppercase tracking-wider text-ink">
            VALIDATIE
          </div>
          <p className="font-sans text-sm text-ink">
            Loop de intake éénmaal door. Klik onderaan "Akkoord — start
            research" wanneer je klaar bent. Wijzigingen worden bij die klik
            opgeslagen.
          </p>
        </div>

        {!snapshot && (
          <div className="mb-8 border border-ink/20 bg-paper2 p-3 font-mono text-[10px] uppercase tracking-wider text-ink/60">
            Geen originele intake-snapshot beschikbaar — diff-vergelijking uitgeschakeld voor deze prep.
          </div>
        )}

        <div className="space-y-10">
          {/* PROSPECT */}
          <section>
            <SectionHeader
              title="Prospect"
              subtitle="Het bedrijf waar je een meeting mee hebt."
              changed={sectionChanged.prospect}
            />
            <Field label="Bedrijfsnaam" required>
              <input
                type="text"
                value={form.prospect_company_name}
                onChange={(e) => set("prospect_company_name", e.target.value)}
                className={clsFor("prospect_company_name", form.prospect_company_name)}
              />
              {isChanged("prospect_company_name", form.prospect_company_name) && (
                <ChangedHint
                  original={origDisplay("prospect_company_name")}
                  onRevert={() => revert("prospect_company_name")}
                />
              )}
            </Field>
            <Field label="Bedrijfs-URL" required>
              <input
                type="text"
                value={form.prospect_company_url}
                onChange={(e) => set("prospect_company_url", e.target.value)}
                className={clsFor("prospect_company_url", form.prospect_company_url)}
              />
              {isChanged("prospect_company_url", form.prospect_company_url) && (
                <ChangedHint
                  original={origDisplay("prospect_company_url")}
                  onRevert={() => revert("prospect_company_url")}
                />
              )}
            </Field>
            <Field label="Sector (optioneel)">
              <input
                type="text"
                value={form.prospect_sector}
                onChange={(e) => set("prospect_sector", e.target.value)}
                className={clsFor("prospect_sector", form.prospect_sector)}
              />
              {isChanged("prospect_sector", form.prospect_sector) && (
                <ChangedHint
                  original={origDisplay("prospect_sector")}
                  onRevert={() => revert("prospect_sector")}
                />
              )}
            </Field>
          </section>

          {/* PEOPLE */}
          <section>
            <SectionHeader
              title="De mensen aan tafel"
              subtitle="Wie ga je spreken?"
              changed={sectionChanged.people}
            />
            <div className="border-l-2 pl-5 mb-6" style={{ borderLeftColor: "#FF2D87" }}>
              <div
                className="font-mono text-[10px] uppercase tracking-wider mb-3"
                style={{ color: "#FF2D87" }}
              >
                Primary decision maker
              </div>
              <Field label="LinkedIn-profiel" required>
                <input
                  type="text"
                  value={form.decision_maker_linkedin_url}
                  onChange={(e) => set("decision_maker_linkedin_url", e.target.value)}
                  className={clsFor(
                    "decision_maker_linkedin_url",
                    form.decision_maker_linkedin_url,
                  )}
                />
                {isChanged(
                  "decision_maker_linkedin_url",
                  form.decision_maker_linkedin_url,
                ) && (
                  <ChangedHint
                    original={origDisplay("decision_maker_linkedin_url")}
                    onRevert={() => revert("decision_maker_linkedin_url")}
                  />
                )}
              </Field>
              <Field label="Naam (optioneel)">
                <input
                  type="text"
                  value={form.decision_maker_name}
                  onChange={(e) => set("decision_maker_name", e.target.value)}
                  className={clsFor("decision_maker_name", form.decision_maker_name)}
                />
                {isChanged("decision_maker_name", form.decision_maker_name) && (
                  <ChangedHint
                    original={origDisplay("decision_maker_name")}
                    onRevert={() => revert("decision_maker_name")}
                  />
                )}
              </Field>
              <Field label="Functie (optioneel)">
                <input
                  type="text"
                  value={form.decision_maker_role}
                  onChange={(e) => set("decision_maker_role", e.target.value)}
                  className={clsFor("decision_maker_role", form.decision_maker_role)}
                />
                {isChanged("decision_maker_role", form.decision_maker_role) && (
                  <ChangedHint
                    original={origDisplay("decision_maker_role")}
                    onRevert={() => revert("decision_maker_role")}
                  />
                )}
              </Field>
            </div>

            {form.additional_stakeholders.map((s, idx) => {
              const added = stakeDiff.added(s);
              return (
                <div
                  key={idx}
                  className={
                    "pl-5 mb-4 border-l-2 " +
                    (added ? "border-fluoYellow bg-fluoYellow/10" : "border-ink/20")
                  }
                >
                  <div className="flex items-center justify-between mb-3 pt-2">
                    <div className="flex items-center gap-2">
                      <div className="font-mono text-[10px] uppercase tracking-wider text-ink/60">
                        Extra persoon {idx + 1}
                      </div>
                      {added && (
                        <span className="inline-block border border-fluoYellow bg-fluoYellow/30 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-ink">
                          + toegevoegd door admin
                        </span>
                      )}
                    </div>
                    <button
                      type="button"
                      onClick={() => removeStake(idx)}
                      className="font-mono text-[10px] uppercase tracking-wider text-ink/50 hover:text-pink-500 underline"
                    >
                      Verwijder
                    </button>
                  </div>
                  <Field label="Naam">
                    <input
                      type="text"
                      value={s.name}
                      onChange={(e) => updateStake(idx, "name", e.target.value)}
                      className={inputDefault}
                    />
                  </Field>
                  <Field label="Functie">
                    <input
                      type="text"
                      value={s.role}
                      onChange={(e) => updateStake(idx, "role", e.target.value)}
                      className={inputDefault}
                    />
                  </Field>
                  <Field label="LinkedIn-URL">
                    <input
                      type="text"
                      value={s.linkedin_url}
                      onChange={(e) => updateStake(idx, "linkedin_url", e.target.value)}
                      className={inputDefault}
                    />
                  </Field>
                </div>
              );
            })}

            {stakeDiff.removedItems.map((s, i) => (
              <div
                key={`removed-${i}`}
                className="pl-5 mb-4 border-l-2 border-fluoYellow bg-fluoYellow/5 py-2"
              >
                <div className="flex items-center justify-between mb-2">
                  <span className="inline-block border border-fluoYellow bg-fluoYellow/30 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-ink">
                    − verwijderd door admin
                  </span>
                  <button
                    type="button"
                    onClick={() => restoreStake(s)}
                    className="inline-flex items-center gap-1 font-mono text-[10px] uppercase tracking-wider text-ink/60 underline hover:text-ink"
                  >
                    <RotateCcw className="h-3 w-3" />
                    zet terug
                  </button>
                </div>
                <div className="text-sm text-ink/70">
                  {s.name || <em className="text-ink/40">naam onbekend</em>}
                  {s.role && <span className="text-ink/60"> — {s.role}</span>}
                  {s.linkedin_url && (
                    <div className="text-xs text-ink/50 break-all">{s.linkedin_url}</div>
                  )}
                </div>
              </div>
            ))}

            <button
              type="button"
              onClick={addStake}
              className="font-mono text-[10px] uppercase tracking-wider border border-ink/30 px-3 py-2 hover:border-ink/60"
            >
              + Voeg extra persoon toe
            </button>
          </section>

          {/* MEETING */}
          <section>
            <SectionHeader
              title="Meeting-context"
              subtitle="Wanneer, waar, waarom?"
              changed={sectionChanged.meeting}
            />
            <Field label="Datum & tijd">
              <input
                type="datetime-local"
                value={form.meeting_datetime}
                onChange={(e) => set("meeting_datetime", e.target.value)}
                className={clsFor("meeting_datetime", form.meeting_datetime)}
              />
              {isChanged("meeting_datetime", form.meeting_datetime) && (
                <ChangedHint
                  original={origDisplay("meeting_datetime")}
                  onRevert={() => revert("meeting_datetime")}
                />
              )}
            </Field>
            <Field label="Locatie / online">
              <input
                type="text"
                value={form.meeting_location}
                onChange={(e) => set("meeting_location", e.target.value)}
                className={clsFor("meeting_location", form.meeting_location)}
              />
              {isChanged("meeting_location", form.meeting_location) && (
                <ChangedHint
                  original={origDisplay("meeting_location")}
                  onRevert={() => revert("meeting_location")}
                />
              )}
            </Field>
            <Field label="Agenda">
              <textarea
                value={form.meeting_agenda}
                onChange={(e) => set("meeting_agenda", e.target.value)}
                rows={3}
                className={clsFor("meeting_agenda", form.meeting_agenda)}
              />
              {isChanged("meeting_agenda", form.meeting_agenda) && (
                <ChangedHint
                  original={origDisplay("meeting_agenda")}
                  onRevert={() => revert("meeting_agenda")}
                />
              )}
            </Field>
            <Field label="Tijdsdruk / deadline">
              <input
                type="text"
                value={form.meeting_deadline}
                onChange={(e) => set("meeting_deadline", e.target.value)}
                className={clsFor("meeting_deadline", form.meeting_deadline)}
              />
              {isChanged("meeting_deadline", form.meeting_deadline) && (
                <ChangedHint
                  original={origDisplay("meeting_deadline")}
                  onRevert={() => revert("meeting_deadline")}
                />
              )}
            </Field>
          </section>

          {/* CONTEXT dropdowns */}
          <section>
            <div className="mb-2 flex items-center justify-end">
              {sectionChanged.context && (
                <span className="inline-block border border-fluoYellow bg-fluoYellow/20 px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-ink">
                  Aangepast door Agenic
                </span>
              )}
            </div>
            <SalesContextFields values={context} onChange={setContext} variant="intake" />
            <div className="space-y-1 mt-1">
              {(["meeting_type", "deal_stage", "klant_type", "industry_vertical"] as const).map(
                (k) =>
                  isChanged(k, context[k]) && (
                    <ChangedHint
                      key={k}
                      original={
                        <>
                          <span className="font-mono uppercase">{k}:</span>{" "}
                          {origDisplay(k)}
                        </>
                      }
                      onRevert={() => revertContext(k)}
                    />
                  ),
              )}
            </div>
          </section>

          {/* JOUW KANT */}
          <section>
            <SectionHeader
              title="Jouw kant"
              subtitle="Wat verkoop je en wat hoop je te bereiken?"
              changed={sectionChanged.sales}
            />
            <Field label="Sales-objectief" required>
              <textarea
                value={form.sales_objective}
                onChange={(e) => set("sales_objective", e.target.value)}
                rows={3}
                className={clsFor("sales_objective", form.sales_objective)}
              />
              {isChanged("sales_objective", form.sales_objective) && (
                <ChangedHint
                  original={origDisplay("sales_objective")}
                  onRevert={() => revert("sales_objective")}
                />
              )}
            </Field>
            <Field label="Wat verkoop je / aanbod" required>
              <textarea
                value={form.product_offering}
                onChange={(e) => set("product_offering", e.target.value)}
                rows={3}
                className={clsFor("product_offering", form.product_offering)}
              />
              {isChanged("product_offering", form.product_offering) && (
                <ChangedHint
                  original={origDisplay("product_offering")}
                  onRevert={() => revert("product_offering")}
                />
              )}
            </Field>
            <Field label="Hypotheses — Wat denk je dat hun pijn is?">
              <textarea
                value={form.hypotheses}
                onChange={(e) => set("hypotheses", e.target.value)}
                rows={3}
                className={clsFor("hypotheses", form.hypotheses)}
              />
              {isChanged("hypotheses", form.hypotheses) && (
                <ChangedHint
                  original={origDisplay("hypotheses")}
                  onRevert={() => revert("hypotheses")}
                />
              )}
            </Field>
            <Field label="Concurrenten / incumbents">
              <textarea
                value={form.competitors}
                onChange={(e) => set("competitors", e.target.value)}
                rows={2}
                className={clsFor("competitors", form.competitors)}
              />
              {isChanged("competitors", form.competitors) && (
                <ChangedHint
                  original={origDisplay("competitors")}
                  onRevert={() => revert("competitors")}
                />
              )}
            </Field>
          </section>

          {/* EXTRA */}
          <section className="border border-ink/15 bg-paperLight">
            <button
              type="button"
              onClick={() => setShowExtra((v) => !v)}
              className="w-full flex items-center justify-between px-5 py-3 text-left"
            >
              <span className="font-mono text-[10px] uppercase tracking-wider text-ink/60">
                Extra context (optioneel)
                {sectionChanged.extra && (
                  <span className="ml-2 inline-block border border-fluoYellow bg-fluoYellow/30 px-1.5 py-0.5 text-ink">
                    Aangepast
                  </span>
                )}
              </span>
              <span className="font-mono text-[10px]" style={{ color: "#FF2D87" }}>
                {showExtra ? "− verberg" : "+ toon"}
              </span>
            </button>
            {showExtra && (
              <div className="px-5 pb-5 space-y-4 border-t border-ink/15 pt-4">
                <Field label="Voorgaande contact-historiek">
                  <textarea
                    value={form.prior_contact_summary}
                    onChange={(e) => set("prior_contact_summary", e.target.value)}
                    rows={2}
                    className={clsFor("prior_contact_summary", form.prior_contact_summary)}
                  />
                  {isChanged("prior_contact_summary", form.prior_contact_summary) && (
                    <ChangedHint
                      original={origDisplay("prior_contact_summary")}
                      onRevert={() => revert("prior_contact_summary")}
                    />
                  )}
                </Field>
                <Field label="Grootste angst voor deze meeting">
                  <textarea
                    value={form.biggest_concern}
                    onChange={(e) => set("biggest_concern", e.target.value)}
                    rows={2}
                    className={clsFor("biggest_concern", form.biggest_concern)}
                  />
                  {isChanged("biggest_concern", form.biggest_concern) && (
                    <ChangedHint
                      original={origDisplay("biggest_concern")}
                      onRevert={() => revert("biggest_concern")}
                    />
                  )}
                </Field>
                <Field label="Specifieke vraag die je beantwoord wil zien">
                  <textarea
                    value={form.specific_question}
                    onChange={(e) => set("specific_question", e.target.value)}
                    rows={2}
                    className={clsFor("specific_question", form.specific_question)}
                  />
                  {isChanged("specific_question", form.specific_question) && (
                    <ChangedHint
                      original={origDisplay("specific_question")}
                      onRevert={() => revert("specific_question")}
                    />
                  )}
                </Field>
                <Field label="Geografie / cultuur">
                  <select
                    value={form.geography_culture}
                    onChange={(e) => set("geography_culture", e.target.value)}
                    className={clsFor("geography_culture", form.geography_culture)}
                  >
                    <option value="">Niet relevant</option>
                    {GEOGRAPHY_OPTIONS.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                  {isChanged("geography_culture", form.geography_culture) && (
                    <ChangedHint
                      original={origDisplay("geography_culture")}
                      onRevert={() => revert("geography_culture")}
                    />
                  )}
                </Field>
                <Field label="Status van de relatie">
                  <select
                    value={form.relationship_status}
                    onChange={(e) => set("relationship_status", e.target.value)}
                    className={clsFor("relationship_status", form.relationship_status)}
                  >
                    <option value="">— Kies één —</option>
                    {Object.entries(RELATIONSHIP_LABELS).map(([v, l]) => (
                      <option key={v} value={v}>
                        {l}
                      </option>
                    ))}
                  </select>
                  {isChanged("relationship_status", form.relationship_status) && (
                    <ChangedHint
                      original={
                        RELATIONSHIP_LABELS[origOf("relationship_status")] ||
                        origDisplay("relationship_status")
                      }
                      onRevert={() => revert("relationship_status")}
                    />
                  )}
                </Field>
                <Field label="Sales-methode voorkeur">
                  <select
                    value={form.sales_method}
                    onChange={(e) => set("sales_method", e.target.value)}
                    className={clsFor("sales_method", form.sales_method)}
                  >
                    {SALES_METHODS.map((m) => (
                      <option key={m.v || "none"} value={m.v}>
                        {m.label}
                      </option>
                    ))}
                  </select>
                  {isChanged("sales_method", form.sales_method) && (
                    <ChangedHint
                      original={
                        SALES_METHODS.find((m) => m.v === origOf("sales_method"))?.label ||
                        origDisplay("sales_method")
                      }
                      onRevert={() => revert("sales_method")}
                    />
                  )}
                </Field>
              </div>
            )}
          </section>
        </div>

        <div className="mt-10 border-t border-ink/20 pt-6">
          <p className="text-sm text-ink/70 mb-4">
            Als alles correct is, klik dan op &quot;Akkoord — klaar voor review&quot;.
            Twijfel je over iets? Mail dan{" "}
            <a href="mailto:nestor@agenic.be" className="underline">
              nestor@agenic.be
            </a>{" "}
            en we passen het aan.
          </p>

          {error && (
            <div className="mb-4 border border-red-500/40 bg-red-500/5 px-3 py-2 font-mono text-xs text-red-700">
              {error}
            </div>
          )}

          <button
            type="button"
            onClick={handleValidate}
            disabled={submitting}
            className="inline-flex items-center gap-2 bg-ink px-5 py-3 font-mono text-xs uppercase tracking-wider text-paper hover:bg-ink/90 disabled:opacity-50"
          >
            {submitting ? "Bezig..." : "✓ Akkoord — klaar voor review"}
          </button>
        </div>
      </div>
    </div>
  );
}
