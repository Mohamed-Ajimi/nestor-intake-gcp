import { initializeApp, type FirebaseApp } from "firebase/app";
import { connectAuthEmulator, getAuth, type Auth } from "firebase/auth";

// Identity Platform / Firebase Authentication client singleton.
//
// Mirrors the env-guarded shape of `supabase.ts`: the module reads only the
// PUBLIC `VITE_FIREBASE_*` values. The Firebase web `apiKey` is a public
// project identifier (NOT a secret/credential) — it does not grant data
// access. The only data path is the FastAPI backend with a verified Bearer
// ID token; no Supabase env values or DB DSN are shipped from this module.

/** Set VITE_MOCK_AUTH=1 to bypass Firebase and use a local mock superadmin session. */
export const MOCK_AUTH = import.meta.env.VITE_MOCK_AUTH === "1";

const apiKey = import.meta.env.VITE_FIREBASE_API_KEY as string | undefined;
const authDomain = import.meta.env.VITE_FIREBASE_AUTH_DOMAIN as string | undefined;
const projectId = import.meta.env.VITE_FIREBASE_PROJECT_ID as string | undefined;

const app: FirebaseApp = initializeApp({ apiKey, authDomain, projectId });

export const auth: Auth = getAuth(app);

// Local-dev Identity Platform emulator (D-09). Guarded so production builds
// never point at the emulator. `connectAuthEmulator` is idempotent-unsafe if
// called twice, but this module is a singleton so it runs at most once.
if (import.meta.env.VITE_FIREBASE_EMULATOR === "1") {
  connectAuthEmulator(auth, "http://localhost:9099", { disableWarnings: true });
}

// Backend API base URL (WR-01). The FastAPI backend (Cloud Run) is a SEPARATE
// origin from this frontend (Cloudflare Workers), so the login-sync handshake
// must target an absolute backend URL — a relative `/auth/session` resolves
// against the frontend origin and never reaches the backend. `VITE_API_BASE_URL`
// supplies that origin (no trailing slash, e.g. "https://api.nestor.example.com").
// When empty (local dev with a same-origin proxy/rewrite) it stays relative.
const rawApiBase = import.meta.env.VITE_API_BASE_URL as string | undefined;

/** Build a backend URL for `path` (which must start with "/"). */
export function apiUrl(path: string): string {
  const base = (rawApiBase ?? "").replace(/\/+$/, "");
  return `${base}${path}`;
}
