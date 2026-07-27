import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Brain,
  CheckCircle2,
  ChevronDown,
  FileSearch,
  GitBranch,
  Layers,
  Loader2,
  RotateCw,
  Search,
  Wrench,
  XCircle,
  Zap,
} from "lucide-react";
import { fmtCost } from "@/lib/research/runClock";
import type { RunEvent } from "@/lib/api/research";

// frontend/src/components/research/RunFeed.tsx — the run page's activity feed, converted
// from the operator's design of record (docs/design/prototypes/ResearchRunImproved.tsx).
// The INTERACTION design is preserved; only the delivery changes (Tailwind utilities instead
// of inline styles, t() instead of hardcoded English, real events instead of a mock timeline).
//
// The six things the design's header comment names as WHAT TO PRESERVE, and where each lives:
//   - blinking cursor on the latest line ......... `cursorSeq` + the one blink timer below
//   - "Dispatching N agents" headers ............. the `dispatch` branch (bold, zap glyph)
//   - indented agent children .................... the agent_* branches (one indent level)
//   - completed phases collapse to 2 lines ....... FeedGroup's collapsed preview
//   - per-phase "Worked for X · …" summaries ..... the `summary` branch
//   - the live badge ............................. `meta.is_live` on an agent_run
//
// GROUPING IS DERIVED, NEVER DECLARED. Consecutive events sharing a `stage` are one group.
// `stage` IS the group key — the engine already emits it and it already carries the stage
// vocabulary. There is no stage list, no stage count and no stage order anywhere in this
// file, which is why an engine that adds a phase costs this component nothing. That property
// is the current progress panel's best one and it is deliberately carried over.
//
// RENDERING IS A LOOKUP WITH A DEFAULT, NEVER AN EXHAUSTIVE SWITCH. A newer engine revision
// may emit a kind this build has never heard of — that is the normal state of a rolling
// deploy, not an edge case. The default branch renders a plain line, so an unknown kind is a
// slightly plainer row rather than a blank one or a thrown error (T-15.3-83).
//
// SECURITY (T-15.3-72 / T-15.3-80): every event string is a React TEXT CHILD, so React
// escapes it. Engine event text is untrusted input; it is rendered as text and NEVER as
// markup. No raw-HTML injection prop and no markdown renderer appears anywhere in this file,
// and the check for that is a source scan — which is why neither is named here verbatim.
//
// ACCESSIBILITY (T-15.3-82): this component declares NO live region of any kind. The run page
// scopes its own to status and phase. A region announcing every one of a thousand rows is
// worse than none at all — and again, the attribute is described rather than spelled, so the
// scan that enforces its absence cannot be tripped by this comment.
//
// ⚠ VOLUME BEHAVIOUR IS INSPECTED, NOT MEASURED. The memo boundaries below are real and every
// prop crossing one is a primitive or a stable reference — but no render count is asserted
// anywhere, because this repo has no frontend test framework. A React.memo defeated by an
// inline object or inline callback prop would still LOOK correct in review while re-rendering
// every row on every tick, which is the exact failure these boundaries exist to prevent. The
// honest proof is a Vitest render-count assertion across appended events; that is separate
// work and is deliberately not smuggled in here. Do not cite this file as measured.

/** How long the block cursor stays on/off, matching the design of record. */
const CURSOR_BLINK_MS = 530;

/** Rows previewed when a completed phase is collapsed — two, per the design. */
const COLLAPSED_PREVIEW_ROWS = 2;

const FLUO_PINK = "#FF2D87";

type Group = { key: string; stage: string; events: RunEvent[] };

export function RunFeed({
  events,
  isActive,
  onDrillDown,
  drilldownAuditId,
  renderAfterRow,
}: {
  events: RunEvent[];
  isActive: boolean;
  onDrillDown?: (auditId: string) => void;
  drilldownAuditId?: string | null;
  renderAfterRow?: (event: RunEvent) => React.ReactNode;
}): React.JSX.Element {
  // Callback props are held in refs and exposed through STABLE wrappers. A caller that
  // passes an inline arrow — the normal thing to write — would otherwise hand a new function
  // identity to every memoised row on every render and silently defeat the whole memo
  // boundary. The refs are assigned during render, not in an effect, so the wrapper can never
  // call a stale closure.
  const drillRef = useRef(onDrillDown);
  drillRef.current = onDrillDown;
  const afterRowRef = useRef(renderAfterRow);
  afterRowRef.current = renderAfterRow;

  const stableDrill = useCallback((auditId: string) => {
    drillRef.current?.(auditId);
  }, []);
  const stableAfterRow = useCallback(
    (event: RunEvent) => afterRowRef.current?.(event) ?? null,
    [],
  );
  const canDrill = !!onDrillDown;

  // Grouping is recomputed only when the events array identity changes — i.e. when the
  // loader actually appended something, not on every cursor blink.
  const groups = useMemo<Group[]>(() => {
    const out: Group[] = [];
    for (const ev of events) {
      const last = out[out.length - 1];
      if (last && last.stage === ev.stage) last.events.push(ev);
      else out.push({ key: `${ev.stage}:${ev.seq}`, stage: ev.stage, events: [ev] });
    }
    return out;
  }, [events]);

  // ONE blink timer for the entire feed. The design prototype owns one per row, which is
  // fine for a demo of 26 lines and is a thousand timers on a real run.
  const [cursorOn, setCursorOn] = useState(true);
  useEffect(() => {
    if (!isActive) {
      setCursorOn(false);
      return;
    }
    setCursorOn(true);
    const id = setInterval(() => setCursorOn((v) => !v), CURSOR_BLINK_MS);
    return () => clearInterval(id);
  }, [isActive]);

  const latestSeq = events.length > 0 ? events[events.length - 1].seq : null;

  // ── Follow the newest row, but never yank the viewport away from a reader. ──────────
  const endRef = useRef<HTMLDivElement | null>(null);
  const atBottomRef = useRef(true);
  useEffect(() => {
    const el = endRef.current;
    if (!el || typeof IntersectionObserver === "undefined") return;
    // The scrolling container belongs to the PAGE, not to this component, so "is the user
    // at the bottom" is answered by whether the end sentinel is on screen — which needs no
    // reference to the container at all.
    const obs = new IntersectionObserver((entries) => {
      atBottomRef.current = entries.some((e) => e.isIntersecting);
    });
    obs.observe(el);
    return () => obs.disconnect();
  }, []);
  useEffect(() => {
    if (!isActive) return;
    if (!atBottomRef.current) return;
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [events.length, isActive]);

  return (
    <div>
      {groups.map((group, i) => {
        const isLast = i === groups.length - 1;
        return (
          <FeedGroup
            key={group.key}
            events={group.events}
            // A group is COMPLETE once a later group exists after it — the engine has moved
            // on, so nothing further will be appended to this one.
            isComplete={!isLast}
            // Only the last group can ever hold the latest row, so only it sees a changing
            // cursor prop. Every earlier group receives a constant null and its memo holds
            // through the blink.
            cursorSeq={isLast && cursorOn ? latestSeq : null}
            canDrill={canDrill}
            onDrill={stableDrill}
            drilldownAuditId={drilldownAuditId ?? null}
            renderAfterRow={stableAfterRow}
          />
        );
      })}
      <div ref={endRef} />
    </div>
  );
}

/**
 * One phase block: its divider, its rows, its summary — and, once complete, a collapse
 * toggle that previews the last two rows exactly as the design does.
 */
const FeedGroup = React.memo(function FeedGroup({
  events,
  isComplete,
  cursorSeq,
  canDrill,
  onDrill,
  drilldownAuditId,
  renderAfterRow,
}: {
  events: RunEvent[];
  isComplete: boolean;
  cursorSeq: number | null;
  canDrill: boolean;
  onDrill: (auditId: string) => void;
  drilldownAuditId: string | null;
  renderAfterRow: (event: RunEvent) => React.ReactNode;
}) {
  const { t } = useTranslation("intake");
  const [collapsed, setCollapsed] = useState(isComplete);
  // Auto-collapse at the moment the phase completes, per the design. A phase the operator
  // has deliberately reopened stays open until it completes again, which it never does.
  useEffect(() => {
    if (isComplete) setCollapsed(true);
  }, [isComplete]);

  const divider = events.find((e) => e.kind === "divider");
  const summary = events.find((e) => e.kind === "summary");
  const body = events.filter((e) => e.kind !== "divider" && e.kind !== "summary");
  const shown = collapsed ? body.slice(-COLLAPSED_PREVIEW_ROWS) : body;

  return (
    <div>
      {divider && (
        <FeedRow
          event={divider}
          cursorSeq={cursorSeq}
          canDrill={canDrill}
          onDrill={onDrill}
          drilldownAuditId={drilldownAuditId}
        />
      )}

      {isComplete && (
        <button
          type="button"
          onClick={() => setCollapsed((c) => !c)}
          className="flex items-center gap-1.5 pb-1.5 font-mono text-[11.5px] text-ink/50 hover:text-ink"
        >
          <ChevronDown
            className={`h-3 w-3 transition-transform ${collapsed ? "" : "rotate-180"}`}
          />
          {collapsed
            ? t("research.runPage.feed.showMore")
            : t("research.feed.showLess")}
        </button>
      )}

      {shown.map((ev) => (
        <React.Fragment key={ev.seq}>
          <FeedRow
            event={ev}
            cursorSeq={cursorSeq}
            canDrill={canDrill}
            onDrill={onDrill}
            drilldownAuditId={drilldownAuditId}
          />
          {/* The 15.3-09 seam: an injected panel hangs BENEATH a row without this
              component importing it, and stays outside the row's memo boundary. */}
          {renderAfterRow(ev)}
        </React.Fragment>
      ))}

      {summary && (
        <FeedRow
          event={summary}
          cursorSeq={cursorSeq}
          canDrill={canDrill}
          onDrill={onDrill}
          drilldownAuditId={drilldownAuditId}
        />
      )}
    </div>
  );
});

/** Kinds rendered one indent level in, as children of the dispatch header above them. */
const INDENTED_KINDS = new Set(["agent_run", "agent_done", "agent_retry", "agent_fail"]);

/**
 * ONE feed row. Memoised on its props, every one of which is a primitive or a stable
 * reference: `event` objects are parsed once and only ever appended (never rebuilt), and
 * `onDrill` / `renderAfterRow` are the stable wrappers created in RunFeed. `cursorSeq` is the
 * only prop that changes on a blink, and only for the group holding the latest row.
 */
const FeedRow = React.memo(function FeedRow({
  event,
  cursorSeq,
  canDrill,
  onDrill,
  drilldownAuditId,
}: {
  event: RunEvent;
  cursorSeq: number | null;
  canDrill: boolean;
  onDrill: (auditId: string) => void;
  drilldownAuditId: string | null;
}) {
  const { t } = useTranslation("intake");
  const showCursor = cursorSeq != null && cursorSeq === event.seq;
  const meta = event.meta ?? null;

  // ── divider: the uppercase phase label with a hairline rule beside it. ──────────────
  // The text is the human LABEL, carried by the event itself (15.3-03) — this component
  // looks up no stage vocabulary and needs none.
  if (event.kind === "divider") {
    return (
      <div className="flex items-center gap-3 pb-2 pt-5">
        <span className="whitespace-nowrap font-mono text-[10.5px] uppercase tracking-[0.13em] text-ink/50">
          {event.text}
        </span>
        <div className="h-px flex-1 bg-ink/10" />
      </div>
    );
  }

  // ── summary: "Worked for X · N actions · N items · $Y", each part only if carried. ──
  if (event.kind === "summary") {
    const parts: string[] = [];
    const worked = metaStr(meta, "worked");
    const actions = metaNum(meta, "actions");
    const items = metaNum(meta, "items");
    const cost = metaStr(meta, "cost");
    if (worked) parts.push(t("research.runPage.feed.workedFor", { duration: worked }));
    if (actions != null) parts.push(t("research.runPage.feed.actionsCount", { count: actions }));
    if (items != null && items > 0) {
      parts.push(t("research.runPage.feed.itemsCount", { count: items }));
    }
    if (cost) {
      const formatted = fmtCost(cost, "");
      if (formatted) parts.push(formatted);
    }
    if (parts.length === 0 && !event.text) return null;
    return (
      <div className="flex flex-wrap gap-x-4 pb-2.5 pl-[26px] pt-1.5 font-mono text-[11.5px] text-ink/50">
        {parts.map((p) => (
          <span key={p}>{p}</span>
        ))}
        {event.text && <span>{event.text}</span>}
      </div>
    );
  }

  // ── dispatch: the bold header the agent rows hang under. ────────────────────────────
  if (event.kind === "dispatch") {
    return (
      <div className="flex items-center gap-2 py-1.5">
        <Zap className="h-3.5 w-3.5 shrink-0 text-ink" />
        <span className="font-mono text-[13px] font-semibold text-ink">{event.text}</span>
        <BlinkCursor on={showCursor} />
      </div>
    );
  }

  // ── everything else: icon + text, indented one level for the agent kinds. ───────────
  const indented = INDENTED_KINDS.has(event.kind);
  const isLive = event.kind === "agent_run" && metaBool(meta, "is_live");
  const auditId = metaStr(meta, "audit_id");
  const sub = metaStr(meta, "sub");
  const drillOpen = !!auditId && drilldownAuditId === auditId;

  return (
    <div className={`flex items-start gap-2 ${indented ? "py-0.5 pl-[22px]" : "py-1"}`}>
      <span className="mt-0.5 flex w-3.5 shrink-0 justify-center">
        <KindIcon kind={event.kind} />
      </span>
      <div className="min-w-0 flex-1">
        <div className={`font-mono text-[13px] leading-relaxed ${kindTextClass(event.kind)}`}>
          {event.text}
          {isLive && (
            <span
              className="ml-1.5 border px-1.5 py-px align-middle text-[10px] uppercase tracking-[0.08em]"
              style={{ color: FLUO_PINK, borderColor: FLUO_PINK }}
            >
              {t("research.runPage.feed.liveBadge")}
            </span>
          )}
          <BlinkCursor on={showCursor} />
        </div>
        {sub && <div className="mt-px font-mono text-[11px] text-ink/50">{sub}</div>}
        {canDrill && auditId && (
          <button
            type="button"
            onClick={() => onDrill(auditId)}
            className="mt-1 inline-flex items-center gap-1 text-[11px] uppercase tracking-wider text-ink/50 hover:text-ink"
          >
            <FileSearch className="h-3 w-3" />
            {drillOpen ? t("research.feed.hideAudit") : t("research.feed.viewAudit")}
          </button>
        )}
      </div>
    </div>
  );
});

/** The block cursor on the latest line. Rendered always, hidden by opacity, so it cannot
 *  reflow the row it sits on as it blinks. */
function BlinkCursor({ on }: { on: boolean }) {
  return (
    <span
      aria-hidden="true"
      className={`ml-0.5 font-mono text-[13px] transition-opacity ${on ? "opacity-100" : "opacity-0"}`}
      style={{ color: FLUO_PINK }}
    >
      ▋
    </span>
  );
}

/**
 * Icon per kind — a LOOKUP WITH A DEFAULT, which is the point. An unknown kind from a newer
 * engine build falls through to no icon and still renders its text as a plain line.
 */
function KindIcon({ kind }: { kind: string }) {
  switch (kind) {
    case "agent_run":
      return <Loader2 className="h-3.5 w-3.5 animate-spin" style={{ color: FLUO_PINK }} />;
    case "agent_done":
      return <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" />;
    case "agent_retry":
      return <RotateCw className="h-3.5 w-3.5 text-amber-600" />;
    case "agent_fail":
      return <XCircle className="h-3.5 w-3.5 text-red-600" />;
    case "thinking":
      return <Brain className="h-3.5 w-3.5 text-ink/40" />;
    case "tool":
      return <Wrench className="h-3.5 w-3.5 text-ink/40" />;
    case "search":
      return <Search className="h-3.5 w-3.5 text-ink/40" />;
    case "plan":
      return <GitBranch className="h-3.5 w-3.5 text-ink/40" />;
    case "streams":
      return <Layers className="h-3.5 w-3.5 text-ink/40" />;
    default:
      return null;
  }
}

/** Text colour per kind — again defaulting rather than falling through to nothing. */
function kindTextClass(kind: string): string {
  switch (kind) {
    case "agent_fail":
      return "text-red-700";
    case "agent_retry":
      return "text-amber-700";
    case "agent_run":
      return "text-ink";
    default:
      return "text-ink/70";
  }
}

// ── meta readers. `meta` is engine-authored JSON, so every read is defensive. ──────────

function metaStr(meta: Record<string, unknown> | null, key: string): string | null {
  const v = meta?.[key];
  if (typeof v === "string") return v.length > 0 ? v : null;
  if (typeof v === "number") return String(v);
  return null;
}

function metaNum(meta: Record<string, unknown> | null, key: string): number | null {
  const v = meta?.[key];
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string" && v.trim() !== "") {
    const n = Number(v);
    if (Number.isFinite(n)) return n;
  }
  return null;
}

function metaBool(meta: Record<string, unknown> | null, key: string): boolean {
  return meta?.[key] === true;
}
