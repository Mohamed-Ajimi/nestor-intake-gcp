import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useState, type ReactNode } from "react";
import { supabase } from "@/lib/supabase";
import {
  SalesContextFields,
  EMPTY_SALES_CONTEXT,
  type SalesContextValues,
} from "@/components/sales/SalesContextFields";


export const Route = createFileRoute("/admin/sales/projects/new")({
  component: NewSalesProjectPage,
});

function NewSalesProjectPage() {
  const navigate = useNavigate();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [klantName, setKlantName] = useState("");
  const [klantEmail, setKlantEmail] = useState("");
  const [klantCompany, setKlantCompany] = useState("");
  const [klantRole, setKlantRole] = useState("");
  const [projectTitle, setProjectTitle] = useState("");
  const [context, setContext] = useState<SalesContextValues>(EMPTY_SALES_CONTEXT);


  function validateEmail(e: string): boolean {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(e.trim());
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (!klantName.trim()) {
      setError("Naam is verplicht");
      return;
    }
    if (!validateEmail(klantEmail)) {
      setError("Geldige email is verplicht");
      return;
    }
    if (!klantCompany.trim()) {
      setError("Bedrijf is verplicht");
      return;
    }

    if (!supabase) {
      setError("Supabase niet geconfigureerd.");
      return;
    }

    setSaving(true);
    const { data, error: rpcErr } = await supabase
      .schema("sales" as never)
      .rpc("create_project", {
        p_klant_name: klantName.trim(),
        p_klant_email: klantEmail.trim(),
        p_klant_company: klantCompany.trim(),
        p_klant_role: klantRole.trim() || null,
        p_project_title: projectTitle.trim() || null,
        p_meeting_type: context.meeting_type || null,
        p_deal_stage: context.deal_stage || null,
        p_klant_type: context.klant_type || null,
        p_industry_vertical: context.industry_vertical.trim() || null,
      });
    setSaving(false);

    if (rpcErr) {
      setError(`Aanmaken faalde: ${rpcErr.message}`);
      return;
    }

    const projectId = (data as Array<{ id: string }> | null)?.[0]?.id;
    if (projectId) {
      navigate({ to: "/admin/sales/projects" });
    } else {
      navigate({ to: "/admin/sales/projects" });
    }
  }

  return (
    <div className="max-w-2xl">
      <Link
        to="/admin/sales/projects"
        className="font-mono text-xs uppercase tracking-wider text-ink/60 hover:text-ink"
      >
        ← Terug naar projecten
      </Link>

      <h1 className="mt-6 font-serif text-3xl font-normal lowercase tracking-tight text-ink">
        nieuw project
      </h1>
      <p className="mt-2 max-w-xl text-sm text-ink/60">
        Vul de basisinfo in van de klant. Die krijgt straks een mail met een
        intake-link om de meeting-prep details door te geven.
      </p>

      <form onSubmit={handleSubmit} className="mt-10 space-y-10">
        <section>
          <h2 className="font-mono text-xs uppercase tracking-wider text-ink/60">
            Klant-info
          </h2>
          <div className="mt-4 space-y-4">
            <Field label="Naam" required>
              <input
                type="text"
                value={klantName}
                onChange={(e) => setKlantName(e.target.value)}
                placeholder="bv. Sven Luyten"
                className="w-full border border-ink/30 bg-paper px-3 py-2 font-mono text-sm"
                required
              />
            </Field>

            <Field label="Email" required>
              <input
                type="email"
                value={klantEmail}
                onChange={(e) => setKlantEmail(e.target.value)}
                placeholder="bv. sven@cronos.be"
                className="w-full border border-ink/30 bg-paper px-3 py-2 font-mono text-sm"
                required
              />
              <p className="mt-1 text-xs text-ink/50">
                Waar de intake-link naar gestuurd wordt.
              </p>
            </Field>

            <Field label="Bedrijf" required>
              <input
                type="text"
                value={klantCompany}
                onChange={(e) => setKlantCompany(e.target.value)}
                placeholder="bv. Cronos"
                className="w-full border border-ink/30 bg-paper px-3 py-2 font-mono text-sm"
                required
              />
            </Field>

            <Field label="Rol">
              <input
                type="text"
                value={klantRole}
                onChange={(e) => setKlantRole(e.target.value)}
                placeholder="bv. Investment Lead, CCO, Sales Director"
                className="w-full border border-ink/30 bg-paper px-3 py-2 font-mono text-sm"
              />
            </Field>
          </div>
        </section>

        <section>
          <h2 className="font-mono text-xs uppercase tracking-wider text-ink/60">
            Intern (optioneel)
          </h2>
          <div className="mt-4">
            <Field label="Project-titel">
              <input
                type="text"
                value={projectTitle}
                onChange={(e) => setProjectTitle(e.target.value)}
                placeholder="bv. Sven Luyten — Cronos Q2 funding"
                className="w-full border border-ink/30 bg-paper px-3 py-2 font-mono text-sm"
              />
              <p className="mt-1 text-xs text-ink/50">
                Eigen label om dit project te herkennen. Klant ziet dit niet.
              </p>
            </Field>
          </div>
        </section>

        <section>
          <h2 className="font-mono text-xs uppercase tracking-wider text-ink/60">
            Context & nadruk
          </h2>
          <p className="mt-2 max-w-xl text-xs text-ink/50">
            Deze velden sturen de nadruk van de battlecard. Optioneel — klant
            kan ze ook zelf invullen in de intake.
          </p>
          <div className="mt-4">
            <SalesContextFields
              values={context}
              onChange={setContext}
              variant="admin"
            />
          </div>
        </section>



        {error && (
          <div className="border border-red-500/40 bg-red-500/5 px-3 py-2 font-mono text-xs text-red-700">
            {error}
          </div>
        )}

        <div className="flex items-center justify-between border-t border-ink/15 pt-6">
          <button
            type="button"
            onClick={() => navigate({ to: "/admin/sales/projects" })}
            className="font-mono text-xs uppercase tracking-wider text-ink/60 hover:text-ink"
          >
            Annuleer
          </button>
          <button
            type="submit"
            disabled={saving}
            className="bg-ink px-4 py-2 font-mono text-xs uppercase tracking-wider text-paper hover:bg-ink/90 disabled:opacity-50"
          >
            {saving ? "Bezig..." : "Project aanmaken →"}
          </button>
        </div>
      </form>
    </div>
  );
}

function Field({
  label,
  children,
  required,
}: {
  label: string;
  children: ReactNode;
  required?: boolean;
}) {
  return (
    <label className="block">
      <span className="block font-mono text-[11px] uppercase tracking-wider text-ink/70">
        {label}
        {required && <span className="ml-1 text-red-600">*</span>}
      </span>
      <div className="mt-1.5">{children}</div>
    </label>
  );
}
