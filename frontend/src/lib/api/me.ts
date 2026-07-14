import { apiFetch, type ApiResult } from "@/lib/api/client";

// frontend/src/lib/api/me.ts — the /me boot + locale-persistence seam (Phase 11).
// One thin function per backend route over apiFetch, returning the ApiResult union,
// never throwing, never forking the transport (mirrors admin.ts).
//
// SECURITY (T-5-18 convention): `locale` is DISPLAY-ONLY UX state — never an
// authorization input. The backend re-derives the user from the verified token;
// a client-supplied locale can only change display, never widen access.

export type SupportedLocale = "nl" | "fr" | "en";

/** Mirror of the backend Me response model (me_routes.py, 11-02). */
export type Me = {
  /** Per-user locale override; null means "inherit the space default" (D-07). */
  locale: SupportedLocale | null;
  /** The space's default locale, resolved server-side from the org. */
  space_default_locale: SupportedLocale;
};

/** Read the current user's locale preferences (client boot / post-login reconcile). */
export function getMe(): Promise<ApiResult<Me>> {
  return apiFetch<Me>("/me", { method: "GET" });
}

/** Persist the user's locale override (best-effort auto-persist on switch, D-10). */
export function patchLocale(locale: SupportedLocale): Promise<ApiResult<Me>> {
  return apiFetch<Me>("/me/locale", {
    method: "PATCH",
    body: JSON.stringify({ locale }),
  });
}
