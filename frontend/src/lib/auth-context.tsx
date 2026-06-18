import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import type { Session } from "@supabase/supabase-js";
import { supabase } from "@/lib/supabase";

type AuthContextValue = {
  session: Session | null;
  loading: boolean;
};

const AuthContext = createContext<AuthContextValue>({ session: null, loading: true });

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!supabase) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    let settled = false;
    const settle = (s: Session | null) => {
      if (cancelled) return;
      setSession(s);
      if (!settled) {
        settled = true;
        setLoading(false);
      }
    };

    const { data: sub } = supabase.auth.onAuthStateChange((_event, s) => {
      settle(s);
    });

    (async () => {
      try {
        const url = new URL(window.location.href);
        const code = url.searchParams.get("code");
        if (code) {
          try {
            await supabase!.auth.exchangeCodeForSession(window.location.href);
            // Clean ?code= from URL
            url.searchParams.delete("code");
            url.searchParams.delete("state");
            window.history.replaceState({}, "", url.pathname + (url.search ? url.search : "") + url.hash);
          } catch {
            // fall through to getSession
          }
        }
        const { data } = await supabase!.auth.getSession();
        settle(data.session);
      } catch {
        settle(null);
      }
    })();

    return () => {
      cancelled = true;
      sub.subscription.unsubscribe();
    };
  }, []);

  return <AuthContext.Provider value={{ session, loading }}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  return useContext(AuthContext);
}
