import { useEffect, type ReactNode } from "react";
import { redirect, useNavigate } from "@tanstack/react-router";
import { onAuthStateChanged, type User } from "firebase/auth";
import { auth, MOCK_AUTH } from "@/lib/firebase";
import { useAuth } from "@/lib/auth-context";

// frontend/src/lib/auth-guard.tsx — the ONE definition of the authenticated-route gate.
//
// THE BUG THIS FIXES. Five routes (/admin, /intake, /intake/$id, /intake/$id/results,
// /intake/$id/report) each carried their own copy of an `authReady()` + `throw redirect`
// `beforeLoad`. Under SSR (Nitro `node-server` on Cloud Run — see vite.config.ts and
// frontend/Dockerfile) `beforeLoad` runs ON THE SERVER, where the Firebase session lives
// in the BROWSER's IndexedDB and is structurally invisible. So `onAuthStateChanged` fired
// with `null` server-side and the guard emitted a 307 to /auth/login on EVERY hard
// navigation or refresh — measured against the live deployment with curl. The client then
// rehydrated, found a live session, and `AuthRedirector` (routes/__root.tsx:92-107) /
// LoginPage (routes/auth.login.tsx:51-53) sent it to `landingPathForRole(role)`, i.e.
// /admin — which is the reported "refreshing any page starts logging in again and
// switches to home page".
//
// THE SHAPE OF THE FIX. The guard is UX gating only — the authoritative control is the
// backend `get_current_identity` dependency — so declining to evaluate it on the server
// removes no real protection. `requireAuthBeforeLoad` therefore no-ops under SSR, and the
// client-side gate below re-establishes the genuine signed-out redirect after Firebase has
// settled, where the session can actually be seen. BOTH halves are needed: `beforeLoad` is
// not re-run on the client for the initially-matched routes after hydration, so without a
// component-side check a hard load would carry no check at all.
//
// Deliberately ONE definition, imported by all five routes — five divergent copies is
// what let this ship in the first place.

/**
 * Firebase resolves `auth.currentUser` only after the first `onAuthStateChanged` tick,
 * so await the initial auth state instead of racing a not-yet-populated `currentUser`.
 */
function authReady(): Promise<User | null> {
  if (auth.currentUser) return Promise.resolve(auth.currentUser);
  return new Promise((resolve) => {
    const unsubscribe = onAuthStateChanged(auth, (user) => {
      unsubscribe();
      resolve(user);
    });
  });
}

/**
 * `beforeLoad` body for an authenticated route.
 *
 * Returns immediately on the server: the session is browser-held, so a server-side
 * verdict is always a false negative (that WAS the bug). Retained for CLIENT-side
 * navigations, where it redirects a signed-out visitor before the target route's
 * component ever mounts.
 */
export async function requireAuthBeforeLoad(): Promise<void> {
  if (MOCK_AUTH) return; // mock mode: bypass Firebase auth check
  // SSR: Firebase persistence is browser IndexedDB — invisible here. Never decide.
  if (typeof window === "undefined") return;
  const user = await authReady();
  if (!user) {
    throw redirect({ to: "/auth/login" });
  }
}

/**
 * Client-side half of the gate: send a settled-and-signed-out visitor to /auth/login.
 *
 * Returns `{ checking }` — true while a session cannot yet be confirmed, i.e. auth is
 * still settling OR we are signed out and the redirect is in flight. Callers must render
 * nothing while `checking` is true. That matches the SSR shell, which also renders nothing
 * (`AuthProvider` starts at `loading: true`), so there is no hydration mismatch and no
 * flash of protected chrome.
 *
 * `replace` keeps the protected URL out of history so Back does not bounce between the
 * page and the login screen.
 *
 * This is the ONLY unauthenticated redirect for these routes; a ROLE-based redirect is
 * deliberately NOT done here, because LoginPage auto-navigates back whenever a session
 * exists and the pair would loop (D-LI2-02) — role denial is rendered in place instead.
 */
export function useRequireAuth(): { checking: boolean } {
  const { session, loading } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    if (loading || session) return;
    void navigate({ to: "/auth/login", replace: true });
  }, [loading, session, navigate]);

  return { checking: loading || !session };
}

/**
 * Component form of {@link useRequireAuth} for routes whose page component owns data
 * effects. Renders `children` only once a real session is observed, so the wrapped page
 * never mounts — and therefore never fires a tokenless request that would 401 — while
 * signed out. Prefer this at route boundaries; use the hook directly only where the
 * component must also render something of its own during the gate (e.g. the /admin
 * layout's in-place role-denial wall).
 */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { checking } = useRequireAuth();
  if (checking) return null;
  return <>{children}</>;
}
