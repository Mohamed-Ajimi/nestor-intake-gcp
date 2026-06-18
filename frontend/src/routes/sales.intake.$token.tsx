import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState, type ReactNode } from "react";
import { supabase } from "@/lib/supabase";
import {
  SalesContextFields,
  EMPTY_SALES_CONTEXT,
  type SalesContextValues,
} from "@/components/sales/SalesContextFields";
import { GEOGRAPHY_OPTIONS, type Stakeholder } from "@/lib/salesLabels";


export const Route = createFileRoute("/sales/intake/$token")({
  component: SalesKlantIntakePage,
});

type ProjectIntake = {
  klant_name: string;
  klant_company: string;
  klant_email?: string;
  status?: string;
  prospect_company_name?: string | null;
  prospect_company_url?: string | null;
  prospect_sector?: string | null;
  decision_maker_name?: string | null;
  decision_maker_role?: string | null;
  decision_maker_linkedin_url?: string | null;
  meeting_datetime?: string | null;
  meeting_location?: string | null;
  meeting_agenda?: string | null;
  sales_objective?: string | null;
  relationship_status?: string | null;
  hypotheses?: string | null;
  sales_method?: string | null;
  meeting_type?: string | null;
  deal_stage?: string | null;
  klant_type?: string | null;
  industry_vertical?: string | null;
  product_offering?: string | null;
  competitors?: string | null;
  meeting_deadline?: string | null;
  biggest_concern?: string | null;
  specific_question?: string | null;
  prior_contact_summary?: string | null;
  geography_culture?: string | null;
  additional_stakeholders?: Stakeholder[] | null;
};


const inputCls =
  "w-full border border-ink/30 px-3 py-2 font-mono text-sm bg-paperLight focus:outline-none focus:border-ink";

function normalizeUrl(raw: string): string {
  const t = raw.trim();
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
}: {
  title: string;
  subtitle?: string;
}) {
  return (
    <div className="mb-4">
      <h2 className="font-serif text-2xl lowercase">{title}</h2>
      {subtitle && <p className="text-sm text-ink/60 mt-1">{subtitle}</p>}
    </div>
  );
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

function ThankYouScreen({ project }: { project: ProjectIntake }) {
  return (
    <div className="min-h-screen bg-paper flex items-center justify-center">
      <div className="text-center max-w-md px-8">
        <div className="font-mono text-[10px] uppercase tracking-wider text-pink-500 mb-2">
          Nestor Sales
        </div>
        <h1 className="font-serif text-4xl mb-4 lowercase">
          bedankt {project.klant_name}
        </h1>
        <p className="text-ink/70 mb-6">
          Je intake is ingediend. Agenic reviewt nu de input en stuurt je
          binnen 24 uur een validatie-link via mail. Daarna gaan we aan de slag
          met je battlecard.
        </p>
        <p className="text-xs text-ink/50">Je mag dit venster sluiten.</p>
      </div>
    </div>
  );
}

const SALES_METHODS = [
  { v: "", label: "Geen voorkeur", desc: "Nestor kiest zelf de meest passende aanpak." },
  { v: "meddpicc", label: "MEDDPICC", desc: "B2B-standaard voor complexe deals." },
  { v: "spin", label: "SPIN", desc: "Discovery-aanpak (Rackham)." },
  { v: "challenger", label: "Challenger", desc: "Status-quo doorbreken." },
  { v: "voss", label: "Voss (Tactical Empathy)", desc: "Onderhandeling — Never Split the Difference." },
  { v: "pre_suasion", label: "Pre-Suasion", desc: "Frame-setting (Cialdini)." },
];

function SalesKlantIntakePage() {
  const { token } = Route.useParams();
  const [project, setProject] = useState<ProjectIntake | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);

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
  const [showExtraContext, setShowExtraContext] = useState(false);


  useEffect(() => {
    async function load() {
      if (!supabase) {
        setError("Supabase niet geconfigureerd.");
        setLoading(false);
        return;
      }
      const { data, error: err } = await supabase
        .schema("sales" as never)
        .rpc("get_intake_by_token", { p_token: token });
      if (err || !data) {
        setError("Deze link is niet meer geldig.");
        setLoading(false);
        return;
      }
      const p = data as ProjectIntake;
      setProject(p);
      setForm({
        prospect_company_name: p.prospect_company_name || "",
        prospect_company_url: p.prospect_company_url || "",
        prospect_sector: p.prospect_sector || "",
        decision_maker_name: p.decision_maker_name || "",
        decision_maker_role: p.decision_maker_role || "",
        decision_maker_linkedin_url: p.decision_maker_linkedin_url || "",
        meeting_datetime: p.meeting_datetime
          ? p.meeting_datetime.slice(0, 16)
          : "",
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
        setShowExtraContext(true);
      }

      setLoading(false);
    }
    load();
  }, [token]);

  const addStakeholder = () =>
    setForm((f) => ({
      ...f,
      additional_stakeholders: [
        ...f.additional_stakeholders,
        { name: "", role: "", linkedin_url: "" },
      ],
    }));
  const updateStakeholder = (
    idx: number,
    field: keyof Stakeholder,
    value: string,
  ) =>
    setForm((f) => ({
      ...f,
      additional_stakeholders: f.additional_stakeholders.map((s, i) =>
        i === idx ? { ...s, [field]: value } : s,
      ),
    }));
  const removeStakeholder = (idx: number) =>
    setForm((f) => ({
      ...f,
      additional_stakeholders: f.additional_stakeholders.filter(
        (_, i) => i !== idx,
      ),
    }));

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
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

    if (!supabase) return;
    setSubmitting(true);

    const cleanStakeholders = form.additional_stakeholders.filter(
      (s) => s.name.trim() || s.role.trim() || s.linkedin_url.trim(),
    );

    const { error: rpcErr } = await supabase
      .schema("sales" as never)
      .rpc("submit_intake_by_token", {
        p_token: token,
        p_prospect_company_name: form.prospect_company_name.trim(),
        p_prospect_company_url: normalizeUrl(form.prospect_company_url),
        p_decision_maker_linkedin_url: normalizeUrl(
          form.decision_maker_linkedin_url,
        ),
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
      setError(`Opslaan faalde: ${rpcErr.message}`);
      return;
    }

    setSubmitted(true);
  }

  if (loading) return <CenteredLoading />;
  if (error && !project) return <CenteredError text={error} />;
  if (submitted && project) return <ThankYouScreen project={project} />;
  if (!project) return <CenteredError text="Onbekende fout." />;

  return (
    <div className="min-h-screen bg-paper text-ink">
      <div className="border-b border-ink/20 px-8 py-4">
        <div className="font-mono text-[10px] uppercase tracking-wider text-pink-500">
          Nestor Sales
        </div>
        <div className="font-serif text-xl">AGENIC</div>
      </div>

      <div className="max-w-3xl mx-auto px-8 py-10">
        <h1 className="font-serif text-4xl mb-2 lowercase">
          welkom {project.klant_name}
        </h1>
        <p className="text-ink/70 mb-8 max-w-2xl">
          {project.klant_company} heeft via Agenic een Nestor Sales meeting-prep
          gevraagd. Vul deze intake in zodat we voor jou de perfecte battlecard
          kunnen voorbereiden voor je volgende verkoopgesprek.
        </p>

        <form onSubmit={handleSubmit} className="space-y-10">
          {/* SECTIE 1 — PROSPECT */}
          <section>
            <SectionHeader
              title="Prospect"
              subtitle="Het bedrijf waar je een meeting mee hebt."
            />

            <Field label="Bedrijfsnaam" required>
              <input
                type="text"
                value={form.prospect_company_name}
                onChange={(e) =>
                  setForm({ ...form, prospect_company_name: e.target.value })
                }
                placeholder="bv. Lukoil België"
                required
                className={inputCls}
              />
            </Field>

            <Field label="Bedrijfs-URL" required>
              <input
                type="text"
                inputMode="url"
                value={form.prospect_company_url}
                onChange={(e) =>
                  setForm({ ...form, prospect_company_url: e.target.value })
                }
                placeholder="lukoil.be"
                required
                className={inputCls}
              />
            </Field>

            <Field label="Sector (optioneel)">
              <input
                type="text"
                value={form.prospect_sector}
                onChange={(e) =>
                  setForm({ ...form, prospect_sector: e.target.value })
                }
                placeholder="bv. Energie / Retail / SaaS"
                className={inputCls}
              />
            </Field>
          </section>

          {/* SECTIE 2 — DE MENSEN AAN TAFEL */}
          <section>
            <SectionHeader
              title="De mensen aan tafel"
              subtitle="Wie ga je spreken?"
            />

            <div
              className="border-l-2 pl-5 mb-6"
              style={{ borderLeftColor: "#FF2D87" }}
            >
              <div
                className="font-mono text-[10px] uppercase tracking-wider mb-3"
                style={{ color: "#FF2D87" }}
              >
                Primary decision maker
              </div>

              <Field
                label="LinkedIn-profiel"
                required
                hint="Kopieer de URL van zijn/haar LinkedIn-profiel."
              >
                <input
                  type="text"
                  inputMode="url"
                  value={form.decision_maker_linkedin_url}
                  onChange={(e) =>
                    setForm({
                      ...form,
                      decision_maker_linkedin_url: e.target.value,
                    })
                  }
                  placeholder="https://linkedin.com/in/voornaam-naam"
                  required
                  className={inputCls}
                />
              </Field>

              <Field label="Naam (optioneel)">
                <input
                  type="text"
                  value={form.decision_maker_name}
                  onChange={(e) =>
                    setForm({ ...form, decision_maker_name: e.target.value })
                  }
                  placeholder="Voor- en achternaam"
                  className={inputCls}
                />
              </Field>

              <Field label="Functie (optioneel)">
                <input
                  type="text"
                  value={form.decision_maker_role}
                  onChange={(e) =>
                    setForm({ ...form, decision_maker_role: e.target.value })
                  }
                  placeholder="bv. CCO, Head of Procurement"
                  className={inputCls}
                />
              </Field>
            </div>

            {form.additional_stakeholders.map((s, idx) => (
              <div
                key={idx}
                className="border-l-2 border-ink/20 pl-5 mb-4"
              >
                <div className="flex items-center justify-between mb-3">
                  <div className="font-mono text-[10px] uppercase tracking-wider text-ink/60">
                    Extra persoon {idx + 1}
                  </div>
                  <button
                    type="button"
                    onClick={() => removeStakeholder(idx)}
                    className="font-mono text-[10px] uppercase tracking-wider text-ink/50 hover:text-pink-500 underline"
                  >
                    Verwijder
                  </button>
                </div>
                <Field label="Naam">
                  <input
                    type="text"
                    value={s.name}
                    onChange={(e) =>
                      updateStakeholder(idx, "name", e.target.value)
                    }
                    className={inputCls}
                  />
                </Field>
                <Field label="Functie">
                  <input
                    type="text"
                    value={s.role}
                    onChange={(e) =>
                      updateStakeholder(idx, "role", e.target.value)
                    }
                    className={inputCls}
                  />
                </Field>
                <Field label="LinkedIn-URL">
                  <input
                    type="text"
                    inputMode="url"
                    value={s.linkedin_url}
                    onChange={(e) =>
                      updateStakeholder(idx, "linkedin_url", e.target.value)
                    }
                    placeholder="https://linkedin.com/in/..."
                    className={inputCls}
                  />
                </Field>
              </div>
            ))}

            <button
              type="button"
              onClick={addStakeholder}
              className="font-mono text-[10px] uppercase tracking-wider border border-ink/30 px-3 py-2 hover:border-ink/60"
            >
              + Voeg extra persoon toe
            </button>
          </section>

          {/* SECTIE 3 — MEETING-CONTEXT */}
          <section>
            <SectionHeader
              title="Meeting-context"
              subtitle="Wanneer, waar, waarom?"
            />

            <Field label="Datum & tijd">
              <input
                type="datetime-local"
                value={form.meeting_datetime}
                onChange={(e) =>
                  setForm({ ...form, meeting_datetime: e.target.value })
                }
                className={inputCls}
              />
            </Field>

            <Field label="Locatie / online">
              <input
                type="text"
                value={form.meeting_location}
                onChange={(e) =>
                  setForm({ ...form, meeting_location: e.target.value })
                }
                placeholder="bv. Hun kantoor / Zoom / Brussel"
                className={inputCls}
              />
            </Field>

            <Field label="Agenda">
              <textarea
                value={form.meeting_agenda}
                onChange={(e) =>
                  setForm({ ...form, meeting_agenda: e.target.value })
                }
                placeholder="Wat staat er op de agenda?"
                rows={3}
                className={inputCls}
              />
            </Field>

            <Field label="Tijdsdruk / deadline">
              <input
                type="text"
                value={form.meeting_deadline}
                onChange={(e) =>
                  setForm({ ...form, meeting_deadline: e.target.value })
                }
                placeholder='bv. "Beslissing voor Q3" / "Geen druk"'
                className={inputCls}
              />
            </Field>
          </section>

          {/* SECTIE 4 — CONTEXT & NADRUK */}
          <section>
            <SalesContextFields
              values={context}
              onChange={setContext}
              variant="intake"
            />
          </section>

          {/* SECTIE 5 — JOUW KANT */}
          <section>
            <SectionHeader
              title="Jouw kant"
              subtitle="Wat verkoop je en wat hoop je te bereiken?"
            />

            <Field label="Sales-objectief" required>
              <textarea
                value={form.sales_objective}
                onChange={(e) =>
                  setForm({ ...form, sales_objective: e.target.value })
                }
                placeholder="Wat wil je uit deze meeting halen? Vrij beschrijven."
                rows={3}
                required
                className={inputCls}
              />
            </Field>

            <Field
              label="Wat verkoop je / aanbod"
              required
              hint="Zonder dit blijft de battlecard generiek. Nestor weet niet wat hij moet verdedigen tegen objections."
            >
              <textarea
                value={form.product_offering}
                onChange={(e) =>
                  setForm({ ...form, product_offering: e.target.value })
                }
                placeholder="2-3 zinnen. Welk product/dienst, voor wie, met welke prijs-indicatie?"
                rows={3}
                required
                className={inputCls}
              />
            </Field>

            <Field label="Hypotheses — Wat denk je dat hun pijn is?">
              <textarea
                value={form.hypotheses}
                onChange={(e) =>
                  setForm({ ...form, hypotheses: e.target.value })
                }
                placeholder="Jouw best guess. Nestor valideert en scherpt aan."
                rows={3}
                className={inputCls}
              />
            </Field>

            <Field label="Concurrenten / incumbents">
              <textarea
                value={form.competitors}
                onChange={(e) =>
                  setForm({ ...form, competitors: e.target.value })
                }
                placeholder='Wie gebruiken ze nu? Met wie vergelijken ze? bv. "Gebruiken Salesforce, evalueren HubSpot"'
                rows={2}
                className={inputCls}
              />
            </Field>
          </section>

          {/* COLLAPSIBLE — EXTRA CONTEXT */}
          <section className="border border-ink/15 bg-paperLight">
            <button
              type="button"
              onClick={() => setShowExtraContext((v) => !v)}
              className="w-full flex items-center justify-between px-5 py-3 text-left"
            >
              <span className="font-mono text-[10px] uppercase tracking-wider text-ink/60">
                Extra context (optioneel)
              </span>
              <span
                className="font-mono text-[10px]"
                style={{ color: "#FF2D87" }}
              >
                {showExtraContext ? "− verberg" : "+ toon"}
              </span>
            </button>
            {showExtraContext && (
              <div className="px-5 pb-5 space-y-4 border-t border-ink/15 pt-4">
                <Field label="Voorgaande contact-historiek">
                  <textarea
                    value={form.prior_contact_summary}
                    onChange={(e) =>
                      setForm({
                        ...form,
                        prior_contact_summary: e.target.value,
                      })
                    }
                    placeholder="Calls, demos, referral via wie? Hoe hebben ze ons gevonden?"
                    rows={2}
                    className={inputCls}
                  />
                </Field>

                <Field
                  label="Grootste angst voor deze meeting"
                  hint="Nestor maakt hier expliciet een Wat-als scenario voor."
                >
                  <textarea
                    value={form.biggest_concern}
                    onChange={(e) =>
                      setForm({ ...form, biggest_concern: e.target.value })
                    }
                    placeholder='bv. "Dat ze al iets intern bouwen" / "Dat CFO meekomt en het kapot wil maken"'
                    rows={2}
                    className={inputCls}
                  />
                </Field>

                <Field label="Specifieke vraag die je beantwoord wil zien">
                  <textarea
                    value={form.specific_question}
                    onChange={(e) =>
                      setForm({ ...form, specific_question: e.target.value })
                    }
                    placeholder='bv. "Hebben ze al een AI-strategie?" / "Wie is de echte budget-houder?"'
                    rows={2}
                    className={inputCls}
                  />
                </Field>

                <Field label="Geografie / cultuur">
                  <select
                    value={form.geography_culture}
                    onChange={(e) =>
                      setForm({ ...form, geography_culture: e.target.value })
                    }
                    className={inputCls}
                  >
                    <option value="">Niet relevant</option>
                    {GEOGRAPHY_OPTIONS.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                </Field>

                <Field label="Status van de relatie">
                  <select
                    value={form.relationship_status}
                    onChange={(e) =>
                      setForm({
                        ...form,
                        relationship_status: e.target.value,
                      })
                    }
                    className={inputCls}
                  >
                    <option value="">— Kies één —</option>
                    <option value="first_contact">Eerste contact</option>
                    <option value="ongoing">Lopend gesprek</option>
                    <option value="re_engagement">Re-engagement</option>
                    <option value="close">Close-meeting</option>
                  </select>
                </Field>

                <Field label="Sales-methode voorkeur">
                  <select
                    value={form.sales_method}
                    onChange={(e) =>
                      setForm({ ...form, sales_method: e.target.value })
                    }
                    className={inputCls}
                  >
                    {SALES_METHODS.map((m) => (
                      <option key={m.v || "none"} value={m.v}>
                        {m.label} — {m.desc}
                      </option>
                    ))}
                  </select>
                </Field>
              </div>
            )}
          </section>

          {error && (
            <div className="bg-pink-50 border border-pink-300 px-4 py-3 text-sm text-pink-800">
              {error}
            </div>
          )}

          <div className="flex justify-end pt-4 border-t border-ink/20">
            <button
              type="submit"
              disabled={submitting}
              className="bg-ink text-paperLight font-mono text-xs uppercase tracking-wider px-8 py-3 disabled:opacity-50"
            >
              {submitting ? "Bezig..." : "Indienen →"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
