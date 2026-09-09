import React from "react";
import { useTranslation } from "react-i18next";
import { Check, ChevronDown, Circle, Clock3, RotateCw, X, Minus } from "lucide-react";
import { displayTaskState, type TraceExecution, type TraceTask } from "@/lib/research/groupedTrace";

type DisplayState = ReturnType<typeof displayTaskState>;
const label = (key: string) => `research.runPage.trace.${key}`;

/** Presentation only. Original rows (and their audit panels) are supplied by RunFeed. */
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
    <section className="my-4 min-w-0 border border-ink/20 bg-paper text-ink [color-scheme:only_light]">
      <header className="border-b border-ink/15 px-4 py-4 sm:px-5">
        <h3 className="font-serif text-xl leading-tight sm:text-2xl">{t(label("title"))}</h3>
        <p className="mt-2 max-w-2xl font-sans text-xs leading-relaxed text-ink/60">
          {t(label("scope"))}
        </p>
      </header>
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
      <details className="border-t border-ink/20">
        <summary className="cursor-pointer px-4 py-3 font-mono text-[11px] focus-visible:outline-2 focus-visible:outline-ink sm:px-5">
          {t(label("raw"), { count: eventCount })}
        </summary>
        <div className="border-t border-ink/10 px-4 pb-4 sm:px-5">
          <p className="my-3 font-sans text-xs text-ink/60">{t(label("rawHint"))}</p>
          {children}
        </div>
      </details>
      {unmatched && (
        <p className="border-t border-ink/10 px-4 py-2 font-sans text-xs text-ink/60 sm:px-5">
          {t(label("unmatched"))}
        </p>
      )}
    </section>
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
