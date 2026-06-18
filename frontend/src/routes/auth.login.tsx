import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import { useAuth } from "@/lib/auth-context";

export const Route = createFileRoute("/auth/login")({
  component: LoginPage,
});

const ALLOWED_DOMAINS = ["agenic.be"];
const ALLOWED_EXPLICIT: string[] = [
  "wimvanhenden@gmail.com",
];

function LoginPage() {
  const navigate = useNavigate();
  const { session, loading } = useAuth();
  const [email, setEmail] = useState("");
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!loading && session) navigate({ to: "/admin" });
  }, [loading, session, navigate]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const err = params.get("error");
    if (err === "no_membership") {
      setError("Geen toegang gevonden voor dit account. Neem contact op met de admin.");
    } else if (err === "callback") {
      setError("Inloggen mislukt. Probeer opnieuw.");
    }
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!supabase) return;
    setError(null);

    const domain = email.split("@")[1]?.toLowerCase();
    const allowedByDomain = !!domain && ALLOWED_DOMAINS.includes(domain);
    const allowedByList = ALLOWED_EXPLICIT.includes(email.toLowerCase());
    if (!allowedByDomain && !allowedByList) {
      setError("Dit emailadres heeft geen toegang. Login alleen voor @agenic.be.");
      return;
    }

    setSending(true);
    const { error: err } = await supabase.auth.signInWithOtp({
      email,
      options: {
        emailRedirectTo: `${window.location.origin}/auth/callback`,
        shouldCreateUser: true,
      },
    });
    setSending(false);
    if (err) setError(`Fout bij versturen: ${err.message}`);
    else setSent(true);
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-paper2 px-6">
      <div className="w-full max-w-md border border-ink bg-paper p-10">
        <p className="font-mono text-xs uppercase tracking-[0.2em] text-ink/60">
          Agenic × Nestor
        </p>
        <h1 className="mt-3 font-serif text-3xl font-normal lowercase tracking-tight text-ink">
          Inloggen bij admin
        </h1>

        {sent ? (
          <div className="mt-8 space-y-4">
            <div className="border border-ink bg-paper2 p-4">
              <p className="font-mono text-xs uppercase tracking-wider text-ink">
                Mail verstuurd
              </p>
              <p className="mt-2 text-sm text-ink/80">
                Klik op de link in de mail om in te loggen.
              </p>
            </div>
            <p className="text-xs text-ink/60">
              Geen mail ontvangen? Check je spam of probeer opnieuw.
            </p>
            <button
              onClick={() => {
                setSent(false);
                setEmail("");
              }}
              className="font-mono text-xs uppercase tracking-wider text-ink underline-offset-2 hover:underline"
            >
              Opnieuw versturen
            </button>
          </div>
        ) : (
          <>
            <form onSubmit={handleSubmit} className="mt-8 space-y-4">
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="jouw@agenic.be"
                required
                autoFocus
                className="w-full border border-ink/20 bg-paper px-4 py-3 text-sm outline-none focus:border-ink"
              />
              <button
                type="submit"
                disabled={sending}
                className="w-full bg-ink px-4 py-3 font-mono text-xs uppercase tracking-wider text-paper hover:bg-ink/80 disabled:opacity-50"
              >
                {sending ? "Bezig..." : "Stuur inloglink"}
              </button>
            </form>
            {error && (
              <p className="mt-4 text-sm text-red-600">{error}</p>
            )}
            <div className="mt-8 border-t border-ink/10 pt-6 space-y-2">
              <p className="text-xs text-ink/60">
                Geen account? Login alleen toegestaan voor @agenic.be email-adressen.
              </p>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
