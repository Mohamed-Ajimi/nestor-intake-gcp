import { describe, it, expect } from "vitest";
import { resolveAnswerValue } from "@/lib/i18n/resolveAnswerValue";

// DEF-23.2-16. The intake skill persists every string it authors as a localized
// `{nl, fr, en}` object, and the AI review panel writes that RAW OBJECT into
// `answers.value_json`. Each read boundary handed it straight to the renderers, so a
// `<textarea>` showed `[object Object]` and read-only views showed the same via
// `String(value)`. `resolveAnswerValue` resolves on READ, which repairs already-broken
// intakes with no data migration.
//
// Two halves to these cases, and the SECOND half is the one that constrains the design:
//  1. REGRESSION — a localized object must become the exact expected text.
//  2. MUST-NOT-BREAK — every other canonical answer shape must reach the renderers
//     structurally unchanged, BY REFERENCE where no descendant changed. Those are
//     asserted with `toBe` (identity) on purpose: a helper that rebuilt every object
//     would still satisfy `toEqual` while breaking the admin page's initial-vs-draft
//     dirty-field diff (every answer would read as edited).
//
// Vacuity note: no case here asserts merely `typeof result === "string"`. `String({})`
// is a string, so that assertion passes on the BROKEN code. Every regression case pins
// exact text and the headline case additionally pins NOT `"[object Object]"`.

describe("resolveAnswerValue — regression (DEF-23.2-16)", () => {
  const localized = { nl: "Doel NL", fr: "But FR", en: "Goal EN" };

  it("resolves a localized answer object to the nl variant", () => {
    expect(resolveAnswerValue(localized, "nl")).toBe("Doel NL");
  });

  it("resolves a localized answer object to the fr variant", () => {
    expect(resolveAnswerValue(localized, "fr")).toBe("But FR");
  });

  it("resolves a localized answer object to the en variant", () => {
    expect(resolveAnswerValue(localized, "en")).toBe("Goal EN");
  });

  it("never yields the stringified-object rendering that was the reported defect", () => {
    // The literal symptom: `value={value ?? ""}` on a `<textarea>` produced this.
    expect(resolveAnswerValue(localized, "nl")).not.toBe("[object Object]");
    expect(resolveAnswerValue(localized, "fr")).not.toBe("[object Object]");
    expect(resolveAnswerValue(localized, "en")).not.toBe("[object Object]");
  });

  it("falls back to nl when the requested variant is missing (D-05)", () => {
    expect(resolveAnswerValue({ nl: "Alleen NL" }, "fr")).toBe("Alleen NL");
  });

  it("resolves a full locale tag, not just a bare two-letter code", () => {
    expect(resolveAnswerValue(localized, "fr-BE")).toBe("But FR");
  });
});

describe("resolveAnswerValue — must-not-break canonical answer shapes", () => {
  it("returns a plain string list by reference (questions/stakeholders_list/competitors_list)", () => {
    const value = ["a", "b"];
    expect(resolveAnswerValue(value, "nl")).toBe(value);
  });

  it("returns a proposal_list with plain string text by reference", () => {
    const value = [{ text: "Q1", kind: "gap" }];
    expect(resolveAnswerValue(value, "nl")).toBe(value);
  });

  it("resolves proposal_list localized text while preserving the row shape", () => {
    const value = [{ text: { nl: "V1", fr: "Q1" }, kind: "gap" }];
    const out = resolveAnswerValue(value, "nl") as Array<Record<string, unknown>>;
    expect(Object.keys(out[0]).sort()).toEqual(["kind", "text"]);
    expect(out[0].text).toBe("V1");
    expect(out[0].kind).toBe("gap");
  });

  it("returns a materials_files descriptor by reference", () => {
    const value = [{ path: "gs://x", name: "a.pdf", size: 12 }];
    expect(resolveAnswerValue(value, "nl")).toBe(value);
  });

  it("returns a radio-with-other answer by reference", () => {
    // `pick()` returns undefined for this shape, so it must survive untouched —
    // otherwise the free-text half of a radio answer would be promoted to the answer.
    const value = { choice: "other", text: "vrije tekst" };
    expect(resolveAnswerValue(value, "nl")).toBe(value);
  });

  it("returns a stakeholder row by reference and does NOT resolve it to a name", () => {
    // Exactly the case `pick()`'s docstring warns about: scanning every value would
    // make this object resolve to "Jan" and look like a successful resolution.
    const value = { name: "Jan", role: "CTO", email: "j@x.be" };
    const out = resolveAnswerValue(value, "nl");
    expect(out).toBe(value);
    expect(out).not.toBe("Jan");
  });

  it("returns an empty object by reference (FieldDisplay's isEmpty relies on it)", () => {
    const value = {};
    expect(resolveAnswerValue(value, "nl")).toBe(value);
  });

  it("passes a plain string through unchanged (pre-260831 intakes hold these)", () => {
    const value = "oud antwoord";
    expect(resolveAnswerValue(value, "nl")).toBe(value);
  });

  it("passes null and undefined through unchanged", () => {
    expect(resolveAnswerValue(null, "nl")).toBe(null);
    expect(resolveAnswerValue(undefined, "nl")).toBe(undefined);
  });

  it("passes numbers and booleans through unchanged", () => {
    expect(resolveAnswerValue(42, "nl")).toBe(42);
    expect(resolveAnswerValue(true, "nl")).toBe(true);
  });
});

describe("resolveAnswerValue — nesting and reference discipline", () => {
  it("resolves a nested localized value and returns a NEW container reference", () => {
    const value = { a: { b: { nl: "diep", en: "deep" } }, c: "x" };
    const out = resolveAnswerValue(value, "en");
    expect(out).toEqual({ a: { b: "deep" }, c: "x" });
    // A descendant changed, so the container must be rebuilt rather than mutated.
    expect(out).not.toBe(value);
    expect(value.a.b).toEqual({ nl: "diep", en: "deep" });
  });

  it("does not mutate its input", () => {
    const value = { a: { nl: "een", en: "one" } };
    resolveAnswerValue(value, "en");
    expect(value.a).toEqual({ nl: "een", en: "one" });
  });

  it("returns a deeply unchanged nested container by reference", () => {
    const value = { outer: { inner: ["a", "b"] } };
    expect(resolveAnswerValue(value, "nl")).toBe(value);
  });
});
