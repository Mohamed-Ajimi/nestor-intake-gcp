import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { getIdToken, onAuthStateChanged, type User } from "firebase/auth";
import { auth } from "@/lib/firebase";

type AuthContextValue = {
  session: User | null;
  loading: boolean;
  // Returns a fresh ID token for the current user, or null when signed out.
  // `forceRefresh` re-fetches the token so freshly-minted custom claims (role,
  // space_id) are picked up immediately — the login-sync handshake + the
  // Phase-6 token-attach seam.
  getToken: (forceRefresh?: boolean) => Promise<string | null>;
};

async function getToken(forceRefresh = false): Promise<string | null> {
  return auth.currentUser ? getIdToken(auth.currentUser, forceRefresh) : Promise.resolve(null);
}

const AuthContext = createContext<AuthContextValue>({
  session: null,
  loading: true,
  getToken,
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    let settled = false;
    const settle = (s: User | null) => {
      if (cancelled) return;
      setSession(s);
      if (!settled) {
        settled = true;
        setLoading(false);
      }
    };

    // onAuthStateChanged returns its unsubscribe fn directly; use it in cleanup.
    const unsubscribe = onAuthStateChanged(auth, (user) => {
      settle(user);
    });

    return () => {
      cancelled = true;
      unsubscribe();
    };
  }, []);

  return (
    <AuthContext.Provider value={{ session, loading, getToken }}>{children}</AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
