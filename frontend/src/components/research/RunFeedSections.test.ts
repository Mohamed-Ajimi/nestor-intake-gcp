import { createElement, type ReactElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createInstance } from "i18next";
import { I18nextProvider } from "react-i18next";
import { describe, expect, it } from "vitest";
import { EmptyFeed } from "@/components/research/EmptyFeed";
import { RunFeed } from "@/components/research/RunFeed";
import { COLLAPSED_PREVIEW_ROWS } from "@/lib/research/feedRows";
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

/** A correlated deep-research row — the only shape `projectResearchTrace` groups. */
function researchTask(seq: number, state: string, kind: string): RunEvent {
  return ev({
    seq,
    stage: "deep_research",
    kind,
    text: `Original provider record ${seq}`,
    meta: {
      trace_execution_id: "pass-1",
      trace_task_id: `task-${seq}`,
      trace_group_id: "question-1",
      trace_question: "Which pricing model works?",
      trace_state: state,
      trace_attempt: 1,
      provider: "gemini",
    },
  });
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

  it("puts the grouped trace inside its own phase's shell while other phases keep plain rows", async () => {
    const mixed: RunEvent[] = [
      ev({ seq: 1, stage: "adaptive_intake", kind: "divider", text: "Adaptive intake" }),
      ev({
        seq: 2,
        stage: "adaptive_intake",
        kind: "thinking",
        text: "Reading the intake answers",
      }),
      ev({ seq: 3, stage: "deep_research", kind: "divider", text: "Deep research" }),
      ev({
        seq: 4,
        stage: "deep_research",
        kind: "dispatch",
        text: "Dispatching research tasks",
        meta: { trace_execution_id: "pass-1", trace_total: 2 },
      }),
      researchTask(5, "completed", "agent_done"),
      researchTask(6, "running", "agent_run"),
    ];
    const html = await markup(createElement(RunFeed, { events: mixed, isActive: true }));

    // BOTH bodies, same run, one shell each.
    expect(occurrences(html, "data-trace-section")).toBe(2);
    expect(occurrences(html, "Adaptive intake")).toBe(1);
    expect(occurrences(html, "Deep research")).toBe(1);

    // The research phase gets the grouping: question cards, the results bar, and the caveat.
    expect(html).toContain("Which pricing model works?");
    expect(html).toContain("Results received: 1 / 2 tasks");
    expect(html).toContain('role="progressbar"');
    expect(html).toContain("this does not indicate claim verification or report readiness");

    // The intake phase keeps its plain row, in its own shell, ahead of the research one.
    expect(html).toContain("Reading the intake answers");
    expect(html.indexOf("Reading the intake answers")).toBeLessThan(html.indexOf("Deep research"));

    // Only the re-presented body offers the originals; the plain rows are not printed twice.
    expect(occurrences(html, "Original events")).toBe(1);
    expect(html).toContain("Original events · 3");
    expect(occurrences(html, "Reading the intake answers")).toBe(1);
  });

  it("renders a queued run with no events in the shell, and marks a started one live", async () => {
    const queued = await markup(
      createElement(EmptyFeed, { status: "queued", isTerminal: false, title: "Queued" }),
    );
    expect(occurrences(queued, "data-trace-section")).toBe(1);
    expect(queued).toContain("Queued");
    expect(queued).toContain("the engine has not started it yet");
    // A queued run is NOT live — the engine has not picked it up.
    expect(queued).not.toContain(">live<");

    const started = await markup(
      createElement(EmptyFeed, { status: "running", isTerminal: false, title: "Running" }),
    );
    expect(occurrences(started, "data-trace-section")).toBe(1);
    expect(started).toContain("Waiting for the first event");
    expect(started).toContain(">live<");
  });

  it("offers the collapse toggle only when rows are actually hidden (D-09)", async () => {
    const phase = (rows: number): RunEvent[] => [
      ev({ seq: 1, stage: "adaptive_intake", kind: "divider", text: "Adaptive intake" }),
      ...Array.from({ length: rows }, (_, i) =>
        ev({
          seq: i + 2,
          stage: "adaptive_intake",
          kind: "thinking",
          text: `Row ${i + 1} of many`,
        }),
      ),
      // A LATER group is what makes the one above it complete, and completion is what
      // auto-collapses it. Without this the phase is still live and nothing is hidden.
      ev({ seq: 100, stage: "question_workshop", kind: "divider", text: "Question workshop" }),
      ev({ seq: 101, stage: "question_workshop", kind: "plan", text: "Drafting questions" }),
    ];

    const hiding = await markup(
      createElement(RunFeed, { events: phase(COLLAPSED_PREVIEW_ROWS + 1), isActive: false }),
    );
    expect(hiding).toContain("Show more");
    // The toggle is honest: the hidden row really is absent from the markup.
    expect(hiding).not.toContain("Row 1 of many");
    expect(hiding).toContain("Row 3 of many");

    const nothingHidden = await markup(
      createElement(RunFeed, { events: phase(COLLAPSED_PREVIEW_ROWS), isActive: false }),
    );
    expect(nothingHidden).not.toContain("Show more");
    expect(nothingHidden).toContain("Row 1 of many");
    expect(nothingHidden).toContain("Row 2 of many");
  });
});
