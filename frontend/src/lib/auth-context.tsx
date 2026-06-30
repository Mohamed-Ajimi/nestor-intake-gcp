import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { getIdToken, getIdTokenResult, onIdTokenChanged, type User } from "firebase/auth";
import { auth } from "@/lib/firebase";

// The verified `role` custom claim, minted server-side by Identity Platform and
// read here for UX gating ONLY — the backend remains the sole authority.
export type Role = "superadmin" | "user" | null;

/**
 * Post-login landing path for a role (UX routing only — the backend stays the
 * authority on every route). Superadmins land in the admin area; everyone else
 * (regular `user`, plus the not-yet-resolved / no-claim case) lands on the
 * authenticated user intake list. Routing a non-superadmin to `/admin` would hit
 * the superadmin guard's "geen toegang" wall, so users MUST go to `/intake`.
 */
export function landingPathForRole(role: Role): "/admin" | "/intake" {
  return role === "superadmin" ? "/admin" : "/intake";
}

type AuthContextValue = {
  session: User | null;
  loading: boolean;
  // Returns a fresh ID token for the current user, or null when signed out.
  // `forceRefresh` re-fetches the token so freshly-minted custom claims (role,
  // space_id) are picked up immediately — the login-sync handshake + the
  // Phase-6 token-attach seam.
  getToken: (forceRefresh?: boolean) => Promise<string | null>;
  // The `role` custom claim from the verified ID token (null when signed out or
  // before the claim resolves). UX gating only; never trusted for authorization.
  role: Role;
  // Convenience derived flag: true iff `role === "superadmin"`.
  isSuperadmin: boolean;
};

async function getToken(forceRefresh = false): Promise<string | null> {
  return auth.currentUser ? getIdToken(auth.currentUser, forceRefresh) : Promise.resolve(null);
}

const AuthContext = createContext<AuthContextValue>({
  session: null,
  loading: true,
  getToken,
  role: null,
  isSuperadmin: false,
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [role, setRole] = useState<Role>(null);

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

    // onIdTokenChanged is a superset of onAuthStateChanged (D-LI2-01): it fires on
    // sign-in/out AND on token refresh, so the `role` claim minted server-side after
    // sign-in (picked up via the login `getToken(true)` force-refresh) is observed
    // here. Identical signature/unsubscribe contract — session/loading behavior is
    // preserved. Returns its unsubscribe fn directly; use it in cleanup.
    const unsubscribe = onIdTokenChanged(auth, (user) => {
      // Settle session/loading on the first tick exactly as before — do NOT block
      // on the async claim read.
      settle(user);

      if (!user) {
        if (!cancelled) setRole(null);
        return;
      }

      // Read the verified custom claim asynchronously; populate role once resolved.
      // Respect `cancelled` — the user may have signed out mid-await.
      void getIdTokenResult(user)
        .then((res) => {
          if (cancelled) return;
          const claimRole = res.claims.role;
          setRole(claimRole === "superadmin" || claimRole === "user" ? claimRole : null);
        })
        .catch((err) => {
          if (cancelled) return;
          console.error("[auth-context] failed to read role claim", err);
          setRole(null);
        });
    });

    return () => {
      cancelled = true;
      unsubscribe();
    };
  }, []);

  return (
    <AuthContext.Provider
      value={{ session, loading, getToken, role, isSuperadmin: role === "superadmin" }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
