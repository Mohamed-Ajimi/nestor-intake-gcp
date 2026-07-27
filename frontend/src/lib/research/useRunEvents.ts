import { useCallback, useEffect, useRef, useState } from "react";
import { getRunEvents, type RunEvent } from "@/lib/api/research";

// frontend/src/lib/research/useRunEvents.ts — the run page's event loader: BACKFILL the
// whole history once, then fetch ONLY the delta the SSE cursor points past.
//
// The two properties this hook exists for:
//
//  1. D-01 REOPEN. The live stream carries only what happened while somebody was watching.
//     Reopening the page must show the run's FULL history, so the first thing this does is
//     page the persisted feed from `seq` 0 forward.
//
//  2. DELTA-ONLY. `run.event_seq` rides the SSE frame at a ~3-second cadence. Refetching on
//     every frame would turn a 3-second stream cadence into a 3-second REQUEST cadence
//     against a run that may hold thousands of rows. So a fetch happens only when the
//     incoming cursor is STRICTLY GREATER than the position already held (`afterSeqRef`).
//     A tick that adds nothing issues no request at all.
//
// ⚠ THE DELTA-ONLY BEHAVIOUR IS INSPECTED, NOT TESTED. This repo has no frontend test
// framework, so nothing drives cursor ticks and counts the resulting requests. What is
// established is that the guard is present and reads correctly; what is NOT established is
// that it holds under every re-render, StrictMode double-invoke or racing backfill. The
// honest form of a real proof is a Vitest + Testing Library harness asserting a fetch-spy
// call count across simulated cursor advances — deliberately separate work, not smuggled in
// here. Do not cite this hook as evidence of a measured request count.
//
// FAILURE POLICY: every path silent-degrades. `getRunEvents` returns `ApiResult`, so a
// `success:false` keeps whatever is already held, stops the in-flight loop, and waits for the
// next cursor advance to retry. No throw and no toast — a transient events failure must not
// take the run's status card down with it.

/** Rows requested per page. The server bounds `limit` at 1000; this stays well inside it. */
const PAGE_LIMIT = 500;

/**
 * Hard cap on pages drained in one pass — 10 × 500 = 5000 events (T-15.3-73).
 *
 * A pathological run must not be able to hold this loop open forever. When the cap is hit
 * with `has_more` still true the hook stops and raises `truncated`, so the page can say in
 * words that older history was not loaded rather than silently presenting a partial feed as
 * if it were whole.
 */
const MAX_PAGES = 10;

export type UseRunEventsResult = {
  /** Append-only, ascending by `seq`, de-duplicated. Never reordered, never pruned. */
  events: RunEvent[];
  /** True only during the FIRST backfill pass; a delta fetch does not blank the page. */
  loading: boolean;
  /** The page cap was reached with more history still available upstream. */
  truncated: boolean;
};

export function useRunEvents(
  intakeId: string | null,
  runId: string | null,
  cursor: number | null,
): UseRunEventsResult {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [truncated, setTruncated] = useState(false);

  /** The highest `seq` this hook has consumed. The delta guard compares against THIS. */
  const afterSeqRef = useRef(0);
  /** Seen `seq` values — a reconnect that replays a page cannot double a line. */
  const seenRef = useRef<Set<number>>(new Set());
  /** One drain at a time: a cursor tick during a backfill must not start a second loop. */
  const inFlightRef = useRef(false);

  const drain = useCallback(
    async (token: { cancelled: boolean }) => {
      if (!intakeId || !runId) return;
      if (inFlightRef.current) return;
      inFlightRef.current = true;
      try {
        for (let page = 0; page < MAX_PAGES; page++) {
          const res = await getRunEvents(intakeId, runId, afterSeqRef.current, PAGE_LIMIT);
          // An unmount (or a runId change) between request and response must not write.
          if (token.cancelled) return;
          // Silent degrade: keep what is held and let the next cursor advance retry.
          if (!res.success) return;

          const pageData = res.data;
          const incoming = pageData?.events ?? [];
          const fresh = incoming.filter((e) => !seenRef.current.has(e.seq));
          for (const e of fresh) seenRef.current.add(e.seq);
          if (fresh.length > 0) setEvents((prev) => [...prev, ...fresh]);

          // NEVER REWIND. `next_after_seq` on an empty page is the cursor that was passed
          // in (15.3-02's anti-rewind property), so this max() is belt-and-braces against a
          // future server that regresses it — a rewind would re-fetch the run from row one
          // on every quiet tick.
          const next = pageData?.next_after_seq;
          if (typeof next === "number") {
            afterSeqRef.current = Math.max(afterSeqRef.current, next);
          }

          if (!pageData?.has_more) return;
          // Cap reached with history still upstream — stop and say so.
          if (page === MAX_PAGES - 1) setTruncated(true);
        }
      } finally {
        inFlightRef.current = false;
      }
    },
    [intakeId, runId],
  );

  // ── Backfill: the run's whole history, once per (intakeId, runId) identity. ──────────
  useEffect(() => {
    // A new run means a new feed: drop everything, including the cursor position and the
    // de-dup set, or the next run's rows would be filtered against the previous run's seqs.
    setEvents([]);
    setTruncated(false);
    seenRef.current = new Set();
    afterSeqRef.current = 0;
    inFlightRef.current = false;

    if (!intakeId || !runId) {
      setLoading(false);
      return;
    }

    const token = { cancelled: false };
    setLoading(true);
    void drain(token).finally(() => {
      if (!token.cancelled) setLoading(false);
    });

    return () => {
      token.cancelled = true;
    };
  }, [intakeId, runId, drain]);

  // ── Delta: fetch ONLY when the cursor has moved past what is held. ───────────────────
  useEffect(() => {
    if (!intakeId || !runId) return;
    // No cursor at all — a run that has emitted nothing (or a pre-15.3 run). Nothing to ask
    // for, and asking anyway is the request-per-tick this hook exists to avoid.
    if (cursor == null) return;
    // THE GUARD. `<=` means the stream re-sent a frame whose event high-water mark has not
    // moved: there is provably nothing past what is held, so no request is issued.
    if (cursor <= afterSeqRef.current) return;

    const token = { cancelled: false };
    void drain(token);
    return () => {
      token.cancelled = true;
    };
  }, [cursor, intakeId, runId, drain]);

  return { events, loading, truncated };
}
