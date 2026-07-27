import { useEffect, useRef, useState } from "react";
import { createFileRoute, Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { ArrowLeft, Loader2 } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { getIntake } from "@/lib/api/intakes";
import { locateResearchRun } from "@/lib/api/research";
import { fmtCost, useElapsed } from "@/lib/research/runClock";
import { useRunEvents } from "@/lib/research/useRunEvents";
import { useActiveResearchRun } from "@/components/intake/ResearchRunProgress";

// frontend/src/routes/admin.pulse.runs.$runId.tsx — the dedicated research-run page (D-01).
//
// WHY THIS ROUTE IS FLAT (D-08). The file name gives `/admin/pulse/runs/:runId`, a LEAF under
// the existing `admin.pulse` layout, which already renders <ProductShell> around its own
// outlet. Nesting this under `admin.pulse.intakes.$id.tsx` would turn that leaf into a PARENT
// requiring an outlet of its own — the trap that cost a cycle in Phase 18 — and it would tie
// the run's URL to an intake id the operator's bookmark does not carry. A flat route is what
// makes the URL genuinely standalone, which is the whole of D-01.
//
// WHY THE INTAKE ID IS RESOLVED, NEVER ACCEPTED (T-15.3-71 / TENANT-02). The page learns its
// intake ONLY from `locateResearchRun(runId)`. It takes no intake id from a query parameter:
// a bookmarked link will not have one, and a URL-supplied tenant hint is precisely the shape
// of input tenant isolation forbids. Every downstream read is keyed on the RESOLVED id.
//
// SECURITY (T-15.3-70 / D-08). Superadmin-only twice over: by PLACEMENT under `admin.pulse`,
// which inherits the admin guard, and by API — every verb this page calls is superadmin-gated
// and space-scoped server-side, returning an existence-hiding 404 to anyone else. No
// client-facing route imports anything from this file.
//
// ACCESSIBILITY. The live region is scoped to the STATUS AND PHASE block only. The feed body
// deliberately carries none: a region announcing every one of a thousand events is worse than
// no region at all (T-15.3-82).

export const Route = createFileRoute("/admin/pulse/runs/$runId")({
  component: ResearchRunPage,
});

/**
 * Terminal research-run statuses, VERBATIM from the Tribunal contract (D-05) — the same set
 * the stream and the embedded card use. `completed_degraded` and `parked` are terminal here
 * too; `needs_input` is the engine's parked clarification state and stops the clock as well.
 */
const RESEARCH_TERMINAL = new Set([
  "completed",
  "completed_degraded",
  "failed",
  "cancelled",
  "parked",
  "needs_input",
]);

function ResearchRunPage() {
  const { runId } = Route.useParams();
  const { t } = useTranslation("intake");

  // ── Cold open: resolve run → intake before anything else can be read. ───────────────
  const [intakeId, setIntakeId] = useState<string | null>(null);
  const [locating, setLocating] = useState(true);
  const [locateFailed, setLocateFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLocating(true);
    setLocateFailed(false);
    setIntakeId(null);
    void locateResearchRun(runId).then((res) => {
      if (cancelled) return;
      if (res.success && res.data?.intake_id) {
        setIntakeId(res.data.intake_id);
      } else {
        // A denial here is existence-hidden by design — the page cannot and must not
        // distinguish "no such run" from "not yours". One message covers both.
        setLocateFailed(true);
      }
      setLocating(false);
    });
    return () => {
      cancelled = true;
    };
  }, [runId]);

  // The client name for the header. Purely cosmetic — a failure leaves the fallback title
  // and must never block the run itself from rendering.
  const [clientName, setClientName] = useState<string | null>(null);
  useEffect(() => {
    if (!intakeId) return;
    let cancelled = false;
    void getIntake(intakeId).then((res) => {
      if (cancelled) return;
      if (res.success) setClientName(res.data?.client_name ?? null);
    });
    return () => {
      cancelled = true;
    };
  }, [intakeId]);

  // ── The run itself: ONE SSE connection, the single authority on status/stage/cost/cursor.
  const { run } = useActiveResearchRun(intakeId ?? undefined);
  const status = run?.status ?? "queued";
  const isTerminal = RESEARCH_TERMINAL.has(status);

  // THE CLOCK. Derived from the RUN's own started_at — never from mount. This is the whole
  // point of D-01/D-09: closing this page and reopening it must show the run's real elapsed
  // time, not a counter that restarts at 00:00 on every visit.
  const elapsed = useElapsed(run?.started_at ?? null, !isTerminal);

  // ── The feed: backfill the full history, then only the delta past the SSE cursor. ──────
  const { events, loading: eventsLoading } = useRunEvents(
    intakeId,
    intakeId ? runId : null,
    run?.event_seq ?? null,
  );

  const scrollRef = useRef<HTMLDivElement | null>(null);

  if (locating) {
    return (
      <div>
        <Skeleton className="h-4 w-48" />
        <Skeleton className="mt-3 h-8 w-96" />
        <Skeleton className="mt-8 h-64 w-full" />
      </div>
    );
  }

  if (locateFailed || !intakeId) {
    return (
      <div className="mx-auto max-w-md py-16 text-center">
        <p className="text-sm text-ink/60">{t("research.runPage.notFound")}</p>
        <Link
          to="/admin/pulse/intakes"
          className="mt-4 inline-flex items-center gap-1 text-sm font-medium text-ink hover:underline"
        >
          <ArrowLeft className="h-4 w-4" />
          {t("research.runPage.backToIntakes")}
        </Link>
      </div>
    );
  }

  // ONE full-height column: a fixed header, a single scrolling region, a fixed footer ticker
  // while the run is live. The height budget subtracts the shell's TopBar (h-11) and the
  // shell main's vertical padding (md:py-10) so this column ends exactly at the viewport and
  // the page never grows a second scrollbar of its own.
  return (
    <div className="flex h-[calc(100vh-7.75rem)] min-h-[30rem] flex-col">
      {/* ── Header ─────────────────────────────────────────────────────────────────── */}
      <header className="shrink-0 border-b border-ink/10 pb-4">
        <div className="flex flex-wrap items-start justify-between gap-6">
          <div className="min-w-0">
            <div className="font-mono text-[10.5px] uppercase tracking-[0.1em] text-ink/50">
              <span>{t("research.runPage.breadcrumbProduct")}</span>
              <span className="px-1.5">·</span>
              <Link to="/admin/pulse/intakes" className="hover:text-ink">
                {t("research.runPage.breadcrumbIntakes")}
              </Link>
              {clientName && (
                <>
                  <span className="px-1.5">·</span>
                  <Link
                    to="/admin/pulse/intakes/$id"
                    params={{ id: intakeId }}
                    className="hover:text-ink"
                  >
                    {clientName}
                  </Link>
                </>
              )}
              <span className="px-1.5">·</span>
              <span>{t("research.runPage.breadcrumbRun")}</span>
            </div>

            <h1 className="mt-1 font-serif text-xl font-semibold leading-tight text-ink">
              {clientName
                ? t("research.runPage.title", { client: clientName })
                : t("research.runPage.titleFallback")}
            </h1>

            <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 font-mono text-[11px] text-ink/50">
              <span>{t("research.runPage.metaRun", { id: runId.slice(0, 8) })}</span>
              <span>{t("research.runPage.metaEngine", { engine: "tribunal" })}</span>
              {events.length > 0 && (
                <span>{t("research.runPage.metaEvents", { count: events.length })}</span>
              )}
            </div>
          </div>

          {/* Stats: elapsed from the run's own clock, cost from the mirrored total. */}
          <div className="flex shrink-0 gap-8">
            <div className="text-right">
              <div className="font-mono text-[10px] uppercase tracking-[0.1em] text-ink/50">
                {t("research.elapsed")}
              </div>
              <div className="mt-0.5 font-mono text-xl tabular-nums text-ink">{elapsed}</div>
            </div>
            <div className="text-right">
              <div className="font-mono text-[10px] uppercase tracking-[0.1em] text-ink/50">
                {t("research.cost")}
              </div>
              <div className="mt-0.5 font-mono text-xl tabular-nums text-ink">
                {fmtCost(run?.cost_usd_total ?? null, t("research.costFallback"))}
              </div>
            </div>
          </div>
        </div>

        {/* THE live region — status and phase only, never the feed body. */}
        <div
          role="status"
          aria-live="polite"
          className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-[11px] uppercase tracking-wider text-ink/60"
        >
          <span className="text-ink">{statusLabel(status, t)}</span>
          {run?.current_stage && (
            <span>{t("research.currentStage", { stage: run.current_stage })}</span>
          )}
        </div>
      </header>

      {/* ── The single scrolling region ─────────────────────────────────────────────── */}
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto py-4">
        <div className="mx-auto max-w-3xl">
          {/* ⚠ PLACEHOLDER — replace me. Task 5 of plan 15.3-08 swaps this block for the
              real <RunFeed/> renderer (grouping, collapse, the live badge, one cursor).
              It exists ONLY so this route is verifiable on its own; it is not a design and
              must NOT survive into the next plan. Delete the whole block, not parts of it. */}
          {eventsLoading && events.length === 0 && (
            <div className="flex items-center gap-2 font-mono text-[12px] text-ink/50">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              {t("research.runPage.loadingEvents")}
            </div>
          )}
          {events.map((ev) => (
            <div key={ev.seq} className="py-0.5 font-mono text-[13px] text-ink/80">
              {ev.text}
            </div>
          ))}
          {/* ⚠ END PLACEHOLDER */}
        </div>
      </div>

      {/* ── Footer ticker, live runs only ───────────────────────────────────────────── */}
      {!isTerminal && (
        <div className="flex shrink-0 items-center gap-2 border-t border-ink/10 pt-2 font-mono text-[11px] text-ink/50">
          <Loader2 className="h-3 w-3 animate-spin" style={{ color: "#FF2D87" }} />
          <span style={{ color: "#FF2D87" }}>
            {run?.current_stage ?? t("research.runPage.status.queued")}
          </span>
        </div>
      )}
    </div>
  );
}

/**
 * All EIGHT run statuses (D-11), each a literal `t()` call so the i18n audit's CHECK B
 * actually covers them, plus a fallback so a status this build has never heard of still
 * renders words rather than a raw key.
 */
function statusLabel(status: string, t: (key: string) => string): string {
  switch (status) {
    case "queued":
      return t("research.runPage.status.queued");
    case "running":
      return t("research.runPage.status.running");
    case "completed":
      return t("research.runPage.status.completed");
    case "completed_degraded":
      return t("research.runPage.status.completedDegraded");
    case "failed":
      return t("research.runPage.status.failed");
    case "cancelled":
      return t("research.runPage.status.cancelled");
    case "parked":
      return t("research.runPage.status.parked");
    case "needs_input":
      return t("research.runPage.status.needsInput");
    default:
      return t("research.runPage.status.unknown");
  }
}
