import { createElement, type ReactElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createInstance } from "i18next";
import { I18nextProvider } from "react-i18next";
import { describe, expect, it, vi } from "vitest";
import { ResearchTrace } from "@/components/research/ResearchTrace";
import { RunFeed } from "@/components/research/RunFeed";
import { projectResearchTrace, type TraceState } from "@/lib/research/groupedTrace";
import type { RunEvent } from "@/lib/api/research";
import en from "@/locales/en/intake.json";
import nl from "@/locales/nl/intake.json";
import fr from "@/locales/fr/intake.json";

// Server-rendered markup checks exercise real components and translations without a
// browser, research calls or timers. Browser interaction/visual QA is a separate gate.
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

function task(seq: number, state: TraceState, meta: Record<string, unknown> = {}): RunEvent {
  const kinds: Record<TraceState, string> = {
    queued: "plan",
    running: "agent_run",
    retrying: "agent_retry",
    completed: "agent_done",
    restored: "agent_done",
    skipped: "agent_done",
    failed: "agent_fail",
  };
  return {
    seq,
    ts: "2026-09-09T12:00:00Z",
    stage: "deep_research",
    kind: kinds[state],
    text: `Original provider record ${seq}`,
    meta: {
      trace_execution_id: "pass-1",
      trace_task_id: `task-${seq}`,
      trace_group_id: "question-1",
      trace_question: "Which pricing model works?",
      trace_state: state,
      trace_attempt: 1,
      provider: "gemini",
      ...meta,
    },
  };
}

function dispatch(total: number): RunEvent {
  return {
    seq: 0,
    ts: "2026-09-09T12:00:00Z",
    stage: "deep_research",
    kind: "dispatch",
    text: "Dispatching research tasks",
    meta: { trace_execution_id: "pass-1", trace_total: total },
  };
}

function trace(events: RunEvent[], active = true): ReactElement {
  return createElement(ResearchTrace, {
    executions: projectResearchTrace(events),
    active,
    eventCount: events.length,
    unmatched: false,
    children: createElement("p", {}, "Original chronological records remain available"),
  });
}

describe("research trace presentation — truthful, localized and text-only", () => {
  it("a late old-pass group stays inactive even after a different stage splits the feed", async () => {
    const html = await markup(
      createElement(RunFeed, {
        events: [
          dispatch(1),
          task(1, "running"),
          task(2, "running", { trace_execution_id: "pass-2" }),
          { seq: 3, ts: "", stage: "verify", kind: "divider", text: "Verification" },
          task(4, "running"),
        ],
        isActive: true,
      }),
    );
    // Previous groups are inactive; the last group belongs to the older pass, not pass-2.
    expect(html).not.toContain("gemini · Running");
    expect(html).not.toContain("running or retrying");
    expect(html).toContain("No longer active");
  });
  it("shows grouped questions and measured task results with a complete manifest", async () => {
    const html = await markup(trace([dispatch(2), task(1, "completed"), task(2, "running")]));
    expect(html).toContain("Investigating your questions");
    expect(html).toContain("Which pricing model works?");
    expect(html).toContain("Results received: 1 / 2 tasks");
    expect(html).toContain('role="progressbar"');
    expect(html).toContain('aria-valuemax="2"');
    expect(html).toContain('aria-valuenow="1"');
    expect(html).toContain("this does not indicate claim verification or report readiness");
    expect(html).toContain("Original events · 3");
    expect(html).toContain("Original chronological records remain available");
    expect(html).toContain("<details");
    expect(html).toContain("<summary");
    expect(html).toContain("bg-paper");
    expect(html).toContain("font-serif");
    expect(html).toContain("font-mono");
    expect(html).not.toContain("aria-live=");
  });

  it("does not invent a total or progress bar when dispatch metadata is missing", async () => {
    const html = await markup(trace([task(1, "completed")]));
    expect(html).toContain("1 recorded tasks");
    expect(html).toContain("Some task details are missing");
    expect(html).not.toContain("Results received:");
    expect(html).not.toContain('role="progressbar"');
  });

  it("does not show a progress bar when some declared tasks were not recorded", async () => {
    const html = await markup(trace([dispatch(4), task(1, "completed")]));
    expect(html).toContain("Some task details are missing");
    expect(html).not.toContain('role="progressbar"');
  });

  it("labels restored, skipped and failed work distinctly and excludes skipped and failed from results", async () => {
    const html = await markup(
      trace(
        [
          dispatch(4),
          task(1, "completed"),
          task(2, "restored"),
          task(3, "skipped"),
          task(4, "failed"),
        ],
        false,
      ),
    );
    expect(html).toContain("Results received: 2 / 4 tasks");
    expect(html).toContain("Output received");
    expect(html).toContain("Restored");
    expect(html).toContain("Skipped");
    expect(html).toContain("Failed");
  });

  it("escapes question, provider and event content rather than rendering supplied markup", async () => {
    const event = task(1, "running", {
      trace_question: '<script>alert("question")</script>',
      provider: 'future-provider<img src=x onerror="alert(1)">',
    });
    event.text = '<iframe src="https://untrusted.example">activity</iframe>';
    const html = await markup(trace([dispatch(1), event]));
    expect(html).toContain("&lt;script&gt;");
    expect(html).toContain("future-provider&lt;img");
    expect(html).toContain("&lt;iframe");
    expect(html).not.toContain("<script");
    expect(html).not.toContain("<img");
    expect(html).not.toContain("<iframe");
  });

  it("removes active labels on stopped runs without presenting a missing outcome as success", async () => {
    const html = await markup(trace([dispatch(1), task(1, "running")], false));
    expect(html).toContain("No longer active");
    expect(html).not.toContain("running or retrying");
    expect(html).not.toContain("Output received");
  });

  it("keeps only the latest execution live", async () => {
    const html = await markup(
      trace([task(1, "running"), task(2, "running", { trace_execution_id: "pass-2" })]),
    );
    expect(html).toContain("Research pass 1");
    expect(html).toContain("Research pass 2");
    expect(html).toContain("Earlier research pass");
    expect(html).toContain("No longer active");
    expect(html).toContain("gemini · Running");
  });

  it.each([
    ["en", "Investigating your questions"],
    ["nl", "We onderzoeken je vragen"],
    ["fr", "Nous étudions vos questions"],
  ])(
    "renders translated trace wording in %s without exposing translation keys",
    async (language, title) => {
      const html = await markup(trace([dispatch(1), task(1, "running")]), language);
      expect(html).toContain(title);
      expect(html).not.toContain("research.runPage.trace.");
      expect(html).not.toContain("{{");
    },
  );
});

describe("RunFeed integration — original evidence stays reachable", () => {
  it("preserves raw rows, audit affordance and injected audit content under Original events", async () => {
    const onDrillDown = vi.fn();
    const events = [dispatch(1), task(1, "completed", { audit_id: "audit-1" })];
    const html = await markup(
      createElement(RunFeed, {
        events,
        isActive: false,
        onDrillDown,
        renderAfterRow: (event) =>
          event.meta?.audit_id ? createElement("aside", {}, "Injected audit content") : null,
      }),
    );
    expect(html).toContain("Investigating your questions");
    expect(html).toContain("Original events · 2");
    expect(html).toContain("Original provider record 1");
    expect(html).toContain("View audit body");
    expect(html).toContain("Injected audit content");
    expect(onDrillDown).not.toHaveBeenCalled();
  });

  it("preserves the open audit label and does not render audit actions without a callback", async () => {
    const events = [dispatch(1), task(1, "completed", { audit_id: "audit-1" })];
    const opened = await markup(
      createElement(RunFeed, {
        events,
        isActive: false,
        onDrillDown: vi.fn(),
        drilldownAuditId: "audit-1",
      }),
    );
    expect(opened).toContain("Hide audit body");
    const unavailable = await markup(createElement(RunFeed, { events, isActive: false }));
    expect(unavailable).not.toContain("View audit body");
    expect(unavailable).not.toContain("Hide audit body");
  });

  it("leaves historical and unknown events readable without fabricating a grouped trace", async () => {
    const events = [
      { ...task(1, "running"), meta: null, text: "Historical researcher started" },
      {
        ...task(2, "completed"),
        meta: null,
        kind: "future_event_kind",
        text: "Future diagnostic event",
      },
    ];
    const html = await markup(createElement(RunFeed, { events, isActive: false }));
    expect(html).toContain("Historical researcher started");
    expect(html).toContain("Future diagnostic event");
    expect(html).not.toContain("Investigating your questions");
    expect(html).not.toContain('role="progressbar"');
  });

  it("keeps uncorrelated rows alongside grouped records and explains the mismatch", async () => {
    const legacy = { ...task(2, "running"), meta: null, text: "Uncorrelated diagnostic" };
    const html = await markup(
      createElement(RunFeed, {
        events: [dispatch(1), task(1, "completed"), legacy],
        isActive: false,
      }),
    );
    expect(html).toContain("Original events · 3");
    expect(html).toContain("Uncorrelated diagnostic");
    expect(html).toContain("Some events cannot be grouped reliably");
  });

  it("keeps previous stage summaries and disables live researcher badges after research", async () => {
    const summary = {
      seq: 2,
      ts: "2026-09-09T12:00:00Z",
      stage: "deep_research",
      kind: "summary",
      text: "Research stage ended",
      meta: {},
    };
    const next = {
      seq: 3,
      ts: "2026-09-09T12:00:00Z",
      stage: "verification",
      kind: "thinking",
      text: "Verification is running",
      meta: {},
    };
    const html = await markup(
      createElement(RunFeed, {
        events: [dispatch(1), task(1, "running"), summary, next],
        isActive: true,
      }),
    );
    expect(html).toContain("No longer active");
    expect(html).toContain("Research stage ended");
    expect(html).toContain("Verification is running");
  });
});
