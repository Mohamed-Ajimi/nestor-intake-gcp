import { describe, it, expect } from "vitest";
import { ERROR_CODES, resolveErrorKey } from "@/lib/i18n/error-codes";

// Phase 11 (D-11): backend machine `code` → i18n key map for translated toasts.
// An unknown or missing code resolves to undefined so the toast caller falls back
// to the raw server error string (D-11 raw fallback) — never a broken t() key.

describe("ERROR_CODES map — curated user-visible backend codes", () => {
  it("seeds the four foundation codes with common:errors.* keys", () => {
    expect(ERROR_CODES.INTAKE_NOT_FOUND).toBe("common:errors.intakeNotFound");
    expect(ERROR_CODES.INVALID_LOCALE).toBe("common:errors.invalidLocale");
    expect(ERROR_CODES.MAIL_SEND_FAILED).toBe("common:errors.mailSendFailed");
    expect(ERROR_CODES.RECIPIENT_INVALID).toBe("common:errors.recipientInvalid");
  });

  it("maps NOT_LOGGED_IN (client-side signed-out) to common:errors.notLoggedIn", () => {
    expect(ERROR_CODES.NOT_LOGGED_IN).toBe("common:errors.notLoggedIn");
  });

  it("every value is a namespaced common:errors.* key", () => {
    for (const key of Object.values(ERROR_CODES)) {
      expect(key).toMatch(/^common:errors\./);
    }
  });
});

describe("resolveErrorKey — known code → key, unknown → undefined (raw fallback)", () => {
  it("returns the i18n key for a known code", () => {
    expect(resolveErrorKey("INTAKE_NOT_FOUND")).toBe("common:errors.intakeNotFound");
  });

  it("returns undefined for an unknown code", () => {
    expect(resolveErrorKey("SOME_UNKNOWN_CODE")).toBeUndefined();
  });

  it("returns undefined when the code is undefined (no code on the failure)", () => {
    expect(resolveErrorKey(undefined)).toBeUndefined();
  });

  it("returns undefined for the empty string", () => {
    expect(resolveErrorKey("")).toBeUndefined();
  });
});
