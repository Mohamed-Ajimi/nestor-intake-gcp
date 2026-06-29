import { apiFetch, type ApiResult } from "@/lib/api/client";

// frontend/src/lib/api/search.ts — semantic-search endpoints over the token-attaching
// `apiFetch` transport. Mirrors `admin.ts`: never fork the transport.
//
// NOTE: the AI/search BACKEND lands in Phase 7. The seam shape is fixed now so the
// re-point plans can wire the buttons; until Phase 7 these calls may surface a
// not-yet-available error. Do NOT build the AI backend here.

/** A single search hit (shape finalized with the Phase 7 backend). */
export type SearchHit = {
  id: string;
  score: number;
  content: string | null;
};

/** Run a semantic search query. */
export function search(query: string): Promise<ApiResult<SearchHit[]>> {
  return apiFetch<SearchHit[]>(
    `/search?q=${encodeURIComponent(query)}`,
    { method: "GET" },
  );
}

/** Trigger a re-index / refresh of the search corpus. */
export function refreshSearch(): Promise<ApiResult<void>> {
  return apiFetch<void>("/search/refresh", { method: "POST" });
}
