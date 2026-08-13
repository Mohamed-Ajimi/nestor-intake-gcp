import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { formatDistanceToNow } from "date-fns";
import { getDateLocale } from "@/lib/i18n/date-locale";
import { Inbox } from "lucide-react";
import { signOut } from "firebase/auth";
import { auth } from "@/lib/firebase";
import { useAuth } from "@/lib/auth-context";
import { requireAuthBeforeLoad, RequireAuth } from "@/lib/auth-guard";
import { listIntakes, type Intake } from "@/lib/api/intakes";
import { StatusPill } from "@/components/intake/_status";
import { TopBar } from "@/components/TopBar";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";

// frontend/src/routes/intake.index.tsx — the authenticated, space-scoped USER intake
// list (`/intake`). Net-New Surface 2 (06-UI-SPEC). NOT under /admin, does NOT mount
// ProductShell or the space switcher — a user is hard-pinned to one space, which the
// backend derives from the verified token (the list call sends no space_id). Reuses the
// shared StatusPill atom + the lib/api seam (no inline legacy data client). The header
// DOES mount the persisting LanguageSwitcher (UAT defect 1): a user needs to change
// their display language post-login, and this page has no other chrome to host it.

export const Route = createFileRoute("/intake/")({
  // UX gating only — the authoritative control is the backend get_current_identity
  // dependency. Redirect to login when signed out (no session → cannot loop).
  //
  // Shared SSR-safe guard (lib/auth-guard.tsx). The local copy this replaced also ran
  // during SSR, where the browser-held Firebase session is invisible, so refreshing this
  // page 307'd to /auth/login and then landed the user on their role's home instead of
  // here. <RequireAuth> keeps the real signed-out redirect, client-side, and also keeps
  // this page's data effect from firing tokenless.
  beforeLoad: requireAuthBeforeLoad,
  component: () => (
    <RequireAuth>
      <UserIntakeListPage />
    </RequireAuth>
  ),
});

// The seam `Intake` projection is status + phase markers; `title`/`updated_at` are
// optional list-display extras the backend `IntakeView` may carry. Read them defensively
// so the list renders whatever the projection provides without widening the seam type.
type IntakeListRow = Intake & { title?: string | null; updated_at?: string | null };

type RowCta = { label: string; target: "fill" | "results" | "report" };

// Status → contextual CTA (06-UI-SPEC § Net-New 2). draft fills; submitted/reviewed view
// answers read-only (still /intake/$id); delivered opens the report page (D-09);
// validated/decomposed view the result set.
// `t` is threaded in from the component (this pure helper cannot call hooks).
function rowCta(status: string | null, t: TFunction): RowCta {
  if (status === "draft") return { label: t("list.ctaFill"), target: "fill" };
  if (status === "submitted" || status === "reviewed")
    return { label: t("list.ctaView"), target: "fill" };
  // Delivered → the client-facing report page (D-09), not the generic result CTA.
  if (status === "delivered") return { label: t("list.ctaReport"), target: "report" };
  return { label: t("list.ctaResult"), target: "results" };
}

function UserIntakeListPage() {
  const { t, i18n } = useTranslation("intake");
  const { session } = useAuth();
  const navigate = useNavigate();
  const [intakes, setIntakes] = useState<IntakeListRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      const res = await listIntakes();
      if (cancelled) return;
      if (!res.success) {
        setError(t("route.loadFailed"));
        setIntakes([]);
        setLoading(false);
        return;
      }
      setError(null);
      setIntakes(res.data as IntakeListRow[]);
      setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [t]);

  const spaceName = intakes.find((i) => i.client_name)?.client_name ?? null;

  const openRow = (row: IntakeListRow) => {
    const cta = rowCta(row.status, t);
    if (cta.target === "report") {
      navigate({ to: "/intake/$id/report", params: { id: row.id } });
      return;
    }
    if (cta.target === "results") {
      navigate({ to: "/intake/$id/results", params: { id: row.id } });
    } else {
      navigate({ to: "/intake/$id", params: { id: row.id } });
    }
  };

  const handleLogout = async () => {
    try {
      await signOut(auth);
    } finally {
      navigate({ to: "/auth/login" });
    }
  };

  return (
    <div className="min-h-screen bg-paper text-ink">
      <TopBar />
      <div className="mx-auto max-w-4xl px-6 py-12">
        {/* Minimal authenticated chrome — no admin nav, no space switcher */}
        <div className="mb-10 flex items-center justify-between">
          <p className="font-mono text-xs uppercase tracking-widest text-ink/60">{t("list.brand")}</p>
          <div className="flex items-center gap-4 font-mono text-xs uppercase tracking-wider text-ink/60">
            {session?.email && <span className="font-medium text-ink/70">{session.email}</span>}
            <button
              type="button"
              onClick={handleLogout}
              className="underline-offset-2 hover:text-ink hover:underline"
            >
              {t("list.logout")}
            </button>
          </div>
        </div>

        <header className="mb-8">
          <h1 className="font-serif text-3xl font-normal lowercase tracking-tight text-ink">
            {t("list.heading")}
          </h1>
          <p className="mt-1 text-sm text-ink/60">
            {spaceName
              ? t("list.subtitleForSpace", { name: spaceName })
              : t("list.subtitle")}
          </p>
        </header>

        <div className="border border-ink bg-paper">
          <Table>
            <TableHeader>
              <TableRow className="border-ink hover:bg-transparent">
                <TableHead className="px-4 font-mono text-xs uppercase tracking-wider text-ink">
                  {t("list.colTitle")}
                </TableHead>
                <TableHead className="px-4 font-mono text-xs uppercase tracking-wider text-ink">
                  {t("list.colStatus")}
                </TableHead>
                <TableHead className="px-4 font-mono text-xs uppercase tracking-wider text-ink">
                  {t("list.colLastEdited")}
                </TableHead>
                <TableHead className="px-4 text-right font-mono text-xs uppercase tracking-wider text-ink">
                  {""}
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                Array.from({ length: 3 }).map((_, i) => (
                  <TableRow key={i}>
                    {Array.from({ length: 4 }).map((__, j) => (
                      <TableCell key={j} className="px-4 py-4">
                        <Skeleton className="h-4 w-full max-w-[140px]" />
                      </TableCell>
                    ))}
                  </TableRow>
                ))
              ) : error ? (
                <TableRow className="hover:bg-transparent">
                  <TableCell colSpan={4} className="px-4 py-12 text-center text-sm text-red-600">
                    {error}
                  </TableCell>
                </TableRow>
              ) : intakes.length === 0 ? (
                <TableRow className="hover:bg-transparent">
                  <TableCell colSpan={4} className="px-4 py-16">
                    <div className="flex flex-col items-center text-center">
                      <Inbox className="h-8 w-8 text-ink/30" />
                      <p className="mt-3 text-sm font-medium text-ink">
                        {t("list.empty")}
                      </p>
                      <p className="mt-1 max-w-md text-sm text-ink/60">
                        {t("list.emptyBody")}
                      </p>
                    </div>
                  </TableCell>
                </TableRow>
              ) : (
                intakes.map((row) => {
                  const cta = rowCta(row.status, t);
                  return (
                    <TableRow
                      key={row.id}
                      className="group cursor-pointer"
                      onClick={() => openRow(row)}
                    >
                      <TableCell className="px-4 py-3 text-sm text-ink/70">
                        {row.title ?? row.client_name ?? t("list.dash")}
                      </TableCell>
                      <TableCell className="px-4 py-3">
                        <StatusPill status={row.status} />
                      </TableCell>
                      <TableCell className="px-4 py-3 text-sm text-ink/60">
                        {row.updated_at
                          ? formatDistanceToNow(new Date(row.updated_at), {
                              addSuffix: true,
                              locale: getDateLocale(i18n.language),
                            })
                          : t("list.dash")}
                      </TableCell>
                      <TableCell className="px-4 py-3 text-right">
                        <span className="font-mono text-xs uppercase tracking-wider text-ink/60 underline-offset-2 group-hover:underline">
                          {cta.label}
                        </span>
                      </TableCell>
                    </TableRow>
                  );
                })
              )}
            </TableBody>
          </Table>
        </div>
      </div>
    </div>
  );
}
