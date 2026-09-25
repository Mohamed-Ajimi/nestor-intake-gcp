import asyncio
import json
import httpx
import os
import logging

# Suppress debug logging from httpcore and httpx
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

ANTHROPIC_API_BASE = "https://api.anthropic.com/v1/messages"
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
# Quick 260925-cop (operator ruling 2026-09-25): Claude research moves from
# claude-sonnet-4-6 to claude-opus-5-5 and the web-search cap is REMOVED.
# Opus 5.5 rejects thinking.type "enabled" + budget_tokens (HTTP 400, measured) - it takes
# thinking.type "adaptive" + output_config.effort. Model, effort and max_tokens are env-tunable.
# A full revert to claude-sonnet-4-6 is a git revert (4.6 needs the old "enabled" shape).
ANTHROPIC_MODEL = os.environ.get("NESTOR_CLAUDE_RESEARCH_MODEL", "claude-opus-5-5")
# Adaptive-thinking effort: "high" (default) or "max".
RESEARCH_EFFORT = os.environ.get("NESTOR_CLAUDE_RESEARCH_EFFORT", "high")
# Max output tokens per request. With adaptive thinking the thinking and the report share
# this budget (the old 16k held 10k of thinking, leaving about 6k for the report).
MAX_TOKENS = int(os.environ.get("NESTOR_CLAUDE_RESEARCH_MAX_TOKENS", "32000"))
# NO web-search cap (operator ruling). Remaining brakes: the per-angle deep-research timeout
# (NESTOR_DR_TIMEOUT_S in research_division) and MAX_CONTINUATIONS below.
# Without a cap a long server-tool turn can end with stop_reason "pause_turn"; the caller must
# send the partial assistant turn back so Claude continues. Before this change a pause would
# have been taken as the final answer and the report silently cut short.
MAX_CONTINUATIONS = int(os.environ.get("NESTOR_CLAUDE_RESEARCH_MAX_CONTINUATIONS", "10"))
# Retry configuration
MAX_RETRIES = 3
INITIAL_RETRY_DELAY = 2.0
MAX_RETRY_DELAY = 30.0

# Streaming keeps the connection alive, so we only need a connect timeout
# and a generous read timeout between individual SSE chunks.
STREAM_TIMEOUT = httpx.Timeout(None, connect=15.0)

RESEARCH_SYSTEM_PROMPT = """You are a deep research analyst. Your task is to produce a comprehensive,
well-structured research report on the given topic.

Instructions:
- Use web search extensively to gather current, factual information from multiple sources.
- Cross-reference findings across sources for accuracy.
- Structure your report with clear sections and headings.
- Include specific data points, statistics, and quotes where relevant.
- Note any conflicting information found across sources.
- Cite your sources inline.
- Aim for thoroughness — this is a deep research report, not a quick summary."""


def _build_headers() -> dict:
    return {
        "Content-Type": "application/json",
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
    }


def _build_payload(query: str, prior_assistant: list | None = None) -> dict:
    """The Messages request. ``prior_assistant`` = the content blocks of a paused turn."""
    messages: list[dict] = [{"role": "user", "content": query}]
    if prior_assistant:
        messages.append({"role": "assistant", "content": prior_assistant})
    return {
        "model": ANTHROPIC_MODEL,
        "max_tokens": MAX_TOKENS,
        "stream": True,
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": RESEARCH_EFFORT},
        "system": RESEARCH_SYSTEM_PROMPT,
        # No "max_uses": the search cap is removed (quick 260925-cop).
        "tools": [{"type": "web_search_20250305", "name": "web_search"}],
        "messages": messages,
    }


def _parse_sse_line(line: str) -> dict | None:
    """Parse a single SSE data line into a dict, or None if not a data line."""
    line = line.strip()
    if not line or not line.startswith("data: "):
        return None
    data_str = line[len("data: "):]
    if data_str == "[DONE]":
        return None
    try:
        return json.loads(data_str)
    except json.JSONDecodeError:
        return None


async def _stream_research(
    client: httpx.AsyncClient, url: str, headers: dict, payload: dict
) -> dict:
    """Stream ONE request. Returns status, text parts, the FULL content blocks (so a paused
    turn can be sent back verbatim), stop_reason, usage and the web-search count.

    Streaming keeps the HTTP connection alive across thinking pauses and web search
    round-trips, avoiding timeout issues.
    """
    text_parts: list[str] = []
    blocks: list[dict] = []
    usage: dict = {}
    web_search_count = 0
    stop_reason = None

    async with client.stream("POST", url, headers=headers, json=payload) as response:
        # Check for immediate HTTP errors (auth, bad request, etc.)
        if response.status_code >= 400:
            body = await response.aread()
            error_detail = body.decode("utf-8", errors="replace")
            return {
                "status": "error",
                "error_message": f"HTTP {response.status_code}: {error_detail}",
            }

        current: dict | None = None
        partial_json = ""

        async for raw_line in response.aiter_lines():
            event = _parse_sse_line(raw_line)
            if event is None:
                continue

            event_type = event.get("type", "")

            if event_type == "content_block_start":
                current = dict(event.get("content_block", {}) or {})
                partial_json = ""
                if current.get("type") == "web_search_tool_result":
                    web_search_count += 1
                    logging.debug(f"Claude deep research: web search #{web_search_count}")

            elif event_type == "content_block_delta" and current is not None:
                delta = event.get("delta", {})
                delta_type = delta.get("type", "")
                if delta_type == "text_delta":
                    current["text"] = current.get("text", "") + delta.get("text", "")
                elif delta_type == "citations_delta":
                    current.setdefault("citations", []).append(delta.get("citation"))
                elif delta_type == "thinking_delta":
                    current["thinking"] = current.get("thinking", "") + delta.get("thinking", "")
                elif delta_type == "signature_delta":
                    current["signature"] = delta.get("signature", "")
                elif delta_type == "input_json_delta":
                    partial_json += delta.get("partial_json", "")

            elif event_type == "content_block_stop" and current is not None:
                if partial_json:
                    try:
                        current["input"] = json.loads(partial_json)
                    except json.JSONDecodeError:
                        current["input"] = {}
                if current.get("type") == "text" and current.get("text"):
                    text_parts.append(current["text"])
                blocks.append(current)
                current = None
                partial_json = ""

            elif event_type == "message_delta":
                # Final usage stats and the stop_reason arrive here
                stop_reason = (event.get("delta", {}) or {}).get("stop_reason") or stop_reason
                u = event.get("usage", {})
                if u:
                    usage.update(u)

            elif event_type == "message_start":
                msg = event.get("message", {})
                u = msg.get("usage", {})
                if u:
                    usage.update(u)

            elif event_type == "error":
                error_msg = event.get("error", {}).get("message", str(event))
                return {"status": "error", "error_message": f"Stream error: {error_msg}"}

    return {
        "status": "success",
        "text_parts": text_parts,
        "blocks": blocks,
        "stop_reason": stop_reason,
        "usage": usage,
        "web_search_count": web_search_count,
    }


async def _research_with_continuations(
    client: httpx.AsyncClient, url: str, headers: dict, query: str
) -> dict:
    """Run the request; on stop_reason "pause_turn" send the paused turn back and continue,
    at most MAX_CONTINUATIONS times. Text from every leg is kept, in order."""
    text_parts: list[str] = []
    prior: list[dict] = []
    searches = 0
    legs = 0
    stop_reason = None
    while True:
        leg = await _stream_research(client, url, headers, _build_payload(query, prior or None))
        if leg["status"] != "success":
            return leg
        legs += 1
        text_parts.extend(leg["text_parts"])
        searches += leg["web_search_count"]
        stop_reason = leg["stop_reason"]
        if stop_reason != "pause_turn":
            break
        if legs > MAX_CONTINUATIONS:
            logging.warning(
                f"Claude deep research: still paused after {MAX_CONTINUATIONS} continuations "
                f"({searches} searches) - keeping the text so far"
            )
            break
        # The whole paused assistant turn goes back verbatim (thinking + signatures,
        # server_tool_use, web_search_tool_result, text) so Claude resumes where it stopped.
        prior = prior + leg["blocks"]

    report = "\n".join(text_parts)
    if not report:
        return {"status": "error", "error_message": "No text content in streamed response"}

    logging.info(
        f"Claude deep research complete: model={ANTHROPIC_MODEL} effort={RESEARCH_EFFORT} "
        f"{searches} web searches, {legs} request(s), stop_reason={stop_reason}"
    )
    if stop_reason == "max_tokens":
        logging.warning("Claude deep research: report hit max_tokens and may be cut short")
    return {"status": "success", "report": report}


async def deep_research_async(query: str) -> dict:
    """Perform deep research using Claude with extended thinking + web search.

    Uses Claude (ANTHROPIC_MODEL, default claude-opus-5-5) with adaptive thinking and the uncapped web search tool to produce
    a comprehensive research report. The request is streamed to keep the
    connection alive — no timeout even if research takes 10+ minutes.

    Args:
        query: The research query / topic to investigate.

    Returns:
        dict with "status" ("success" or "error") and "report" or "error_message".
    """
    logging.debug(f"Starting Claude deep research for query: {query}")

    if not ANTHROPIC_API_KEY:
        return {"status": "error", "error_message": "ANTHROPIC_API_KEY not set"}

    headers = _build_headers()

    last_error = None
    for attempt in range(MAX_RETRIES):
        async with httpx.AsyncClient(timeout=STREAM_TIMEOUT) as client:
            try:
                result = await _research_with_continuations(
                    client, ANTHROPIC_API_BASE, headers, query
                )
                # If we got a transient HTTP error, retry
                if (
                    result["status"] == "error"
                    and any(code in result["error_message"] for code in ("HTTP 500", "HTTP 529"))
                    and attempt < MAX_RETRIES - 1
                ):
                    delay = min(INITIAL_RETRY_DELAY * (2 ** attempt), MAX_RETRY_DELAY)
                    logging.warning(
                        f"Claude deep research: transient error, "
                        f"retrying in {delay}s (attempt {attempt + 1}/{MAX_RETRIES})"
                    )
                    await asyncio.sleep(delay)
                    last_error = result
                    continue
                return result

            except httpx.RequestError as e:
                if attempt < MAX_RETRIES - 1:
                    delay = min(INITIAL_RETRY_DELAY * (2 ** attempt), MAX_RETRY_DELAY)
                    logging.warning(
                        f"Claude deep research: request error, retrying in {delay}s "
                        f"(attempt {attempt + 1}/{MAX_RETRIES}): {e}"
                    )
                    await asyncio.sleep(delay)
                    last_error = {"status": "error", "error_message": f"Request failed: {e}"}
                    continue
                return {"status": "error", "error_message": f"Request failed: {e}"}

    return last_error or {"status": "error", "error_message": "Failed after all retries"}
