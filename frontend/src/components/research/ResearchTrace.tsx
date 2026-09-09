import React from "react";
import { useTranslation } from "react-i18next";
import { Check, ChevronDown, Circle, Clock3, RotateCw, X, Minus } from "lucide-react";
import { displayTaskState, type TraceExecution, type TraceTask } from "@/lib/research/groupedTrace";

type DisplayState = ReturnType<typeof displayTaskState>;
const label = (key: string) => `research.runPage.trace.${key}`;

// The brand's live colour. Repeated rather than imported from RunFeed because RunFeed imports
// THIS module — a shared constant would have to move to a third file to avoid the cycle, and
// the run page already carries the literal in two places for the same reason.
const FLUO_PINK = "#FF2D87";

/**
 * THE SHELL — one phase of a run, whatever that phase is.
 *
 * This used to be welded to the deep-research task grouping, so the design appeared for
 * exactly one stage of one run and only once trace metadata had arrived; opening a run showed
 * the old feed and the new design turned up mid-run, once, for one section. The shell knows
 * nothing about executions, tasks or providers now: it takes a title, an optional subline, a
 * body and an optional raw-events footer, which is all it ever actually needed.
 *
 * `title` is the phase label the ENGINE emitted (the divider row's text). No stage vocabulary
 * lives here or in RunFeed — an engine that adds a phase still costs this component nothing.
 *
 * `data-trace-section` is the structural hook the suite counts. "The phase title appears" is
 * satisfied by the old divider row too, so a text assertion cannot tell the two designs apart;
 * counting shells can. It is an attribute rather than a class so no styling can depend on it.
 */
export const TraceSection = React.memo(function TraceSection({
  title,
  subline,
  active,
  eventCount,
  unmatched,
  raw,
  children,
}: {
  title: string;
  subline?: React.ReactNode;
  active: boolean;
  eventCount: number;
  unmatched?: boolean;
  raw?: React.ReactNode;
  children?: React.ReactNode;
}) {
  const { t } = useTranslation("intake");
  return (
    <section
      data-trace-section=""
      className="my-4 min-w-0 border border-ink/20 bg-paper text-ink [color-scheme:only_light]"
    >
      <header className="border-b border-ink/15 px-4 py-4 sm:px-5">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h3 className="min-w-0 break-words font-serif text-xl leading-tight sm:text-2xl">
            {title}
          </h3>
          {/* The phase the engine is working in RIGHT NOW. Driven by the same value the rows'
              spinners are, so the two can never disagree, and it is a plain badge — the page's
              one live region is the status card, and a second one would announce twice. */}
          {active && (
            <span
              className="shrink-0 border px-1.5 py-px font-mono text-[10px] uppercase tracking-[0.08em] motion-safe:animate-pulse"
              style={{ color: FLUO_PINK, borderColor: FLUO_PINK }}
            >
              {t("research.runPage.feed.liveBadge")}
            </span>
          )}
        </div>
        {subline && (
          <p className="mt-2 flex max-w-2xl flex-wrap gap-x-4 gap-y-1 font-sans text-xs leading-relaxed text-ink/60">
            {subline}
          </p>
        )}
      </header>
      {children}
      {/* The original chronological record, only where there IS a second rendering of it to
          fall back to. A plain-row phase already IS its raw rows, so it gets no footer that
          would print every line of it twice. */}
      {raw !== undefined && (
        <details className="border-t border-ink/20">
          <summary className="cursor-pointer px-4 py-3 font-mono text-[11px] focus-visible:outline-2 focus-visible:outline-ink sm:px-5">
            {t(label("raw"), { count: eventCount })}
          </summary>
          <div className="border-t border-ink/10 px-4 pb-4 sm:px-5">
            <p className="my-3 font-sans text-xs text-ink/60">{t(label("rawHint"))}</p>
            {raw}
          </div>
        </details>
      )}
      {unmatched && (
        <p className="border-t border-ink/10 px-4 py-2 font-sans text-xs text-ink/60 sm:px-5">
          {t(label("unmatched"))}
        </p>
      )}
    </section>
  );
});

/**
 * THE DEEP-RESEARCH BODY — question groups, provider task badges and the results bar.
 *
 * An ENHANCEMENT that fills a phase's shell when `projectResearchTrace` found executions, no
 * longer the switch that decides whether the design renders at all. Presentation only: the
 * original rows (and their audit panels) are supplied by RunFeed as the shell's `raw`.
 *
 * The scope caveat lives HERE, not in the shell's subline, because it is a statement about
 * these bands specifically — researcher activity is not claim verification — and it must
 * travel with them wherever they are rendered.
 */
export const ResearchTraceBody = React.memo(function ResearchTraceBody({
  executions,
  active,
  activeExecutionId,
  executionIds,
}: {
  executions: TraceExecution[];
  active: boolean;
  activeExecutionId?: string | null;
  executionIds?: string[];
}) {
  const { t } = useTranslation("intake");
  return (
    <>
      <p className="border-b border-ink/15 px-4 py-3 font-sans text-xs leading-relaxed text-ink/60 sm:px-5">
        {t(label("scope"))}
      </p>
      {executions.map((execution, index) => {
        const current = active && execution.id === (activeExecutionId ?? executions.at(-1)?.id);
        const count = (state: string) =>
          execution.tasks.filter((task) => task.state === state).length;
        const received = count("completed") + count("restored");
        const pending = count("running") + count("retrying");
        return (
          <div key={execution.id} className="border-b border-ink/15 last:border-b-0">
            <div className="bg-paperLight px-4 py-3 sm:px-5">
              <div className="flex flex-wrap items-center justify-between gap-2 font-mono text-[11px]">
                <span title={execution.id} className="uppercase tracking-wider">
                  {t(label("pass"), {
                    number: executionIds ? executionIds.indexOf(execution.id) + 1 : index + 1,
                  })}
                </span>
                {execution.id !== (activeExecutionId ?? executions.at(-1)?.id) && (
                  <span className="text-ink/50">{t(label("history"))}</span>
                )}
                <span>
                  {!execution.incomplete && execution.total !== null
                    ? t(label("results"), { count: received, total: execution.total })
                    : t(label("observed"), { count: execution.tasks.length })}
                </span>
              </div>
              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 font-mono text-[11px] text-ink/60">
                {current && pending > 0 && (
                  <span className="text-fluoPink">
                    {t(label("pendingCount"), { count: pending })}
                  </span>
                )}
                {current && count("queued") > 0 && (
                  <span>{t(label("queuedCount"), { count: count("queued") })}</span>
                )}
                {count("failed") > 0 && (
                  <span className="text-red-700">
                    {t(label("failedCount"), { count: count("failed") })}
                  </span>
                )}
                {count("skipped") > 0 && (
                  <span>{t(label("skippedCount"), { count: count("skipped") })}</span>
                )}
                {count("restored") > 0 && (
                  <span>{t(label("restoredCount"), { count: count("restored") })}</span>
                )}
              </div>
              {!execution.incomplete && execution.total !== null && execution.total > 0 && (
                <div
                  className="mt-3 h-1 bg-ink/10"
                  role="progressbar"
                  aria-label={t(label("results"), { count: received, total: execution.total })}
                  aria-valuemin={0}
                  aria-valuemax={execution.total}
                  aria-valuenow={received}
                >
                  <div
                    className="h-full bg-agenic-green transition-[width] motion-reduce:transition-none"
                    style={{ width: `${(received / execution.total) * 100}%` }}
                  />
                </div>
              )}
              {execution.incomplete && (
                <p className="mt-2 font-sans text-xs text-amber-800">{t(label("incomplete"))}</p>
              )}
            </div>
            {execution.groups.map((group, groupIndex) => (
              <details key={group.id} className="group/question border-t border-ink/15">
                <summary className="flex cursor-pointer list-none items-start gap-3 px-4 py-4 focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-ink sm:px-5 [&::-webkit-details-marker]:hidden">
                  <span className="pt-0.5 font-mono text-xs text-ink/45" aria-hidden="true">
                    {String(groupIndex + 1).padStart(2, "0")}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block whitespace-pre-wrap break-words font-mono text-[13px] leading-relaxed [overflow-wrap:anywhere]">
                      {group.question}
                    </span>
                    <span className="mt-2 flex flex-wrap gap-x-4 gap-y-2">
                      {group.tasks.map((task) => (
                        <TaskBadge key={task.id} task={task} active={current} />
                      ))}
                    </span>
                  </span>
                  <ChevronDown
                    aria-hidden="true"
                    className="mt-1 h-4 w-4 shrink-0 text-ink/50 transition-transform group-open/question:rotate-180"
                  />
                </summary>
                <div className="border-t border-ink/10 bg-paperLight px-4 sm:px-5">
                  {group.tasks.map((task) => (
                    <div
                      key={task.id}
                      className="grid gap-2 border-b border-ink/10 py-3 last:border-b-0 sm:grid-cols-[8rem_minmax(0,1fr)]"
                    >
                      <div>
                        <TaskBadge task={task} active={current} />
                        <p className="mt-1 font-mono text-[10px] text-ink/50">
                          {t(label("attempt"), { number: task.attempt })}
                        </p>
                      </div>
                      <p className="min-w-0 whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed text-ink/65 [overflow-wrap:anywhere]">
                        {task.event.text}
                      </p>
                    </div>
                  ))}
                </div>
              </details>
            ))}
          </div>
        );
      })}
    </>
  );
});

/**
 * The two composed: a deep-research trace in its own shell, titled from the trace vocabulary
 * rather than from a phase divider.
 *
 * RunFeed does NOT use this — it composes `TraceSection` + `ResearchTraceBody` itself so the
 * title can be the engine's own phase label and the subline can be that phase's summary. This
 * export is the standalone rendering (and the one the presentation tests drive directly).
 */
export const ResearchTrace = React.memo(function ResearchTrace({
  executions,
  active,
  activeExecutionId,
  executionIds,
  eventCount,
  unmatched,
  children,
}: {
  executions: TraceExecution[];
  active: boolean;
  activeExecutionId?: string | null;
  executionIds?: string[];
  eventCount: number;
  unmatched: boolean;
  children: React.ReactNode;
}) {
  const { t } = useTranslation("intake");
  return (
    <TraceSection
      title={t(label("title"))}
      active={active}
      eventCount={eventCount}
      unmatched={unmatched}
      raw={children}
    >
      <ResearchTraceBody
        executions={executions}
        active={active}
        activeExecutionId={activeExecutionId}
        executionIds={executionIds}
      />
    </TraceSection>
  );
});

function TaskBadge({ task, active }: { task: TraceTask; active: boolean }) {
  const { t } = useTranslation("intake");
  const state = displayTaskState(task, active);
  const color =
    state === "failed"
      ? "text-red-700"
      : state === "running" || state === "retrying"
        ? "text-fluoPink"
        : state === "completed" || state === "restored"
          ? "text-emerald-700"
          : "text-ink/55";
  return (
    <span
      className={`inline-flex min-w-0 items-center gap-1.5 font-mono text-[10px] leading-relaxed ${color}`}
    >
      <StateIcon state={state} />
      <span className="break-words [overflow-wrap:anywhere]">
        {task.provider} · {t(label(state))}
      </span>
    </span>
  );
}

function StateIcon({ state }: { state: DisplayState }) {
  const Icon =
    state === "completed"
      ? Check
      : state === "restored" || state === "retrying"
        ? RotateCw
        : state === "failed"
          ? X
          : state === "queued"
            ? Clock3
            : state === "skipped" || state === "inactive"
              ? Minus
              : Circle;
  return (
    <Icon
      aria-hidden="true"
      className={`h-3 w-3 shrink-0 ${state === "running" ? "motion-safe:animate-pulse" : ""}`}
    />
  );
}
