import { apiUrl } from "@/lib/firebase";
import { apiFetch, currentIdToken, type ApiResult } from "@/lib/api/client";

// frontend/src/lib/api/research.ts — the admin-side research trigger + live-progress
// transport (Phase 16, RUN-01/SEAM-03). It restores the same live push the skill-run
// stream gives the admin UI, but for a Tribunal research run, WITHOUT a new dependency
// and WITHOUT the browser's native event-source primitive (which cannot attach an
// `Authorization` header), which is why a raw `fetch` + `ReadableStream` is used.
//
// It clones `openSkillRunStream` (skillRunStream.ts) VERBATIM except for two things:
//   1. RESEARCH_TERMINAL = {"completed","completed_degraded","failed","cancelled","parked"}
//      — the VERBATIM Tribunal terminal set (D-05 boundary), NOT the skill-run
//      {succeeded,failed} vocabulary.
//   2. the URL is `/intakes/${intakeId}/research/stream`.
//
// NEVER FORK THE TRANSPORT (skillRuns.ts convention): `triggerResearch` reuses `apiFetch`
// (the token-attaching short request/response transport); the reader reuses only the exact
// TOKEN source (`currentIdToken`) and base-URL builder (`apiUrl`) that `apiFetch` uses —
// not `apiFetch` itself, which calls `resp.text()` and buffers the whole body (it cannot
// stream). The stream body is read incrementally via `resp.body.getReader()`.
//
// RETURN-NO-THROW (CLAUDE.md / client.ts): every failure path surfaces via `onFallback`,
// never a throw — so the caller's swap to a bounded poll is invisible and the UI never
// goes blind. `triggerResearch` returns `{success,error?}` and never throws.
//
// SECURITY (T-16-13): the id token is attached as a Bearer header only — never placed in
// the URL or logged. SSE payloads are untrusted input: each `data:` frame is `JSON.parse`d
// inside a try/catch and malformed frames are skipped.

/**
 * The mirrored `nestor.research_runs` row shape, matching the backend SSE frame
 * (`read_latest_research_run_dict`, Plan 03). `status` carries the Tribunal literals
 * VERBATIM ({queued,running,completed,failed,cancelled}) — never remapped to the
 * skill-run vocabulary (D-05 boundary).
 *
 * `stage_detail` is a JSONB map `{ stage_key: { items: [{ name, status }] } }`; the
 * progress panel renders the stage list DYNAMICALLY from this (no hardcoded count) so a
 * future Phase-15 added pass costs the UI nothing.
 */
export type ResearchStageItem = {
  name: string;
  status: string;
  // ── Phase-15 enriched D15 feed fields (Plan 15-01 fixture + Plan 15-03 schema).
  // ALL OPTIONAL so today's recorded rows and legacy flat {name,status} rows still
  // type-check (additive, D-07 — a row lacking these renders exactly as before).
  task_prompt?: string;
  cost_usd?: string;
  facts?: number;
  retry?: { attempt: number; max: number; wait_s: number };
  audit_id?: string;
};

/**
 * Per-stage summary card fields (D15 "Worked for X · N actions · M items read · $Y").
 * Optional so a stage group that carries only `items` still validates.
 */
export type ResearchStageSummary = {
  duration_s: number;
  actions: number;
  items_read?: number;
  cost_usd: string;
};

export type ResearchStageDetail = Record<
  string,
  { items?: ResearchStageItem[]; summary?: ResearchStageSummary } | undefined
>;

/**
 * The superadmin verification report (Plan 15-03 `build_verification_report`). Shaped from
 * the recorded run's persisted `verification_verdict` rows + `run.verification_summary`
 * funnel + true cost. These types MIRROR the backend `VerificationReport` /
 * `VerificationVerdictItem` pydantic schemas in tribunal `runs/schemas.py` (shaped by
 * `verification/report.py::_verdict_dto`) VERBATIM — the intake proxy returns the tribunal
 * JSON unchanged, so field names here MUST match the backend emit (`claim_id` /
 * `confidence` / `evidence_refs` / `reconciliation`, `true_cost.{cost_usd_total,
 * cost_pending}`, `unverified.{count,claims_with_verdict,total_claims}`). `extra="allow"`
 * server-side means additional rollup fields (`counts`) may ride through — the index
 * signature keeps the type permissive on those.
 */
export type VerificationVerdictItem = {
  claim_id?: string | null;
  verdict?: string | null;
  confidence?: string | null;
  evidence_refs?: unknown[] | null;
  reconciliation?: {
    disputed?: boolean;
    relation?: string | null;
    note?: string | null;
    canonical?: string | null;
    [k: string]: unknown;
  } | null;
  /**
   * G-07 (15.1): the caveat the skeptic MUST supply with a `superseded` verdict — what
   * changed, and from when. Persisted in `verification_verdict.superseded_note` and declared
   * explicitly on the backend `VerificationVerdictItem` (runs/schemas.py) because that model
   * has no `model_config`, so pydantic's default `extra="ignore"` would otherwise drop it.
   * A single-member superseded group emits NO `reconciliation.note`, so this is the only
   * carrier of the caveat for that (ordinary) shape — see VerdictItemRow's note fallback.
   */
  superseded_note?: string | null;
  [k: string]: unknown;
};

export type VerificationReport = {
  // CR-01: NOT `Record<string, number>`. The engine writes non-numeric siblings into this same
  // flat dict — `verification_degraded` is a bool and `degradation_reasons` is a list of the
  // operator-facing sentences (both set in the engine's pipeline alongside the real counts), and a
  // `park` dict can appear too. Typing it as all-numbers is what let a consumer coerce a populated
  // reasons list into the number 0. Consumers MUST narrow per entry and drop what is not a number.
  funnel: Record<string, unknown> | null;
  verdicts: {
    support?: VerificationVerdictItem[];
    refute?: VerificationVerdictItem[];
    insufficient?: VerificationVerdictItem[];
    /**
     * G-06 (15.1): the fourth VERDICT CLASS the group skeptic can emit ("was true, has
     * since changed"). ⚠ This is NOT the top-level `superseded` field two lines below,
     * which carries reconciliation-derived scoped/temporal findings WITH a canonical value.
     * Same word, different question — the backend documents the deliberate name collision
     * on the classing branch in `verification/report.py`. Do NOT unify them.
     */
    superseded?: VerificationVerdictItem[];
  };
  /** Refute verdicts carrying real skeptic evidence_refs (the "why refuted" list). */
  refuted?: VerificationVerdictItem[];
  superseded: VerificationVerdictItem[];
  reconciled: VerificationVerdictItem[];
  unverified: { count: number; claims_with_verdict: number; total_claims: number };
  /** C1 facts-only cost: `cost_pending` true means an un-itemized fee is still open. */
  true_cost: { cost_usd_total: string | null; cost_pending: boolean };
  /**
   * SC4 / D13: the run's DB-numbered `[n]` citation entries (backend
   * `VerificationCitation`, generated by `citations/numbering.py`). The report body
   * renders its clickable markers from EXACTLY this list, so every `[n]` resolves.
   */
  citations?: Citation[];
  [k: string]: unknown;
};

/**
 * A single redacted audit-log body read back from GCS (Plan 15-03 `AuditBody` / Plan 15-04
 * proxy). The body is ALREADY REDACTED server-side and carries NO hash/prev_hash — the
 * request/response are opaque JSON blobs rendered read-only in the drill-down panel.
 */
export type AuditBody = {
  audit_id: string;
  provider: string | null;
  model: string | null;
  request: unknown;
  response: unknown;
};

/**
 * A single citation source snapshot read back through the Plan 15-04 superadmin proxy
 * (`GET /intakes/{id}/research/sources/{sourceId}` → tribunal `GET /api/sources/{id}`,
 * Plan 15-03 renderer payload). `snapshot_text` is the STORED text of the source captured
 * at fetch time — the CitationPanel renders this DIRECTLY and NEVER re-fetches the live
 * `url`, so a dead link still resolves (T-15-15 SSRF + dead-link survival). This is a
 * DISTINCT concern from intake-upload sources (`sources.ts`) — do NOT overload that module.
 */
export type CitationSource = {
  id: string;
  url: string;
  title: string | null;
  provider: string | null;
  fetched_at: string | null;
  snapshot_text: string | null;
};

/**
 * A single numbered citation as GENERATED from the DB by Plan 15-03's numbering (never the
 * model — T-15-16). `n` is the displayed `[n]` marker; `source_id` resolves against the
 * citation-source proxy above so every number is guaranteed to resolve. `quality_tier`
 * maps 1→official / 2→serious press / 3→blog; `single_source` flags a claim resting on a
 * lone source; `temporal_note` carries a verification-flagged outdated-fact caveat inline.
 */
export type Citation = {
  n: number;
  source_id: string;
  title: string | null;
  publication_date: string | null;
  quality_tier: 1 | 2 | 3;
  single_source: boolean;
  temporal_note?: string | null;
  /** The claim that introduced this source (attaches [n] markers to verdict rows). */
  first_claim_id?: string | null;
  /**
   * The source's URL. NOT a new wire field — `VerificationCitation.url` (tribunal
   * `runs/schemas.py`) has always declared it and `number_citations` has always emitted it;
   * declaring it here only closes a pre-existing TYPE gap on this side of the wire.
   */
  url?: string | null;
  /**
   * D-22-4. The engine's read-time dedupe emits ONE citation entry per normalized source URL
   * and drops the rest — and a dropped entry takes its `first_claim_id` with it. This field
   * carries those absorbed claim ids onto the survivor, so a verdict row whose claim
   * introduced only an absorbed source still renders its `[n]` marker instead of silently
   * losing it. Honoured by `lib/research/citationIndex.ts`.
   *
   * OPTIONAL because a pre-dedupe backend — a rolling Cloud Run deploy, or any build before
   * the write-side change lands — simply does not send it. Every reader must tolerate
   * `undefined`.
   */
  also_claim_ids?: string[];
};

/**
 * The twelve line kinds of the design of record
 * (`docs/design/prototypes/ResearchRunImproved.tsx`, `type LineKind`), verbatim and in the
 * same order as the engine's `RUN_EVENT_KINDS` tuple (tribunal `runs/run_events.py`). That
 * tuple and this union are ONE contract in two languages.
 *
 * This type exists for exhaustive switches in the renderer — NOT for parsing. See
 * `RunEvent.kind` below for why the wire field is a plain `string`.
 */
export type RunEventKind =
  | "thinking"
  | "tool"
  | "search"
  | "plan"
  | "streams"
  | "dispatch"
  | "agent_run"
  | "agent_done"
  | "agent_retry"
  | "agent_fail"
  | "summary"
  | "divider";

/**
 * One line of a run's activity feed — one `run_event` row on the wire (D-04), mirroring the
 * backend `RunEventItem` (tribunal `runs/schemas.py`) field for field.
 *
 * `kind` IS A PLAIN `string`, NOT `RunEventKind`, AND THAT IS THE POINT OF THE FIELD'S TYPE.
 * The backend already declares it as a plain `str` for the same reason: Cloud Run replaces
 * revisions gradually, so a NEWER engine revision writing a thirteenth kind while this
 * frontend build is still deployed is the NORMAL state of a rollout. Narrowing it here would
 * push that mismatch into the renderer, where an unhandled kind must still produce a line.
 * The renderer's default branch is what makes that safe — it never returns nothing.
 *
 * `meta` carries only the keys the engine's `_META_FIELDS` allowlist permits: `sub`,
 * `is_live`, `worked`, `actions`, `items`, `cost`, `audit_id`, `provider`, `model`, `angle`,
 * `attempt`, `max`, `wait_s`. It is typed loosely on purpose — the same additive-rollout
 * argument applies.
 */
export type RunEvent = {
  seq: number;
  ts: string;
  stage: string;
  kind: string;
  text: string;
  meta?: Record<string, unknown> | null;
};

/**
 * One bounded, `seq`-ordered page of the feed — the backfill read behind D-01.
 *
 * `next_after_seq` is the caller's NEXT cursor, not an offset. On an EMPTY page it is the
 * cursor the caller passed IN, never 0 (15.3-02's anti-rewind property) — so a client must
 * never reset it locally on a quiet tick, or a live feed rewinds to the run's first row.
 *
 * `has_more` is true when the page was cut by `limit`.
 */
export type RunEventPage = {
  run_id: string;
  events: RunEvent[];
  next_after_seq: number;
  has_more: boolean;
};

export type ResearchRun = {
  id: string;
  status: string;
  current_stage: string | null;
  stage_detail: ResearchStageDetail | null;
  cost_usd_total: string | null;
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
  // Phase-17 chain-guard / bundle lock state (RUN-03). The SSE frame carries these
  // once the backend dict emits them (read_latest_research_run_dict, Plan 01):
  //   chain_status    "verified" | "broken" | null  (null until finalize)
  //   chain_broken_at first divergent audit row index (null when verified)
  //   bundle_key      GCS key of the materialized zip (null until built)
  chain_status: string | null;
  chain_broken_at: number | null;
  bundle_key: string | null;
  // ── THE FEED CURSOR (15.3-06). `MAX(run_event.seq)` for this run, mirrored onto the
  // research_runs row and carried on the EXISTING SSE frame rather than by a second
  // transport. It is the ONLY thing that tells the run page new events exist: the page
  // fetches the delta past its own held position, so a tick where this has not advanced
  // costs ZERO requests. NULL means the run has emitted no events (a pre-15.3 run, or one
  // that has not started) — NOT 0, which would claim a feed positioned at its start.
  event_seq: number | null;
};

/** Handle returned to the caller; `close()` aborts the fetch and stops all retries. */
export type StreamHandle = { close: () => void };

/**
 * Terminal research-run statuses, VERBATIM from the Tribunal contract (D-05) — the
 * stream's stop condition. This is NOT the skill-run success vocabulary.
 *
 * `completed_degraded` IS terminal for the stream (D-12): the server closes a degraded
 * run's stream, so leaving it out here makes the client read that close as a drop and
 * enter its `retry()` reconnect loop until unmount — a self-inflicted request amplifier.
 *
 * `parked` IS terminal for the STREAM (15.2-19 / DEC-3) — it was absent until the Resume
 * button existed, because a terminal `parked` without an affordance is a dead-end card.
 * It closes the stream because a parked run waits on a HUMAN click that may be hours away:
 * holding the stream open would burn the server handler to its 10-minute
 * `MAX_STREAM_SECONDS` cap and then drop this client into its bounded reconnect loop.
 * The RUN is not finished — `resumeResearch` restarts it and a fresh stream opens.
 *
 * EXPORTED so the dedicated run page imports this set rather than declaring a fourth copy of
 * it. Terminality decides when the clock stops, when the footer ticker disappears and which
 * affordances are legal — three answers that must never be able to disagree with the stream's
 * own stop condition. A consumer that also treats the clarification pause as terminal adds
 * that ONE literal at the call site; it is deliberately not in this set, because the stream's
 * behaviour for it is not the same.
 */
export const RESEARCH_TERMINAL = new Set([
  "completed",
  "completed_degraded",
  "failed",
  "cancelled",
  "parked",
]);

/**
 * Trigger a deep-research run for an intake. Mirrors `getSkillRunFull`: a one-shot
 * `apiFetch` over the token-attaching transport (never fork the transport), method POST.
 * Returns `{ research_run_id }` on 202. Space-scoped server-side; a cross-space intake is
 * existence-hidden as 404. Returns `{success,error?}` — never throws (CLAUDE.md).
 */
export function triggerResearch(
  intakeId: string,
): Promise<ApiResult<{ research_run_id: string }>> {
  return apiFetch<{ research_run_id: string }>(`/intakes/${intakeId}/research`, {
    method: "POST",
  });
}

/**
 * Resume a PARKED research run (F-01 — the click-only resume). Mirrors `triggerResearch`:
 * a one-shot `apiFetch` over the token-attaching transport (never fork the transport),
 * method POST. Returns `{ research_run_id }` on 202.
 *
 * Superadmin-only + space-scoped server-side: a client / cross-space caller is
 * existence-hidden as 404 (never 403), and a run that is not exactly `parked` is 409.
 *
 * Free and unlimited (F-02): a checkpoint resume re-queues the SAME engine run, so it
 * re-charges nothing and does NOT consume one of the three trigger attempts. Returns
 * `ApiResult` — never throws (CLAUDE.md return-no-throw).
 */
export function resumeResearch(intakeId: string): Promise<ApiResult<{ research_run_id: string }>> {
  return apiFetch<{ research_run_id: string }>(`/intakes/${intakeId}/research/resume`, {
    method: "POST",
  });
}

/**
 * Stop a live research run — the operator's ONLY stop path (D-D, plan 15.2-25). Mirrors
 * `resumeResearch`: a one-shot `apiFetch` over the token-attaching transport (never fork
 * the transport), method POST. Returns `{ research_run_id, status }` on 202.
 *
 * Server-side guarantees this transport relies on:
 * - superadmin-only and space-scoped; a client / cross-space caller is existence-hidden
 *   as **404**, never 403 and never 200;
 * - an already-terminal run is a **200-shaped no-op** that echoes the run's own status
 *   rather than an error — there is no 409 arm, because the engine reports none;
 * - the intake row is NOT touched. Resolving the run row to `cancelled` is by itself what
 *   makes the intake re-triggerable, because `cancelled` is a retryable run status
 *   server-side while `running` is not.
 *
 * `RESEARCH_TERMINAL` already contains `cancelled`, so the open stream closes on the
 * cancelled frame by itself — nothing here needs to touch that set.
 *
 * Returns `ApiResult` — never throws (CLAUDE.md return-no-throw).
 */
export function cancelResearch(
  intakeId: string,
): Promise<ApiResult<{ research_run_id: string; status: string }>> {
  return apiFetch<{ research_run_id: string; status: string }>(
    `/intakes/${intakeId}/research/cancel`,
    { method: "POST" },
  );
}

/**
 * Mint a signed download URL for a verified completed run's raw-output bundle (RUN-03 SC1).
 * A one-shot `apiFetch` over the token-attaching transport (never fork the transport),
 * method GET. Superadmin-only + space-scoped server-side; a client / cross-space caller is
 * existence-hidden as 404, and a not-yet-verified run is 409. Returns `{url, expires_in}` on
 * success. Returns `ApiResult` — never throws (CLAUDE.md return-no-throw).
 */
export function getBundleUrl(
  intakeId: string,
  runId: string,
): Promise<ApiResult<{ url: string; expires_in: number }>> {
  return apiFetch<{ url: string; expires_in: number }>(
    `/intakes/${intakeId}/research/${runId}/bundle-url`,
    { method: "GET" },
  );
}

/**
 * Fetch the superadmin verification report for a completed run (Plan 15-05 / ENGINE-09).
 * A one-shot `apiFetch` over the token-attaching transport (never fork the transport),
 * method GET, hitting the Plan 15-04 superadmin proxy `/intakes/{id}/research/{runId}/
 * verification`. Superadmin-only + space-scoped server-side; a client / cross-space caller
 * is existence-hidden as 404. Returns `ApiResult<VerificationReport>` — never throws
 * (CLAUDE.md return-no-throw).
 */
export function getVerification(
  intakeId: string,
  runId: string,
): Promise<ApiResult<VerificationReport>> {
  return apiFetch<VerificationReport>(
    `/intakes/${intakeId}/research/${runId}/verification`,
    { method: "GET" },
  );
}

/**
 * Fetch a single redacted audit-log body for the D15 feed drill-down (Plan 15-05).
 * A one-shot `apiFetch` (never fork the transport), method GET, hitting the Plan 15-04
 * superadmin proxy `/intakes/{id}/research/{runId}/audit/{auditId}`. The body is already
 * redacted server-side (no live-URL fetch, no key re-exposure). Superadmin-only + space-
 * scoped; a client / cross-space caller is existence-hidden as 404. Returns
 * `ApiResult<AuditBody>` — never throws (CLAUDE.md return-no-throw).
 */
export function getAuditBody(
  intakeId: string,
  runId: string,
  auditId: string,
): Promise<ApiResult<AuditBody>> {
  return apiFetch<AuditBody>(
    `/intakes/${intakeId}/research/${runId}/audit/${auditId}`,
    { method: "GET" },
  );
}

/**
 * Fetch a single citation source snapshot for the D13 numbered-citation panel (Plan 15-06 /
 * ENGINE-09). A one-shot `apiFetch` over the token-attaching transport (never fork the
 * transport), method GET, hitting the Plan 15-04 superadmin proxy `/intakes/{id}/research/
 * sources/{sourceId}`. The returned `snapshot_text` is rendered DIRECTLY — the live `url` is
 * NEVER re-fetched (T-15-15 SSRF + dead-link survival). Superadmin-only + space-scoped; a
 * client / cross-space caller is existence-hidden as 404. Returns `ApiResult<CitationSource>`
 * — never throws (CLAUDE.md return-no-throw). This is a DISTINCT surface from the intake-upload
 * `sources.ts` module — do NOT overload that one.
 */
export function getSource(
  intakeId: string,
  sourceId: string,
): Promise<ApiResult<CitationSource>> {
  return apiFetch<CitationSource>(
    `/intakes/${intakeId}/research/sources/${sourceId}`,
    { method: "GET" },
  );
}

/**
 * Fetch one page of a run's persisted activity feed (15.3-07 proxy → 15.3-02 engine read).
 * A one-shot `apiFetch` over the token-attaching transport (never fork the transport),
 * method GET, hitting `/intakes/{id}/research/{runId}/events`.
 *
 * Server contract this transport relies on:
 * - superadmin-only and space-scoped; a client / cross-space / null-space caller is
 *   existence-hidden as **404**, never 403 and never 200 — so a failure here is never a
 *   signal the caller may interpret as "the run exists but you may not read it";
 * - a run whose `tribunal_run_id` is still NULL is **404** on THIS verb (the engine has
 *   never heard of it, so there is nothing to page) — which is exactly the freshly-queued
 *   window, and is why the page must render sensibly with no events rather than treat a
 *   failure as fatal;
 * - the engine page rides through VERBATIM, `next_after_seq` and `has_more` included.
 *
 * `limit` is bounded 1..1000 server-side in two places; the engine's clamp is the authority,
 * so nothing is clamped here. Returns `ApiResult` — never throws (CLAUDE.md return-no-throw).
 */
export function getRunEvents(
  intakeId: string,
  runId: string,
  afterSeq = 0,
  limit = 500,
): Promise<ApiResult<RunEventPage>> {
  const qs = new URLSearchParams({ after_seq: String(afterSeq), limit: String(limit) });
  return apiFetch<RunEventPage>(
    `/intakes/${intakeId}/research/${runId}/events?${qs.toString()}`,
    { method: "GET" },
  );
}

/**
 * Resolve a run id to the intake that owns it — the COLD-OPEN path for the standalone run
 * URL (D-01). A one-shot `apiFetch` (never fork the transport), method GET, hitting
 * `/intakes/research/runs/{runId}/locate`.
 *
 * This is the ONLY way the run page learns its intake id. It deliberately does NOT accept an
 * intake id from the URL: a bookmarked link will not carry one, and a URL-supplied tenant
 * hint is exactly what TENANT-02 forbids.
 *
 * Server contract (15.3-07): superadmin-only and space-scoped; a client / cross-space /
 * null-space caller is existence-hidden as **404**. Unlike the events verb it does NOT 404 a
 * run whose `tribunal_run_id` is still NULL — a freshly triggered run carries no engine id
 * for exactly the window in which an operator opens this page, and "which intake owns this
 * run" is knowable without the engine ever having heard of it. It returns exactly two ids
 * and NO run state: a status here would be a second source of truth that can disagree with
 * the SSE frame (D-05). Returns `ApiResult` — never throws.
 */
export function locateResearchRun(
  runId: string,
): Promise<ApiResult<{ intake_id: string; research_run_id: string }>> {
  return apiFetch<{ intake_id: string; research_run_id: string }>(
    `/intakes/research/runs/${runId}/locate`,
    { method: "GET" },
  );
}

/**
 * Re-run the audit-chain verification for a run and lift the lock on a now-passing chain
 * (RUN-03 / D-08). A one-shot `apiFetch` (never fork the transport), method POST.
 * Superadmin-only + space-scoped; returns the new `{chain_status}`. On success a
 * now-verified chain lets the next `getBundleUrl` build-on-download the bundle. Returns
 * `ApiResult` — never throws (CLAUDE.md return-no-throw).
 */
export function reVerifyChain(
  intakeId: string,
  runId: string,
): Promise<ApiResult<{ chain_status: string }>> {
  return apiFetch<{ chain_status: string }>(
    `/intakes/${intakeId}/research/${runId}/verify-chain`,
    { method: "POST" },
  );
}

/**
 * Open an SSE stream for an intake's latest research run and drive it into React state.
 *
 * Cloned from `openSkillRunStream` VERBATIM except the terminal set + URL.
 *
 * @param intakeId    the intake whose latest run is streamed (per-intake addressing)
 * @param onEvent     called with each parsed snapshot — `null` when the intake has no run
 *                    yet (a `data: null` frame)
 * @param onTerminal  called once the run reaches a terminal status; the stream then closes
 * @param onFallback  called when the stream is unavailable (no token / 401·404 / backoff
 *                    exhausted) — the caller starts a bounded poll
 */
export function openResearchStream(
  intakeId: string,
  onEvent: (r: ResearchRun | null) => void,
  onTerminal: () => void,
  onFallback: () => void,
): StreamHandle {
  const controller = new AbortController();
  let closed = false;
  let attempts = 0;

  const connect = async (): Promise<void> => {
    // Reuse the SAME token source as apiFetch — a fresh token per (re)connect.
    const token = await currentIdToken();
    if (!token) {
      // Signed out: nothing to stream. Degrade to the poll (which will also no-op).
      onFallback();
      return;
    }

    let resp: Response;
    try {
      resp = await fetch(apiUrl(`/intakes/${intakeId}/research/stream`), {
        headers: {
          Authorization: `Bearer ${token}`,
          Accept: "text/event-stream",
        },
        signal: controller.signal,
      });
    } catch {
      // Network error opening the connection — retry with backoff.
      retry();
      return;
    }

    // 404 (intake/run gone or cross-space, existence-hidden) or 401 (auth failed) are
    // terminal for the stream: stop and hand off to the poll, do not retry.
    if (resp.status === 404 || resp.status === 401) {
      closed = true;
      onFallback();
      return;
    }
    if (!resp.ok || !resp.body) {
      retry();
      return;
    }

    // A good connection resets the backoff budget.
    attempts = 0;
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";

    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (done || closed) break;
        buf += decoder.decode(value, { stream: true });
        // SSE frames are separated by a blank line.
        let idx: number;
        while ((idx = buf.indexOf("\n\n")) !== -1) {
          const frame = buf.slice(0, idx);
          buf = buf.slice(idx + 2);
          // Take the `data:` payload lines; ignore `:`-comment heartbeat lines (": ping").
          // Per the SSE spec, strip only ONE optional leading space after the colon and
          // join multiple `data:` lines with a newline.
          const data = frame
            .split("\n")
            .filter((l) => l.startsWith("data:"))
            .map((l) => l.slice(5).replace(/^ /, ""))
            .join("\n");
          if (!data) continue;
          let r: ResearchRun | null;
          try {
            // A `data: null` snapshot (intake with no runs yet) parses to `null`.
            r = JSON.parse(data) as ResearchRun | null;
          } catch {
            // Malformed frame: skip it, keep reading.
            continue;
          }
          onEvent(r);
          // Guard the terminal check for a null snapshot — `null.status` would throw
          // (escaping the JSON try/catch) and trigger a needless retry.
          if (r && RESEARCH_TERMINAL.has(r.status)) {
            closed = true;
            onTerminal();
            return;
          }
        }
      }
    } catch {
      // Read error mid-stream — fall through to retry (unless we closed intentionally).
    }
    // Server closed the stream (in-handler cap) or the network dropped: reconnect.
    if (!closed) retry();
  };

  const retry = (): void => {
    if (closed) return;
    if (attempts >= 3) {
      // Reconnects exhausted: silently degrade to the bounded poll.
      closed = true;
      onFallback();
      return;
    }
    const delay = 1000 * 2 ** attempts; // 1s, 2s, 4s
    attempts += 1;
    setTimeout(() => {
      if (!closed) void connect();
    }, delay);
  };

  void connect();

  return {
    close: () => {
      closed = true;
      controller.abort();
    },
  };
}
