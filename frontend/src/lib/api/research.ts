import { apiUrl } from "@/lib/firebase";
import { apiFetch, currentIdToken, type ApiResult } from "@/lib/api/client";

// frontend/src/lib/api/research.ts — the admin-side research trigger + live-progress
// transport (Phase 16, RUN-01/SEAM-03). It restores the same live push the skill-run
// stream gives the admin UI, but for a Tribunal research run, WITHOUT a new dependency
// and WITHOUT the browser's native event-source primitive (which cannot attach an
// `Authorization` header), which is why a raw `fetch` + `ReadableStream` is used.
//
// It clones `openSkillRunStream` (skillRunStream.ts) VERBATIM except for two things:
//   1. RESEARCH_TERMINAL = {"completed","failed","cancelled"} — the VERBATIM Tribunal
//      terminal set (D-05 boundary), NOT the skill-run {succeeded,failed} vocabulary.
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
 * funnel + true cost. `extra="allow"` server-side means additional rollup fields (`counts`)
 * may ride through — the type is intentionally permissive on those.
 */
export type VerificationVerdictItem = {
  claim?: string | null;
  verdict?: string | null;
  evidence?: string | null;
  effect?: string | null;
  [k: string]: unknown;
};

export type VerificationReport = {
  funnel: Record<string, number>;
  verdicts: {
    support?: VerificationVerdictItem[];
    refute?: VerificationVerdictItem[];
    insufficient?: VerificationVerdictItem[];
  };
  superseded: VerificationVerdictItem[];
  reconciled: VerificationVerdictItem[];
  unverified: { count: number; items?: VerificationVerdictItem[] };
  cost: { total: string; pending: boolean };
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
};

/** Handle returned to the caller; `close()` aborts the fetch and stops all retries. */
export type StreamHandle = { close: () => void };

/**
 * Terminal research-run statuses, VERBATIM from the Tribunal contract (D-05) — the
 * stream's stop condition. This is NOT the skill-run success vocabulary.
 */
const RESEARCH_TERMINAL = new Set(["completed", "failed", "cancelled"]);

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
