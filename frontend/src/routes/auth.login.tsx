import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { signInWithEmailAndPassword } from "firebase/auth";
import { toast } from "sonner";
import { auth } from "@/lib/firebase";
import { useAuth } from "@/lib/auth-context";

export const Route = createFileRoute("/auth/login")({
  component: LoginPage,
});

function LoginPage() {
  const navigate = useNavigate();
  const { session, loading, getToken } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!loading && session) navigate({ to: "/admin" });
  }, [loading, session, navigate]);

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
      const token = await getToken();
      await fetch("/auth/session", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      await getToken(true);

      navigate({ to: "/admin" });
    } catch (err) {
      const message = err instanceof Error ? err.message : "Inloggen mislukt. Probeer opnieuw.";
      setError("Inloggen mislukt. Controleer je email en wachtwoord.");
      toast.error(`Inloggen mislukt: ${message}`);
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
