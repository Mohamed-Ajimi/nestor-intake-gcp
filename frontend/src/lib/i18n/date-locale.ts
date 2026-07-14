import type { Locale } from "date-fns";
import { nl, fr, enUS } from "date-fns/locale";

// frontend/src/lib/i18n/date-locale.ts — the ONE date-fns locale resolver (D-04).
// Replaces the hardcoded `import { nl } from "date-fns/locale"` at every in-scope
// call site: components pass the active i18n language and get the matching date-fns
// Locale back, with nl as the guaranteed fallback for anything unrecognized.
//
// Pure helper — no React, no i18next dependency (mirrors utils.ts cn()).

/** Resolve an i18n language tag ("nl" | "fr" | "en" | "fr-BE" | ...) to a date-fns Locale. */
export function getDateLocale(lang: string): Locale {
  if (lang.startsWith("fr")) return fr;
  if (lang.startsWith("en")) return enUS;
  return nl; // nl fallback (D-04)
}
