import i18n from "i18next";
import { initReactI18next } from "react-i18next";

// frontend/src/lib/i18n/index.ts — the SINGLE i18next instance (RESEARCH Pattern 1).
//
// Initialized SYNCHRONOUSLY at module load with all catalogs bundled statically:
// no i18next-http-backend (async load = hydration flash risk) and no
// browser-languagedetector plugin (post-hydration language switch on an SSR'd node
// is Pitfall 1 — detection is hand-rolled in detect.ts and applied explicitly).
//
// nl is BOTH the deterministic initial language and the fallback for any missing
// key/locale (D-04/D-09). The resolved post-login changeLanguage happens in the
// client boot after /me resolves (11-06) — never in a useEffect on the SSR shell.
//
// SECURITY (T-11-01): `interpolation.escapeValue: false` is safe ONLY because React
// auto-escapes rendered strings — NEVER dangerouslySetInnerHTML a catalog value.

import nlCommon from "@/locales/nl/common.json";
import nlIntake from "@/locales/nl/intake.json";
import nlAdmin from "@/locales/nl/admin.json";
import nlAuth from "@/locales/nl/auth.json";
import frCommon from "@/locales/fr/common.json";
import frIntake from "@/locales/fr/intake.json";
import frAdmin from "@/locales/fr/admin.json";
import frAuth from "@/locales/fr/auth.json";
import enCommon from "@/locales/en/common.json";
import enIntake from "@/locales/en/intake.json";
import enAdmin from "@/locales/en/admin.json";
import enAuth from "@/locales/en/auth.json";

export const resources = {
  nl: { common: nlCommon, intake: nlIntake, admin: nlAdmin, auth: nlAuth },
  fr: { common: frCommon, intake: frIntake, admin: frAdmin, auth: frAuth },
  en: { common: enCommon, intake: enIntake, admin: enAdmin, auth: enAuth },
} as const;

void i18n.use(initReactI18next).init({
  resources,
  lng: "nl", // deterministic default — SSR shell and first paint are always nl
  fallbackLng: "nl", // nl is the guaranteed fallback for any missing key (D-05)
  ns: ["common", "intake", "admin", "auth"],
  defaultNS: "common",
  interpolation: { escapeValue: false }, // React escapes — see security note above
  returnNull: false,
});

export default i18n;
