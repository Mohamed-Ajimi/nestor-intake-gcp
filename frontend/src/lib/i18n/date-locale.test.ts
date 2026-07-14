import { describe, it, expect } from "vitest";
import { nl, fr, enUS } from "date-fns/locale";
import { getDateLocale } from "@/lib/i18n/date-locale";

// Phase 11 (D-04): central date-fns locale resolver replacing the hardcoded
// `import { nl } from "date-fns/locale"` call sites. nl is the guaranteed fallback
// for any unknown/empty language tag.

describe("getDateLocale — lang → date-fns Locale with nl fallback (D-04)", () => {
  it('"fr" returns the date-fns fr locale', () => {
    expect(getDateLocale("fr")).toBe(fr);
  });

  it('"fr-BE" (region tag) still returns fr', () => {
    expect(getDateLocale("fr-BE")).toBe(fr);
  });

  it('"en-US" returns the date-fns enUS locale', () => {
    expect(getDateLocale("en-US")).toBe(enUS);
  });

  it('"en" returns enUS', () => {
    expect(getDateLocale("en")).toBe(enUS);
  });

  it('"nl" returns the date-fns nl locale', () => {
    expect(getDateLocale("nl")).toBe(nl);
  });

  it('unsupported language ("de") falls back to nl', () => {
    expect(getDateLocale("de")).toBe(nl);
  });

  it("empty string falls back to nl", () => {
    expect(getDateLocale("")).toBe(nl);
  });
});
