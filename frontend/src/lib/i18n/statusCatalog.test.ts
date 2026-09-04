import { describe, expect, it } from "vitest";

import enAdmin from "@/locales/en/admin.json";
import enCommon from "@/locales/en/common.json";
import frAdmin from "@/locales/fr/admin.json";
import frCommon from "@/locales/fr/common.json";
import nlAdmin from "@/locales/nl/admin.json";
import nlCommon from "@/locales/nl/common.json";

// frontend/src/lib/i18n/statusCatalog.test.ts — the licence for the phase 23.1 StatusPill
// dedupe (plan 23.1-08, T-23.1-32).
//
// THIS IS NOT A RENDER TEST, AND THE COMPONENT IS NOT RENDER-TESTED ANYWHERE.
// `vitest.config.ts` collects only `src/**/*.test.ts` in a `node` environment — no `.tsx`
// and no DOM — so this repo has no component-render harness at all. Do not read a green
// run here as "the pill was rendered and checked".
//
// What it DOES prove: the two status catalogues are interchangeable. There used to be two
// StatusPill implementations — the shared `components/intake/_status.tsx` reading
// `common:status.<value>`, and a duplicate inside `routes/admin.pulse.intakes.$id.tsx`
// reading `admin:intakeDetail.status.<value>`. Collapsing onto the shared one changes the
// catalogue the label is looked up in, so it would silently change user-visible copy in any
// locale where the two disagreed. These assertions pin that they do not disagree — in any
// of the three locales, for any of the eight statuses.
//
// If this file ever goes red, the dedupe has started changing what users read. Fix the
// catalogues, do not relax the assertion.
//
// NOTE: `admin.intakeDetail.status.*` is still LIVE and must not be deleted —
// `admin.pulse.intakes.$id.tsx` reads it for the status dropdown via an interpolated
// `t()` call, which `scripts/i18n-audit.mjs` is structurally blind to.

/** The eight intake status domain keys, as enumerated by STATUS_VALUES in the detail route. */
const INTAKE_STATUSES = [
  "draft",
  "submitted",
  "reviewed",
  "validated_by_client",
  "decomposed",
  "in_research",
  "delivered",
  "archived",
] as const;

const CATALOGUES: ReadonlyArray<{
  locale: string;
  common: Record<string, string>;
  admin: Record<string, string>;
}> = [
  { locale: "en", common: enCommon.status, admin: enAdmin.intakeDetail.status },
  { locale: "nl", common: nlCommon.status, admin: nlAdmin.intakeDetail.status },
  { locale: "fr", common: frCommon.status, admin: frAdmin.intakeDetail.status },
];

describe("status catalogue parity (licences the StatusPill dedupe)", () => {
  it("covers all three shipped locales", () => {
    expect(CATALOGUES.map((c) => c.locale)).toEqual(["en", "nl", "fr"]);
  });

  for (const { locale, common, admin } of CATALOGUES) {
    describe(locale, () => {
      it("holds exactly the eight intake statuses in BOTH catalogues", () => {
        const expected = [...INTAKE_STATUSES].sort();
        expect(Object.keys(common).sort()).toEqual(expected);
        expect(Object.keys(admin).sort()).toEqual(expected);
      });

      it("has the same key set in common:status and admin:intakeDetail.status", () => {
        expect(Object.keys(common).sort()).toEqual(Object.keys(admin).sort());
      });

      it("has BYTE-IDENTICAL values for every status in both catalogues", () => {
        for (const status of INTAKE_STATUSES) {
          expect(
            common[status],
            `common:status.${status} must equal admin:intakeDetail.status.${status} in ${locale}`,
          ).toBe(admin[status]);
        }
      });

      it("has a non-empty label for every status (an empty pill is invisible)", () => {
        for (const status of INTAKE_STATUSES) {
          expect(common[status]?.trim()).toBeTruthy();
          expect(admin[status]?.trim()).toBeTruthy();
        }
      });
    });
  }

  // The pill uppercases its label. Guard the transform the two implementations shared, so a
  // locale whose casing rules surprise us cannot silently blank the badge.
  it("every label survives the pill's .toUpperCase() as non-empty text", () => {
    for (const { locale, common } of CATALOGUES) {
      for (const status of INTAKE_STATUSES) {
        expect(common[status].toUpperCase().trim(), `${locale}/${status}`).not.toBe("");
      }
    }
  });
});
