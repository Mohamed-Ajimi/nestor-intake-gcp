import { createElement, type ReactElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createInstance } from "i18next";
import { I18nextProvider } from "react-i18next";
import { describe, expect, it } from "vitest";
import { RunFeed } from "@/components/research/RunFeed";
import type { RunEvent } from "@/lib/api/research";
import en from "@/locales/en/intake.json";
import nl from "@/locales/nl/intake.json";
import fr from "@/locales/fr/intake.json";

// frontend/src/components/research/RunFeedSections.test.ts — the run page's SHELL contract.
//
// ResearchTrace.test.ts already covers the deep-research task grouping. What it cannot cover
// is the question this file exists for: does EVERY phase of a run render in the new section
// shell, from the first event, whether or not the deep-research projection found anything?
// Before this file, the shell appeared for exactly one stage of one run and only once trace
// metadata had arrived, so the first thing an operator saw on opening a run was the old feed.
//
// The structural hook is `data-trace-section` on the shell's own <section>. It is COUNTED, not
// merely searched for: "the phase title appears" is satisfied by the OLD divider row too, so
// only counting sections and asserting where the summary sits relative to the rows can tell
// the two designs apart. No DOM, no jsdom, no new dependency — server markup is enough.

async function markup(element: ReactElement, language = "en"): Promise<string> {
  const instance = createInstance();
  await instance.init({
    lng: language,
    fallbackLng: "en",
    resources: { en: { intake: en }, nl: { intake: nl }, fr: { intake: fr } },
    interpolation: { escapeValue: false },
  });
  return renderToStaticMarkup(createElement(I18nextProvider, { i18n: instance }, element));
}

const occurrences = (html: string, needle: string): number => html.split(needle).length - 1;

function ev(
  partial: Partial<RunEvent> & Pick<RunEvent, "seq" | "stage" | "kind" | "text">,
): RunEvent {
  return { ts: "2026-09-09T12:00:00Z", meta: null, ...partial };
}

/** A whole run that never reaches deep research: two phases, each divider + row + summary. */
const plainPhases: RunEvent[] = [
  ev({ seq: 1, stage: "adaptive_intake", kind: "divider", text: "Adaptive intake" }),
  ev({ seq: 2, stage: "adaptive_intake", kind: "thinking", text: "Reading the intake answers" }),
  ev({
    seq: 3,
    stage: "adaptive_intake",
    kind: "summary",
    text: "",
    meta: { worked: "12s", actions: 3 },
  }),
  ev({ seq: 4, stage: "question_workshop", kind: "divider", text: "Question workshop" }),
  ev({ seq: 5, stage: "question_workshop", kind: "plan", text: "Drafting research questions" }),
  ev({
    seq: 6,
    stage: "question_workshop",
    kind: "summary",
    text: "",
    meta: { worked: "34s", actions: 5 },
  }),
];

describe("run feed sections — every phase renders in the new shell", () => {
  it("gives a non-research run one section per phase, the title once, the summary in the header", async () => {
    const html = await markup(createElement(RunFeed, { events: plainPhases, isActive: false }));

    // One shell per phase — under the old design this count was zero for this run.
    expect(occurrences(html, "data-trace-section")).toBe(2);

    // The phase label is the section TITLE and is not also emitted as a divider row.
    expect(occurrences(html, "Adaptive intake")).toBe(1);
    expect(occurrences(html, "Question workshop")).toBe(1);

    // The summary is the header subline: the same words, but ABOVE its phase's rows.
    expect(html).toContain("Worked for 12s");
    expect(html).toContain("3 actions");
    expect(html).toContain("Worked for 34s");
    expect(html.indexOf("Worked for 12s")).toBeLessThan(html.indexOf("Reading the intake answers"));
    expect(html.indexOf("Worked for 34s")).toBeLessThan(html.indexOf("Drafting research questions"));

    // Rows themselves are untouched, and nothing fabricates deep-research grouping.
    expect(html).toContain("Reading the intake answers");
    expect(html).toContain("Drafting research questions");
    expect(html).not.toContain('role="progressbar"');
  });
});
