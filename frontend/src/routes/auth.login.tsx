import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { getIdTokenResult, signInWithEmailAndPassword } from "firebase/auth";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { apiUrl, auth } from "@/lib/firebase";
import { landingPathForRole, useAuth, type Role } from "@/lib/auth-context";
import { LanguageSwitcher, LOCALE_STORAGE_KEY } from "@/components/LanguageSwitcher";
import { detectLocale } from "@/lib/i18n/detect";

// WR-02: a failed login-sync handshake throws this so the catch can surface an
// authorization-specific message and NOT navigate to /admin (vs. a sign-in error).
class SyncError extends Error {}

export const Route = createFileRoute("/auth/login")({
  component: LoginPage,
});

function LoginPage() {
  const navigate = useNavigate();
  const { t, i18n } = useTranslation("auth");
  const { session, loading, role, getToken } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Pre-login language (D-08/D-09): on first client render, if the visitor has not
  // yet made an explicit choice (no pending pre-login localStorage entry), initialize
  // the display language from `detectLocale()` (browser → nl/fr/en else nl). This runs
  // client-side only — `detectLocale` is `typeof window`-guarded, and this effect never
  // runs on the SSR shell (Pitfall 1). The pre-login switcher below (persist=false)
  // writes the choice to localStorage so the post-login boot can reconcile it (Task 3).
  useEffect(() => {
    let chosen: string | null = null;
    try {
      chosen = window.localStorage.getItem(LOCALE_STORAGE_KEY);
    } catch {
      /* ignore — detection falls back to the browser default */
    }
    if (!chosen) {
      const detected = detectLocale();
      if (detected !== i18n.language) void i18n.changeLanguage(detected);
    }
    // Run once on mount — subsequent language flips go through the switcher.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Already signed in (revisiting the login URL): bounce to the role's landing page.
  // Wait for `role` to resolve so a superadmin isn't briefly routed to /intake.
  useEffect(() => {
    if (!loading && session && role) navigate({ to: landingPathForRole(role) });
  }, [loading, session, role, navigate]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSending(true);
    try {
      // D-01: Identity Platform email+password sign-in (no magic-link, no SSO).
      await signInWithEmailAndPassword(auth, email, password);

      // Claims-refresh handshake (Pitfall 2): hand the just-minted ID token to
      // the backend so it can sync/issue custom claims, then force-refresh the
      // token so the NEXT request already carries role/space_id claims.
      //
      // WR-01: target the backend's absolute origin (apiUrl), not a same-origin
      // relative path that never reaches the Cloud Run backend.
      // WR-02: getToken() returns null until auth.currentUser is populated — never
      // send "Bearer null"; await a real token first.
      const token = await getToken();
      if (!token) throw new SyncError(t("login.errors.noToken"));

      const resp = await fetch(apiUrl("/auth/session"), {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      // WR-02: a non-OK handshake (401 invalid token, 403 no membership) must NOT
      // be ignored — surface it and DO NOT navigate to /admin, where the user would
      // otherwise hit a wall of 403s with no actionable error.
      if (!resp.ok) {
        throw new SyncError(t("login.errors.unauthorized"));
      }

      // Force-refresh so the next request carries the freshly-written claims.
      await getToken(true);

      // Route by the freshly-minted role claim, read straight from the refreshed
      // token so routing is deterministic and does not race the auth-context effect:
      // superadmin → /admin, everyone else → /intake (avoids the admin "no access"
      // wall a non-superadmin would otherwise hit).
      const result = auth.currentUser ? await getIdTokenResult(auth.currentUser) : null;
      const claim = result?.claims.role;
      const claimRole: Role =
        claim === "superadmin" ? "superadmin" : claim === "user" ? "user" : null;
      navigate({ to: landingPathForRole(claimRole) });
    } catch (err) {
      if (err instanceof SyncError) {
        // Handshake/authorization failure: sign-in itself succeeded, so show the
        // authorization-specific message rather than the credential hint.
        setError(err.message);
        toast.error(err.message);
      } else {
        const message = err instanceof Error ? err.message : t("login.errors.generic");
        setError(t("login.errors.credentials"));
        toast.error(t("login.errors.toast", { message }));
      }
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-paper2 px-6">
      <div className="w-full max-w-md border border-ink bg-paper p-10">
        <div className="flex items-start justify-between gap-4">
          <p className="font-mono text-xs uppercase tracking-[0.2em] text-ink/60">
            Agenic × Nestor
          </p>
          {/* D-08: pre-login switcher — persist=false writes localStorage only (no session yet). */}
          <div className="w-36 shrink-0">
            <LanguageSwitcher persist={false} />
          </div>
        </div>
        <h1 className="mt-3 font-serif text-3xl font-normal lowercase tracking-tight text-ink">
          {t("login.heading")}
        </h1>

        <form onSubmit={handleSubmit} className="mt-8 space-y-4">
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder={t("login.emailPlaceholder")}
            autoComplete="email"
            required
            autoFocus
            className="w-full border border-ink/20 bg-paper px-4 py-3 text-sm outline-none focus:border-ink"
          />
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder={t("login.passwordPlaceholder")}
            autoComplete="current-password"
            required
            className="w-full border border-ink/20 bg-paper px-4 py-3 text-sm outline-none focus:border-ink"
          />
          <button
            type="submit"
            disabled={sending}
            className="w-full bg-ink px-4 py-3 font-mono text-xs uppercase tracking-wider text-paper hover:bg-ink/80 disabled:opacity-50"
          >
            {sending ? t("login.submitting") : t("login.submit")}
          </button>
        </form>
        {error && <p className="mt-4 text-sm text-red-600">{error}</p>}
        <div className="mt-8 border-t border-ink/10 pt-6 space-y-2">
          <p className="text-xs text-ink/60">{t("login.noAccount")}</p>
        </div>
      </div>
    </div>
  );
}
