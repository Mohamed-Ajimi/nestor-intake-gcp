/**
 * Which intake fields a CLIENT may actually WRITE, per lifecycle phase.
 *
 * Pure — no React, no network, no i18n (cf. `intake-phase.ts`).
 *
 * Why this exists
 * ---------------
 * The rule was written out twice in `IntakeForm.tsx` and the two copies disagreed.
 * The `disabled=` prop re-opened `proposal_list` fields for the validation phase
 * (260831-gk7), while `handleChange` and `saveCurrentSection` still early-returned on
 * a blanket `!editable`. So the control rendered ENABLED and its value was never sent:
 * the client ticked which AI-proposed extra research questions to include, pressed
 * Akkoord, and the selection was discarded while the status advanced (DEF-23.2-12).
 *
 * One definition, three call sites — that is the fix. A field that cannot be saved must
 * not be enabled, and a field that is enabled must be saved.
 *
 * ⛔ This MUST stay in step with the SERVER rule (D-23.2-05,
 * `backend/app/intake_write_policy.py`): in `reviewed` / `validated_by_client` the API
 * accepts ONLY `proposal_list` fields and answers 409 for anything else. Widening this
 * predicate without widening that table marks a field dirty, 409s the section PATCH, and
 * — because `doSubmit` gates on `saveCurrentSection` — leaves the client unable to submit
 * at all. That is strictly worse than the silent discard this file exists to fix.
 */

/** The one schema `type` that stays writable through the validation phase (D-23.2-05). */
export const VALIDATION_PHASE_WRITABLE_TYPE = "proposal_list";

/** Structural minimum this helper needs — keeps it testable without a full `IntakeField`. */
type WritableSection = {
  fields?: readonly { key: string; type?: string }[] | null;
};

/**
 * The set of field keys the client may write, given the sections currently rendered.
 *
 * @param sections  the sections on screen (already phase-filtered by the caller)
 * @param editable  the form is open for editing — today `status === "draft"`
 * @param isValidationPhase  the client-validation phase (`reviewed` / `validated_by_client`)
 */
export function writableFieldKeys(
  sections: readonly WritableSection[],
  { editable, isValidationPhase }: { editable: boolean; isValidationPhase: boolean },
): Set<string> {
  const keys = new Set<string>();
  for (const section of sections) {
    for (const field of section.fields ?? []) {
      if (!field?.key) continue;
      if (editable || (isValidationPhase && field.type === VALIDATION_PHASE_WRITABLE_TYPE)) {
        keys.add(field.key);
      }
    }
  }
  return keys;
}
