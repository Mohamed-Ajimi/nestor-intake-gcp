import { apiUrl, auth } from "@/lib/firebase";
import { getIdToken, signOut } from "firebase/auth";

// frontend/src/lib/api/client.ts — the FIRST lib/api module and the generalizable
// token-attach transport seam that Phase 6 extends (NOT a throwaway). It reuses the
// Phase 3 Firebase auth (`getToken` from auth-context, mirrored here against the same
// `auth` singleton so the transport has no React-hook dependency) and follows the
// project's `{success, error?}` return-no-throw convention (CLAUDE.md / salesMail.ts):
// a non-2xx response is returned as `{ success: false, error }`, never thrown.
//
// SECURITY (T-5-18): this transport only ATTACHES the verified id token. It makes NO
// authorization decision and reads NO role/space_id from the browser — the backend
// gates every admin route on the verified token.

/**
 * Discriminated result: success carries typed `data`, failure carries `error`.
 *
 * The failure variant additionally carries an OPTIONAL machine `code` (Phase 11 / D-11):
 * when the backend emits `{"detail": "...", "code": "SOME_CODE"}`, toast callers resolve
 * the code via `resolveErrorKey` (lib/i18n/error-codes.ts) to a translated message and
 * fall back to the raw `error` string when unmapped. `error` itself is unchanged.
 */
export type ApiResult<T> =
  | { success: true; data: T }
  | { success: false; error: string; code?: string };

/**
 * Fetch the current user's Firebase ID token, or `null` when signed out.
 *
 * Mirrors `auth-context.tsx`'s `getToken` against the same `auth` singleton so the
 * transport stays a plain async module (no hook), reusable from anywhere.
 */
export async function currentIdToken(
  forceRefresh = false,
): Promise<string | null> {
  return auth.currentUser ? getIdToken(auth.currentUser, forceRefresh) : null;
}

/**
 * Generic token-attaching JSON transport.
 *
 * - Prefixes the backend base URL via `apiUrl` (reads `VITE_API_BASE_URL`; never hardcoded).
 * - Attaches `Authorization: Bearer <id token>` + `Content-Type: application/json`.
 * - Returns `{ success: true, data }` on 2xx, else `{ success: false, error }`.
 * - NEVER throws (CLAUDE.md convention) — network errors are caught and returned.
 *
 * Keep this transport ENDPOINT-AGNOSTIC: endpoint specifics live in `admin.ts`. This is
 * the seam Phase 6 generalizes when the existing Supabase screens are re-pointed.
 *
 * @param path backend path beginning with "/" (e.g. "/admin/users")
 */
export async function apiFetch<T>(path: string, init?: RequestInit): Promise<ApiResult<T>> {
  try {
    const token = await currentIdToken();
    if (!token) {
      // WR-02 parity: never send "Bearer null" — surface a signed-out state as an error.
      // Emit a stable machine code (D-11) so toast call sites translate via
      // resolveErrorKey(code) → common:errors.notLoggedIn; the raw `error` is the
      // English fallback shown only if a caller does not map the code.
      return {
        success: false,
        error: "Not logged in. Please log in again.",
        code: "NOT_LOGGED_IN",
      };
    }

    const headers = new Headers(init?.headers);
    headers.set("Authorization", `Bearer ${token}`);
    // Only default to JSON when the caller didn't set a type AND the body is not
    // FormData — a multipart body must let the browser author the boundary itself
    // (setting application/json here would strip it and break upload parsing).
    if (!headers.has("Content-Type") && !(init?.body instanceof FormData)) {
      headers.set("Content-Type", "application/json");
    }

    const resp = await fetch(apiUrl(path), { ...init, headers });

    // Tolerate empty bodies (204 / status-flip endpoints return no JSON).
    const raw = await resp.text();
    const body = raw ? safeJsonParse(raw) : undefined;

    if (!resp.ok) {
      const detail =
        (body && typeof body === "object" && "detail" in body
          ? (body as { detail?: unknown }).detail
          : undefined) ??
        (body && typeof body === "object" && "error" in body
          ? (body as { error?: unknown }).error
          : undefined);
      const message =
        typeof detail === "string" && detail.length > 0 ? detail : `HTTP ${resp.status}`;

      // Phase 11 (D-11) ADDITIVE code extraction: surface a top-level machine `code`
      // when the backend sends one, WITHOUT touching the string-`detail` path above —
      // the raw `error` message stays the guaranteed fallback for unmapped codes.
      const rawCode =
        body && typeof body === "object" && "code" in body
          ? (body as { code?: unknown }).code
          : undefined;
      const code = typeof rawCode === "string" && rawCode.length > 0 ? rawCode : undefined;

      // Disabled/revoked-session eject UX: the backend is still the authority (it
      // returned 401); we simply clear the dead client session and bounce to login
      // so the user isn't stranded behind a wall of 401s. The `{success,error}`
      // contract is preserved — the error is still returned to the caller below.
      if (resp.status === 401 && (message === "Account disabled" || message === "Session revoked")) {
        // Never let a signOut failure throw out of apiFetch.
        await signOut(auth).catch(() => {
          /* ignore — we redirect regardless */
        });
        // Guard against redirect loops and SSR: only navigate in the browser and
        // when we are not already on the login page. A full navigation is correct
        // here — it clears in-memory state and cannot re-enter this module.
        if (
          typeof window !== "undefined" &&
          !window.location.pathname.startsWith("/auth/login")
        ) {
          window.location.assign("/auth/login");
        }
      }

      return { success: false, error: message, code };
    }

    return { success: true, data: (body as T) ?? (undefined as T) };
  } catch (err) {
    return { success: false, error: err instanceof Error ? err.message : "Onbekende fout" };
  }
}

function safeJsonParse(raw: string): unknown {
  try {
    return JSON.parse(raw);
  } catch {
    return undefined;
  }
}
