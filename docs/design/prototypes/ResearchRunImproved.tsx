// docs/design/prototypes/ResearchRunImproved.tsx
//
// OPERATOR-SUPPLIED DESIGN PROTOTYPE — 2026-07-27. Reference only.
//
// This file is DELIBERATELY OUTSIDE frontend/src and is NOT compiled, NOT linted
// and NOT shipped. It is the operator's design for the dedicated research-run
// page, produced from docs/design/research-run-page-mockup.html and handed back
// for implementation in phase 15.3. Keep it verbatim: it is the design of record
// and the thing the implementation is judged against.
//
// It is a SELF-CONTAINED DEMO, not a component. `TL` below is a hardcoded
// timeline replayed with setTimeout; there is no data layer. Phase 15.3's job is
// to keep the interaction design and replace the mock with the real run stream.
//
// ─────────────────────────────────────────────────────────────────────────────
// KNOWN GAPS vs the production system — established 2026-07-27, do not re-derive:
//
// 1. ~40% OF THE LINE KINDS HAVE NO DATA SOURCE TODAY. `thinking`, `tool`,
//    `search`, `plan`, `streams` and `dispatch` are not emitted by the engine.
//    `stage_detail` provides only {name, status, task_prompt, cost_usd, facts,
//    retry, audit_id}, which covers agent_run/done/retry/fail + summary +
//    divider. OPERATOR DECISION 2026-07-27: build the engine events FIRST, then
//    the UI — so this gap is closed by phase 15.3's own backend plans rather
//    than by thinning the design.
//
// 2. FIVE OF EIGHT RUN STATUSES ARE UNHANDLED. The prototype models
//    idle/running/done. Production has queued, running, completed,
//    completed_degraded, failed, cancelled, parked, needs_input.
//
// 3. FOUR LOAD-BEARING AFFORDANCES ARE ABSENT and must be carried over:
//    - audit body drill-down          (EU AI Act Art. 12 record)
//    - chain_status handling          (a broken chain MUST lock the download;
//                                      the "Download output" button here is
//                                      unconditional)
//    - resume on `parked`             (a retry discards paid checkpoints)
//    - Stop confirmation dialog       (cost so far is not refunded)
//
// 4. THE TIMER REGRESSES A BUG FIXED ON 2026-07-27. `setSecs(s => s+1)` from
//    useState(0) counts from MOUNT, so closing and reopening the page restarts
//    at 00:00 — the exact behaviour the operator asked to eliminate. The
//    implementation must use useElapsed(run.started_at); plan 15.2-24 landed
//    `started_at` across the seam specifically to make that possible.
//
// 5. EVERY STRING IS HARDCODED ENGLISH. frontend/scripts/i18n-audit.mjs is a
//    HARD CI gate — en/nl/fr all required.
//
// 6. 100% INLINE STYLES where the app is Tailwind + shadcn. Convert; do not
//    modify components/ui/** (CLAUDE.md).
//
// 7. ROUTE IT FLAT — /admin/pulse/runs/:runId. Nesting under
//    admin.pulse.intakes.$id.tsx would make that route a parent needing an
//    <Outlet/>, which is the phase-18 trap.
//
// WHAT TO PRESERVE (this is why the design is better than what ships today):
//    - the streaming feed with a blinking cursor on the latest line
//    - explicit "Dispatching N agents" headers with indented agent children
//    - completed phases auto-collapsing to a 2-line preview
//    - per-phase "Worked for X · N actions · N items · $Y" summaries
//    - the live badge on the currently-streaming agent
//    - one full-height page, one scroll, no nested scroll areas
// ─────────────────────────────────────────────────────────────────────────────

import { useState, useEffect, useRef, useCallback } from "react";

// ── Tokens ────────────────────────────────────────────────────────────────────
const T = {
  bg:        "#EDECE5",
  surface:   "#E4E3DC",
  text:      "#111",
  sub:       "#555",
  dim:       "#999",
  border:    "rgba(0,0,0,.1)",
  pink:      "#FF2D87",
  olive:     "#5a6e00",
  amber:     "#b45309",
  red:       "#c41f1f",
  mono:      '"IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace',
  sans:      '"IBM Plex Sans", ui-sans-serif, system-ui, sans-serif',
  serif:     '"IBM Plex Serif", Georgia, serif',
};

// ── Icons ─────────────────────────────────────────────────────────────────────
const sv = (size: number, color: string, children: React.ReactNode) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
    stroke={color} strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round"
    style={{ display:"block", flexShrink:0 }}>{children}</svg>
);
const Spin = ({ size=13, color=T.pink }: {size?:number;color?:string}) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
    stroke={color} strokeWidth={1.75} strokeLinecap="round"
    style={{ display:"block", flexShrink:0, animation:"ag-spin .8s linear infinite", transformOrigin:"50% 50%" }}>
    <path d="M21 12a9 9 0 1 1-6.219-8.56"/>
  </svg>
);
const Check  = ({s=13,c=T.olive}:{s?:number;c?:string}) => sv(s,c,<><polyline points="20 6 9 17 4 12"/></>);
const X      = ({s=13,c=T.red} :{s?:number;c?:string}) => sv(s,c,<><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></>);
const Retry  = ({s=13,c=T.amber}:{s?:number;c?:string}) => sv(s,c,<><path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/></>);
const Brain  = ({s=13,c=T.dim} :{s?:number;c?:string}) => sv(s,c,<><path d="M9.5 2A2.5 2.5 0 0 1 12 4.5v15a2.5 2.5 0 0 1-4.96-.44 2.5 2.5 0 0 1-2.96-3.08 3 3 0 0 1-.34-5.58 2.5 2.5 0 0 1 1.32-4.24 2.5 2.5 0 0 1 1.98-3A2.5 2.5 0 0 1 9.5 2Z"/><path d="M14.5 2A2.5 2.5 0 0 0 12 4.5v15a2.5 2.5 0 0 0 4.96-.44 2.5 2.5 0 0 0 2.96-3.08 3 3 0 0 0 .34-5.58 2.5 2.5 0 0 0-1.32-4.24 2.5 2.5 0 0 0-1.98-3A2.5 2.5 0 0 0 14.5 2Z"/></>);
const Wrench = ({s=13,c=T.dim} :{s?:number;c?:string}) => sv(s,c,<><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></>);
const Search = ({s=13,c=T.dim} :{s?:number;c?:string}) => sv(s,c,<><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></>);
const Branch = ({s=13,c=T.dim} :{s?:number;c?:string}) => sv(s,c,<><line x1="6" y1="3" x2="6" y2="15"/><circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M18 9a9 9 0 0 1-9 9"/></>);
const Layers = ({s=13,c=T.dim} :{s?:number;c?:string}) => sv(s,c,<><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></>);
const Play   = ({s=11}:{s?:number}) => sv(s,"currentColor",<polygon points="5 3 19 12 5 21 5 3"/>);
const Stop   = ({s=11}:{s?:number}) => sv(s,"currentColor",<rect x="3" y="3" width="18" height="18" rx="1"/>);
const Dl     = ({s=11}:{s?:number}) => sv(s,"currentColor",<><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></>);
const Chev   = ({down=true,s=11,c=T.dim}:{down?:boolean;s?:number;c?:string}) => (
  <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth={2}
    strokeLinecap="round" strokeLinejoin="round"
    style={{ display:"block", flexShrink:0, transform:down?"none":"rotate(180deg)", transition:"transform .15s" }}>
    <polyline points="6 9 12 15 18 9"/>
  </svg>
);

// ── Feed line model ───────────────────────────────────────────────────────────
type LineKind =
  | "thinking"    // brain — agent reasoning aloud
  | "tool"        // wrench — skill / tool loaded
  | "search"      // magnifier — web fetch / search
  | "plan"        // branch — routing / planning
  | "streams"     // layers — stream config
  | "dispatch"    // bold zap line — "Dispatching N agents"
  | "agent_run"   // indented spinner — live agent
  | "agent_done"  // indented check — agent complete
  | "agent_retry" // indented retry — agent retrying
  | "agent_fail"  // indented x — agent failed
  | "summary"     // "Worked for X" stats line
  | "divider";    // subtle phase label

interface Line {
  id:       string;
  kind:     LineKind;
  text:     string;
  sub?:     string;
  isLive?:  boolean;
  // summary
  worked?:  string;
  actions?: number;
  items?:   number;
  cost?:    number;
  // grouping for collapse
  group?:   string;
}

// ── Timeline ──────────────────────────────────────────────────────────────────
interface TL { ms: number; line: Line; addCost?: number; setPhase?: string }

const TL: TL[] = [
  // Intake
  { ms:  200, line: { id:"i0", kind:"divider",   text:"Adaptive intake",                                         group:"g1" } },
  { ms:  450, line: { id:"i1", kind:"thinking",  text:"Analyzing brief — Moetest BV, market entry for speciality coffee",      group:"g1" } },
  { ms:  950, line: { id:"i2", kind:"tool",      text:"Loaded parse_brief — split questions from context",        group:"g1" } },
  { ms: 1500, line: { id:"i3", kind:"thinking",  text:"Extracting questions and filtering context lines",         group:"g1" } },
  { ms: 2100, line: { id:"i4", kind:"summary",   text:"", worked:"2s", actions:3, items:11, cost:0,              group:"g1" } },

  // Workshop
  { ms: 2500, line: { id:"w0", kind:"divider",   text:"Question workshop",                                       group:"g2" }, setPhase:"Question workshop" },
  { ms: 2750, line: { id:"w1", kind:"dispatch",  text:"Dispatching orientation agent",                           group:"g2" } },
  { ms: 3000, line: { id:"w2", kind:"agent_run", text:"Checking web sources for brief conflicts",                group:"g2" } },
  { ms: 5600, line: { id:"w3", kind:"agent_done",text:"3 conflicts found — EUDR date · volume trend · direct-trade def.", group:"g2" }, addCost:0.38 },
  { ms: 5900, line: { id:"w4", kind:"dispatch",  text:"Dispatching tournament — 62 angle candidates to rank",   group:"g2" } },
  { ms: 6150, line: { id:"w5", kind:"agent_run", text:"Running 4 ranking rounds",                               group:"g2" } },
  { ms:10500, line: { id:"w6", kind:"agent_done",text:"15 winners selected · 62 candidates → 4 rounds → 15",    group:"g2" }, addCost:1.49 },
  { ms:10800, line: { id:"w7", kind:"summary",   text:"", worked:"3m 12s", actions:47, items:15, cost:1.87,     group:"g2" } },

  // Research division
  { ms:11100, line: { id:"r0", kind:"divider",   text:"Research division",                                       group:"g3" }, setPhase:"Research division" },
  { ms:11350, line: { id:"r1", kind:"plan",      text:"Planning angle routing — 24 angles across 4 streams",    group:"g3" } },
  { ms:11700, line: { id:"r2", kind:"tool",      text:"Loaded research_division — angle assignment engine",     group:"g3" } },
  { ms:12400, line: { id:"r3", kind:"streams",   text:"Configured streams — OpenAI · Gemini · Anthropic · Own researcher", group:"g3" } },
  { ms:12800, line: { id:"r4", kind:"summary",   text:"", worked:"8s", actions:6, items:24, cost:0,             group:"g3" } },

  // Deep + own (parallel)
  { ms:13100, line: { id:"d0", kind:"divider",   text:"Deep research  ·  Own research",                         group:"g4" }, setPhase:"Deep research" },
  { ms:13350, line: { id:"d1", kind:"dispatch",  text:"Dispatching 3 agents — Angles 01, 02, 03",               group:"g4" } },
  { ms:13600, line: { id:"d2", kind:"agent_run", text:"Angle 01 — EU speciality coffee import volumes 2024–2026 · gpt-5.6-sol",      group:"g4" } },
  { ms:13800, line: { id:"d3", kind:"agent_run", text:"Angle 02 — Belgian roaster margin structure · gemini-2.5-pro",                group:"g4" } },
  { ms:14050, line: { id:"d4", kind:"agent_run", text:"Angle 03 — EUDR enforcement timeline for coffee importers · gpt-5.6-sol", isLive:true, group:"g4" } },
  { ms:14450, line: { id:"d5", kind:"dispatch",  text:"Dispatching 2 own queries",                              group:"g4" } },
  { ms:14650, line: { id:"d6", kind:"search",    text:"Searching — Belgian speciality roasters, direct-import segment",             group:"g4" } },
  { ms:14850, line: { id:"d7", kind:"search",    text:"Searching — Antwerp green-coffee terminal handling fees",                    group:"g4" } },
  { ms:17200, line: { id:"d8", kind:"agent_done",text:"Angle 02 done — 14 facts · Wholesale 38–44% · DTC 62–68%", group:"g4" }, addCost:1.95 },
  { ms:18600, line: { id:"d9", kind:"dispatch",  text:"Dispatching Angle 04 — Dutch vs Belgian retail benchmarks", group:"g4" } },
  { ms:18850, line: { id:"d10",kind:"agent_run", text:"Angle 04 — Dutch vs Belgian retail price benchmarks · gemini-2.5-pro",       group:"g4" } },
  { ms:19200, line: { id:"d11",kind:"agent_done",text:"Own query 01 done — 7 facts from 5 pages · 2 skipped (paywall)",             group:"g4" }, addCost:0.12 },
  { ms:19800, line: { id:"d12",kind:"agent_retry",text:"Angle 04 retrying — 429 RESOURCE_EXHAUSTED · retry 2/3 · backoff 8s",      group:"g4" } },
  { ms:20250, line: { id:"d13",kind:"dispatch",  text:"Dispatching Angle 06 — competitor landscape, direct-trade importers",       group:"g4" } },
  { ms:20500, line: { id:"d14",kind:"search",    text:"Fetching beliancoffee-directtrade.be",                    group:"g4" } },
  { ms:20850, line: { id:"d15",kind:"agent_fail",text:"Angle 06 failed — 403 · 0 facts · tool conversation poisoned",              group:"g4" }, addCost:0.02 },
  { ms:21150, line: { id:"d16",kind:"agent_done",text:"Angle 01 done — 21 facts · Antwerp 31% · Rotterdam 44% EU entry",           group:"g4" }, addCost:2.40 },
  { ms:21500, line: { id:"d17",kind:"dispatch",  text:"Dispatching 3 agents — Angles 05, 07 (queued), 08 (queued)",                group:"g4" } },
  { ms:21750, line: { id:"d18",kind:"agent_run", text:"Angle 05 — green-coffee sourcing models and importer margin · claude-opus-5",group:"g4" } },
  { ms:22150, line: { id:"d19",kind:"agent_done",text:"Own query 02 done — 9 facts · 2 rejected (placeholder source)",             group:"g4" }, addCost:0.19 },
  { ms:22750, line: { id:"d20",kind:"search",    text:"Searching — ICO 2025 annual review import statistics",                      group:"g4" } },
  { ms:23450, line: { id:"d21",kind:"agent_done",text:"Angle 04 done — retry succeeded · 9 facts · Dutch +12% YoY vs Belgian flat",group:"g4" }, addCost:0.31 },
  { ms:24100, line: { id:"d22",kind:"agent_done",text:"Angle 03 done — 18 facts · EUDR large operators: 30 Dec 2025",              group:"g4" }, addCost:2.80 },
  { ms:24650, line: { id:"d23",kind:"agent_done",text:"Own query 03 done — 6 facts · EU28 speciality imports +3.1% YoY",          group:"g4" }, addCost:0.09 },
  { ms:25150, line: { id:"d24",kind:"agent_done",text:"Angle 05 done — 11 facts · Direct-trade margin premium 8–14% over spot",   group:"g4" }, addCost:1.20 },
  { ms:25650, line: { id:"d25",kind:"summary",   text:"", worked:"12m 24s", actions:87, items:95, cost:9.08,                       group:"g4" } },
];

// ── Icon map ──────────────────────────────────────────────────────────────────
function LineIcon({ kind, isLive }: { kind: LineKind; isLive?: boolean }) {
  if (kind === "agent_run")   return <Spin size={13}/>;
  if (kind === "agent_done")  return <Check s={13}/>;
  if (kind === "agent_retry") return <Retry s={13}/>;
  if (kind === "agent_fail")  return <X s={13}/>;
  if (kind === "thinking")    return <Brain s={13}/>;
  if (kind === "tool")        return <Wrench s={13}/>;
  if (kind === "search")      return <Search s={13}/>;
  if (kind === "plan")        return <Branch s={13}/>;
  if (kind === "streams")     return <Layers s={13}/>;
  return null;
}

// ── Single feed line ──────────────────────────────────────────────────────────
function FeedLine({ line, isLatest, fresh }: { line: Line; isLatest: boolean; fresh: boolean }) {
  const [showCursor, setShowCursor] = useState(true);
  useEffect(() => {
    if (!isLatest) return;
    const id = setInterval(() => setShowCursor(v => !v), 530);
    return () => clearInterval(id);
  }, [isLatest]);

  // Divider
  if (line.kind === "divider") {
    return (
      <div style={{ display:"flex", alignItems:"center", gap:12, padding:"20px 0 8px",
        animation: fresh ? "ag-in .2s ease" : "none" }}>
        <span style={{ fontFamily:T.mono, fontSize:10.5, textTransform:"uppercase",
          letterSpacing:".13em", color:T.dim, whiteSpace:"nowrap" }}>{line.text}</span>
        <div style={{ flex:1, height:1, background:T.border }}/>
      </div>
    );
  }

  // Summary / stats
  if (line.kind === "summary") {
    return (
      <div style={{ padding:"6px 0 10px 26px", fontFamily:T.mono, fontSize:11.5,
        color:T.dim, display:"flex", flexWrap:"wrap", gap:"0 16px",
        animation: fresh ? "ag-in .2s ease" : "none" }}>
        {line.worked  && <span>Worked for {line.worked}</span>}
        {line.actions != null && <span>{line.actions} actions</span>}
        {line.items   != null && line.items > 0 && <span>{line.items} items</span>}
        {line.cost    != null && <span>${line.cost.toFixed(2)}</span>}
      </div>
    );
  }

  // Dispatch header line
  if (line.kind === "dispatch") {
    return (
      <div style={{ padding:"6px 0", display:"flex", alignItems:"center", gap:8,
        animation: fresh ? "ag-in .2s ease" : "none" }}>
        <svg width={13} height={13} viewBox="0 0 24 24" fill="none" stroke={T.text}
          strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" style={{ display:"block", flexShrink:0 }}>
          <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
        </svg>
        <span style={{ fontFamily:T.mono, fontSize:13, color:T.text, fontWeight:600 }}>{line.text}</span>
        {isLatest && (
          <span style={{ fontFamily:T.mono, fontSize:13, color:T.pink,
            opacity: showCursor ? 1 : 0, transition:"opacity .1s" }}>▋</span>
        )}
      </div>
    );
  }

  // Indented agent lines (run / done / retry / fail)
  const isAgent = ["agent_run","agent_done","agent_retry","agent_fail"].includes(line.kind);
  const textColor =
    line.kind === "agent_fail"  ? T.red  :
    line.kind === "agent_retry" ? T.amber :
    line.kind === "agent_done"  ? T.sub  :
    T.sub;

  return (
    <div style={{
      display:"flex", alignItems:"flex-start", gap:8,
      padding: isAgent ? "3px 0 3px 22px" : "4px 0",
      animation: fresh ? "ag-in .2s ease" : "none",
    }}>
      <span style={{ marginTop:2, width:14, display:"flex", justifyContent:"center", flexShrink:0 }}>
        <LineIcon kind={line.kind} isLive={line.isLive}/>
      </span>
      <div style={{ flex:1, minWidth:0 }}>
        <div style={{ fontFamily:T.mono, fontSize:13, color:textColor, lineHeight:1.5 }}>
          {line.text}
          {line.isLive && line.kind === "agent_run" && (
            <span style={{ marginLeft:7, fontSize:10, color:T.pink,
              border:`1px solid ${T.pink}`, padding:"1px 5px",
              textTransform:"uppercase", letterSpacing:".08em", verticalAlign:"middle" }}>live</span>
          )}
          {isLatest && (
            <span style={{ fontFamily:T.mono, fontSize:13, color:T.pink,
              opacity: showCursor ? 1 : 0, transition:"opacity .1s", marginLeft:2 }}>▋</span>
          )}
        </div>
        {line.sub && (
          <div style={{ fontFamily:T.mono, fontSize:11, color:T.dim, marginTop:1 }}>{line.sub}</div>
        )}
      </div>
    </div>
  );
}

// ── Collapsible group ─────────────────────────────────────────────────────────
function FeedGroup({ lines, isDone, freshIds, latestId }:
  { lines: Line[]; isDone: boolean; freshIds: Set<string>; latestId: string }) {
  const [collapsed, setCollapsed] = useState(false);

  // Auto-collapse when group completes
  useEffect(() => { if (isDone) setCollapsed(true); }, [isDone]);

  const nonSummary = lines.filter(l => l.kind !== "summary" && l.kind !== "divider");
  const summary    = lines.find(l => l.kind === "summary");
  const divider    = lines.find(l => l.kind === "divider");

  return (
    <div>
      {divider && <FeedLine line={divider} isLatest={latestId === divider.id} fresh={freshIds.has(divider.id)}/>}

      {/* Collapse toggle — only after group is done */}
      {isDone && (
        <button onClick={() => setCollapsed(c => !c)} style={{
          display:"flex", alignItems:"center", gap:6, padding:"2px 0 6px 0",
          background:"none", border:"none", cursor:"pointer",
          fontFamily:T.mono, fontSize:11.5, color:T.dim,
        }}>
          <Chev down={collapsed} s={11}/>
          {collapsed ? "Show more" : "Show less"}
        </button>
      )}

      {!collapsed && nonSummary.map(l => (
        <FeedLine key={l.id} line={l} isLatest={latestId === l.id} fresh={freshIds.has(l.id)}/>
      ))}

      {/* When collapsed, preview last 2 non-summary items */}
      {collapsed && nonSummary.slice(-2).map(l => (
        <FeedLine key={l.id} line={l} isLatest={false} fresh={false}/>
      ))}

      {summary && <FeedLine line={summary} isLatest={latestId === summary.id} fresh={freshIds.has(summary.id)}/>}
    </div>
  );
}

// ── Clock ─────────────────────────────────────────────────────────────────────
function fmt(s: number) {
  return `${String(Math.floor(s/60)).padStart(2,"0")}:${String(s%60).padStart(2,"0")}`;
}

// ── Main ──────────────────────────────────────────────────────────────────────
export function ResearchRunImproved() {
  const [lines,    setLines]    = useState<Line[]>([]);
  const [freshIds, setFreshIds] = useState<Set<string>>(new Set());
  const [runState, setRunState] = useState<"idle"|"running"|"done">("idle");
  const [secs,     setSecs]     = useState(0);
  const [cost,     setCost]     = useState(0);
  const [phase,    setPhase]    = useState("Adaptive intake");

  const timers  = useRef<ReturnType<typeof setTimeout>[]>([]);
  const clock   = useRef<ReturnType<typeof setInterval>|null>(null);
  const feedRef = useRef<HTMLDivElement>(null);

  const clearAll = useCallback(() => {
    timers.current.forEach(clearTimeout); timers.current = [];
    if (clock.current) { clearInterval(clock.current); clock.current = null; }
  }, []);
  useEffect(() => () => clearAll(), [clearAll]);

  // Auto-scroll
  useEffect(() => {
    if (feedRef.current) feedRef.current.scrollTop = feedRef.current.scrollHeight;
  }, [lines.length]);

  const startRun = useCallback(() => {
    clearAll();
    setLines([]); setFreshIds(new Set());
    setRunState("running"); setSecs(0); setCost(0); setPhase("Adaptive intake");

    clock.current = setInterval(() => setSecs(s => s+1), 1000);

    TL.forEach(entry => {
      const t = setTimeout(() => {
        setLines(prev => [...prev, entry.line]);
        setFreshIds(prev => new Set([...prev, entry.line.id]));
        if (entry.addCost) setCost(c => c + entry.addCost!);
        if (entry.setPhase) setPhase(entry.setPhase);
        // remove "fresh" after animation plays
        setTimeout(() => setFreshIds(prev => { const n=new Set(prev); n.delete(entry.line.id); return n; }), 400);
      }, entry.ms);
      timers.current.push(t);
    });

    const maxMs = Math.max(...TL.map(e => e.ms));
    timers.current.push(setTimeout(() => {
      setRunState("done");
      if (clock.current) { clearInterval(clock.current); clock.current = null; }
    }, maxMs + 600));
  }, [clearAll]);

  // Group lines by group key
  const groups = lines.reduce<{ key: string; lines: Line[] }[]>((acc, l) => {
    const k = l.group ?? "__";
    const last = acc[acc.length-1];
    if (last?.key === k) last.lines.push(l);
    else acc.push({ key: k, lines: [l] });
    return acc;
  }, []);

  const latestId = lines[lines.length-1]?.id ?? "";

  return (
    <div style={{ background:T.bg, color:T.text, fontFamily:T.sans, fontSize:14,
      height:"100vh", display:"flex", flexDirection:"column", overflow:"hidden" }}>
      <style>{`
        @keyframes ag-spin { to { transform:rotate(360deg) } }
        @keyframes ag-in { from { opacity:0; transform:translateY(-4px) } to { opacity:1; transform:translateY(0) } }
        button { transition: opacity .15s }
        button:hover { opacity:.7 }
      `}</style>

      {/* ── Header ── */}
      <header style={{ borderBottom:`1px solid ${T.border}`, padding:"14px 28px",
        display:"flex", alignItems:"flex-start", justifyContent:"space-between",
        gap:24, flexShrink:0, background:T.surface }}>
        <div>
          <div style={{ fontFamily:T.mono, fontSize:10.5, color:T.dim, letterSpacing:".1em",
            textTransform:"uppercase", marginBottom:4 }}>
            Pulse · Intakes · Moetest BV · Run
          </div>
          <h1 style={{ fontFamily:T.serif, fontSize:20, fontWeight:600, margin:0, lineHeight:1.2 }}>
            Moetest BV — market entry, speciality coffee
          </h1>
          <div style={{ fontFamily:T.mono, fontSize:11, color:T.dim, marginTop:5,
            display:"flex", gap:14, flexWrap:"wrap" }}>
            <span>run d6bb3aae</span><span>engine tribunal</span>
            <span>11 questions · 24 angles · 4 streams</span>
          </div>
        </div>

        <div style={{ display:"flex", alignItems:"center", gap:28, flexShrink:0 }}>
          {/* stats */}
          <div style={{ display:"flex", gap:20 }}>
            {[
              { label:"Elapsed", value:fmt(secs) },
              { label:"Cost",    value:`$${cost.toFixed(2)}` },
            ].map(({ label, value }) => (
              <div key={label} style={{ textAlign:"right" }}>
                <div style={{ fontFamily:T.mono, fontSize:10, textTransform:"uppercase",
                  letterSpacing:".1em", color:T.dim }}>{label}</div>
                <div style={{ fontFamily:T.mono, fontSize:20, fontVariantNumeric:"tabular-nums",
                  lineHeight:1.15, marginTop:2 }}>{value}</div>
              </div>
            ))}
          </div>

          {/* buttons */}
          <div style={{ display:"flex", flexDirection:"column", gap:6 }}>
            {runState !== "running" ? (
              <button onClick={startRun} style={{
                display:"inline-flex", alignItems:"center", gap:7,
                background:T.text, color:T.bg, border:"none",
                fontFamily:T.mono, fontSize:11, textTransform:"uppercase",
                letterSpacing:".1em", padding:"8px 14px", cursor:"pointer",
              }}>
                <Play/>{runState==="done" ? "Run again" : "Mock run"}
              </button>
            ) : (
              <button style={{
                display:"inline-flex", alignItems:"center", gap:7,
                border:`1px solid ${T.border}`, background:"transparent", color:T.sub,
                fontFamily:T.mono, fontSize:11, textTransform:"uppercase",
                letterSpacing:".1em", padding:"7px 13px", cursor:"pointer",
              }}>
                <Stop/>Stop run
              </button>
            )}
            {runState === "done" && (
              <button style={{
                display:"inline-flex", alignItems:"center", gap:7,
                border:`1px solid ${T.olive}`, background:"rgba(90,110,0,.07)", color:T.olive,
                fontFamily:T.mono, fontSize:11, textTransform:"uppercase",
                letterSpacing:".1em", padding:"7px 13px", cursor:"pointer",
              }}>
                <Dl/>Download output
              </button>
            )}
          </div>
        </div>
      </header>

      {/* ── Feed ── */}
      <div ref={feedRef} style={{ flex:1, overflowY:"auto", padding:"0 28px 32px" }}>

        {runState === "idle" && (
          <div style={{ display:"flex", flexDirection:"column", alignItems:"center",
            justifyContent:"center", height:"100%", gap:16 }}>
            <div style={{ fontFamily:T.mono, fontSize:11, textTransform:"uppercase",
              letterSpacing:".14em", color:T.dim }}>No active run</div>
            <button onClick={startRun} style={{
              display:"inline-flex", alignItems:"center", gap:9,
              background:T.text, color:T.bg, border:"none",
              fontFamily:T.mono, fontSize:12, textTransform:"uppercase",
              letterSpacing:".12em", padding:"11px 22px", cursor:"pointer",
            }}>
              <Play s={12}/>Start mock run
            </button>
            <div style={{ fontFamily:T.mono, fontSize:11, color:T.dim }}>
              Simulates all 8 phases — dispatch, parallel streams, retries, failures
            </div>
          </div>
        )}

        {(runState === "running" || runState === "done") && (
          <div style={{ maxWidth:720, margin:"0 auto" }}>
            {groups.map((g, i) => {
              const isDone = g.lines.some(l => l.kind === "summary");
              const isLast = i === groups.length - 1;
              return (
                <FeedGroup
                  key={g.key}
                  lines={g.lines}
                  isDone={isDone && !isLast}
                  freshIds={freshIds}
                  latestId={latestId}
                />
              );
            })}

            {runState === "done" && (
              <div style={{ marginTop:24, padding:"14px 18px",
                border:`1px solid rgba(90,110,0,.3)`,
                background:"rgba(90,110,0,.06)",
                display:"flex", alignItems:"center", gap:12 }}>
                <Check s={15} c={T.olive}/>
                <div>
                  <div style={{ fontFamily:T.mono, fontSize:12, color:T.olive,
                    textTransform:"uppercase", letterSpacing:".08em" }}>Run complete</div>
                  <div style={{ fontFamily:T.mono, fontSize:11, color:T.dim, marginTop:3 }}>
                    {fmt(secs)} elapsed · ${cost.toFixed(2)} · audit chain pending
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── Footer ticker ── */}
      {runState === "running" && (
        <div style={{ borderTop:`1px solid ${T.border}`, padding:"7px 28px",
          fontFamily:T.mono, fontSize:11, color:T.dim, flexShrink:0,
          display:"flex", alignItems:"center", gap:8 }}>
          <Spin size={11} color={T.pink}/>
          <span style={{ color:T.pink }}>{phase}</span>
          <span>·</span>
          <span>scroll to latest</span>
        </div>
      )}
    </div>
  );
}
