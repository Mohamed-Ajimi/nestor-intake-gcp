import { describe, it, expect } from "vitest";
import { deriveIntakeHeaderTitle, objectListTextKey } from "@/lib/intake-display";

// Quick 261006-jgn — tester items 4 (stakeholder rows lost their name/role) and 2b
// (admin header "organisation — project").

describe("objectListTextKey", () => {
  it("returns 'text' for research-question rows (unchanged V1. path)", () => {
    expect(
      objectListTextKey([
        { key: "text", type: "longtext" },
        { key: "kind", type: "select" },
      ] as never),
    ).toBe("text");
  });

  it("returns undefined for stakeholder rows so every sub-field renders", () => {
    expect(
      objectListTextKey([
        { key: "name", type: "text" },
        { key: "role", type: "text" },
        { key: "expectation", type: "longtext" },
      ] as never),
    ).toBeUndefined();
  });

  it("returns undefined for an empty sub-field list", () => {
    expect(objectListTextKey([])).toBeUndefined();
  });
});

describe("deriveIntakeHeaderTitle", () => {
  const base = { intakeClientName: "x", fallback: "F", lang: "nl" };

  it("joins organisation and project with an em dash", () => {
    expect(
      deriveIntakeHeaderTitle({ ...base, organisation: "Acme NV", project: "Marktintrede" }),
    ).toBe("Acme NV — Marktintrede");
  });

  it("shows the project alone when the organisation is missing or blank", () => {
    expect(
      deriveIntakeHeaderTitle({ ...base, organisation: undefined, project: "Marktintrede" }),
    ).toBe("Marktintrede");
    expect(
      deriveIntakeHeaderTitle({ ...base, organisation: "   ", project: "Marktintrede" }),
    ).toBe("Marktintrede");
  });

  it("falls back to the intake's client_name when the project answer is missing", () => {
    expect(
      deriveIntakeHeaderTitle({
        ...base,
        organisation: "Acme NV",
        project: undefined,
        intakeClientName: "Project X",
      }),
    ).toBe("Acme NV — Project X");
  });

  it("collapses equal values (case-insensitive, trimmed) to the organisation's spelling", () => {
    expect(
      deriveIntakeHeaderTitle({ ...base, organisation: "nestor", project: " Nestor " }),
    ).toBe("nestor");
  });

  it("resolves a localized organisation via pick (lang, then nl)", () => {
    const organisation = { nl: "Acme NL", fr: "Acme FR", en: "Acme EN" };
    expect(
      deriveIntakeHeaderTitle({ ...base, organisation, project: "P", lang: "fr" }),
    ).toBe("Acme FR — P");
    expect(
      deriveIntakeHeaderTitle({ ...base, organisation, project: "P", lang: "de" }),
    ).toBe("Acme NL — P");
  });

  it("returns the fallback when nothing is known", () => {
    expect(
      deriveIntakeHeaderTitle({
        organisation: null,
        project: "",
        intakeClientName: null,
        fallback: "F",
        lang: "nl",
      }),
    ).toBe("F");
  });
});
