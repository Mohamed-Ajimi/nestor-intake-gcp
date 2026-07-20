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
ANTHROPIC_MODEL = "claude-sonnet-4-6"

# Extended thinking budget (tokens dedicated to internal reasoning)
THINKING_BUDGET = 10000
# Max output tokens (must exceed thinking budget)
MAX_TOKENS = 16000
# Max web searches per request
MAX_WEB_SEARCHES = 10

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


def _build_payload(query: str) -> dict:
    return {
        "model": ANTHROPIC_MODEL,
        "max_tokens": MAX_TOKENS,
        "stream": True,
        "thinking": {
            "type": "enabled",
            "budget_tokens": THINKING_BUDGET,
        },
        "system": RESEARCH_SYSTEM_PROMPT,
        "tools": [
            {
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": MAX_WEB_SEARCHES,
            }
        ],
        "messages": [
            {
                "role": "user",
                "content": query,
            }
        ],
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
    """Stream the response and accumulate text blocks. Returns final result dict.

    Streaming keeps the HTTP connection alive across extended thinking pauses
    and web search round-trips, avoiding timeout issues.
    """
    text_parts = []
    usage = {}
    web_search_count = 0

    async with client.stream("POST", url, headers=headers, json=payload) as response:
        # Check for immediate HTTP errors (auth, bad request, etc.)
        if response.status_code >= 400:
            body = await response.aread()
            error_detail = body.decode("utf-8", errors="replace")
            return {
                "status": "error",
                "error_message": f"HTTP {response.status_code}: {error_detail}",
            }

        current_block_type = None
        current_text = ""

        async for raw_line in response.aiter_lines():
            event = _parse_sse_line(raw_line)
            if event is None:
                continue

            event_type = event.get("type", "")

            if event_type == "content_block_start":
                block = event.get("content_block", {})
                current_block_type = block.get("type")
                current_text = ""
                if current_block_type == "text":
                    current_text = block.get("text", "")
                elif current_block_type == "web_search_tool_result":
                    web_search_count += 1
                    logging.debug(f"Claude deep research: web search #{web_search_count}")

            elif event_type == "content_block_delta":
                delta = event.get("delta", {})
                delta_type = delta.get("type", "")
                if delta_type == "text_delta" and current_block_type == "text":
                    current_text += delta.get("text", "")
                elif delta_type == "thinking_delta":
                    pass  # thinking content — skip

            elif event_type == "content_block_stop":
                if current_block_type == "text" and current_text:
                    text_parts.append(current_text)
                current_block_type = None
                current_text = ""

            elif event_type == "message_delta":
                # Final usage stats arrive here
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

    report = "\n".join(text_parts)
    if not report:
        return {"status": "error", "error_message": "No text content in streamed response"}

    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    logging.info(
        f"Claude deep research complete: {web_search_count} web searches, "
        f"{input_tokens} input tokens, {output_tokens} output tokens"
    )

    return {"status": "success", "report": report}


async def deep_research_async(query: str) -> dict:
    """Perform deep research using Claude with extended thinking + web search.

    Uses Claude Opus with extended thinking and the web search tool to produce
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
    payload = _build_payload(query)

    last_error = None
    for attempt in range(MAX_RETRIES):
        async with httpx.AsyncClient(timeout=STREAM_TIMEOUT) as client:
            try:
                result = await _stream_research(
                    client, ANTHROPIC_API_BASE, headers, payload
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
