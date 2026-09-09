import type { RunEvent } from "@/lib/api/research";

/** A read-only projection of trace metadata, not the research execution state machine. */
export type TraceState =
  "queued" | "running" | "retrying" | "completed" | "restored" | "skipped" | "failed";
export type TraceTask = {
  id: string;
  groupId: string;
  question: string;
  provider: string;
  state: TraceState;
  attempt: number;
  event: RunEvent;
};
export type TraceExecution = {
  id: string;
  total: number | null;
  tasks: TraceTask[];
  groups: { id: string; question: string; tasks: TraceTask[] }[];
  incomplete: boolean;
};

const STATE_KIND: Record<TraceState, string> = {
  queued: "plan",
  running: "agent_run",
  retrying: "agent_retry",
  completed: "agent_done",
  restored: "agent_done",
  skipped: "agent_done",
  failed: "agent_fail",
};
export const isPendingTask = (state: TraceState): boolean =>
  state === "queued" || state === "running" || state === "retrying";

function stringField(meta: RunEvent["meta"], key: string): string | null {
  const value = meta?.[key];
  return typeof value === "string" && value.trim() ? value : null;
}

export function traceIdentity(event: Pick<RunEvent, "meta">): string | null {
  const execution = stringField(event.meta, "trace_execution_id");
  const task = stringField(event.meta, "trace_task_id");
  return execution && task ? JSON.stringify([execution, task]) : null;
}

/** First appearance establishes pass order; late events cannot revive an older pass. */
export function traceExecutionIds(events: readonly Pick<RunEvent, "seq" | "meta">[]): string[] {
  const seen = new Set<string>();
  for (const event of [...events].sort((a, b) => a.seq - b.seq)) {
    const id = stringField(event.meta, "trace_execution_id");
    if (id) seen.add(id);
  }
  return [...seen];
}

export function latestTraceExecutionId(
  events: readonly Pick<RunEvent, "seq" | "meta">[],
): string | null {
  return traceExecutionIds(events).at(-1) ?? null;
}

function readTask(event: RunEvent): TraceTask | null {
  const id = stringField(event.meta, "trace_task_id");
  const groupId = stringField(event.meta, "trace_group_id");
  const question = stringField(event.meta, "trace_question");
  const provider = stringField(event.meta, "provider");
  const state = stringField(event.meta, "trace_state") as TraceState | null;
  const attempt = event.meta?.trace_attempt;
  if (
    !id ||
    !groupId ||
    !question ||
    !provider ||
    !state ||
    !Object.prototype.hasOwnProperty.call(STATE_KIND, state) ||
    STATE_KIND[state] !== event.kind ||
    typeof attempt !== "number" ||
    !Number.isSafeInteger(attempt) ||
    attempt < 1
  )
    return null;
  return { id, groupId, question, provider, state, attempt, event };
}

/** Seq is authoritative, not arrival order. Never group by wording or provider name.
 * A new invocation has a fresh execution ID; coverage retries retain the task ID.
 * Missing/malformed events stay in the original feed, never become fabricated successes.
 */
export function projectResearchTrace(events: readonly RunEvent[]): TraceExecution[] {
  const executions = new Map<
    string,
    { total: number | null; tasks: Map<string, TraceTask>; invalid: boolean }
  >();
  const seen = new Set<number>();
  for (const event of [...events].sort((a, b) => a.seq - b.seq)) {
    if (seen.has(event.seq)) continue;
    seen.add(event.seq);
    if (event.stage !== "deep_research") continue;
    const id = stringField(event.meta, "trace_execution_id");
    if (!id) continue;
    let execution = executions.get(id);
    if (!execution) {
      execution = { total: null, tasks: new Map(), invalid: false };
      executions.set(id, execution);
    }
    if (event.kind === "dispatch") {
      const total = event.meta?.trace_total;
      if (typeof total === "number" && Number.isSafeInteger(total) && total >= 0) {
        if (execution.total !== null && execution.total !== total) execution.invalid = true;
        execution.total = total;
      } else execution.invalid = true;
      continue;
    }
    const task = readTask(event);
    if (!task) {
      execution.invalid = true;
      continue;
    }
    const previous = execution.tasks.get(task.id);
    if (previous && previous.groupId !== task.groupId) {
      execution.invalid = true;
      continue;
    }
    if (
      previous &&
      (task.attempt < previous.attempt ||
        (task.attempt === previous.attempt &&
          !isPendingTask(previous.state) &&
          isPendingTask(task.state)))
    )
      continue;
    execution.tasks.set(task.id, task);
  }
  return [...executions].map(([id, execution]) => {
    const tasks = [...execution.tasks.values()];
    const groups = new Map<string, TraceExecution["groups"][number]>();
    for (const task of tasks) {
      let group = groups.get(task.groupId);
      if (!group) {
        group = { id: task.groupId, question: task.question, tasks: [] };
        groups.set(task.groupId, group);
      }
      group.tasks.push(task);
    }
    return {
      id,
      total: execution.total,
      tasks,
      groups: [...groups.values()],
      incomplete: execution.invalid || execution.total === null || execution.total !== tasks.length,
    };
  });
}

/** Never leave a spinner on an older pass or stopped run; absence of an outcome is not failure. */
export function displayTaskState(task: TraceTask, active: boolean): TraceState | "inactive" {
  return !active && isPendingTask(task.state) ? "inactive" : task.state;
}
