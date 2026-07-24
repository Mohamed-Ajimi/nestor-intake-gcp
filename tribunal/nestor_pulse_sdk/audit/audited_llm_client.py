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

Canonical JSON rule (MUST stay frozen across deploys -- Pitfall 3):
  The payload passed to link_hash is built by _build_payload_dict().
  The fields in this dict MUST match _payload_for_row() in hash_chain.py exactly.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal, Optional

log = logging.getLogger(__name__)

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
OPENAI_DEEP_RESEARCH_MODEL = os.environ.get(
    "NESTOR_OPENAI_DR_MODEL", "o4-mini-deep-research"
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

        return resp

    async def gemini_generate(
        self,
        *,
        run_id: uuid.UUID,
        tenant_id: uuid.UUID,
        model: str,
        contents: Any,
        **kwargs: Any,
    ):
        """
        Call self._g.models.generate_content(model, contents, config=...) + write audit row.

        google-genai exposes usage_metadata:
          - prompt_token_count
          - candidates_token_count
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

        return resp

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
            if handle.provider == "anthropic":
                prompt_tokens = usage.get("input_tokens", 0) or 0
                completion_tokens = usage.get("output_tokens", 0) or 0
                # Pitfall 6: explicit cache token extraction
                cached_tokens = usage.get("cache_read_input_tokens", 0) or 0
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

            # Pitfall 5: unknown model -> None
            cost_usd = self._costs.compute(
                provider=handle.provider,
                model=handle.model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cached_tokens=cached_tokens,
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
    ) -> dict:
        """Poll the Gemini deep-research API and return the canonical envelope.

        Returns {"status": "success"|"error"|"timeout", "report"|"error_message": ...}.

        Issued over REST (httpx) against the v1beta /interactions endpoint with the
        `Api-Revision: 2026-05-20` header so the pinned google-genai 1.75 client
        receives the new "steps" schema. See GEMINI_INTERACTIONS_BASE notes above
        for why the SDK cannot be bumped to >= 2.0. The create call returns
        immediately (background=True); we poll GET until status is completed/failed.
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

        try:
            # Per-request timeout only; the long wait is the poll loop, not one call.
            async with httpx.AsyncClient(timeout=60.0) as http:
                log.debug("Gemini deep-research: starting interaction (agent=%s)", agent)
                resp = await http.post(
                    f"{base}/interactions",
                    headers=create_headers,
                    json={"input": query, "agent": agent, "background": True},
                )
                resp.raise_for_status()
                interaction = resp.json()
                interaction_id = interaction.get("id") or interaction.get("name") or ""
                # Some responses return a fully-qualified name ("interactions/abc").
                interaction_id = str(interaction_id).split("/")[-1]
                if not interaction_id:
                    return {
                        "status": "error",
                        "error_message": (
                            "Research error: no interaction id in create response: "
                            f"{str(interaction)[:300]}"
                        ),
                    }

                for _ in range(max_attempts):
                    await asyncio.sleep(poll_interval)
                    g = await http.get(
                        f"{base}/interactions/{interaction_id}", headers=get_headers
                    )
                    g.raise_for_status()
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
                        return {
                            "status": "error",
                            "error_message": f"Research failed: {error}",
                        }

                timeout_msg = (
                    f"Research timed out after {max_attempts * poll_interval / 60:.0f} minutes"
                )
                log.warning("Gemini deep-research timed out (agent=%s)", agent)
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
    ) -> dict:
        """Poll the OpenAI deep-research Responses API and return the canonical envelope.

        Returns {"status": "success"|"error"|"timeout", "report"|"error_message": ...}.

        Transient connection/timeout errors on the initial responses.create call are
        retried up to max_connect_retries times with exponential back-off (2**attempt s).
        Clean failure statuses ("failed", "cancelled", "incomplete") are NOT retried.
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

        try:
            from openai import AsyncOpenAI  # noqa: PLC0415 -- construction allowed here only

            client = AsyncOpenAI(api_key=api_key, timeout=3600)

            # ---- Retry loop for the initial create call ----
            response = None
            last_exc: Exception | None = None
            for attempt in range(max_connect_retries):
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

            if response is None:
                return {
                    "status": "error",
                    "error_message": (
                        f"OpenAI deep-research create failed after {max_connect_retries} "
                        f"retries: {last_exc}"
                    ),
                }

            # ---- Polling loop ----
            for _ in range(max_attempts):
                await asyncio.sleep(poll_interval)
                response = await client.responses.retrieve(response.id)

                if response.status == "completed":
                    report = response.output_text
                    if not report:
                        return {"status": "error", "error_message": "No text content in response"}
                    log.info("OpenAI deep-research completed (model=%s)", model)
                    return {"status": "success", "report": report}
                elif response.status in ("failed", "cancelled"):
                    error = getattr(response, "error", None) or "Unknown error"
                    return {"status": "error", "error_message": f"Research {response.status}: {error}"}
                elif response.status == "incomplete":
                    return {"status": "error", "error_message": "Research ended incomplete"}

            timeout_msg = (
                f"Research timed out after {max_attempts * poll_interval / 60:.0f} minutes"
            )
            log.warning("OpenAI deep-research timed out (model=%s)", model)
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
