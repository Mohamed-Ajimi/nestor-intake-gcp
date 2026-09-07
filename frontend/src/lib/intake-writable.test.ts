import { describe, it, expect } from "vitest";
import { writableFieldKeys, VALIDATION_PHASE_WRITABLE_TYPE } from "@/lib/intake-writable";

// DEF-23.2-12 regression suite.
//
// The defect was NOT that the rule was wrong — the `disabled=` prop had it right. It was
// that the rule existed in three places and the save paths held an older copy, so a control
// rendered enabled and its value was silently dropped on submit. These tests pin the single
// predicate the three call sites now share.
//
// The lockout case is the one that matters most: widening this to non-`proposal_list` fields
// during the validation phase would mark them dirty, 409 the section PATCH against the
// server's D-23.2-05 table, and — because `doSubmit` gates on `saveCurrentSection` — leave
// the client unable to submit at all. That is worse than the bug being fixed.

// Mirrors the shape of the live canonical form: the validation-phase section holding the one
// `proposal_list` field, plus ordinary fields that must stay closed after review.
const SECTIONS = [
  {
    fields: [
      { key: "company_intro", type: "longtext" },
      { key: "output_size", type: "radio" },
    ],
  },
  {
    fields: [{ key: "extra_questions_proposed", type: VALIDATION_PHASE_WRITABLE_TYPE }],
  },
];

describe("writableFieldKeys", () => {
  it("opens every field while the intake is a draft", () => {
    const keys = writableFieldKeys(SECTIONS, { editable: true, isValidationPhase: false });
    expect(keys).toEqual(
      new Set(["company_intro", "output_size", "extra_questions_proposed"]),
    );
  });

  it("opens ONLY the proposal_list field during the validation phase", () => {
    const keys = writableFieldKeys(SECTIONS, { editable: false, isValidationPhase: true });
    expect(keys).toEqual(new Set(["extra_questions_proposed"]));
  });

  it("keeps reviewed answers closed during validation (the 409-lockout guard)", () => {
    const keys = writableFieldKeys(SECTIONS, { editable: false, isValidationPhase: true });
    // These are exactly the fields `ValidationDiffForField`'s revert button targets. The
    // server refuses them in this phase; marking them dirty blocks submission entirely.
    expect(keys.has("company_intro")).toBe(false);
    expect(keys.has("output_size")).toBe(false);
  });

  it("closes everything once the intake is neither draft nor in validation", () => {
    const keys = writableFieldKeys(SECTIONS, { editable: false, isValidationPhase: false });
    expect(keys.size).toBe(0);
  });

  it("opens a proposal_list field in draft even outside the validation phase", () => {
    // `editable` alone is sufficient — the type exception is additive, not a replacement.
    const keys = writableFieldKeys(SECTIONS, { editable: true, isValidationPhase: false });
    expect(keys.has("extra_questions_proposed")).toBe(true);
  });

  it("derives the exception from `type`, never from a field-key literal", () => {
    // A SECOND proposal_list field added to the canonical JSON must widen the exception
    // with no code change here — the same discipline as `app.intake_write_policy`.
    const withSecond = [
      { fields: [{ key: "some_future_proposal", type: VALIDATION_PHASE_WRITABLE_TYPE }] },
    ];
    const keys = writableFieldKeys(withSecond, { editable: false, isValidationPhase: true });
    expect(keys).toEqual(new Set(["some_future_proposal"]));
  });

  it("tolerates a malformed section rather than throwing mid-render", () => {
    const malformed = [{ fields: null }, { fields: [{ key: "", type: "text" }] }, {}];
    const keys = writableFieldKeys(malformed, { editable: true, isValidationPhase: false });
    expect(keys.size).toBe(0);
  });
});
