import { createFileRoute, Outlet, redirect, useNavigate } from "@tanstack/react-router";
import { onAuthStateChanged, signOut, type User } from "firebase/auth";
import { useTranslation } from "react-i18next";
import { auth, MOCK_AUTH } from "@/lib/firebase";
import { useAuth } from "@/lib/auth-context";

// Firebase resolves `auth.currentUser` only after the first onAuthStateChanged
// tick (Open Q2). This promise resolves with the initial auth state so the
// guard can await it instead of racing a not-yet-populated currentUser.
function authReady(): Promise<User | null> {
  if (auth.currentUser) return Promise.resolve(auth.currentUser);
  return new Promise((resolve) => {
    const unsubscribe = onAuthStateChanged(auth, (user) => {
      unsubscribe();
      resolve(user);
    });
  });
}

export const Route = createFileRoute("/admin")({
  // UX gating only — the authoritative control is the backend
  // get_current_identity dependency (plans 02/03). This guard is
  // defense-in-depth; live behavior is validated in GCP at/after Phase 12 (D-09).
  beforeLoad: async () => {
    if (MOCK_AUTH) return; // mock mode: bypass Firebase auth check
    const user = await authReady();
    if (!user) {
      throw redirect({ to: "/auth/login" });
    }
  },
  component: AdminLayout,
});

// Component-level superadmin guard (D-LI2-02). A beforeLoad role redirect to
// /auth/login would LOOP — LoginPage auto-navigates back to /admin whenever a
// session exists — so denial is rendered in-place with an explicit logout that
// clears the session first. The beforeLoad UNAUTHENTICATED redirect above is
// kept (no session there, so it cannot loop). UX gating only — the backend is
// the authority on every admin route.
function AdminLayout() {
  const { loading, isSuperadmin } = useAuth();
  const navigate = useNavigate();
  const { t } = useTranslation("common");

  // Avoid a denial flash before the auth/claim state resolves.
  if (loading) return null;

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
