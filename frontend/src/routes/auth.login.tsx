import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { getIdTokenResult, signInWithEmailAndPassword } from "firebase/auth";
import { toast } from "sonner";
import { apiUrl, auth } from "@/lib/firebase";
import { landingPathForRole, useAuth, type Role } from "@/lib/auth-context";

// WR-02: a failed login-sync handshake throws this so the catch can surface an
// authorization-specific message and NOT navigate to /admin (vs. a sign-in error).
class SyncError extends Error {}

export const Route = createFileRoute("/auth/login")({
  component: LoginPage,
});

function LoginPage() {
  const navigate = useNavigate();
  const { session, loading, role, getToken } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
      if (!token) throw new SyncError("Geen ID-token na inloggen. Probeer opnieuw.");

      const resp = await fetch(apiUrl("/auth/session"), {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      // WR-02: a non-OK handshake (401 invalid token, 403 no membership) must NOT
      // be ignored — surface it and DO NOT navigate to /admin, where the user would
      // otherwise hit a wall of 403s with no actionable error.
      if (!resp.ok) {
        throw new SyncError("Account is niet gemachtigd voor toegang.");
      }

      // Force-refresh so the next request carries the freshly-written claims.
      await getToken(true);

      // Route by the freshly-minted role claim, read straight from the refreshed
      // token so routing is deterministic and does not race the auth-context effect:
      // superadmin → /admin, everyone else → /intake (avoids the admin "geen toegang"
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
        const message = err instanceof Error ? err.message : "Inloggen mislukt. Probeer opnieuw.";
        setError("Inloggen mislukt. Controleer je email en wachtwoord.");
        toast.error(`Inloggen mislukt: ${message}`);
      }
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-paper2 px-6">
      <div className="w-full max-w-md border border-ink bg-paper p-10">
        <p className="font-mono text-xs uppercase tracking-[0.2em] text-ink/60">Agenic × Nestor</p>
        <h1 className="mt-3 font-serif text-3xl font-normal lowercase tracking-tight text-ink">
          Inloggen bij admin
        </h1>

        <form onSubmit={handleSubmit} className="mt-8 space-y-4">
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="email"
            autoComplete="email"
            required
            autoFocus
            className="w-full border border-ink/20 bg-paper px-4 py-3 text-sm outline-none focus:border-ink"
          />
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="wachtwoord"
            autoComplete="current-password"
            required
            className="w-full border border-ink/20 bg-paper px-4 py-3 text-sm outline-none focus:border-ink"
          />
          <button
            type="submit"
            disabled={sending}
            className="w-full bg-ink px-4 py-3 font-mono text-xs uppercase tracking-wider text-paper hover:bg-ink/80 disabled:opacity-50"
          >
            {sending ? "Bezig..." : "Inloggen"}
          </button>
        </form>
        {error && <p className="mt-4 text-sm text-red-600">{error}</p>}
        <div className="mt-8 border-t border-ink/10 pt-6 space-y-2">
          <p className="text-xs text-ink/60">
            Geen account? Toegang wordt door de beheerder aangemaakt.
          </p>
        </div>
      </div>
    </div>
  );
}
