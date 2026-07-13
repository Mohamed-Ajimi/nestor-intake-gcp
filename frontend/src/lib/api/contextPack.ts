import { apiFetch, type ApiResult } from "@/lib/api/client";

// frontend/src/lib/api/contextPack.ts — read-only context-pack projection over the
// token-attaching `apiFetch` transport. Mirrors `skillRuns.ts`: never fork the transport.
//
// Consumes the 07-09 backend read surface `GET /intakes/{intake_id}/context-pack`, which
// returns `{ latest, history }` and existence-hides a cross-tenant/missing intake as
// `{ latest: null, history: [] }` (server-side `_scope`, never a distinguishable 403).
// The seam sends only `intakeId` in the path and renders whatever the scoped endpoint
// returns — it adds no authorization decision (T-7-10-01).

/** Mirrors the backend `ContextPackView` projection (no space/storage identifiers). */
export type ContextPackView = {
  id: string;
  text_content: string | null;
  created_at: string | null;
  notes: string | null;
};

/** Mirrors the backend context-pack read shape (`{ latest, history }`). */
export type ContextPackRead = {
  latest: ContextPackView | null;
  history: ContextPackView[];
};

/** Read an intake's generated context pack (latest + history), space-scoped server-side. */
export function getContextPack(intakeId: string): Promise<ApiResult<ContextPackRead>> {
  return apiFetch<ContextPackRead>(`/intakes/${intakeId}/context-pack`, {
    method: "GET",
  });
}
