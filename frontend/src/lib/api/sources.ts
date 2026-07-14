import { apiFetch, type ApiResult } from "@/lib/api/client";

// frontend/src/lib/api/sources.ts — read-only intake-sources projection over the
// token-attaching `apiFetch` transport. Mirrors `contextPack.ts`: never fork the transport.
//
// Consumes the 12-03 backend read surface `GET /intakes/{intake_id}/sources`, which returns
// `{ sources: [...] }` and existence-hides a cross-tenant/missing intake as `{ sources: [] }`
// (server-side `_scope`, never a distinguishable 403 — T-12-07). The seam sends only
// `intakeId` in the path and renders whatever the scoped endpoint returns — it adds no
// authorization decision (T-12-09). It feeds the transcribe CTA real `source.id` values;
// the transcribe dispatch itself already lives in `skills.transcribeSource`.

/** Mirrors the backend `IntakeSourceView` projection (no space/storage identifiers). */
export type IntakeSourceView = {
  id: string;
  kind: string | null;
  file_name: string | null;
  language: string | null;
  created_at: string | null;
};

/** Mirrors the backend sources read shape (`{ sources: [...] }`). */
export type IntakeSourcesRead = {
  sources: IntakeSourceView[];
};

/** Read an intake's source uploads, space-scoped server-side (existence-hidden). */
export function getIntakeSources(
  intakeId: string,
): Promise<ApiResult<IntakeSourcesRead>> {
  return apiFetch<IntakeSourcesRead>(`/intakes/${intakeId}/sources`, {
    method: "GET",
  });
}
