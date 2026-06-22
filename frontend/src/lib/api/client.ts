import { apiUrl, auth } from "@/lib/firebase";
import { getIdToken } from "firebase/auth";

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

/** Discriminated result: success carries typed `data`, failure carries `error`. */
export type ApiResult<T> = { success: true; data: T } | { success: false; error: string };

/**
 * Fetch the current user's Firebase ID token, or `null` when signed out.
 *
 * Mirrors `auth-context.tsx`'s `getToken` against the same `auth` singleton so the
 * transport stays a plain async module (no hook), reusable from anywhere.
 */
async function currentIdToken(forceRefresh = false): Promise<string | null> {
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
      return { success: false, error: "Niet ingelogd. Log opnieuw in." };
    }

    const headers = new Headers(init?.headers);
    headers.set("Authorization", `Bearer ${token}`);
    if (!headers.has("Content-Type")) {
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
      return { success: false, error: message };
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
