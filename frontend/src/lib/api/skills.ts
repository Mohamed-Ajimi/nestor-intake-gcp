import { apiFetch, type ApiResult } from "./client";

/**
 * Triggers for the Phase-7 AI skill routes (`backend/app/api/ai_routes.py`).
 *
 * Every dispatch endpoint is a bare POST (no body — tenant comes from the verified
 * Identity, never the request) answering 202 + `{skill_run_id, status: "running"}`.
 * Run progress is observed separately via `skillRuns.ts` / `skillRunStream.ts`
 * (Phase 8), so these functions only fire the trigger.
 */

export type SkillDispatch = { skill_run_id: string; status: string };

export function applyIntakeSkill(intakeId: string): Promise<ApiResult<SkillDispatch>> {
  return apiFetch<SkillDispatch>(`/intakes/${intakeId}/skills/apply`, { method: "POST" });
}

export function generateContextPack(intakeId: string): Promise<ApiResult<SkillDispatch>> {
  return apiFetch<SkillDispatch>(`/intakes/${intakeId}/skills/context-pack`, { method: "POST" });
}

export function structureAnswers(intakeId: string): Promise<ApiResult<SkillDispatch>> {
  return apiFetch<SkillDispatch>(`/intakes/${intakeId}/skills/structure-answers`, {
    method: "POST",
  });
}

export function extractInsights(intakeId: string): Promise<ApiResult<SkillDispatch>> {
  return apiFetch<SkillDispatch>(`/intakes/${intakeId}/skills/extract-insights`, {
    method: "POST",
  });
}

export function generateEmbeddings(intakeId: string): Promise<ApiResult<SkillDispatch>> {
  return apiFetch<SkillDispatch>(`/intakes/${intakeId}/embeddings`, { method: "POST" });
}

export function transcribeSource(
  intakeId: string,
  sourceId: string,
): Promise<ApiResult<SkillDispatch>> {
  return apiFetch<SkillDispatch>(`/intakes/${intakeId}/sources/${sourceId}/transcribe`, {
    method: "POST",
  });
}

export type SearchHit = {
  id: string;
  artifact_id: string | null;
  chunk_text: string;
  distance: number | null;
};

export function searchIntakeArtifacts(
  intakeId: string,
  query: string,
): Promise<ApiResult<{ results: SearchHit[] }>> {
  return apiFetch<{ results: SearchHit[] }>(
    `/intakes/${intakeId}/search?q=${encodeURIComponent(query)}`,
  );
}
