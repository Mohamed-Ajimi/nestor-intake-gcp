import { createFileRoute, redirect, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { onAuthStateChanged, signOut, type User } from "firebase/auth";
import { auth } from "@/lib/firebase";
import { useAuth } from "@/lib/auth-context";
import { getIntake } from "@/lib/api/intakes";
import { listAnswers } from "@/lib/api/answers";
import { getTemplates } from "@/lib/api/templates";
import type { IntakePayload, IntakeSchema } from "@/lib/intake-types";
import { IntakeForm } from "@/components/intake/IntakeForm";

// frontend/src/routes/intake.$id.tsx — the authenticated USER fill/submit route
// (`/intake/$id`). Net-New Surface 2 (06-UI-SPEC). Hosts the REUSED IntakeForm (save-per-
// section + submit live in the form, swapped to the lib/api seam in plan 06) — do NOT
// fork it. NOT under /admin, no ProductShell: IntakeForm renders its own full-bleed
// header so this route adds no extra chrome. The form is editable only for `draft`;
// submitted/reviewed are hosted read-only ("Antwoorden bekijken").

function authReady(): Promise<User | null> {
  if (auth.currentUser) return Promise.resolve(auth.currentUser);
  return new Promise((resolve) => {
    const unsubscribe = onAuthStateChanged(auth, (user) => {
      unsubscribe();
      resolve(user);
    });
  });
}

export const Route = createFileRoute("/intake/$id")({
  beforeLoad: async () => {
    const user = await authReady();
    if (!user) {
      throw redirect({ to: "/auth/login" });
    }
  },
  component: UserIntakeFillPage,
});

function UserIntakeFillPage() {
  const { id } = Route.useParams();
  const { t } = useTranslation("intake");
  const { session } = useAuth();
  const navigate = useNavigate();
  const [payload, setPayload] = useState<IntakePayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      // Load the intake, its stored answers, and the space's template via the seam.
      const [intakeRes, answersRes, templatesRes] = await Promise.all([
        getIntake(id),
        listAnswers(id),
        getTemplates(),
      ]);
      if (cancelled) return;

      if (!intakeRes.success || !answersRes.success || !templatesRes.success) {
        setError(t("route.loadFailed"));
        setLoading(false);
        return;
      }

      const template = templatesRes.data[0];
      if (!template) {
        setError(t("route.noTemplate"));
        setLoading(false);
        return;
      }

      // Backend `AnswerView` carries the scalar `value` plus structured `value_json`
      // (lists/objects); the form expects one value per field key.
      const answersMap: Record<string, unknown> = {};
      for (const a of answersRes.data) {
        answersMap[a.field_key] = a.value_json ?? a.value;
      }

      const intake = intakeRes.data;
      setPayload({
        intake: {
          id: intake.id,
          product_slug: "pulse",
          status: intake.status,
          title: intake.client_name ?? "",
          created_at: "",
          updated_at: "",
        },
        client: { id: intake.space_id, name: intake.client_name ?? "" },
        template: {
          id: template.id,
          name: template.name,
          version: 1,
          schema: (template.schema ?? {}) as unknown as IntakeSchema,
        },
        answers: answersMap,
        // Only drafts are editable; submitted/reviewed render read-only.
        editable: intake.status === "draft",
        // Reviewed intakes enter the client-validation phase: the form shows Nestor's
        // refinements (ValidationDiff) and "Akkoord — verstuur" drives the
        // reviewed -> validated_by_client transition. Everything else is the plain form.
        phase:
          intake.status === "reviewed" || intake.status === "validated_by_client"
            ? "validation"
            : "intake",
      });
      setError(null);
      setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [id, t]);

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
        <p className="font-mono text-xs uppercase tracking-wider text-ink/40">{t("route.loading")}</p>
      </div>
    );
  }

  if (error || !payload) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-6 bg-paper px-6 text-center">
        <p className="max-w-md text-sm text-red-600">
          {error ?? t("route.loadFailed")}
        </p>
        <div className="flex items-center gap-4 font-mono text-xs uppercase tracking-wider text-ink/60">
          <button
            type="button"
            onClick={() => navigate({ to: "/intake" })}
            className="underline-offset-2 hover:text-ink hover:underline"
          >
            {t("route.backToOverview")}
          </button>
          {session?.email && (
            <button
              type="button"
              onClick={handleLogout}
              className="underline-offset-2 hover:text-ink hover:underline"
            >
              {t("route.logout")}
            </button>
          )}
        </div>
      </div>
    );
  }

  // Host the reused form — `token` keys the form's local draft cache; the seam keys all
  // persistence on the intake id. Do NOT fork IntakeForm.
  return <IntakeForm payload={payload} token={payload.intake.id} />;
}
