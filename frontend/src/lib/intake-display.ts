// Display helpers for the intake detail page.
// Pure helpers — no React, no API calls (quick 261006-jgn).

import { pick } from "@/lib/i18n/localizeSchema";
import type { IntakeField } from "@/lib/intake-types";

/**
 * The sub-field key that marks an object-list row as a QUESTION-style row (rendered as
 * "V1. text / kind / rationale"), or `undefined` when every sub-field should render.
 *
 * Only rows with a sub-field keyed `text` (the research questions) take the question path.
 * The previous heuristic also matched any `longtext` sub-field, which pulled stakeholder rows
 * (`name`, `role`, `expectation:longtext`) onto the question path and dropped name + role.
 */
export function objectListTextKey(subFields: Pick<IntakeField, "key">[]): string | undefined {
  return subFields.some((sf) => sf.key === "text") ? "text" : undefined;
}

function resolveTrimmed(value: unknown, lang: string): string {
  return (pick(value, lang) ?? "").trim();
}

/**
 * The admin intake header: "<organisation> — <project>".
 *
 * - organisation = the `client_name` form answer (seeded with the organisation name);
 * - project = the `project_name` answer, falling back to the intake's own `client_name`
 *   (the create-screen project name);
 * - both equal (case-insensitive, trimmed) -> shown once, in the organisation's spelling;
 * - one side missing -> that side alone; neither -> `fallback`.
 *
 * Values may be plain strings or localized `{nl, fr, en}` objects — resolved via `pick`, so
 * an object never reaches JSX.
 */
export function deriveIntakeHeaderTitle(input: {
  organisation: unknown;
  project: unknown;
  intakeClientName: string | null | undefined;
  fallback: string;
  lang: string;
}): string {
  const organisation = resolveTrimmed(input.organisation, input.lang);
  const project =
    resolveTrimmed(input.project, input.lang) || (input.intakeClientName ?? "").trim();
  if (organisation && project) {
    if (organisation.toLowerCase() === project.toLowerCase()) return organisation;
    return `${organisation} — ${project}`;
  }
  return organisation || project || input.fallback;
}
