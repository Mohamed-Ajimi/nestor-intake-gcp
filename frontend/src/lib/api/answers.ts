import { apiFetch, type ApiResult } from "@/lib/api/client";

// frontend/src/lib/api/answers.ts — intake answer read + section-batch save over the
// token-attaching `apiFetch` transport. Mirrors `admin.ts`: never fork the transport.
//
// Save is a per-section batch (D-03): one PATCH carries every field in the active
// section as `{ answers: [{ field_key, value, value_json }] }`, matching the backend
// `AnswerBatch` upsert contract from plan 03.

/** Mirrors the backend `AnswerView`. */
export type Answer = {
  field_key: string;
  value: string | null;
  value_json: unknown | null;
};

/** A single answer item in a section batch (mirrors backend `AnswerItem`). */
export type AnswerInput = {
  field_key: string;
  value?: string | null;
  value_json?: unknown | null;
};

/** Read all stored answers for an intake. */
export function listAnswers(intakeId: string): Promise<ApiResult<Answer[]>> {
  return apiFetch<Answer[]>(`/intakes/${intakeId}/answers`, { method: "GET" });
}

/**
 * Save a section's answers as a single batch upsert (D-03). The backend upserts on
 * `(intake_id, field_key)` so re-saving the same section UPDATES in place.
 */
export function saveAnswers(
  intakeId: string,
  answers: AnswerInput[],
): Promise<ApiResult<void>> {
  return apiFetch<void>(`/intakes/${intakeId}/answers`, {
    method: "PATCH",
    body: JSON.stringify({ answers }),
  });
}
