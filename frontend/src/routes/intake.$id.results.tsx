import { createFileRoute, redirect, useNavigate } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { onAuthStateChanged, signOut, type User } from "firebase/auth";
import { auth } from "@/lib/firebase";
import { useAuth } from "@/lib/auth-context";
import { getIntake } from "@/lib/api/intakes";
import { listAnswers } from "@/lib/api/answers";
import { getTemplates } from "@/lib/api/templates";
import type { LocalizedIntakeSchema } from "@/lib/intake-types";
import { localizeSchema } from "@/lib/i18n/localizeSchema";
import { FieldDisplay } from "@/components/intake/FieldDisplay";
import { StatusPill } from "@/components/intake/_status";

// frontend/src/routes/intake.$id.results.tsx — the authenticated USER read-only results
// view (`/intake/$id/results`). Net-New Surface 2 (06-UI-SPEC). Renders ONLY the
// validated answer set via the reused FieldDisplay, grouped by section.
//
// SCOPE CEILING (T-06-26): the flow stops at `decomposed`. This view never renders
// ResearchResultsPanel/ContextPackBlock (post-decomposed / Phase 7+). If the intake is
// not yet validated by the client there is nothing to show, so it redirects back to the
// fill route.

function authReady(): Promise<User | null> {
  if (auth.currentUser) return Promise.resolve(auth.currentUser);
  return new Promise((resolve) => {
    const unsubscribe = onAuthStateChanged(auth, (user) => {
      unsubscribe();
      resolve(user);
    });
  });
}

export const Route = createFileRoute("/intake/$id/results")({
  beforeLoad: async () => {
    const user = await authReady();
    if (!user) {
      throw redirect({ to: "/auth/login" });
    }
  },
  component: UserIntakeResultsPage,
});

// Status ordering — results are available from `validated_by_client` onward; anything
// earlier has no validated answer set to show yet.
const STATUS_RANK: Record<string, number> = {
  draft: 0,
  submitted: 1,
  reviewed: 2,
  validated_by_client: 3,
  decomposed: 4,
  in_research: 5,
  delivered: 6,
  archived: 7,
};

function isValidatedOrLater(status: string): boolean {
  return (STATUS_RANK[status] ?? -1) >= STATUS_RANK.validated_by_client;
}

function UserIntakeResultsPage() {
  const { t, i18n } = useTranslation("intake");
  const { id } = Route.useParams();
  const { session } = useAuth();
  const navigate = useNavigate();
  // The template serves the RAW multi-locale schema (LocalizedString objects, Phase 11);
  // keep the raw source in state and flatten at render time so a language switch
  // re-resolves without refetching (mirrors IntakeForm's useMemo pattern, CR-02).
  const [rawSchema, setRawSchema] = useState<LocalizedIntakeSchema | null>(null);
  const [answers, setAnswers] = useState<Record<string, unknown>>({});
  const [status, setStatus] = useState<string | null>(null);
  const [title, setTitle] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      const intakeRes = await getIntake(id);
      if (cancelled) return;
      if (!intakeRes.success) {
        setError(t("resultsRoute.loadFailed"));
        setLoading(false);
        return;
      }

      // Phase-ceiling gate: nothing to show before the client validated — go fill it.
      if (!isValidatedOrLater(intakeRes.data.status)) {
        navigate({ to: "/intake/$id", params: { id } });
        return;
      }

      const [answersRes, templatesRes] = await Promise.all([listAnswers(id), getTemplates()]);
      if (cancelled) return;
      if (!answersRes.success || !templatesRes.success) {
        setError(t("resultsRoute.loadFailed"));
        setLoading(false);
        return;
      }

      const template = templatesRes.data[0];
      if (!template) {
        setError(t("resultsRoute.noTemplate"));
        setLoading(false);
        return;
      }

      const answersMap: Record<string, unknown> = {};
      for (const a of answersRes.data) {
        answersMap[a.field_key] = a.value_json ?? a.value;
      }

      setRawSchema((template.schema ?? null) as unknown as LocalizedIntakeSchema | null);
      setAnswers(answersMap);
      setStatus(intakeRes.data.status);
      setTitle(intakeRes.data.client_name ?? "");
      setError(null);
      setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [id, navigate, t]);

  // Flatten the multi-locale source to the active locale (nl fallback, D-05).
  const schema = useMemo(
    () => (rawSchema?.sections ? localizeSchema(rawSchema, i18n.language) : null),
    [rawSchema, i18n.language],
  );

  const handleLogout = async () => {
    try {
      await signOut(auth);
    } finally {
      navigate({ to: "/auth/login" });
    }
  };

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-paper px-6">
        <p className="font-mono text-xs uppercase tracking-wider text-ink/40">
          {t("resultsRoute.loading")}
        </p>
      </div>
    );
  }

  if (error || !schema) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-6 bg-paper px-6 text-center">
        <p className="max-w-md text-sm text-red-600">
          {error ?? t("resultsRoute.loadFailed")}
        </p>
        <button
          type="button"
          onClick={() => navigate({ to: "/intake" })}
          className="font-mono text-xs uppercase tracking-wider text-ink/60 underline-offset-2 hover:text-ink hover:underline"
        >
          {t("resultsRoute.backToOverview")}
        </button>
      </div>
    );
  }

  // Validated answer set only — no post-decomposed research output (scope ceiling).
  const sections = schema.sections.filter((s) => !s.admin_only);

  return (
    <div className="min-h-screen bg-paper text-ink">
      <div className="mx-auto max-w-4xl px-6 py-12">
        {/* Minimal authenticated chrome — no admin nav, no space switcher */}
        <div className="mb-10 flex items-center justify-between">
          <p className="font-mono text-xs uppercase tracking-widest text-ink/60">
            {t("resultsRoute.brand")}
          </p>
          <div className="flex items-center gap-4 font-mono text-xs uppercase tracking-wider text-ink/60">
            {session?.email && <span className="font-medium text-ink/70">{session.email}</span>}
            <button
              type="button"
              onClick={handleLogout}
              className="underline-offset-2 hover:text-ink hover:underline"
            >
              {t("resultsRoute.logout")}
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
              {t("resultsRoute.overview")}
            </button>
            <h1 className="mt-2 font-serif text-3xl font-normal lowercase tracking-tight text-ink">
              {title || t("resultsRoute.titleFallback")}
            </h1>
          </div>
          <StatusPill status={status} />
        </header>

        <div className="space-y-8">
          {sections.map((section) => (
            <section key={section.id} className="border border-ink bg-paper p-6 md:p-10">
              <h2 className="mb-6 font-serif text-2xl font-normal lowercase tracking-tight text-ink">
                {section.title}
              </h2>
              <dl>
                {section.fields.map((field) => (
                  <FieldDisplay key={field.key} field={field} value={answers[field.key]} intakeId={id} />
                ))}
              </dl>
            </section>
          ))}
        </div>
      </div>
    </div>
  );
}
