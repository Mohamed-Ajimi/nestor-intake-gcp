import { describe, expect, it } from "vitest";
import type { RunEvent } from "@/lib/api/research";
import {
  displayTaskState,
  latestTraceExecutionId,
  projectResearchTrace,
  traceIdentity,
  type TraceState,
} from "@/lib/research/groupedTrace";
import en from "@/locales/en/intake.json";
import nl from "@/locales/nl/intake.json";
import fr from "@/locales/fr/intake.json";

const kinds: Record<TraceState, string> = {
  queued: "plan",
  running: "agent_run",
  retrying: "agent_retry",
  completed: "agent_done",
  restored: "agent_done",
  skipped: "agent_done",
  failed: "agent_fail",
};

function task(
  seq: number,
  id: string,
  state: TraceState,
  meta: Record<string, unknown> = {},
): RunEvent {
  return {
    seq,
    ts: "2026-09-09T12:00:00Z",
    stage: "deep_research",
    kind: kinds[state],
    text: `Recorded activity ${seq}`,
    meta: {
      trace_execution_id: "pass-1",
      trace_task_id: id,
      trace_group_id: "question-1",
      trace_question: "Which pricing model works?",
      trace_state: state,
      trace_attempt: 1,
      provider: "gemini",
      ...meta,
    },
  };
}

function dispatch(seq: number, total: unknown, execution = "pass-1"): RunEvent {
  return {
    seq,
    ts: "2026-09-09T12:00:00Z",
    stage: "deep_research",
    kind: "dispatch",
    text: "Dispatching researchers",
    meta: { trace_execution_id: execution, trace_total: total },
  };
}

describe("grouped research trace — recorded identity, never arrival position", () => {
  it("late events from an old pass do not rewind the current execution", () => {
    expect(
      latestTraceExecutionId([
        dispatch(1, 1),
        dispatch(3, 1, "pass-2"),
        task(4, "old", "running"),
        task(2, "old", "queued"),
      ]),
    ).toBe("pass-2");
    expect(latestTraceExecutionId([])).toBeNull();
  });
  it("settles the correct task when parallel providers finish out of order", () => {
    const [execution] = projectResearchTrace([
      task(5, "b", "completed", { provider: "openai" }),
      task(3, "b", "running", { provider: "openai" }),
      dispatch(1, 2),
      task(2, "a", "running"),
    ]);
    expect(execution.tasks.map(({ id, state }) => [id, state])).toEqual([
      ["a", "running"],
      ["b", "completed"],
    ]);
    expect(execution.groups).toHaveLength(1);
    expect(execution.incomplete).toBe(false);
  });

  it("makes reconnect sequence replay idempotent", () => {
    const events = [dispatch(1, 1), task(2, "a", "running"), task(3, "a", "completed")];
    expect(projectResearchTrace([...events, ...events, events[1]])).toEqual(
      projectResearchTrace(events),
    );
  });

  it("accepts a terminal event without inventing a missing start", () => {
    const finished = task(2, "a", "completed");
    const [execution] = projectResearchTrace([dispatch(1, 1), finished]);
    expect(execution.tasks).toHaveLength(1);
    expect(execution.tasks[0].state).toBe("completed");
    expect(execution.tasks[0].event).toBe(finished);
  });

  it("does not regress a terminal task to a late start in the same attempt", () => {
    const [execution] = projectResearchTrace([
      task(1, "a", "completed"),
      task(2, "a", "running"),
      task(3, "a", "queued"),
    ]);
    expect(execution.tasks[0].state).toBe("completed");
  });

  it("allows a higher retry attempt to recover without stale lower attempts overwriting it", () => {
    const [execution] = projectResearchTrace([
      task(1, "a", "failed"),
      task(2, "a", "retrying", { trace_attempt: 2 }),
      task(3, "a", "completed", { trace_attempt: 1 }),
      task(4, "a", "running", { trace_attempt: 2 }),
      task(5, "a", "completed", { trace_attempt: 2 }),
      task(6, "a", "failed", { trace_attempt: 1 }),
    ]);
    expect(execution.tasks[0]).toMatchObject({ state: "completed", attempt: 2 });
    expect(execution.tasks[0].event.seq).toBe(5);
  });

  it("keeps equal task IDs in separate execution passes", () => {
    const executions = projectResearchTrace([
      dispatch(1, 1),
      task(2, "a", "completed"),
      dispatch(3, 1, "pass-2"),
      task(4, "a", "running", { trace_execution_id: "pass-2" }),
    ]);
    expect(executions.map(({ id, tasks }) => [id, tasks[0].state])).toEqual([
      ["pass-1", "completed"],
      ["pass-2", "running"],
    ]);
  });

  it("keeps distinct question IDs separate even when their text is identical", () => {
    const [execution] = projectResearchTrace([
      task(1, "a", "running"),
      task(2, "b", "running", { trace_group_id: "question-2" }),
    ]);
    expect(execution.groups.map(({ id }) => id)).toEqual(["question-1", "question-2"]);
    expect(execution.groups[0].question).toBe(execution.groups[1].question);
  });

  it("uses the actual provider after fallback and accepts future provider names", () => {
    const [execution] = projectResearchTrace([
      task(1, "a", "running", { provider: "gemini" }),
      task(2, "a", "completed", { provider: "future-provider/v2" }),
    ]);
    expect(execution.tasks[0].provider).toBe("future-provider/v2");
  });

  it("keeps restored, skipped, failed and newly completed work distinct", () => {
    const states: TraceState[] = ["restored", "skipped", "failed", "completed"];
    const [execution] = projectResearchTrace(states.map((state, i) => task(i + 1, `${i}`, state)));
    expect(execution.tasks.map(({ state }) => state)).toEqual(states);
  });

  it.each<TraceState>(["queued", "running", "retrying"])(
    "%s becomes inactive on a stopped run or older pass without fabricating failure",
    (state) => {
      const projected = projectResearchTrace([task(1, "a", state)])[0].tasks[0];
      expect(displayTaskState(projected, true)).toBe(state);
      expect(displayTaskState(projected, false)).toBe("inactive");
      expect(projected.state).toBe(state);
    },
  );

  it.each<TraceState>(["completed", "restored", "skipped", "failed"])(
    "preserves %s when the run is no longer active",
    (state) => {
      const projected = projectResearchTrace([task(1, "a", state)])[0].tasks[0];
      expect(displayTaskState(projected, false)).toBe(state);
    },
  );
});

describe("grouped research trace — incomplete evidence stays honest", () => {
  it("leaves legacy events and other stages outside the grouped projection", () => {
    expect(
      projectResearchTrace([
        { ...task(1, "a", "running"), meta: null },
        { ...task(2, "b", "running"), meta: undefined },
        { ...task(3, "c", "running"), stage: "workshop" },
      ]),
    ).toEqual([]);
  });

  it.each([
    ["trace_task_id", ""],
    ["trace_group_id", " "],
    ["trace_question", null],
    ["provider", 12],
    ["trace_state", "invented"],
    ["trace_state", "constructor"],
    ["trace_attempt", 0],
    ["trace_attempt", -1],
    ["trace_attempt", 1.5],
    ["trace_attempt", "1"],
    ["trace_attempt", Number.POSITIVE_INFINITY],
    ["trace_attempt", Number.MAX_SAFE_INTEGER + 1],
  ])("does not fabricate a task from invalid %s=%s", (key, value) => {
    const [execution] = projectResearchTrace([
      dispatch(1, 1),
      task(2, "a", "running", { [key]: value }),
    ]);
    expect(execution.tasks).toEqual([]);
    expect(execution.incomplete).toBe(true);
  });

  it("requires an explicit execution ID before grouping", () => {
    expect(projectResearchTrace([task(1, "a", "running", { trace_execution_id: " " })])).toEqual(
      [],
    );
  });

  it("leaves unknown event kinds and mismatched kind/state metadata ungrouped", () => {
    const [execution] = projectResearchTrace([
      dispatch(1, 2),
      { ...task(2, "a", "running"), kind: "future_kind" },
      task(3, "b", "running", { trace_state: "completed" }),
    ]);
    expect(execution.tasks).toEqual([]);
    expect(execution.incomplete).toBe(true);
  });

  it("flags a missing declared total rather than inventing a denominator", () => {
    const [execution] = projectResearchTrace([task(1, "a", "running")]);
    expect(execution.total).toBeNull();
    expect(execution.incomplete).toBe(true);
  });

  it("flags missing task records without inventing queued rows", () => {
    const [execution] = projectResearchTrace([dispatch(1, 3), task(2, "a", "running")]);
    expect(execution.total).toBe(3);
    expect(execution.tasks).toHaveLength(1);
    expect(execution.incomplete).toBe(true);
  });

  it.each([null, "3", -1, 1.5, Number.NaN, Number.POSITIVE_INFINITY])(
    "rejects an invalid declared total %s",
    (total) => {
      const [execution] = projectResearchTrace([dispatch(1, total)]);
      expect(execution.total).toBeNull();
      expect(execution.incomplete).toBe(true);
    },
  );

  it("accepts explicitly declared zero tasks without inventing work", () => {
    expect(projectResearchTrace([dispatch(1, 0)])[0]).toMatchObject({
      total: 0,
      tasks: [],
      groups: [],
      incomplete: false,
    });
  });

  it("flags contradictory totals and task counts greater than the declared total", () => {
    expect(
      projectResearchTrace([
        dispatch(1, 1),
        dispatch(2, 2),
        task(3, "a", "running"),
        task(4, "b", "running"),
      ])[0].incomplete,
    ).toBe(true);
    expect(projectResearchTrace([dispatch(1, 0), task(2, "a", "running")])[0].incomplete).toBe(
      true,
    );
  });

  it("rejects a task switching question identity instead of merging conflicting records", () => {
    const [execution] = projectResearchTrace([
      dispatch(1, 1),
      task(2, "a", "running"),
      task(3, "a", "completed", { trace_group_id: "unrelated-question" }),
    ]);
    expect(execution.incomplete).toBe(true);
    expect(execution.tasks[0]).toMatchObject({ groupId: "question-1", state: "running" });
  });

  it("does not mutate or reorder source events and preserves original event metadata", () => {
    const events = [
      task(3, "b", "completed", { audit_id: "audit-b" }),
      dispatch(1, 2),
      task(2, "a", "running"),
    ];
    const snapshot = JSON.stringify(events);
    for (const event of events) {
      Object.freeze(event.meta);
      Object.freeze(event);
    }
    Object.freeze(events);
    const projected = projectResearchTrace(events);
    expect(JSON.stringify(events)).toBe(snapshot);
    expect(projected[0].tasks[1].event).toBe(events[0]);
    expect(projected[0].tasks[1].event.meta?.audit_id).toBe("audit-b");
  });
});

describe("trace identity and locale contracts", () => {
  it("combines execution and task IDs without delimiter collisions", () => {
    expect(traceIdentity(task(1, "c", "running", { trace_execution_id: "a:b" }))).not.toBe(
      traceIdentity(task(2, "b:c", "running", { trace_execution_id: "a" })),
    );
    expect(traceIdentity(task(3, "c", "running", { trace_execution_id: "a:b" }))).toBe(
      traceIdentity(task(1, "c", "running", { trace_execution_id: "a:b" })),
    );
  });

  it("returns no identity for missing or non-string identifiers", () => {
    expect(traceIdentity({ meta: null })).toBeNull();
    expect(traceIdentity({ meta: { trace_execution_id: "pass", trace_task_id: 1 } })).toBeNull();
    expect(traceIdentity({ meta: { trace_execution_id: " ", trace_task_id: "a" } })).toBeNull();
  });

  it.each([
    ["nl", nl],
    ["fr", fr],
  ] as const)("%s preserves every trace label and interpolation", (_, locale) => {
    const english = en.research.runPage.trace;
    const translated = locale.research.runPage.trace;
    expect(Object.keys(translated).sort()).toEqual(Object.keys(english).sort());
    for (const key of Object.keys(english) as (keyof typeof english)[]) {
      expect(translated[key].trim().length).toBeGreaterThan(0);
      expect(translated[key].match(/\{\{\w+\}\}/g)?.sort() ?? []).toEqual(
        english[key].match(/\{\{\w+\}\}/g)?.sort() ?? [],
      );
    }
  });
});
