import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import i18next from "i18next";
import { I18nextProvider } from "react-i18next";
import { RunFeed } from "@/components/research/RunFeed";
import type { RunEvent } from "@/lib/api/research";
import en from "@/locales/en/intake.json";
import nl from "@/locales/nl/intake.json";
import fr from "@/locales/fr/intake.json";
import "@/styles.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-serif/400.css";

const locale = i18next.createInstance();
await locale.init({
  lng: "en",
  fallbackLng: "en",
  resources: { en: { intake: en }, nl: { intake: nl }, fr: { intake: fr } },
});
const questions = [
  "How do comparable service providers price their work?",
  "What objections do buyers raise during procurement?",
  "How does surface-area pricing affect the commercial model?",
  "Which tender rules constrain changes to the contract?",
];
const states = [
  "completed",
  "completed",
  "restored",
  "running",
  "completed",
  "completed",
  "retrying",
  "failed",
  "running",
  "completed",
  "skipped",
  "queued",
];
const kind: Record<string, string> = {
  completed: "agent_done",
  restored: "agent_done",
  running: "agent_run",
  retrying: "agent_retry",
  failed: "agent_fail",
  skipped: "agent_done",
  queued: "plan",
};
const events: RunEvent[] = [
  {
    seq: 1,
    ts: "2026-09-09T08:00:00Z",
    stage: "deep_research",
    kind: "dispatch",
    text: "Dispatching 12 agents",
    meta: { trace_execution_id: "fixture-pass-1", trace_total: 12 },
  },
];
states.forEach((state, i) =>
  events.push({
    seq: i + 2,
    ts: "2026-09-09T08:01:00Z",
    stage: "deep_research",
    kind: kind[state],
    text:
      state === "failed"
        ? "Provider request failed — fixture timeout"
        : `${questions[Math.floor(i / 3)]} — ${state}`,
    meta: {
      trace_execution_id: "fixture-pass-1",
      trace_task_id: `angle:${i + 1}`,
      trace_group_id: `group:${Math.floor(i / 3)}`,
      trace_question: questions[Math.floor(i / 3)],
      provider: ["Gemini", "OpenAI", "Claude"][i % 3],
      trace_state: state,
      trace_attempt: state === "retrying" ? 2 : 1,
      audit_id: state === "completed" ? `audit-${i}` : undefined,
    },
  }),
);

export function Fixture() {
  const [active, setActive] = useState(true);
  const [legacy, setLegacy] = useState(false);
  const [audit, setAudit] = useState<string | null>(null);
  return (
    <I18nextProvider i18n={locale}>
      <main className="mx-auto max-w-4xl px-4 py-8">
        <p className="font-mono text-xs uppercase tracking-widest">
          Nestor Pulse · offline UI fixture
        </p>
        <h1 className="my-4 font-serif text-4xl">Research trace</h1>
        <div className="mb-5 flex flex-wrap gap-4 font-sans text-sm">
          <label>
            <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />{" "}
            Run active
          </label>
          <label>
            <input type="checkbox" checked={legacy} onChange={(e) => setLegacy(e.target.checked)} />{" "}
            Legacy events
          </label>
          <label>
            Language{" "}
            <select defaultValue="en" onChange={(e) => void locale.changeLanguage(e.target.value)}>
              <option value="en">English</option>
              <option value="nl">Nederlands</option>
              <option value="fr">Français</option>
            </select>
          </label>
        </div>
        <RunFeed
          events={
            legacy
              ? events.map((event) => ({
                  ...event,
                  meta: { provider: event.meta?.provider, audit_id: event.meta?.audit_id },
                }))
              : events
          }
          isActive={active}
          drilldownAuditId={audit}
          onDrillDown={(id) => setAudit((old) => (old === id ? null : id))}
          renderAfterRow={(event) =>
            audit && event.meta?.audit_id === audit ? (
              <p className="border border-ink p-3 font-sans text-sm">
                Offline audit panel · {audit}
              </p>
            ) : null
          }
        />
      </main>
    </I18nextProvider>
  );
}
createRoot(document.getElementById("root")!).render(<Fixture />);
