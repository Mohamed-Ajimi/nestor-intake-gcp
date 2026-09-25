"""Quick 260925-cop — Claude research on claude-opus-5-5, no web-search cap, pause_turn continuation.

Pins, offline (no network, no key):
  * the request shape Opus 5.5 accepts (adaptive thinking + output_config.effort; the old
    ``thinking.type=enabled`` + ``budget_tokens`` is rejected with HTTP 400 by Opus 5.5);
  * that the web_search tool carries NO ``max_uses`` (operator ruling: no search cap);
  * that a ``pause_turn`` stop sends the paused assistant turn back verbatim and the text of
    every leg is kept — before this change a pause was taken as the final answer;
  * that continuations are bounded by MAX_CONTINUATIONS;
  * that the audit label (claude_adapter.MODEL) is the model actually called.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from nestor_pulse.tools import claude_deep_researcher as cdr


def _sse(events: list[dict]) -> list[str]:
    return [f"data: {json.dumps(e)}" for e in events]


def _leg(text: str, stop_reason: str, *, search: bool = False) -> list[str]:
    events: list[dict] = [{"type": "message_start", "message": {"usage": {"input_tokens": 10}}}]
    idx = 0
    events += [
        {"type": "content_block_start", "index": idx, "content_block": {"type": "thinking", "thinking": ""}},
        {"type": "content_block_delta", "index": idx, "delta": {"type": "thinking_delta", "thinking": "plan"}},
        {"type": "content_block_delta", "index": idx, "delta": {"type": "signature_delta", "signature": "sig"}},
        {"type": "content_block_stop", "index": idx},
    ]
    idx += 1
    if search:
        events += [
            {"type": "content_block_start", "index": idx,
             "content_block": {"type": "server_tool_use", "id": "srv_1", "name": "web_search", "input": {}}},
            {"type": "content_block_delta", "index": idx,
             "delta": {"type": "input_json_delta", "partial_json": '{"query": "fuel'}},
            {"type": "content_block_delta", "index": idx,
             "delta": {"type": "input_json_delta", "partial_json": ' prices"}'}},
            {"type": "content_block_stop", "index": idx},
        ]
        idx += 1
        events += [
            {"type": "content_block_start", "index": idx,
             "content_block": {"type": "web_search_tool_result", "tool_use_id": "srv_1", "content": []}},
            {"type": "content_block_stop", "index": idx},
        ]
        idx += 1
    events += [
        {"type": "content_block_start", "index": idx, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": idx, "delta": {"type": "text_delta", "text": text}},
        {"type": "content_block_stop", "index": idx},
        {"type": "message_delta", "delta": {"stop_reason": stop_reason}, "usage": {"output_tokens": 5}},
        {"type": "message_stop"},
    ]
    return _sse(events)


class _Resp:
    def __init__(self, lines: list[str], status: int = 200, body: bytes = b""):
        self._lines = lines
        self.status_code = status
        self._body = body

    async def aread(self) -> bytes:
        return self._body

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _Stream:
    def __init__(self, resp: _Resp):
        self._resp = resp

    async def __aenter__(self):
        return self._resp

    async def __aexit__(self, *exc):
        return False


class _FakeClient:
    def __init__(self, legs: list[_Resp]):
        self._legs = list(legs)
        self.payloads: list[dict] = []

    def stream(self, method, url, headers=None, json=None):
        self.payloads.append(json)
        return _Stream(self._legs.pop(0))


def _run(coro):
    return asyncio.run(coro)


def test_payload_is_opus_5_5_adaptive_with_no_search_cap():
    p = cdr._build_payload("q")
    assert p["model"] == "claude-opus-5-5"
    assert p["thinking"] == {"type": "adaptive"}
    assert p["output_config"] == {"effort": "high"}
    assert "budget_tokens" not in json.dumps(p)
    assert p["max_tokens"] == 32000
    assert p["tools"] == [{"type": "web_search_20250305", "name": "web_search"}]
    assert "max_uses" not in p["tools"][0]
    assert p["messages"] == [{"role": "user", "content": "q"}]


def test_single_leg_returns_the_report():
    client = _FakeClient([_Resp(_leg("Report body.", "end_turn", search=True))])
    out = _run(cdr._research_with_continuations(client, "u", {}, "q"))
    assert out == {"status": "success", "report": "Report body."}
    assert len(client.payloads) == 1


def test_pause_turn_sends_the_paused_turn_back_and_keeps_all_text():
    client = _FakeClient([
        _Resp(_leg("Part one.", "pause_turn", search=True)),
        _Resp(_leg("Part two.", "end_turn")),
    ])
    out = _run(cdr._research_with_continuations(client, "u", {}, "q"))
    assert out["status"] == "success"
    assert out["report"] == "Part one.\nPart two."
    assert len(client.payloads) == 2
    second = client.payloads[1]["messages"]
    assert second[0] == {"role": "user", "content": "q"}
    assert second[1]["role"] == "assistant"
    types = [b["type"] for b in second[1]["content"]]
    assert types == ["thinking", "server_tool_use", "web_search_tool_result", "text"]
    thinking = second[1]["content"][0]
    assert thinking["thinking"] == "plan" and thinking["signature"] == "sig"
    assert second[1]["content"][1]["input"] == {"query": "fuel prices"}
    assert second[1]["content"][3]["text"] == "Part one."


def test_continuations_are_bounded(monkeypatch):
    monkeypatch.setattr(cdr, "MAX_CONTINUATIONS", 2)
    client = _FakeClient([_Resp(_leg(f"P{i}.", "pause_turn")) for i in range(5)])
    out = _run(cdr._research_with_continuations(client, "u", {}, "q"))
    assert out["status"] == "success"
    # first request + 2 continuations = 3 requests, then it stops and keeps the text
    assert len(client.payloads) == 3
    assert out["report"] == "P0.\nP1.\nP2."


def test_http_error_is_passed_through():
    client = _FakeClient([_Resp([], status=400, body=b'{"error":"bad"}')])
    out = _run(cdr._research_with_continuations(client, "u", {}, "q"))
    assert out["status"] == "error"
    assert out["error_message"].startswith("HTTP 400")


def test_audit_label_is_the_model_actually_called():
    from nestor_pulse_sdk.tools import claude_adapter

    assert claude_adapter.MODEL == cdr.ANTHROPIC_MODEL == "claude-opus-5-5"
