import { describe, it, expect } from "vitest";
import type { IntakeSection } from "@/lib/intake-types";
import { resolveAnswerValue } from "@/lib/i18n/resolveAnswerValue";
import {
  getSimpleProposal,
  isFieldChanged,
  sectionHasChange,
  type Proposals,
} from "./ValidationDiff";

// DEF-23.2-16b — the DIFF read boundary.
//
// `apply-intake-skill` emits every string it AUTHORS as a localized `{nl, fr, en}` object
// (backend/app/ai/prompts.py, "=== JSON CONTRACT ==="), so `suggested` and `rationale` are
// objects while `current` is a verbatim quote of the client's own answer. `getSimpleProposal`
// guards with `typeof p.suggested !== "string"`, so it returned null for EVERY proposal,
// `isFieldChanged` returned false, `sectionHasChange` returned false, and the client saw
// "gereviewd" with no visible refinement anywhere on the form.
//
// The fix resolves the proposals payload at its LOAD boundary (IntakeForm.tsx), so the guards
// below — which are correct — are handed the strings they already expect. These tests exercise
// the real exports on both shapes: the raw skill output (still null, permanently pinned as the
// proof the guard really did reject it) and the resolved output (renders).
//
// ANTI-VACUITY: never assert `typeof x === "string"`. That passes on the BROKEN code too,
// because `String({})` is itself a string. Every assertion below pins exact expected text.

const NL_SUGGESTED =
  "Bepalen of we in 2026 de Belgische markt betreden of eerst Nederland verdiepen.";
const FR_SUGGESTED =
  "Déterminer si nous entrons sur le marché belge en 2026 ou approfondissons d'abord les Pays-Bas.";
const EN_SUGGESTED =
  "Decide whether to enter the Belgian market in 2026 or deepen the Dutch one first.";

const NL_CURRENT = "We willen groeien in de Benelux.";
const EN_CURRENT = "We want to grow in the Benelux.";

const NL_RATIONALE = "De oorspronkelijke formulering benoemt geen beslissing.";
const EN_RATIONALE = "The original phrasing names no decision.";

/**
 * The shape the skill actually persists into `skill_runs.output_parsed`.
 *
 * `current` is localized here as well as `suggested`: the prompt asks for a verbatim
 * plain-string quote, but the model does not always comply, and the broken render this task
 * fixes was reported on real data. A separate case below covers the plain-string `current`
 * that the contract specifies, so both are pinned.
 */
function makeRawProposals(): Proposals {
  return {
    decision_or_goal: {
      current: { nl: NL_CURRENT, fr: "Nous voulons croître au Benelux.", en: EN_CURRENT },
      suggested: { nl: NL_SUGGESTED, fr: FR_SUGGESTED, en: EN_SUGGESTED },
      rationale: {
        nl: NL_RATIONALE,
        fr: "La formulation initiale ne nomme aucune décision.",
        en: EN_RATIONALE,
      },
    },
    audience_description: {
      // Contract shape: `current` quoted verbatim as a PLAIN STRING, `suggested` localized.
      current: "Iedereen in de Benelux.",
      suggested: {
        nl: "Inkoopverantwoordelijken bij middelgrote Belgische productiebedrijven.",
        fr: "Responsables achats de PME industrielles belges.",
        en: "Procurement leads at mid-sized Belgian manufacturers.",
      },
      // Already-scalar rationale — must survive resolution byte-for-byte.
      rationale: "Te breed om onderzoekbaar te zijn.",
    },
    // Non-localized members that must survive resolution with their shape intact.
    research_questions_refined: [
      {
        original_index: 0,
        current: "Wie zijn onze concurrenten?",
        suggested: {
          nl: "Welke drie spelers wonnen sinds 2024 marktaandeel in de Belgische maakindustrie?",
          fr: "Quels trois acteurs ont gagné des parts de marché depuis 2024 ?",
          en: "Which three players gained share in Belgian manufacturing since 2024?",
        },
        type: "exploration",
        domain: "competitor",
      },
    ],
    dropped_questions: [
      {
        original: "Wat is jullie budget?",
        reason: { nl: "Niet onderzoekbaar.", en: "Not researchable." },
      },
    ],
  };
}

describe("getSimpleProposal — raw skill output (the defect, pinned)", () => {
  it("returns null for a proposal whose `suggested` is a localized object", () => {
    // RED EVIDENCE, kept permanently: this is the proof the string guard rejected the
    // object outright. If this ever starts returning a proposal, the guard changed and the
    // resolve-at-the-boundary contract this task established no longer holds.
    expect(getSimpleProposal(makeRawProposals(), "decision_or_goal")).toBeNull();
  });

  it("returns null even when only `suggested` is localized and `current` is a plain string", () => {
    expect(getSimpleProposal(makeRawProposals(), "audience_description")).toBeNull();
  });
});

describe("getSimpleProposal — resolved output (the fix)", () => {
  it("returns the exact Dutch strings for lang nl", () => {
    const resolved = resolveAnswerValue(makeRawProposals(), "nl") as Proposals;
    const p = getSimpleProposal(resolved, "decision_or_goal");

    expect(p).not.toBeNull();
    expect(p!.suggested).toBe(NL_SUGGESTED);
    expect(p!.current).toBe(NL_CURRENT);
    expect(p!.rationale).toBe(NL_RATIONALE);
  });

  it("returns the exact English strings for lang en — locale is honoured, not hardcoded", () => {
    const resolved = resolveAnswerValue(makeRawProposals(), "en") as Proposals;
    const p = getSimpleProposal(resolved, "decision_or_goal");

    expect(p).not.toBeNull();
    expect(p!.suggested).toBe(EN_SUGGESTED);
    expect(p!.current).toBe(EN_CURRENT);
    expect(p!.rationale).toBe(EN_RATIONALE);
  });

  it("resolves a full-locale-code (nl-BE) the same way pick() does — first two chars", () => {
    const resolved = resolveAnswerValue(makeRawProposals(), "nl-BE") as Proposals;
    expect(getSimpleProposal(resolved, "decision_or_goal")!.suggested).toBe(NL_SUGGESTED);
  });
});

describe("isFieldChanged — the reported symptom", () => {
  // What the client's form actually holds once the operator applied the refinement: the
  // NEW text. `current` on the proposal still holds the client's original wording.
  const appliedAnswer = NL_SUGGESTED;

  it("is false against the raw skill output — the reported defect", () => {
    expect(isFieldChanged("decision_or_goal", appliedAnswer, makeRawProposals())).toBe(false);
  });

  it("is true against the resolved output", () => {
    const resolved = resolveAnswerValue(makeRawProposals(), "nl") as Proposals;
    expect(isFieldChanged("decision_or_goal", appliedAnswer, resolved)).toBe(true);
  });

  it("stays false when the stored answer still equals the proposal's `current`", () => {
    // Nothing was applied, so there is nothing to show — the guard must not fire merely
    // because resolution succeeded.
    const resolved = resolveAnswerValue(makeRawProposals(), "nl") as Proposals;
    expect(isFieldChanged("decision_or_goal", NL_CURRENT, resolved)).toBe(false);
  });
});

describe("sectionHasChange — the gate that decides whether any card renders", () => {
  const section = {
    id: "goal",
    title: "Doel",
    fields: [
      { key: "decision_or_goal", type: "textarea", label: "Beslissing of doel" },
      { key: "notes", type: "textarea", label: "Notities" },
    ],
  } as unknown as IntakeSection;

  const answers = { decision_or_goal: NL_SUGGESTED, notes: "n.v.t." };

  it("is false against the raw skill output — no DiffCard is ever reached", () => {
    expect(sectionHasChange(section, answers, makeRawProposals())).toBe(false);
  });

  it("is true against the resolved output", () => {
    const resolved = resolveAnswerValue(makeRawProposals(), "nl") as Proposals;
    expect(sectionHasChange(section, answers, resolved)).toBe(true);
  });
});

describe("resolution leaves non-localized members of the proposals object alone", () => {
  it("keeps an already-scalar rationale byte-for-byte", () => {
    const resolved = resolveAnswerValue(makeRawProposals(), "nl") as Proposals;
    expect(resolved.audience_description.rationale).toBe("Te breed om onderzoekbaar te zijn.");
  });

  it("keeps the refined-questions array's shape, indices and verbatim quotes", () => {
    const resolved = resolveAnswerValue(makeRawProposals(), "nl") as Proposals;
    const rq = resolved.research_questions_refined;

    expect(Array.isArray(rq)).toBe(true);
    expect(rq).toHaveLength(1);
    // A number must stay a number — `original_index` indexes into the answers array.
    expect(rq[0].original_index).toBe(0);
    expect(rq[0].current).toBe("Wie zijn onze concurrenten?");
    expect(rq[0].type).toBe("exploration");
    expect(rq[0].domain).toBe("competitor");
    // ...while the localized member inside the same array element does resolve.
    expect(rq[0].suggested).toBe(
      "Welke drie spelers wonnen sinds 2024 marktaandeel in de Belgische maakindustrie?",
    );
  });

  it("keeps a nested plain-string member of dropped_questions", () => {
    const resolved = resolveAnswerValue(makeRawProposals(), "nl") as Proposals;
    expect(resolved.dropped_questions[0].original).toBe("Wat is jullie budget?");
    expect(resolved.dropped_questions[0].reason).toBe("Niet onderzoekbaar.");
  });
});
