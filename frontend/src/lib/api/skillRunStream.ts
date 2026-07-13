import { apiUrl } from "@/lib/firebase";
import { currentIdToken } from "@/lib/api/client";
import type { SkillRun } from "@/lib/api/skillRuns";

// frontend/src/lib/api/skillRunStream.ts — hand-rolled fetch/ReadableStream SSE reader
// (Phase 8, API-04, D-01/D-02/D-07a). It restores the live push the legacy Supabase
// Realtime subscription gave the admin UI, WITHOUT a new dependency and WITHOUT the
// browser's native event-source primitive (which cannot attach an `Authorization`
// header — D-01), which is why a raw `fetch` + `ReadableStream` is used instead.
//
// NEVER FORK THE TRANSPORT (skillRuns.ts convention): this reader reuses only the exact
// TOKEN source (`currentIdToken`) and base-URL builder (`apiUrl`) that `apiFetch` uses —
// not `apiFetch` itself, which calls `resp.text()` and buffers the whole body (it cannot
// stream). The stream body is read incrementally via `resp.body.getReader()`.
//
// RETURN-NO-THROW (CLAUDE.md / client.ts): every failure path surfaces via `onFallback`,
// never a throw — so the caller's swap to the tested 5s poll is invisible and the UI
// never goes blind (D-07a).
//
// SECURITY (T-08-07): the id token is attached as a Bearer header only — never placed in
// the URL or logged. SSE payloads are untrusted input: each `data:` frame is `JSON.parse`d
// inside a try/catch and malformed frames are skipped (T-08-10).

/** Handle returned to the caller; `close()` aborts the fetch and stops all retries. */
export type StreamHandle = { close: () => void };

/** Terminal skill-run statuses, verbatim from Phase 7 D-09 — the stream's stop condition. */
const TERMINAL = new Set(["succeeded", "failed"]);

/**
 * Open an SSE stream for an intake's latest skill run and drive it into React state.
 *
 * @param intakeId    the intake whose latest run is streamed (per-intake addressing, D-06a)
 * @param onEvent     called with each parsed snapshot — `null` when the intake has no run
 *                    yet (a `data: null` frame); map via `toActiveSkillRun`, which guards null
 * @param onTerminal  called once the run reaches a terminal status; the stream then closes
 * @param onFallback  called when the stream is unavailable (no token / 401·404 / backoff
 *                    exhausted) — the caller starts the existing 5s poll (D-07a)
 */
export function openSkillRunStream(
  intakeId: string,
  onEvent: (r: SkillRun | null) => void,
  onTerminal: () => void,
  onFallback: () => void,
): StreamHandle {
  const controller = new AbortController();
  let closed = false;
  let attempts = 0;

  const connect = async (): Promise<void> => {
    // Reuse the SAME token source as apiFetch — a fresh token per (re)connect (D-03).
    const token = await currentIdToken();
    if (!token) {
      // Signed out: nothing to stream. Degrade to the poll (which will also no-op).
      onFallback();
      return;
    }

    let resp: Response;
    try {
      resp = await fetch(apiUrl(`/intakes/${intakeId}/skill-runs/stream`), {
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

    // 404 (intake/run gone or cross-space, existence-hidden per D-04) or 401 (auth
    // failed) are terminal for the stream: stop and hand off to the poll, do not retry.
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
          // join multiple `data:` lines with a newline — a bare .trim()+join("") would
          // mangle any future multi-line or whitespace-significant payload.
          const data = frame
            .split("\n")
            .filter((l) => l.startsWith("data:"))
            .map((l) => l.slice(5).replace(/^ /, ""))
            .join("\n");
          if (!data) continue;
          let r: SkillRun | null;
          try {
            // A `data: null` snapshot (intake with no runs yet) parses to `null`.
            r = JSON.parse(data) as SkillRun | null;
          } catch {
            // Malformed frame (T-08-10): skip it, keep reading.
            continue;
          }
          onEvent(r);
          // Guard the terminal check for a null snapshot — `null.status` would throw
          // (escaping the JSON try/catch) and trigger a needless retry (IN-02).
          if (r && TERMINAL.has(r.status)) {
            closed = true;
            onTerminal();
            return;
          }
        }
      }
    } catch {
      // Read error mid-stream — fall through to retry (unless we closed intentionally).
    }
    // Server closed the stream (10-min in-handler cap) or the network dropped: reconnect.
    if (!closed) retry();
  };

  const retry = (): void => {
    if (closed) return;
    if (attempts >= 3) {
      // Reconnects exhausted (D-07a): silently degrade to the tested 5s poll.
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
