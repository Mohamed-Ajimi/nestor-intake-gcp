import { createFileRoute, Outlet, useNavigate } from "@tanstack/react-router";
import { signOut } from "firebase/auth";
import { useTranslation } from "react-i18next";
import { auth } from "@/lib/firebase";
import { useAuth } from "@/lib/auth-context";
import { requireAuthBeforeLoad, useRequireAuth } from "@/lib/auth-guard";

export const Route = createFileRoute("/admin")({
  // UX gating only — the authoritative control is the backend
  // get_current_identity dependency (plans 02/03). This guard is
  // defense-in-depth; live behavior is validated in GCP at/after Phase 12 (D-09).
  //
  // CLIENT-ONLY (see lib/auth-guard.tsx). The local copy this replaced also ran during
  // SSR, where the browser-held Firebase session is structurally invisible, so it
  // redirected to /auth/login on EVERY refresh of every admin page; the client then
  // rehydrated and dropped the operator on /admin instead of the page they were on.
  // The genuine signed-out redirect now happens post-hydration in `useRequireAuth`.
  beforeLoad: requireAuthBeforeLoad,
  component: AdminLayout,
});

// Component-level superadmin guard (D-LI2-02). A beforeLoad role redirect to
// /auth/login would LOOP — LoginPage auto-navigates back to /admin whenever a
// session exists — so denial is rendered in-place with an explicit logout that
// clears the session first. The UNAUTHENTICATED redirect lives in `useRequireAuth`
// (no session there, so it cannot loop). UX gating only — the backend is
// the authority on every admin route.
function AdminLayout() {
  const { loading, isSuperadmin } = useAuth();
  const { checking } = useRequireAuth();
  const navigate = useNavigate();
  const { t } = useTranslation("common");

  // Avoid a denial flash before the auth/claim state resolves, and while a signed-out
  // visitor is being redirected to /auth/login (`checking`) — showing the role-denial
  // wall to someone who simply is not signed in would be wrong on both counts.
  if (loading || checking) return null;

  if (!isSuperadmin) {
    const handleLogout = async () => {
      try {
        await signOut(auth);
      } finally {
        navigate({ to: "/auth/login" });
      }
    };

    return (
      <div className="flex min-h-screen items-center justify-center bg-paper2 px-6">
        <div className="w-full max-w-md border border-ink bg-paper px-8 py-10">
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-ink/50">
            {t("accessDenied.brand")}
          </p>
          <h1 className="mt-2 font-serif text-2xl lowercase text-ink">
            {t("accessDenied.title")}
          </h1>
          <p className="mt-4 text-sm text-ink/70">{t("accessDenied.body")}</p>
          <button
            onClick={handleLogout}
            className="mt-8 font-mono text-xs uppercase tracking-wider text-ink/60 underline-offset-2 hover:text-ink hover:underline"
          >
            {t("accessDenied.logout")}
          </button>
        </div>
      </div>
    );
  }

  return <Outlet />;
}
