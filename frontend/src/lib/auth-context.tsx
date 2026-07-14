import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { getIdToken, getIdTokenResult, onIdTokenChanged, type User } from "firebase/auth";
import { auth } from "@/lib/firebase";
import i18n from "@/lib/i18n";
import { detectLocale, type SupportedLocale } from "@/lib/i18n/detect";
import { getMe, patchLocale } from "@/lib/api/me";
import { LOCALE_STORAGE_KEY } from "@/components/LanguageSwitcher";

/**
 * Read (and consume) a pending pre-login language choice from localStorage.
 * The pre-login switcher (auth.login.tsx, persist=false) writes this key; the
 * post-login boot below reads it, persists it via patchLocale, and clears it so it
 * is applied exactly once. SSR-guarded — never touches storage on the server.
 */
function readPendingPreLoginLocale(): SupportedLocale | null {
  if (typeof window === "undefined") return null;
  try {
    const v = window.localStorage.getItem(LOCALE_STORAGE_KEY);
    return v === "nl" || v === "fr" || v === "en" ? v : null;
  } catch {
    return null;
  }
}

function clearPendingPreLoginLocale() {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(LOCALE_STORAGE_KEY);
  } catch {
    /* ignore — best-effort cleanup */
  }
}

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
  // Guards the boot-locale reconciliation to exactly once per authenticated session:
  // holds the uid we already reconciled for (reset to null on sign-out).
  const bootedLocaleUidRef = useRef<string | null>(null);

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
        // Allow the boot-locale reconciliation to run again for the next sign-in.
        bootedLocaleUidRef.current = null;
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

  // Boot-locale reconciliation (Pitfall 1 / Pitfall 2, D-09): once the Firebase
  // session and role claim have settled, resolve the UI language ONCE per
  // authenticated session and apply it via i18n.changeLanguage. This is a client-only,
  // post-auth-settle effect — it never runs on the SSR shell (the SSR shell renders nl
  // deterministically, and `session` is null there), so the resolved changeLanguage
  // never lands on an SSR'd node.
  //
  // Resolution order (first hit wins):
  //   pending pre-login localStorage choice → /me locale → /me space_default_locale
  //   → detectLocale() → "nl".
  // A pending pre-login choice is ALSO persisted to the profile via patchLocale and
  // then cleared, so the pre-login FR/EN escape survives the first login.
  //
  // getMe/patchLocale are return-no-throw (ApiResult): on failure we fall back to the
  // detected/nl language. Locale is NEVER read from a Firebase claim (RESEARCH Runtime
  // State — it lives in Cloud SQL, not the token).
  useEffect(() => {
    // Wait for the settle + role to resolve; only reconcile for a signed-in user.
    if (loading || !session || !role) return;
    const uid = session.uid;
    // Once-per-session guard: skip if we already reconciled for this uid.
    if (bootedLocaleUidRef.current === uid) return;
    bootedLocaleUidRef.current = uid;

    let cancelled = false;
    void (async () => {
      const pending = readPendingPreLoginLocale();

      let meLocale: SupportedLocale | null = null;
      let spaceDefault: SupportedLocale | null = null;
      const me = await getMe();
      if (me.success) {
        meLocale = me.data.locale;
        spaceDefault = me.data.space_default_locale;
      }
      if (cancelled) return;

      const resolved: SupportedLocale =
        pending ?? meLocale ?? spaceDefault ?? detectLocale() ?? "nl";

      if (i18n.language !== resolved) void i18n.changeLanguage(resolved);

      // Persist a pending pre-login choice to the profile, then clear it so it is
      // applied exactly once. Best-effort (return-no-throw) — ignore the outcome.
      if (pending) {
        void patchLocale(pending);
        clearPendingPreLoginLocale();
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [loading, session, role]);

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
