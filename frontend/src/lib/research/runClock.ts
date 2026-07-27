import { useEffect, useState } from "react";
import { format } from "date-fns";
import i18n from "@/lib/i18n";
import { getDateLocale } from "@/lib/i18n/date-locale";

// frontend/src/lib/research/runClock.ts — the run page's clock and formatters, EXTRACTED
// VERBATIM from ResearchRunProgress.tsx (Phase 16). Same bodies, now exported and shared.
//
// WHY THIS MODULE EXISTS, AND WHY EXTRACTING BEAT REWRITING.
//
// The operator's design prototype (docs/design/prototypes/ResearchRunImproved.tsx) drives its
// elapsed display from a mount counter — `useState(0)` plus a per-second increment. That
// counts from PAGE LOAD, so closing the run page and reopening it restarts the clock at
// 00:00 while the run keeps going. That is the exact behaviour D-01 exists to eliminate:
// "users can close the page and reopen it to check advancement, timer shouldn't restart each
// time u check on the page" (operator, 2026-07-27). It is also a bug that was already FIXED
// once, in the component below this module's origin.
//
// `useElapsed` derives from the RUN's own `started_at`, which is why plan 15.2-24 carried
// `started_at` across the seam in the first place — this is its first consumer. Extracting
// the working helper (rather than re-deriving a clock next to a design that shows the wrong
// one) makes reuse the path of least resistance and leaves exactly ONE definition to keep
// correct. Do not add a second clock; do not "simplify" the `Date.now()` fallback away — it
// is what keeps a run that has not stamped `started_at` yet from rendering NaN.

export function fmtDate(d: string | null, fallback: string): string {
  if (!d) return fallback;
  try {
    return format(new Date(d), "d MMM yyyy HH:mm", {
      locale: getDateLocale(i18n.language),
    });
  } catch {
    return d;
  }
}

export function fmtCost(cost: string | null, fallback: string): string {
  if (cost == null || cost === "") return fallback;
  const n = Number(cost);
  if (Number.isNaN(n)) return `$${cost}`;
  return `$${n.toFixed(2)}`;
}

/** Elapsed clock (mm:ss) counting up from `startedAt`; falls back to now if unset. */
export function useElapsed(startedAt: string | null, active: boolean): string {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const start = startedAt ? new Date(startedAt).getTime() : Date.now();
    const tick = () => setElapsed(Math.max(0, Math.floor((Date.now() - start) / 1000)));
    tick();
    if (!active) return;
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [startedAt, active]);
  const mm = String(Math.floor(elapsed / 60)).padStart(2, "0");
  const ss = String(elapsed % 60).padStart(2, "0");
  return `${mm}:${ss}`;
}

/** Fixed duration between two timestamps (mm:ss), for the summary card. */
export function fmtDuration(startedAt: string | null, completedAt: string | null): string {
  if (!startedAt || !completedAt) return "—";
  const s = new Date(startedAt).getTime();
  const e = new Date(completedAt).getTime();
  const secs = Math.max(0, Math.floor((e - s) / 1000));
  const mm = String(Math.floor(secs / 60)).padStart(2, "0");
  const ss = String(secs % 60).padStart(2, "0");
  return `${mm}:${ss}`;
}
