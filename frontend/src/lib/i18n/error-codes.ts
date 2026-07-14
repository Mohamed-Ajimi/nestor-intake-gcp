// frontend/src/lib/i18n/error-codes.ts — backend machine `code` → i18n key map (D-11).
//
// apiFetch's failure branch surfaces an optional `code` additively (client.ts); toast
// call sites resolve it here and translate. An unmapped/missing code resolves to
// undefined so the caller falls back to the RAW server error string — a toast must
// never show a broken t() key (D-11 raw fallback).
//
// Curated USER-VISIBLE codes only (label-map style, mirrors salesLabels.ts). More codes
// are appended as the backend CodedError enum lands in 11-02/11-07.

export const ERROR_CODES: Record<string, string> = {
  INTAKE_NOT_FOUND: "common:errors.intakeNotFound",
  INVALID_LOCALE: "common:errors.invalidLocale",
  MAIL_SEND_FAILED: "common:errors.mailSendFailed",
  RECIPIENT_INVALID: "common:errors.recipientInvalid",
};

/**
 * Resolve a backend error code to its i18n key, or undefined when unmapped so the
 * caller falls back to the raw server text.
 *
 * Consumer pattern: `toast.error(key ? t(key) : rawError)`.
 */
export function resolveErrorKey(code?: string): string | undefined {
  if (!code) return undefined;
  return ERROR_CODES[code];
}
