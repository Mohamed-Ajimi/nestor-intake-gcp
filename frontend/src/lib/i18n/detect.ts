// frontend/src/lib/i18n/detect.ts — hand-rolled pre-login browser-language detection (D-09).
//
// Deliberately NOT the i18next-browser-languagedetector plugin: detection must run
// client-side only and never flip the language on an SSR'd node (RESEARCH Pitfall 1).
// The `typeof window` guard mirrors active-space.tsx readPersisted().

export type SupportedLocale = "nl" | "fr" | "en";

/**
 * Detect the visitor's preferred supported locale from the browser.
 *
 * - SSR (no `window`): returns "nl" deterministically — the SSR shell never detects.
 * - Browser: `navigator.language` first two chars, lowercased → "fr" | "en" when they
 *   match, else "nl" (D-09: nl/fr/en else nl).
 */
export function detectLocale(): SupportedLocale {
  if (typeof window === "undefined") return "nl";
  const lang = navigator.language?.slice(0, 2).toLowerCase();
  return lang === "fr" || lang === "en" ? lang : "nl";
}
