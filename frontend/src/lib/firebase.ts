import { initializeApp, type FirebaseApp } from "firebase/app";
import { connectAuthEmulator, getAuth, type Auth } from "firebase/auth";

// Identity Platform / Firebase Authentication client singleton.
//
// Mirrors the env-guarded shape of `supabase.ts`: the module reads only the
// PUBLIC `VITE_FIREBASE_*` values. The Firebase web `apiKey` is a public
// project identifier (NOT a secret/credential) — it does not grant data
// access. The only data path is the FastAPI backend with a verified Bearer
// ID token; no Supabase env values or DB DSN are shipped from this module.

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
