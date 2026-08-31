"""
AuditedLLMClient -- single owner of every LLM call's audit trail.

Exposes TWO interfaces:

1. Atomic-call methods (anthropic_messages, gemini_generate, openai_response, write_failure)
   -- for synthesis-step calls that complete in seconds.

2. Two-phase methods (start_call, end_call)
   -- for long-running deep-research calls that may take up to 35 minutes
      (CLAUDE.md Critical rules section 4: deep research polls every 30s, max 70 attempts).

Plan 09 deep-research adapters consume the two-phase API; they do NOT extend this class.
Synthesis steps consume the atomic-call methods.

Design decisions:
  - _SEMAPHORE(8): bounds all in-flight LLM calls per worker (PATTERNS lines 302-304).
  - Autonomous transactions: each audit write uses a dedicated DB session so the audit row
    commits even if the LLM-using transaction rolls back (Anti-pattern line 584).
  - cache_read_input_tokens + cache_creation_input_tokens extracted explicitly from
    Anthropic responses (Pitfall 6 -- NOT collapsed into input_tokens).
  - Unknown model -> cost_usd=NULL + warning (Pitfall 5 -- never fail, never guess).
  - Per-run asyncio.Lock (_run_locks / _run_lock): serializes seq+hash assignment at
    completion order so concurrent providers/skeptics never collide on
    uq_audit_tenant_run_seq. The slow LLM calls still run in parallel; only the brief
    DB get_prev_hash_and_seq + write_full_row section is serialized per run. (T-16-01)
  - Two-phase crash-recovery trade-off: start_call no longer inserts an IN_FLIGHT_PLACEHOLDER
    row. A worker crash between start_call and end_call now leaves NO audit row rather than
    an orphaned placeholder. This is an accepted trade-off scoped to single-worker scale
    (T-16-03); robust concurrent crash-recovery is deferred to Phase 2. The old
    insert_placeholder / finalize_row methods remain in writer.py (unused by this client)
    so writer.py callers are not broken.

  - Long-poll run-feed events (15.3-04, narrowed 2026-08-31): the two
    deep-research poll loops report reconnects, timeouts and provider-reported
    failures onto the run feed. They no longer announce dispatch and no longer
    emit a strided progress line -- those four emissions were removed on operator
    request because they were noise in the live feed, so a long poll is now
    silent for up to 35 minutes by design (see the comment above _CURRENT_RUN).
    The events are best-effort and cannot fail a call; the audit row, its payload
    and its hash chain are untouched by them.

Canonical JSON rule (MUST stay frozen across deploys -- Pitfall 3):
  The payload passed to link_hash is built by _build_payload_dict().
  The fields in this dict MUST match _payload_for_row() in hash_chain.py exactly.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Awaitable, Callable, Literal, Optional

# R7 (plan 15.2-16). `checkpoints` is a pure module — no database, no provider
# client, no import back into this package — so a module-level import here adds
# no cycle and no load cost. `safe_job_id` is the ONE guard a provider job id
# passes before it is persisted or interpolated into a poll URL (T-15.2-125).
from nestor_pulse_sdk.pipeline.tribunal.checkpoints import safe_job_id
# 15.3-04. THE MODULE OBJECT, NOT ITS NAMES: binding the emitter's functions
# into this namespace would let a bare call slip past this phase's call-site
# grep gate while the gate stayed green. Every site below goes through the
# thunk-taking entry point, so the elapsed-minutes arithmetic and the
# provider-shaped reads that build a line run INSIDE the emitter's own try
# (D-06) — which matters here more than anywhere else in the engine, because
# the loop it sits in is a paid call that can run for thirty-five minutes.
# The phrasing of this comment and of the ones at the sites is deliberately
# roundabout: a grep cannot tell a comment from a call, and this phase gates
# both a forbidden form and a COUNT of the permitted one.
from nestor_pulse_sdk.runs import run_events

log = logging.getLogger(__name__)

# R7 / DEC-2 — A RESUME NEVER SILENTLY RE-DISPATCHES A PAID JOB.
#
# When a persisted background job id is no longer retrievable (Gemini 404/410,
# OpenAI `NotFoundError` past the ~10-minute response-retention window —
# RESEARCH A11), the default is to DEGRADE that one stream with a named reason
# and let D-12/D-17 do their job: one or two streams lost is
# `completed_degraded`. Set NESTOR_TRIBUNAL_RESUME_REDISPATCH=true to fall
# through to a fresh dispatch instead.
#
# Rationale, verbatim from the operator's standing rule — "NO ESTIMATES — facts
# and correct calculations only": quietly paying twice for the same
# deep-research job is the money-side equivalent of a silent green.
RESUME_REDISPATCH = (
    os.environ.get("NESTOR_TRIBUNAL_RESUME_REDISPATCH", "false").lower() == "true"
)

# ---------------------------------------------------------------------------
# A LONG POLL IS SILENT ON THE RUN FEED, BY DESIGN.
#
# On 2026-07-27 an operator watched a flat CPU trace and silent logs, concluded
# a run had hung, and was WRONG: it was mid deep-research long poll and resumed
# on its own twenty-five minutes later. The misreading cost an hour, produced a
# defect report that had to be withdrawn, and very nearly re-executed a paid run
# from the start. THE RUN ROW AND THE FEED ARE THE ONLY AUTHORITIES; log silence
# and idle CPU are not evidence of anything.
#
# 15.3-04 answered that incident with two feed lines per provider: a dispatch
# announcement, and a strided heartbeat restating elapsed minutes, attempt
# number and a sentence asserting the wait was expected. Those four emissions,
# and the stride constant plus its NESTOR_RUN_EVENT_POLL_STRIDE override that
# paced them, were REMOVED on operator request 2026-08-31: the operator watches
# the live feed and judged them noise. A deep-research call is therefore silent
# on the feed for up to 35 minutes, deliberately.
#
# The exact wording is deliberately NOT quoted here. An absence gate greps this
# file for those literals, and a comment reciting them would read as a live
# emission and turn the gate red on correct code.
#
# The incident above is kept because the silence is now expected rather than
# diagnostic, so the 2026-07-27 misreading is EASIER to make, not harder. What
# still reaches the feed is every provider-reported failure, every give-up and
# every rejoin -- see the agent_fail emissions in both poll loops. Restoring the
# heartbeat is a decision to re-open with the operator, not a bug to fix.
# ---------------------------------------------------------------------------

#: The run a two-phase deep-research call belongs to.
#:
#: WHY A ContextVar AND NOT A PARAMETER. The two raw poll methods take no
#: `run_id` and their callers -- `tools/gemini_adapter.py`, `tools/openai_adapter.py`
#: -- are owned by neither this plan nor its siblings, so widening their
#: signatures here was not available. What IS available is that both adapters
#: call `start_call` IMMEDIATELY BEFORE the raw method, in the same coroutine
#: and therefore in the same asyncio Task: a ContextVar set inside `start_call`
#: is visible to everything that follows in that task, and `asyncio.gather`
#: gives every concurrently dispatched angle its own copied Context, so two
#: angles racing in the same worker cannot read each other's run. That property
#: is what makes this safe and it is the reason the binding lives in
#: `start_call` rather than on `self`, which twenty-four concurrent angles would
#: share.
#:
#: A call path with no run context reads None and SKIPS its events. It never
#: invents a run id and never opens a run: a tenant-less write is precisely the
#: isolation defect this project forbids, and `run_events.open_run` is the only
#: place a tenant is bound.
_CURRENT_RUN: "contextvars.ContextVar[Optional[uuid.UUID]]" = contextvars.ContextVar(
    "nestor_audited_current_run", default=None
)


def _job_id_phrase(raw: Any) -> str:
    """" (job <id>)" when `safe_job_id` accepts `raw`, else the empty string.

    T-15.2-125 / T-15.3-32: a provider job id reaches a persisted, operator-
    visible row through this function and no other path. A refused id costs the
    id, not the line -- the event still names the provider, it simply does not
    quote an identifier nobody validated.
    """
    checked = safe_job_id(raw) if raw else None
    return f" (job {checked})" if checked else ""

# ---------------------------------------------------------------------------
# Deep-research model constants -- env-overridable for easy tuning.
# ---------------------------------------------------------------------------
GEMINI_DEEP_RESEARCH_AGENT = os.environ.get(
    # Current-generation "Deep Research Max" agent (built on Gemini 3.1 Pro; released
    # 2026-04-21) — maximum comprehensiveness. There is NO separate "pro" agent tier;
    # "Pro" is the underlying model. The two current agents are this one and the
    # lighter/faster "deep-research-preview-04-2026". The legacy
    # "deep-research-pro-preview-12-2025" (still used by the read-only ADK arm) is
    # superseded. Override via NESTOR_GEMINI_DR_AGENT.
    "NESTOR_GEMINI_DR_AGENT", "deep-research-max-preview-04-2026"
)
# D-A, found dead on run `d6bb3aae` (2026-07-27). This default used to be the
# retired o4-mini deep-research id, and OpenAI shut BOTH deep-research models down
# on 2026-07-23 — four days before that run. The engine did not break; the model
# was switched off underneath it. OpenAI's deprecations page gives ONE migration
# target for both retired ids, and it is the one below. It was verified on THIS
# account by polling a background deep-research probe to a TERMINAL state
# (queued -> completed) — never by whether the request was accepted, because the
# dead model also reached `queued` and only then failed asynchronously with
# `model_not_found`.
#
# THIS DEFAULT IS THE FLOOR WHEN THE ENV VAR IS ABSENT, which is exactly how the
# dead id reached production: `deploy-worker.sh` never bound NESTOR_OPENAI_DR_MODEL,
# so the deployed worker ran on the code default. Both places are pinned now, so
# neither alone can resurrect the failure. KEEP THE TWO IN STEP.
#
# CAVEAT, STILL OPEN: `gpt-5.6-sol` is a GPT-5.x model, not an o-series
# deep-research model. The probe proves it is CALLABLE on the background Responses
# path; it does NOT prove that this file's two-phase start/poll adapter parses its
# response and `usage` fields identically. That parity is unverified until the
# next live run.
#
# (The retired id is deliberately NOT spelled out anywhere in this file, so the
# phase's `grep -c` gate for it can be read literally — see 15.2-22 phase rule 9.)
OPENAI_DEEP_RESEARCH_MODEL = os.environ.get(
    "NESTOR_OPENAI_DR_MODEL", "gpt-5.6-sol"
)

# ---------------------------------------------------------------------------
# D-A's second half: an operator must be able to READ the configuration rather
# than infer it from seven identical per-angle failures. Emitted ONCE per process
# from the first `AuditedLLMClient` construction — module import is too early to
# be useful (the env is read above, but nothing has decided to make a call yet)
# and too noisy in tests.
#
# It names MODEL IDS ONLY. A model id is configuration, not a credential; no
# secret, key or env VALUE other than these two ids is read, echoed or logged
# here (T-15.2-223).
# ---------------------------------------------------------------------------
_DR_MODELS_LOGGED = False


def log_resolved_dr_models() -> None:
    """Log the resolved deep-research model ids and where each came from. Once."""
    global _DR_MODELS_LOGGED
    if _DR_MODELS_LOGGED:
        return
    _DR_MODELS_LOGGED = True

    def _origin(var: str) -> str:
        return f"env {var}" if os.environ.get(var) else "committed default"

    log.info(
        "resolved deep-research models: gemini=%s (%s), openai=%s (%s). A refused "
        "model id classifies as reliability.CONFIG_ERROR and trips that provider "
        "circuit on its FIRST occurrence, so it is one named failure and not one "
        "per angle.",
        GEMINI_DEEP_RESEARCH_AGENT,
        _origin("NESTOR_GEMINI_DR_AGENT"),
        OPENAI_DEEP_RESEARCH_MODEL,
        _origin("NESTOR_OPENAI_DR_MODEL"),
    )

# ---------------------------------------------------------------------------
# Gemini Interactions REST config (deep research).
#
# WHY REST AND NOT THE SDK: Google retired the legacy Interactions API schema in
# May 2026. The new "steps" schema is only emitted to clients on google-genai
# >= 2.0.0 — but google-adk 1.34.1 pins google-genai>=1.72,<2, so we CANNOT bump
# the SDK without breaking the ADK arm (which must stay runnable for A/B). The
# server-side opt-in for the new schema on the pinned 1.75 client is the REST
# header `Api-Revision: 2026-05-20`, so the deep-research call is issued directly
# over HTTP (httpx). Everything else still goes through the 1.75 SDK unchanged.
# Symptom this fixes: 400 "The legacy Interactions API schema is no longer
# supported. Please upgrade your client SDK ... new 'steps' schema."
# ---------------------------------------------------------------------------
GEMINI_INTERACTIONS_BASE = os.environ.get(
    "NESTOR_GEMINI_INTERACTIONS_BASE",
    "https://generativelanguage.googleapis.com/v1beta",
)
GEMINI_INTERACTIONS_REVISION = os.environ.get(
    "NESTOR_GEMINI_INTERACTIONS_REVISION", "2026-05-20"
)

_SEMAPHORE = asyncio.Semaphore(8)  # bounds ALL in-flight LLM calls per worker

#: Leftover numeric citation markers once annotations are resolved into links.
_CITE_MARKER_RE = re.compile(r"\s*\[cite[:_][^\]]*\]")


def _domain_of(url: str) -> str:
    m = re.match(r"https?://(?:www\.)?([^/]+)", url or "")
    return m.group(1) if m else (url or "source")


def resolve_url_citations(text: str, annotations: list) -> str:
    """Resolve Interactions-API citation annotations into inline markdown links.

    THE CITATION FIX (2026-06-11): the deep-research Interactions API returns
    the report text with numeric '[cite: N]' markers and the actual sources as
    a SEPARATE annotations list (URLCitation: url/title/start_index/end_index).
    Keeping only `.text` produced reports full of unresolvable markers, an empty
    Sources section, and unverifiable claims (the blind critique punished
    exactly this). This injects ' [title](url)' right after each cited span so
    every downstream step — scrub, synthesis, the deterministic Sources
    extractor, claim persistence — sees real links.

    Markers are stripped ONLY when at least one annotation resolved; with no
    annotations the text is returned untouched (markers preserved — degraded
    but honest, never destructive).
    """
    if not text or not annotations:
        return text

    insertions: list[tuple[int, str, str]] = []  # (position, title, url)
    seen: set[tuple[int, str]] = set()
    for a in annotations:
        url = getattr(a, "url", None) or (a.get("url") if isinstance(a, dict) else None)
        if not url:
            continue
        end = getattr(a, "end_index", None) if not isinstance(a, dict) else a.get("end_index")
        start = getattr(a, "start_index", None) if not isinstance(a, dict) else a.get("start_index")
        pos = end if isinstance(end, int) else start
        if not isinstance(pos, int) or not (0 <= pos <= len(text)):
            pos = len(text)  # unplaceable -> collect at the end rather than drop
        title = (
            getattr(a, "title", None) if not isinstance(a, dict) else a.get("title")
        ) or _domain_of(url)
        key = (pos, url)
        if key in seen:
            continue
        seen.add(key)
        insertions.append((pos, str(title).strip(), url))

    if not insertions:
        return text

    # Insert from the back so earlier offsets stay valid.
    insertions.sort(key=lambda t: t[0], reverse=True)
    out = text
    for pos, title, url in insertions:
        out = f"{out[:pos]} [{title}]({url}){out[pos:]}"

    out = _CITE_MARKER_RE.sub("", out)
    log.info(
        "resolve_url_citations: %d citation(s) inlined, markers stripped",
        len(insertions),
    )
    return out


def strip_unresolved_cite_markers(text: str) -> tuple[str, int]:
    """Remove citation markers that were never resolved into a real link.

    `resolve_url_citations` converts every marker that HAS a matching URL
    annotation into an inline `[title](url)` link and strips that marker at the
    source (deep-research extraction time). Therefore any `[cite: N]` still
    present further downstream is PROVABLY unresolvable — no annotation ever
    carried a URL for it. Left in the final report it renders as an opaque
    placeholder that points at nothing (an unresolvable reference). This removes
    those orphans from the DELIVERABLE.

    Non-destructive to real citations: the regex matches only the `[cite: ...]`
    marker form, so already-resolved `[title](url)` markdown links are untouched.

    Returns (clean_text, n_removed) so the caller can log/surface the count
    rather than scrub silently.
    """
    if not text:
        return text, 0
    n = len(_CITE_MARKER_RE.findall(text))
    if not n:
        return text, 0
    return _CITE_MARKER_RE.sub("", text), n


def extract_report_from_steps(interaction: dict) -> str:
    """Pull the final report text + inline citations from a new-schema interaction.

    The May-2026 Interactions API replaced the flat `outputs[-1].text` with a
    typed `steps` array. The report lives in `model_output` steps whose `content`
    items are `{"type": "text", "text": ..., "annotations": [url_citation...]}`.
    Annotation offsets are relative to their OWN text block, so each block is
    citation-resolved independently before the blocks are joined (joining first
    would invalidate the offsets). Falls back to the `output_text` convenience
    field if no model_output text is found.
    """
    steps = interaction.get("steps") or []
    parts: list[str] = []
    for step in steps:
        if not isinstance(step, dict) or step.get("type") != "model_output":
            continue
        for content in step.get("content") or []:
            if isinstance(content, dict) and content.get("type") == "text":
                txt = content.get("text") or ""
                if not txt:
                    continue
                annotations = content.get("annotations") or []
                parts.append(resolve_url_citations(txt, annotations))
    text = "\n\n".join(p for p in parts if p)
    if not text:
        text = interaction.get("output_text") or ""
    return text


def _extract_anthropic_tool_counts(usage) -> tuple[int, int]:
    """Return (web_search_count, web_fetch_count) from an Anthropic usage object.

    Plan 15-02 C1: Anthropic reports server-tool invocations under
    usage.server_tool_use (e.g. .web_search_requests). These are FACTS read
    straight off the response -- never estimated. Missing -> 0 (no fee added).
    Accepts either an attribute-style object (SDK) or a dict (replayed row).
    """
    if usage is None:
        return 0, 0

    def _get(obj, name):
        if isinstance(obj, dict):
            return obj.get(name)
        return getattr(obj, name, None)

    stu = _get(usage, "server_tool_use")
    if stu is None:
        return 0, 0
    web_search = _get(stu, "web_search_requests") or 0
    web_fetch = _get(stu, "web_fetch_requests") or 0
    try:
        return int(web_search), int(web_fetch)
    except (TypeError, ValueError):
        return 0, 0


def _extract_gemini_dr_usage(interaction: dict) -> Optional[dict]:
    """Return the Gemini deep-research usageMetadata dict, or None if absent.

    Plan 15-02 C1: the Interactions API MAY return a `usageMetadata` block with
    promptTokenCount / candidatesTokenCount / thoughtsTokenCount. When present,
    the caller prices the DR call from these FACTS (thoughts billed at output rate).
    When ABSENT (confirmed for recorded run-4cbb5311), the caller sets
    run.cost_pending=True -- it NEVER writes a placeholder/estimated number.
    """
    if not isinstance(interaction, dict):
        return None
    meta = interaction.get("usageMetadata")
    if isinstance(meta, dict) and meta:
        return meta
    return None


@dataclass
class AuditHandle:
    """
    Returned by start_call; passed to end_call to finalize the audit row.

    Fields captured at start_call time so end_call can compute duration,
    build the payload, and update the row without re-reading from DB.
    """
    audit_id: uuid.UUID
    run_id: uuid.UUID
    tenant_id: uuid.UUID
    seq: int
    prev_hash: str
    started_at: float   # time.monotonic() for duration_ms computation
    started_dt: datetime  # UTC datetime for the started_at column
    provider: str
    model: str
    request_dict: dict


class AuditedLLMClient:
    """
    Wraps Anthropic, Google Gemini, and OpenAI clients with full audit trail.

    Constructor args:
      anthropic_client:  anthropic.AsyncAnthropic instance
      gemini_client:     google.genai.Client instance
      audit_writer:      object providing insert_placeholder(), finalize_row(),
                         write_full_row(), get_prev_hash_and_seq()
      hash_chain_mod:    nestor_pulse_sdk.audit.hash_chain module
      cost_table_mod:    nestor_pulse_sdk.audit.cost_table module
      gcs_blob_mod:      nestor_pulse_sdk.audit.gcs_blob module
    """

    def __init__(
        self,
        anthropic_client,
        gemini_client,
        audit_writer,
        hash_chain_mod,
        cost_table_mod,
        gcs_blob_mod,
    ) -> None:
        self._a = anthropic_client
        self._g = gemini_client
        self._audit = audit_writer
        self._chain = hash_chain_mod
        self._costs = cost_table_mod
        self._gcs = gcs_blob_mod
        # Per-run locks: serializes seq+hash assignment at completion order.
        # dict.get/set without an await between is race-free in single-threaded asyncio.
        self._run_locks: dict[uuid.UUID, asyncio.Lock] = {}
        # D-A: say out loud, once, which deep-research models this process
        # resolved. Best-effort — a log line must never break client construction.
        try:
            log_resolved_dr_models()
        except Exception:  # noqa: BLE001 — a startup log is never load-bearing
            pass

    def _run_lock(self, run_id: uuid.UUID) -> asyncio.Lock:
        """Return (or create) the per-run asyncio.Lock for seq+hash serialization."""
        lock = self._run_locks.get(run_id)
        if lock is None:
            lock = asyncio.Lock()
            self._run_locks[run_id] = lock
        return lock

    # =========================================================================
    # Atomic-call methods (synthesis path -- completes in seconds)
    # =========================================================================

    async def anthropic_messages(
        self,
        *,
        run_id: uuid.UUID,
        tenant_id: uuid.UUID,
        model: str,
        audit_out: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ):
        """
        Call self._a.messages.create(**kwargs) + write audit row atomically.

        Extracts:
          - usage.input_tokens (prompt)
          - usage.output_tokens (completion)
          - usage.cache_read_input_tokens (Pitfall 6 -- 0 if absent)
          - usage.cache_creation_input_tokens (Pitfall 6 -- for cost formula)

        Returns the raw anthropic response.

        audit_out (F4 -- 15.2 plan 03, ADDITIVE):
          An OPTIONAL caller-owned dict. When supplied, it is populated AFTER the
          audit row is written with audit_id / cost_usd / provider / model /
          duration_ms.

          WHY IT EXISTS. `StageDetailItem.audit_id` (`runs/schemas.py:167`) is the
          D15 feed's drill-down target -- the frontend already renders it and
          `GET /{run_id}/audit/{audit_id}` (`runs/api.py:885`) already serves it,
          tenant-scoped. But only the two-phase deep-research pair exposed an id
          (`AuditHandle.audit_id`); this method generated `audit_id` internally and
          threw it away, so a workshop / skeptic / gate feed row had no way to
          learn which call it represented.

          WHY AN OUT-PARAM AND NOT A CHANGED RETURN TYPE. Every existing call site
          consumes the raw provider response directly; widening the return to a
          tuple would break all of them. An out-param on a caller-owned dict is
          purely additive -- omit it and nothing about this method changes.

          The 15.2 outline floats `audit_out` and `with_audit_id=True` as
          alternatives. This is the ONE mechanism; do not add a second.

          It is declared as an EXPLICIT keyword-only parameter, deliberately ahead
          of **kwargs, because kwargs is forwarded VERBATIM to the provider SDK
          below -- an unknown key there is an HTTP 400.

          It writes NOTHING to the database: no new audit column, no new field in
          the frozen hash-chain payload. `verify_chain` is unaffected (EU AI Act
          Art. 12; see the Canonical JSON rule in this module's docstring).
        """
        async with _SEMAPHORE:
            started = time.monotonic()
            started_dt = datetime.now(tz=timezone.utc)
            kwargs["model"] = model

            resp = await self._a.messages.create(**kwargs)
            duration_ms = int((time.monotonic() - started) * 1000)

            usage = resp.usage
            prompt_tokens = getattr(usage, "input_tokens", 0) or 0
            completion_tokens = getattr(usage, "output_tokens", 0) or 0
            # Pitfall 6: extract cache token fields explicitly -- do NOT collapse into input_tokens
            cache_read_input_tokens = getattr(usage, "cache_read_input_tokens", 0) or 0
            cache_creation_input_tokens = getattr(usage, "cache_creation_input_tokens", 0) or 0
            # Plan 15-02 C1: count server-tool invocations (web_search/web_fetch) so their
            # published flat fees enter this call's cost. Anthropic reports these under
            # usage.server_tool_use.web_search_requests (facts from the response, never guessed).
            web_search_count, web_fetch_count = _extract_anthropic_tool_counts(usage)

            # Cost uses cache_read_input_tokens as cached_tokens; cache_creation is now
            # CHARGED (Plan 15-02 C1) at the 5m rate, and server-tool fees are added.
            cost_usd = self._costs.compute(
                provider="anthropic",
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cached_tokens=cache_read_input_tokens,
                cache_creation_tokens=cache_creation_input_tokens,
                web_search_count=web_search_count,
                web_fetch_count=web_fetch_count,
            )

            request_dict = {k: v for k, v in kwargs.items() if k != "model"}
            response_dict = self._response_to_dict(resp)

            audit_id = uuid.uuid4()
            gcs_uri = await self._gcs.upload_audit_body(
                run_id=run_id,
                audit_id=audit_id,
                provider="anthropic",
                model=model,
                request_dict=request_dict,
                response_dict=response_dict,
            )

            # Critical section: seq+hash assignment serialized per run so concurrent
            # providers never collide on uq_audit_tenant_run_seq (T-16-01).
            async with self._run_lock(run_id):
                prev_hash, seq = await self._audit.get_prev_hash_and_seq(run_id, tenant_id)
                payload = _build_payload_dict(
                    provider="anthropic", model=model, started_dt=started_dt,
                    duration_ms=duration_ms, prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens, cached_tokens=cache_read_input_tokens,
                    gcs_uri=gcs_uri, seq=seq, tenant_id=tenant_id, run_id=run_id,
                )
                row_hash = self._chain.link_hash(prev_hash, payload)

                await self._audit.write_full_row(
                    audit_id=audit_id,
                    run_id=run_id,
                    tenant_id=tenant_id,
                    seq=seq,
                    provider="anthropic",
                    model=model,
                    started_at=started_dt,
                    duration_ms=duration_ms,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    cached_tokens=cache_read_input_tokens,
                    cache_creation_tokens=cache_creation_input_tokens,
                    cost_usd=cost_usd,
                    gcs_uri=gcs_uri,
                    prev_hash=prev_hash,
                    hash=row_hash,
                )

            # F4: hand the caller the id of the row that was just written, so a D15
            # feed row can carry a drill-down that actually resolves. Populated
            # AFTER the write (the id is final and the row exists) and never read
            # back -- nothing here reaches the payload or the audit row.
            self._fill_audit_out(
                audit_out,
                audit_id=audit_id,
                cost_usd=cost_usd,
                provider="anthropic",
                model=model,
                duration_ms=duration_ms,
            )

        return resp

    async def serpapi_search(
        self,
        *,
        run_id: uuid.UUID,
        tenant_id: uuid.UUID,
        q: str,
        hl: str = "",
        gl: str = "",
        google_domain: str = "",
        location: str = "",
        num: int = 10,
        plan: Any = None,
        client: Any = None,
        audit_out: Optional[dict[str, Any]] = None,
    ) -> dict:
        """Run ONE audited SerpApi search for the D10 own-researcher (15.2-12).

        THE ONLY SANCTIONED SerpApi EGRESS. Phase rule 1 routes all provider
        egress through `audited.*`; SerpApi is not a model endpoint, but its calls
        are audited anyway for C1 cost truth -- the run total is
        `SELECT SUM(cost_usd) FROM audit_log WHERE run_id = :id`
        (`runs/worker.py:150/172/231`), so an audited SerpApi row lands in the
        run's cost with zero extra wiring, and an UN-audited one would be an
        untracked cost class (T-15.2-36).

        A SerpApi row is a new ROW, not a new FIELD. `_build_payload_dict`'s 11
        frozen chain fields are passed exactly as they stand and nothing is added
        to them, so `verify_chain` and `test_hash_chain_replay.py` are unaffected
        (EU AI Act Art. 12; see the Canonical JSON rule in the module docstring).

        COST (D-16). Billable is `search_metadata.status == "Success"` and
        nothing else -- SerpApi does not bill cached, errored or failed searches,
        so a non-billable search costs exactly `Decimal("0")`, and that zero is a
        FACT rather than an absence. When the plan's unit price is unknown,
        `compute` returns None, this method flags the run `cost_pending` through
        the same defensive `getattr` the deep-research path uses, and the row is
        written with a NULL cost. No tier price is ever guessed.

        SECRET HYGIENE (T-15.2-31). The SerpApi key rides in the QUERY STRING, so
        the audit request blob is built from a whitelist that contains no
        `api_key` under any spelling and no full URL at all -- only the path. The
        `gcs_blob` redactor is belt-and-braces here, not the control.

        Args:
          plan:   a `serpapi.SerpApiPlan` (or None). Supplies the published unit
                  price in force for this run.
          client: test seam forwarded to `serpapi.search`; None uses real httpx.

        Returns:
          {"billable", "status", "results", "metadata", "cost_usd", "audit_id"}

        Raises:
          SerpApiError (or any other provider exception) after recording the
          failure on the SerpApi breaker and writing a failure audit row. The
          agent loop -- not this method -- owns the retry/degrade decision.
        """
        # Local import: keeps module load light and avoids an import cycle
        # (pipeline.tribunal imports audit). Same idiom as the httpx import at
        # gemini_deep_research_raw.
        from nestor_pulse_sdk.pipeline.tribunal import serpapi as _serpapi  # noqa: PLC0415

        async with _SEMAPHORE:
            started = time.monotonic()
            started_dt = datetime.now(tz=timezone.utc)

            try:
                result = await _serpapi.search(
                    q=q,
                    hl=hl,
                    gl=gl,
                    google_domain=google_domain,
                    location=location,
                    num=num,
                    client=client,
                )
            except Exception as exc:
                # Let the breaker see it FIRST, so a hard wall is booked even if
                # the failure-row write itself has trouble.
                try:
                    _serpapi.note_failure(exc)
                except Exception:  # noqa: BLE001 -- bookkeeping never masks the real error
                    log.warning("serpapi_search: could not record failure on the breaker")
                await self.write_failure(
                    run_id=run_id, tenant_id=tenant_id, provider="serpapi", error=exc
                )
                raise

            duration_ms = int((time.monotonic() - started) * 1000)

            billable_count = 1 if result.get("billable") else 0
            unit = getattr(plan, "unit_price_usd", None) if plan is not None else None
            cost_usd = self._costs.compute(
                provider="serpapi",
                model="google",
                prompt_tokens=0,
                completion_tokens=0,
                cached_tokens=0,
                serpapi_search_count=billable_count,
                serpapi_unit_price_usd=unit,
            )

            if cost_usd is None:
                # The SerpApi plan could not be established, so the exact fee is
                # not knowable yet. Flag it, never estimate it (C1 / D-16).
                mark_pending = getattr(self._audit, "mark_cost_pending", None)
                if callable(mark_pending):
                    try:
                        await mark_pending(run_id=run_id, tenant_id=tenant_id)
                    except Exception as exc:  # noqa: BLE001
                        log.warning(
                            "serpapi_search: mark_cost_pending failed (run=%s): %s",
                            run_id,
                            exc,
                        )
                log.warning(
                    "serpapi_search: no published unit price for this run's SerpApi "
                    "plan -- writing NULL cost_usd + cost_pending rather than a guess"
                )

            # WHITELIST. No api_key under any spelling, and no full URL -- only
            # the path. What we never carry, we can never leak (T-15.2-31).
            request_dict = {
                "url_path": "/search.json",
                "engine": "google",
                "q": str(q or "")[:2000],
                "hl": hl,
                "gl": gl,
                "google_domain": google_domain,
                "location": location,
                "num": num,
            }
            response_dict = {
                "status": result.get("status"),
                "billable": result.get("billable"),
                "search_id": result.get("search_id"),
                "result_count": len(result.get("results") or []),
                # Already coerced, truncated and http(s)-filtered by _clean_results.
                "results": result.get("results") or [],
            }

            audit_id = uuid.uuid4()
            gcs_uri = await self._gcs.upload_audit_body(
                run_id=run_id,
                audit_id=audit_id,
                provider="serpapi",
                model="google",
                request_dict=request_dict,
                response_dict=response_dict,
            )

            # Critical section: seq+hash assignment serialized per run (T-16-01).
            async with self._run_lock(run_id):
                prev_hash, seq = await self._audit.get_prev_hash_and_seq(run_id, tenant_id)
                payload = _build_payload_dict(
                    provider="serpapi", model="google", started_dt=started_dt,
                    duration_ms=duration_ms, prompt_tokens=0,
                    completion_tokens=0, cached_tokens=0,
                    gcs_uri=gcs_uri, seq=seq, tenant_id=tenant_id, run_id=run_id,
                )
                row_hash = self._chain.link_hash(prev_hash, payload)

                await self._audit.write_full_row(
                    audit_id=audit_id,
                    run_id=run_id,
                    tenant_id=tenant_id,
                    seq=seq,
                    provider="serpapi",
                    model="google",
                    started_at=started_dt,
                    duration_ms=duration_ms,
                    prompt_tokens=0,
                    completion_tokens=0,
                    cached_tokens=0,
                    cache_creation_tokens=0,
                    cost_usd=cost_usd,
                    gcs_uri=gcs_uri,
                    prev_hash=prev_hash,
                    hash=row_hash,
                )

            # F4 -- the SHARED helper from 15.2-03. Additive, post-write, never
            # read back, and it touches neither the row nor the frozen payload.
            self._fill_audit_out(
                audit_out,
                audit_id=audit_id,
                cost_usd=cost_usd,
                provider="serpapi",
                model="google",
                duration_ms=duration_ms,
            )

        return {
            "billable": bool(result.get("billable")),
            "status": result.get("status") or "",
            "results": result.get("results") or [],
            "metadata": result.get("metadata") or {},
            "cost_usd": cost_usd,
            "audit_id": str(audit_id),
        }

    async def gemini_generate(
        self,
        *,
        run_id: uuid.UUID,
        tenant_id: uuid.UUID,
        model: str,
        contents: Any,
        audit_out: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ):
        """
        Call self._g.models.generate_content(model, contents, config=...) + write audit row.

        google-genai exposes usage_metadata:
          - prompt_token_count
          - candidates_token_count

        audit_out (F4 -- 15.2 plan 03, ADDITIVE): see `anthropic_messages` for the
        full rationale. Same contract, `provider == "google"`. Optional, keyword-only,
        declared ahead of **kwargs so it is never forwarded to the provider SDK
        (an unknown key there is an HTTP 400), populated after the audit row is
        written, and writing nothing to the DB or the frozen hash-chain payload.
        """
        async with _SEMAPHORE:
            started = time.monotonic()
            started_dt = datetime.now(tz=timezone.utc)

            # google-genai sync call wrapped in to_thread (matches _llm() in steps.py)
            def _call():
                return self._g.models.generate_content(
                    model=model, contents=contents, **kwargs
                )

            resp = await asyncio.to_thread(_call)
            duration_ms = int((time.monotonic() - started) * 1000)

            usage = getattr(resp, "usage_metadata", None)
            prompt_tokens = getattr(usage, "prompt_token_count", 0) or 0
            completion_tokens = getattr(usage, "candidates_token_count", 0) or 0
            # Gemini does not have prompt caching in the same sense; cached_tokens = 0
            cached_tokens = 0

            cost_usd = self._costs.compute(
                provider="google",
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cached_tokens=cached_tokens,
            )

            request_dict = {"model": model, "contents": str(contents)[:2000]}
            response_dict = self._response_to_dict(resp)

            audit_id = uuid.uuid4()
            gcs_uri = await self._gcs.upload_audit_body(
                run_id=run_id,
                audit_id=audit_id,
                provider="google",
                model=model,
                request_dict=request_dict,
                response_dict=response_dict,
            )

            # Critical section: seq+hash assignment serialized per run (T-16-01).
            async with self._run_lock(run_id):
                prev_hash, seq = await self._audit.get_prev_hash_and_seq(run_id, tenant_id)
                payload = _build_payload_dict(
                    provider="google", model=model, started_dt=started_dt,
                    duration_ms=duration_ms, prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens, cached_tokens=cached_tokens,
                    gcs_uri=gcs_uri, seq=seq, tenant_id=tenant_id, run_id=run_id,
                )
                row_hash = self._chain.link_hash(prev_hash, payload)

                await self._audit.write_full_row(
                    audit_id=audit_id,
                    run_id=run_id,
                    tenant_id=tenant_id,
                    seq=seq,
                    provider="google",
                    model=model,
                    started_at=started_dt,
                    duration_ms=duration_ms,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    cached_tokens=cached_tokens,
                    cost_usd=cost_usd,
                    gcs_uri=gcs_uri,
                    prev_hash=prev_hash,
                    hash=row_hash,
                )

            # F4 -- see anthropic_messages. Additive, post-write, never read back.
            self._fill_audit_out(
                audit_out,
                audit_id=audit_id,
                cost_usd=cost_usd,
                provider="google",
                model=model,
                duration_ms=duration_ms,
            )

        return resp

    @staticmethod
    def _fill_audit_out(
        audit_out: Any,
        *,
        audit_id: uuid.UUID,
        cost_usd: Any,
        provider: str,
        model: str,
        duration_ms: int,
    ) -> None:
        """Populate a caller-supplied out-param dict with this call's audit facts.

        F4 (15.2 plan 03). STRICTLY additive and one-way: this writes only into the
        caller's own dict, is never read back, and touches neither the audit row nor
        the frozen hash-chain payload.

        A caller that passes something which is not a dict must not be able to break
        an LLM call that already succeeded and was already audited -- so a non-dict
        is a debug line, not an exception.

        `cost_usd` is stringified, never float()ed: `StageDetailItem.cost_usd` is
        `str | None` and the exact Decimal cent text must survive into JSONB.
        """
        if not isinstance(audit_out, dict):
            if audit_out is not None:
                log.debug(
                    "audit_out is %s, not a dict -- audit facts not surfaced",
                    type(audit_out).__name__,
                )
            return
        audit_out["audit_id"] = str(audit_id)
        audit_out["cost_usd"] = str(cost_usd)
        audit_out["provider"] = provider
        audit_out["model"] = model
        audit_out["duration_ms"] = duration_ms

    async def openai_response(
        self,
        *,
        run_id: uuid.UUID,
        tenant_id: uuid.UUID,
        model: str,
        **kwargs: Any,
    ):
        """
        Call OpenAI API + write audit row.

        OpenAI responses expose usage.input_tokens, usage.output_tokens,
        and usage.input_tokens_details.cached_tokens for prompt caching.
        """
        async with _SEMAPHORE:
            started = time.monotonic()
            started_dt = datetime.now(tz=timezone.utc)

            from openai import AsyncOpenAI  # type: ignore

            client = self._a if hasattr(self._a, "responses") else AsyncOpenAI()
            resp = await client.responses.create(model=model, **kwargs)
            duration_ms = int((time.monotonic() - started) * 1000)

            usage = getattr(resp, "usage", None)
            prompt_tokens = getattr(usage, "input_tokens", 0) or 0
            completion_tokens = getattr(usage, "output_tokens", 0) or 0
            # OpenAI: cached input tokens in usage.input_tokens_details.cached_tokens
            details = getattr(usage, "input_tokens_details", None)
            cached_tokens = getattr(details, "cached_tokens", 0) or 0

            cost_usd = self._costs.compute(
                provider="openai",
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cached_tokens=cached_tokens,
            )

            request_dict = {"model": model, **kwargs}
            response_dict = self._response_to_dict(resp)

            audit_id = uuid.uuid4()
            gcs_uri = await self._gcs.upload_audit_body(
                run_id=run_id,
                audit_id=audit_id,
                provider="openai",
                model=model,
                request_dict=request_dict,
                response_dict=response_dict,
            )

            # Critical section: seq+hash assignment serialized per run (T-16-01).
            async with self._run_lock(run_id):
                prev_hash, seq = await self._audit.get_prev_hash_and_seq(run_id, tenant_id)
                payload = _build_payload_dict(
                    provider="openai", model=model, started_dt=started_dt,
                    duration_ms=duration_ms, prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens, cached_tokens=cached_tokens,
                    gcs_uri=gcs_uri, seq=seq, tenant_id=tenant_id, run_id=run_id,
                )
                row_hash = self._chain.link_hash(prev_hash, payload)

                await self._audit.write_full_row(
                    audit_id=audit_id,
                    run_id=run_id,
                    tenant_id=tenant_id,
                    seq=seq,
                    provider="openai",
                    model=model,
                    started_at=started_dt,
                    duration_ms=duration_ms,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    cached_tokens=cached_tokens,
                    cost_usd=cost_usd,
                    gcs_uri=gcs_uri,
                    prev_hash=prev_hash,
                    hash=row_hash,
                )

        return resp

    async def write_failure(
        self,
        *,
        run_id: uuid.UUID,
        tenant_id: uuid.UUID,
        provider: str,
        error: Exception,
    ) -> None:
        """
        Write a failure audit row with cost_usd=None and a small error-detail GCS blob.
        Used when an LLM call raises an exception before returning usage data.
        """
        started_dt = datetime.now(tz=timezone.utc)
        audit_id = uuid.uuid4()
        error_dict = {"error": str(error), "type": type(error).__name__}

        try:
            gcs_uri = await self._gcs.upload_audit_body(
                run_id=run_id,
                audit_id=audit_id,
                provider=provider,
                model="unknown",
                request_dict={},
                response_dict=error_dict,
            )
        except Exception:
            gcs_uri = f"error://no-gcs-upload/{run_id}"

        # Critical section: seq+hash assignment serialized per run (T-16-01).
        async with self._run_lock(run_id):
            prev_hash, seq = await self._audit.get_prev_hash_and_seq(run_id, tenant_id)
            payload = _build_payload_dict(
                provider=provider, model="unknown", started_dt=started_dt,
                duration_ms=0, prompt_tokens=0, completion_tokens=0, cached_tokens=0,
                gcs_uri=gcs_uri, seq=seq, tenant_id=tenant_id, run_id=run_id,
            )
            row_hash = self._chain.link_hash(prev_hash, payload)

            await self._audit.write_full_row(
                audit_id=audit_id,
                run_id=run_id,
                tenant_id=tenant_id,
                seq=seq,
                provider=provider,
                model="unknown",
                started_at=started_dt,
                duration_ms=0,
                prompt_tokens=0,
                completion_tokens=0,
                cached_tokens=0,
                cost_usd=None,
                gcs_uri=gcs_uri,
                prev_hash=prev_hash,
                hash=row_hash,
            )

    # =========================================================================
    # Two-phase methods (deep-research path; consumed by Plan 09 adapters)
    # =========================================================================

    async def start_call(
        self,
        *,
        run_id: uuid.UUID,
        tenant_id: uuid.UUID,
        provider: str,
        model: str,
        request: dict,
    ) -> AuditHandle:
        """
        Capture start metadata and return an AuditHandle. NO DB write.

        Seq and prev_hash are assigned at completion in end_call() under the
        per-run lock, so concurrent deep-research providers never collide on
        uq_audit_tenant_run_seq (T-16-01, completion-order assignment).

        Crash-recovery trade-off: because no placeholder row is written here,
        a worker crash between start_call and end_call leaves NO audit row
        (rather than an orphaned IN_FLIGHT_PLACEHOLDER). This is an accepted
        trade-off scoped to single-worker scale (T-16-03); robust crash-recovery
        is deferred to Phase 2. insert_placeholder/finalize_row remain in
        writer.py (unused by this client) for future use.

        Returns AuditHandle with sentinel seq=-1/prev_hash="" (assigned in end_call).
        """
        started_dt = datetime.now(tz=timezone.utc)
        audit_id = uuid.uuid4()

        # 15.3-04: bind this task's run so the long poll that follows can narrate
        # itself. Best-effort and never load-bearing -- a failure here costs the
        # poll's feed lines, never the call. See `_CURRENT_RUN` for why the
        # binding lives in this method.
        try:
            _CURRENT_RUN.set(run_id)
        except Exception as exc:  # noqa: BLE001 -- an observability binding may never fail a call
            log.warning(
                "audited: could not bind the run for poll events (%r) -- the "
                "deep-research call proceeds with no progress lines", exc,
            )

        return AuditHandle(
            audit_id=audit_id,
            run_id=run_id,
            tenant_id=tenant_id,
            seq=-1,       # sentinel -- assigned under lock in end_call
            prev_hash="",  # sentinel -- assigned under lock in end_call
            started_at=time.monotonic(),
            started_dt=started_dt,
            provider=provider,
            model=model,
            request_dict=request,
        )

    async def end_call(
        self,
        handle: AuditHandle,
        *,
        response: dict,
        status: Literal["success", "error", "timeout"],
    ) -> None:
        """
        Write a full audit row for a completed deep-research call.

        Seq and prev_hash are assigned here under the per-run lock (completion-order
        assignment) so concurrent providers never collide on uq_audit_tenant_run_seq
        (T-16-01). The slow GCS upload happens OUTSIDE the lock so parallel providers
        continue uploading their bodies concurrently.

        Unlike the old two-phase approach (placeholder + UPDATE), this path does a
        single INSERT via write_full_row once the call has completed.

        Args:
          handle:   AuditHandle returned by start_call.
          response: Provider response dict (may be partial on error/timeout).
          status:   "success", "error", or "timeout".
        """
        async with _SEMAPHORE:
            duration_ms = int((time.monotonic() - handle.started_at) * 1000)

            # Extract usage from response (provider-shaped)
            usage = response.get("usage", {})
            # Plan 15-02 C1: deep-research grounding-fee pending flag. Set True only
            # when a DR call completes WITHOUT usageMetadata -- its un-itemizable
            # grounding/search fee is then backfilled from GCP billing, never estimated.
            dr_cost_pending = False
            cache_creation_tokens = 0
            web_search_count = 0
            web_fetch_count = 0
            if handle.provider == "anthropic":
                prompt_tokens = usage.get("input_tokens", 0) or 0
                completion_tokens = usage.get("output_tokens", 0) or 0
                # Pitfall 6: explicit cache token extraction
                cached_tokens = usage.get("cache_read_input_tokens", 0) or 0
                # WR-01 / Plan 15-02 C1: the two-phase path must count the SAME
                # facts the atomic anthropic_messages path counts -- cache-WRITE
                # tokens (charged at the 5m rate) and server-tool invocations
                # (published flat fees). Omitting them silently under-priced any
                # Anthropic call routed through start_call/end_call and dropped
                # the cache_creation_tokens fact from the audit row.
                cache_creation_tokens = usage.get("cache_creation_input_tokens", 0) or 0
                web_search_count, web_fetch_count = _extract_anthropic_tool_counts(usage)
            elif handle.provider == "google":
                # Plan 15-02 C1: Gemini deep-research returns camelCase usageMetadata
                # (promptTokenCount/candidatesTokenCount/thoughtsTokenCount). Thoughts
                # bill at the output rate, so fold them into completion_tokens.
                dr_meta = response.get("usageMetadata")
                if isinstance(dr_meta, dict) and dr_meta:
                    prompt_tokens = int(dr_meta.get("promptTokenCount", 0) or 0)
                    candidates = int(dr_meta.get("candidatesTokenCount", 0) or 0)
                    thoughts = int(dr_meta.get("thoughtsTokenCount", 0) or 0)
                    completion_tokens = candidates + thoughts
                else:
                    # No usageMetadata (confirmed for recorded run-4cbb5311): fall back
                    # to the flat-shape usage dict if any; mark the grounding fee pending.
                    prompt_tokens = usage.get("prompt_token_count", 0) or 0
                    completion_tokens = usage.get("candidates_token_count", 0) or 0
                    if status == "success":
                        dr_cost_pending = True
                cached_tokens = 0
            elif handle.provider == "openai":
                prompt_tokens = usage.get("input_tokens", 0) or 0
                completion_tokens = usage.get("output_tokens", 0) or 0
                details = usage.get("input_tokens_details", {})
                cached_tokens = details.get("cached_tokens", 0) if isinstance(details, dict) else 0
            else:
                prompt_tokens = 0
                completion_tokens = 0
                cached_tokens = 0

            # Pitfall 5: unknown model -> None. Cache-write + server-tool facts
            # enter the price exactly as on the atomic path (WR-01 / C1).
            cost_usd = self._costs.compute(
                provider=handle.provider,
                model=handle.model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cached_tokens=cached_tokens,
                cache_creation_tokens=cache_creation_tokens,
                web_search_count=web_search_count,
                web_fetch_count=web_fetch_count,
            )

            # Plan 15-02 C1: flag the run's grounding fee as pending (backfilled from
            # billing) when a DR call has no usageMetadata. The production writer
            # (DBAuditWriter.mark_cost_pending) implements this; a writer that lacks
            # the method is a PROTOCOL BUG -- the pending fact would be silently lost
            # and an incomplete cost presented as settled (the CR-02 defect), so the
            # missing-method case logs at ERROR instead of silently no-opping.
            if dr_cost_pending:
                mark_pending = getattr(self._audit, "mark_cost_pending", None)
                if callable(mark_pending):
                    try:
                        await mark_pending(run_id=handle.run_id, tenant_id=handle.tenant_id)
                    except Exception as exc:  # never fail the audit write on a flag update
                        log.warning("mark_cost_pending failed (run=%s): %s", handle.run_id, exc)
                else:
                    log.error(
                        "audit writer %s lacks mark_cost_pending -- run %s cost_pending "
                        "NOT persisted (C1 facts-only cost violated; fix the writer)",
                        type(self._audit).__name__,
                        handle.run_id,
                    )

            # GCS upload OUTSIDE the per-run lock (slow; handle.audit_id is the stable
            # unique key component -- guaranteed unique per call regardless of provider/model).
            gcs_uri = await self._gcs.upload_audit_body(
                run_id=handle.run_id,
                audit_id=handle.audit_id,
                provider=handle.provider,
                model=handle.model,
                request_dict=handle.request_dict,
                response_dict=response,
            )

            # Critical section: seq+hash assignment serialized per run (T-16-01).
            # Single INSERT via write_full_row (no placeholder to UPDATE).
            async with self._run_lock(handle.run_id):
                prev_hash, seq = await self._audit.get_prev_hash_and_seq(
                    handle.run_id, handle.tenant_id
                )
                payload = _build_payload_dict(
                    provider=handle.provider,
                    model=handle.model,
                    started_dt=handle.started_dt,
                    duration_ms=duration_ms,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    cached_tokens=cached_tokens,
                    gcs_uri=gcs_uri,
                    seq=seq,
                    tenant_id=handle.tenant_id,
                    run_id=handle.run_id,
                )
                real_hash = self._chain.link_hash(prev_hash, payload)

                await self._audit.write_full_row(
                    audit_id=handle.audit_id,
                    run_id=handle.run_id,
                    tenant_id=handle.tenant_id,
                    seq=seq,
                    provider=handle.provider,
                    model=handle.model,
                    started_at=handle.started_dt,
                    duration_ms=duration_ms,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    cached_tokens=cached_tokens,
                    # WR-01: persist the cache-write token FACT (non-hashed column,
                    # additive -- same as the atomic path). NULL for non-anthropic
                    # providers (fact not applicable); a counted 0 stays 0.
                    cache_creation_tokens=(
                        cache_creation_tokens if handle.provider == "anthropic" else None
                    ),
                    cost_usd=cost_usd,
                    gcs_uri=gcs_uri,
                    prev_hash=prev_hash,
                    hash=real_hash,
                )

    # =========================================================================
    # Deep-research raw methods (provider-owned polling; NO legacy delegation)
    # =========================================================================

    async def gemini_deep_research_raw(
        self,
        query: str,
        *,
        agent: str = GEMINI_DEEP_RESEARCH_AGENT,
        max_attempts: int = 70,
        poll_interval: int = 30,
        resume_job_id: str | None = None,
        on_job_started: Callable[[str], Awaitable[None]] | None = None,
    ) -> dict:
        """Poll the Gemini deep-research API and return the canonical envelope.

        Returns {"status": "success"|"error"|"timeout", "report"|"error_message": ...}.

        Issued over REST (httpx) against the v1beta /interactions endpoint with the
        `Api-Revision: 2026-05-20` header so the pinned google-genai 1.75 client
        receives the new "steps" schema. See GEMINI_INTERACTIONS_BASE notes above
        for why the SDK cannot be bumped to >= 2.0. The create call returns
        immediately (background=True); we poll GET until status is completed/failed.

        R7 (plan 15.2-16) — RESUME INSTEAD OF PAYING TWICE. The dispatch is
        `background: true`, so the interaction keeps running on Google's side
        even when this process dies or the run parks. Two additive keyword-only
        parameters make that reconnectable, and NEITHER changes today's
        behaviour when omitted:

          resume_job_id:   an interaction id recorded by a previous attempt. When
                           present (and accepted by `safe_job_id`) the dispatch
                           POST is SKIPPED entirely and the poll loop reconnects
                           to the existing job. A rejected id falls through to a
                           fresh dispatch, loudly.
          on_job_started:  awaited once with the interaction id the moment a
                           FRESH background job exists, so the caller can record
                           it before the long poll begins. Best-effort — a
                           callback that raises is logged and swallowed, because
                           a checkpoint write must never break a paid call.

        The poll loop itself is UNCHANGED. R7 adds a reconnect entry point and a
        404/410 rule; it does not rebuild the polling.
        """
        import httpx  # noqa: PLC0415 -- local import keeps module load light

        api_key = (
            os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY")
            or ""
        )
        if not api_key:
            return {
                "status": "error",
                "error_message": "GEMINI_API_KEY/GOOGLE_API_KEY not set",
            }

        base = GEMINI_INTERACTIONS_BASE.rstrip("/")
        create_headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
            "Api-Revision": GEMINI_INTERACTIONS_REVISION,
        }
        get_headers = {
            "x-goog-api-key": api_key,
            "Api-Revision": GEMINI_INTERACTIONS_REVISION,
        }

        # T-15.2-125: the id is interpolated into a URL PATH below, and on a
        # resume it arrives from an `output` row rather than from the provider.
        # A rejected id is NOT fatal — it falls through to a fresh dispatch — but
        # it never reaches the URL builder.
        resumed_id = safe_job_id(resume_job_id) if resume_job_id else None
        # 15.3-04: the run this poll belongs to, read ONCE at entry. None on a
        # call path with no run context, and then every event below is skipped.
        _run = _CURRENT_RUN.get()
        if resume_job_id and resumed_id is None:
            log.warning(
                "Gemini deep-research: the recorded job id was refused by the "
                "job-id guard, so this angle is dispatched fresh rather than "
                "polled — nothing was reconnected"
            )
            if _run is not None:
                run_events.emit_safe(
                    _run,
                    stage="deep_research",
                    kind="thinking",
                    build=lambda: (
                        "A recorded Google research job id was refused by the "
                        "job-id guard — this angle is dispatched fresh rather "
                        "than rejoined, so it is paid for again.",
                        {"provider": "google", "model": agent},
                    ),
                )

        try:
            # Per-request timeout only; the long wait is the poll loop, not one call.
            async with httpx.AsyncClient(timeout=60.0) as http:
                if resumed_id is not None:
                    # SKIP THE DISPATCH POST ENTIRELY. The interaction is still
                    # running on Google's side and has already been paid for.
                    interaction_id = resumed_id
                    log.warning(
                        "Gemini deep-research: RESUMING the existing interaction "
                        "%s (agent=%s) — no second job was dispatched and nothing "
                        "was charged twice",
                        interaction_id, agent,
                    )
                    # The money-relevant fact, on the feed rather than only in
                    # Cloud Logging: this angle rejoined work already paid for.
                    if _run is not None:
                        run_events.emit_safe(
                            _run,
                            stage="deep_research",
                            kind="thinking",
                            build=lambda: (
                                "Rejoined the in-flight Google research job"
                                f"{_job_id_phrase(interaction_id)} — no second "
                                "job was dispatched and nothing was charged "
                                f"twice. Polling every {poll_interval}s.",
                                {"provider": "google", "model": agent},
                            ),
                        )
                else:
                    log.debug(
                        "Gemini deep-research: starting interaction (agent=%s)", agent
                    )
                    resp = await http.post(
                        f"{base}/interactions",
                        headers=create_headers,
                        json={"input": query, "agent": agent, "background": True},
                    )
                    resp.raise_for_status()
                    interaction = resp.json()
                    raw_id = interaction.get("id") or interaction.get("name") or ""
                    # Some responses return a fully-qualified name ("interactions/abc").
                    raw_id = str(raw_id).split("/")[-1]
                    if not raw_id:
                        return {
                            "status": "error",
                            "error_message": (
                                "Research error: no interaction id in create response: "
                                f"{str(interaction)[:300]}"
                            ),
                        }
                    interaction_id = safe_job_id(raw_id)
                    if interaction_id is None:
                        # NEVER interpolate an unvalidated provider id into the
                        # poll URL (T-15.2-125). Fail in words instead.
                        return {
                            "status": "error",
                            "error_message": (
                                "Research error: the interaction id returned by the "
                                f"provider is malformed and was refused: {raw_id[:80]!r}"
                            ),
                        }
                    if on_job_started is not None:
                        try:
                            await on_job_started(interaction_id)
                        except Exception as cb_exc:  # noqa: BLE001 — checkpoint writes are best-effort
                            log.warning(
                                "Gemini deep-research: on_job_started callback failed "
                                "(%r) — the job is running but was not recorded, so a "
                                "resume would re-dispatch it",
                                cb_exc,
                            )

                for _attempt in range(max_attempts):
                    await asyncio.sleep(poll_interval)
                    try:
                        g = await http.get(
                            f"{base}/interactions/{interaction_id}", headers=get_headers
                        )
                        g.raise_for_status()
                    except httpx.HTTPStatusError as http_exc:
                        code = getattr(
                            getattr(http_exc, "response", None), "status_code", 0
                        )
                        if resumed_id is not None and code in (404, 410):
                            if RESUME_REDISPATCH:
                                log.warning(
                                    "Gemini deep-research: the resumed interaction is "
                                    "gone (HTTP %s) and NESTOR_TRIBUNAL_RESUME_REDISPATCH "
                                    "is on — dispatching a FRESH, separately billed job",
                                    code,
                                )
                                return await self.gemini_deep_research_raw(
                                    query,
                                    agent=agent,
                                    max_attempts=max_attempts,
                                    poll_interval=poll_interval,
                                    resume_job_id=None,
                                    on_job_started=on_job_started,
                                )
                            return {
                                "status": "error",
                                "error_message": (
                                    "Research error: the resumed Gemini research job "
                                    f"is no longer retrievable (HTTP {code}). This "
                                    "research stream was lost and was NOT "
                                    "re-dispatched, so nothing has been charged twice."
                                ),
                            }
                        raise
                    interaction = g.json()
                    status = interaction.get("status")
                    if status in ("completed", "done"):
                        log.info("Gemini deep-research completed (agent=%s)", agent)
                        report_text = extract_report_from_steps(interaction)
                        # Plan 15-02 C1: surface usageMetadata (promptTokenCount/
                        # candidatesTokenCount/thoughtsTokenCount) so end_call can price
                        # the DR call from facts. ABSENT for recorded run-4cbb5311 -> the
                        # value is None and end_call sets cost_pending (never estimated).
                        envelope = {"status": "success", "report": report_text}
                        dr_usage = _extract_gemini_dr_usage(interaction)
                        if dr_usage is not None:
                            envelope["usageMetadata"] = dr_usage
                        return envelope
                    if status in ("failed", "error", "cancelled"):
                        error = interaction.get("error", "unknown error")
                        log.warning("Gemini deep-research failed: %s", error)
                        if _run is not None:
                            run_events.emit_safe(
                                _run,
                                stage="deep_research",
                                kind="agent_fail",
                                build=lambda: (
                                    f"Google research job reported {status} — "
                                    f"{str(interaction.get('error') or 'no reason given')[:200]}",
                                    {"provider": "google", "model": agent},
                                ),
                            )
                        return {
                            "status": "error",
                            "error_message": f"Research failed: {error}",
                        }

                timeout_msg = (
                    f"Research timed out after {max_attempts * poll_interval / 60:.0f} minutes"
                )
                log.warning("Gemini deep-research timed out (agent=%s)", agent)
                if _run is not None:
                    run_events.emit_safe(
                        _run,
                        stage="deep_research",
                        kind="agent_fail",
                        build=lambda: (
                            f"Google research gave up after {max_attempts} polls "
                            f"({max_attempts * poll_interval / 60:.0f} minutes) — "
                            "the job never reached a terminal state. This is the "
                            "poll budget running out, not a crash.",
                            {
                                "provider": "google",
                                "model": agent,
                                "attempt": max_attempts,
                                "max": max_attempts,
                            },
                        ),
                    )
                return {"status": "timeout", "error_message": timeout_msg}

        except Exception as exc:
            log.error("Gemini deep-research error: %s", exc)
            return {"status": "error", "error_message": f"Research error: {exc}"}

    async def openai_deep_research_raw(
        self,
        query: str,
        *,
        model: str = OPENAI_DEEP_RESEARCH_MODEL,
        max_attempts: int = 70,
        poll_interval: int = 30,
        max_connect_retries: int = 3,
        resume_job_id: str | None = None,
        on_job_started: Callable[[str], Awaitable[None]] | None = None,
    ) -> dict:
        """Poll the OpenAI deep-research Responses API and return the canonical envelope.

        Returns {"status": "success"|"error"|"timeout", "report"|"error_message": ...}.

        Transient connection/timeout errors on the initial responses.create call are
        retried up to max_connect_retries times with exponential back-off (2**attempt s).
        Clean failure statuses ("failed", "cancelled", "incomplete") are NOT retried.

        R7 (plan 15.2-16) — the same two additive keyword-only parameters as the
        Gemini method, with the same contract: `resume_job_id` skips
        `responses.create` entirely and reconnects to the existing background
        response; `on_job_started` is awaited once with a FRESH response id and
        is best-effort.

        THE ONE OPENAI-SPECIFIC DIFFERENCE. A background response is retained
        for roughly ten minutes after it finishes, so a resume that arrives late
        gets `NotFoundError` / HTTP 404. Under DEC-2 that DEGRADES this one
        stream with a named reason (`RESUME_REDISPATCH` false, the default); it
        never crashes the run and never silently pays for the job twice.
        """
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            return {"status": "error", "error_message": "OPENAI_API_KEY not set"}

        # Defensive import of transient error types -- fall back to a repr-based check
        # across openai package versions.
        try:
            from openai import APIConnectionError as _ConnErr, APITimeoutError as _ToutErr  # noqa: PLC0415
            _TRANSIENT = (_ConnErr, _ToutErr)
        except ImportError:
            _TRANSIENT = ()  # type: ignore[assignment]

        def _is_transient(exc: Exception) -> bool:
            if _TRANSIENT and isinstance(exc, _TRANSIENT):
                return True
            name = type(exc).__name__
            rep = repr(exc)
            return "Connection" in rep or "Timeout" in rep or "Connection" in name or "Timeout" in name

        # --- R7 (plan 15.2-16): resume support -------------------------------
        # The local transient-error predicate above is the CREATE-retry rule and
        # is deliberately untouched. The two helpers below concern a RESUMED id
        # only, which is a different question with a different answer.
        resumed_id = safe_job_id(resume_job_id) if resume_job_id else None
        # 15.3-04: the run this poll belongs to, read ONCE at entry. See the
        # matching line in the Gemini method and `_CURRENT_RUN`.
        _run = _CURRENT_RUN.get()
        if resume_job_id and resumed_id is None:
            log.warning(
                "OpenAI deep-research: the recorded response id was refused by the "
                "job-id guard, so this angle is dispatched fresh rather than "
                "polled — nothing was reconnected"
            )
            if _run is not None:
                run_events.emit_safe(
                    _run,
                    stage="deep_research",
                    kind="thinking",
                    build=lambda: (
                        "A recorded OpenAI research response id was refused by "
                        "the job-id guard — this angle is dispatched fresh "
                        "rather than rejoined, so it is paid for again.",
                        {"provider": "openai", "model": model},
                    ),
                )

        def _is_not_found(exc: Exception) -> bool:
            """True for the "this response no longer exists" family. Never raises.

            Read defensively across openai package versions: the class NAME, then
            any int/str status attribute, then a nested response object.
            """
            try:
                if type(exc).__name__ == "NotFoundError":
                    return True
                for attr in ("status_code", "status", "code"):
                    value = getattr(exc, attr, None)
                    if isinstance(value, bool):
                        continue
                    if isinstance(value, int) and value == 404:
                        return True
                    if isinstance(value, str) and value.strip() == "404":
                        return True
                nested = getattr(exc, "response", None)
                return getattr(nested, "status_code", None) == 404
            except Exception:  # noqa: BLE001 — a predicate that raises is worse than a False
                return False

        async def _resume_gone_result() -> dict:
            """DEC-2: degrade this stream by default; re-dispatch only on request."""
            if RESUME_REDISPATCH:
                log.warning(
                    "OpenAI deep-research: the resumed response is gone and "
                    "NESTOR_TRIBUNAL_RESUME_REDISPATCH is on — dispatching a FRESH, "
                    "separately billed job"
                )
                return await self.openai_deep_research_raw(
                    query,
                    model=model,
                    max_attempts=max_attempts,
                    poll_interval=poll_interval,
                    max_connect_retries=max_connect_retries,
                    resume_job_id=None,
                    on_job_started=on_job_started,
                )
            return {
                "status": "error",
                "error_message": (
                    "Research error: the resumed OpenAI research job is no longer "
                    "retrievable (a background response is kept for about ten "
                    "minutes after it finishes). This research stream was lost and "
                    "was NOT re-dispatched, so nothing has been charged twice."
                ),
            }

        try:
            from openai import AsyncOpenAI  # noqa: PLC0415 -- construction allowed here only

            client = AsyncOpenAI(api_key=api_key, timeout=3600)

            # ---- Retry loop for the initial create call ----
            # R7: `range(0)` on a resume — the job already exists and is already
            # paid for, so `responses.create` is never called.
            response = None
            last_exc: Exception | None = None
            for attempt in range(0 if resumed_id is not None else max_connect_retries):
                try:
                    response = await client.responses.create(
                        model=model,
                        input=query,
                        background=True,
                        tools=[{"type": "web_search_preview"}],
                    )
                    last_exc = None
                    break
                except Exception as exc:
                    if _is_transient(exc):
                        wait = 2 ** attempt
                        log.warning(
                            "OpenAI deep-research: transient error on create (attempt %d/%d), "
                            "retrying in %ds: %s",
                            attempt + 1, max_connect_retries, wait, exc,
                        )
                        last_exc = exc
                        await asyncio.sleep(wait)
                    else:
                        raise  # non-transient -- propagate immediately

            if response is None and resumed_id is None:
                return {
                    "status": "error",
                    "error_message": (
                        f"OpenAI deep-research create failed after {max_connect_retries} "
                        f"retries: {last_exc}"
                    ),
                }

            if resumed_id is not None:
                # RECONNECT IMMEDIATELY — no create, and no initial 30 s sleep, so
                # an expired id is discovered now rather than half a minute from
                # now.
                log.warning(
                    "OpenAI deep-research: RESUMING the existing response %s "
                    "(model=%s) — no second job was dispatched and nothing was "
                    "charged twice",
                    resumed_id, model,
                )
                if _run is not None:
                    run_events.emit_safe(
                        _run,
                        stage="deep_research",
                        kind="thinking",
                        build=lambda: (
                            "Rejoined the in-flight OpenAI research response"
                            f"{_job_id_phrase(resumed_id)} — no second job was "
                            "dispatched and nothing was charged twice.",
                            {"provider": "openai", "model": model},
                        ),
                    )
                try:
                    response = await client.responses.retrieve(resumed_id)
                except Exception as exc:  # noqa: BLE001 — an expired resume degrades, never crashes
                    if _is_not_found(exc):
                        return await _resume_gone_result()
                    raise
            else:
                # A FRESH background job exists: record its id before the long
                # poll, so a crash or a park mid-poll can reconnect to it.
                fresh_id = safe_job_id(getattr(response, "id", None))
                if fresh_id is None:
                    return {
                        "status": "error",
                        "error_message": (
                            "Research error: the response id returned by the provider "
                            f"is malformed and was refused: "
                            f"{str(getattr(response, 'id', ''))[:80]!r}"
                        ),
                    }
                if on_job_started is not None:
                    try:
                        await on_job_started(fresh_id)
                    except Exception as cb_exc:  # noqa: BLE001 — checkpoint writes are best-effort
                        log.warning(
                            "OpenAI deep-research: on_job_started callback failed "
                            "(%r) — the job is running but was not recorded, so a "
                            "resume would re-dispatch it",
                            cb_exc,
                        )

            # ---- Polling loop ----
            # R7: on a resume the first iteration EVALUATES the response we just
            # retrieved instead of sleeping and retrieving again. One flag, one
            # shot — the loop below is otherwise the pre-15.2 loop unchanged.
            _have_fresh = resumed_id is not None
            for _attempt in range(max_attempts):
                if _have_fresh:
                    _have_fresh = False
                else:
                    await asyncio.sleep(poll_interval)
                    try:
                        response = await client.responses.retrieve(response.id)
                    except Exception as exc:  # noqa: BLE001
                        if resumed_id is not None and _is_not_found(exc):
                            return await _resume_gone_result()
                        raise

                if response.status == "completed":
                    report = response.output_text
                    if not report:
                        return {"status": "error", "error_message": "No text content in response"}
                    log.info("OpenAI deep-research completed (model=%s)", model)
                    return {"status": "success", "report": report}
                elif response.status in ("failed", "cancelled"):
                    error = getattr(response, "error", None) or "Unknown error"
                    if _run is not None:
                        run_events.emit_safe(
                            _run,
                            stage="deep_research",
                            kind="agent_fail",
                            build=lambda: (
                                f"OpenAI research response reported "
                                f"{response.status} — "
                                f"{str(getattr(response, 'error', None) or 'no reason given')[:200]}",
                                {"provider": "openai", "model": model},
                            ),
                        )
                    return {"status": "error", "error_message": f"Research {response.status}: {error}"}
                elif response.status == "incomplete":
                    if _run is not None:
                        run_events.emit_safe(
                            _run,
                            stage="deep_research",
                            kind="agent_fail",
                            build=lambda: (
                                "OpenAI research ended incomplete — the provider "
                                "stopped before it finished, so this angle "
                                "contributes nothing.",
                                {"provider": "openai", "model": model},
                            ),
                        )
                    return {"status": "error", "error_message": "Research ended incomplete"}

            timeout_msg = (
                f"Research timed out after {max_attempts * poll_interval / 60:.0f} minutes"
            )
            log.warning("OpenAI deep-research timed out (model=%s)", model)
            if _run is not None:
                run_events.emit_safe(
                    _run,
                    stage="deep_research",
                    kind="agent_fail",
                    build=lambda: (
                        f"OpenAI research gave up after {max_attempts} polls "
                        f"({max_attempts * poll_interval / 60:.0f} minutes) — the "
                        "response never reached a terminal state. This is the "
                        "poll budget running out, not a crash.",
                        {
                            "provider": "openai",
                            "model": model,
                            "attempt": max_attempts,
                            "max": max_attempts,
                        },
                    ),
                )
            return {"status": "timeout", "error_message": timeout_msg}

        except Exception as exc:
            log.error("OpenAI deep-research error: %s", exc)
            return {"status": "error", "error_message": f"Research error: {exc}"}

    # =========================================================================
    # Private helpers
    # =========================================================================

    @staticmethod
    def _response_to_dict(resp) -> dict:
        """Convert a provider response to a JSON-serializable dict."""
        if hasattr(resp, "model_dump"):
            return resp.model_dump()
        elif hasattr(resp, "__dict__"):
            return {k: str(v) for k, v in resp.__dict__.items() if not k.startswith("_")}
        elif isinstance(resp, dict):
            return resp
        return {"raw": str(resp)}


# ---------------------------------------------------------------------------
# Payload builder -- MUST match _payload_for_row() in hash_chain.py exactly
# (Pitfall 3 -- frozen payload schema; any change breaks existing chains)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Production factory -- Plan 09 owns this. Lives in this file (rather than
# audit/__init__.py) so the "no direct provider client construction" grep
# gate's exemption (audit/audited_llm_client.py) covers the centralised
# anthropic.AsyncAnthropic() / genai.Client() calls below.
# ---------------------------------------------------------------------------

def build_audited_client(
    sessionmaker=None,
    anthropic_client=None,
    gemini_client=None,
) -> "AuditedLLMClient":
    """Construct a production AuditedLLMClient with DB-backed audit writer.

    All provider client construction is centralised here. Direct
    `anthropic.AsyncAnthropic(...)` / `genai.Client(...)` calls outside
    this file are forbidden (Plan 09 grep gate).
    """
    from nestor_pulse_sdk.db.base import get_sessionmaker
    from nestor_pulse_sdk.audit import hash_chain as hash_chain_mod
    from nestor_pulse_sdk.audit import cost_table as cost_table_mod
    from nestor_pulse_sdk.audit import gcs_blob as gcs_blob_mod
    from nestor_pulse_sdk.audit.writer import DBAuditWriter

    if sessionmaker is None:
        sessionmaker = get_sessionmaker()

    if anthropic_client is None:
        from anthropic import AsyncAnthropic  # noqa: PLC0415

        anthropic_client = AsyncAnthropic()

    if gemini_client is None:
        from google import genai  # noqa: PLC0415

        gemini_client = genai.Client()

    return AuditedLLMClient(
        anthropic_client=anthropic_client,
        gemini_client=gemini_client,
        audit_writer=DBAuditWriter(sessionmaker),
        hash_chain_mod=hash_chain_mod,
        cost_table_mod=cost_table_mod,
        gcs_blob_mod=gcs_blob_mod,
    )


def _build_payload_dict(
    *,
    provider: str,
    model: str,
    started_dt: datetime,
    duration_ms: int,
    prompt_tokens: int,
    completion_tokens: int,
    cached_tokens: int,
    gcs_uri: str,
    seq: int,
    tenant_id: uuid.UUID,
    run_id: Optional[uuid.UUID],
) -> dict:
    """
    Build the canonical payload dict for hash chain computation.

    MUST stay in sync with _payload_for_row() in hash_chain.py.
    These fields are frozen -- changing them breaks all existing chains.
    """
    return {
        "provider": provider,
        "model": model,
        "started_at": started_dt.isoformat(),
        "duration_ms": duration_ms,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cached_tokens": cached_tokens,
        "gcs_uri": gcs_uri,
        "seq": seq,
        "tenant_id": str(tenant_id),
        "run_id": str(run_id) if run_id else None,
    }
