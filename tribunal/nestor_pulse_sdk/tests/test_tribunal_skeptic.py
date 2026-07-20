"""Tests for tribunal skeptic.py + tools.py.

Plan 01-14 Task 3 — TDD RED/GREEN cycle.

Drives run_skeptic with a FAKE audited client whose anthropic_messages returns
a canned sequence reflecting the SERVER/CLIENT tool protocol:
  (a) First response: stop_reason "tool_use", content includes an INLINE
      web_search_tool_result block (server tool resolved within the turn —
      NOT a client tool awaiting dispatch). Client MUST NOT append a synthetic
      tool_result for this server tool — only append the assistant turn.
  (b) Second response: stop_reason "tool_use", content carries an emit_verdict
      CLIENT tool_use block — loop terminates, returns verdict dict.

All tests use only the FakeAuditedClient — no Cloud SQL, no real Anthropic key,
no network calls.

CRITICAL PROTOCOL ASSERTIONS (HTTP-400-trap guards):
  - The messages list recorded by the fake must contain NO synthetic tool_result
    blocks for server tools (web_search/web_fetch). Only assistant turns appended.
  - emit_verdict terminates the loop immediately.
  - Shared claim+sources content block carries cache_control ephemeral.
  - max_turns default <= 4; final turn forces tool_choice=force_emit_verdict().
  - grep gate: no claude-agent-sdk / query() import in skeptic.py.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Fake objects
# ---------------------------------------------------------------------------


class _FakeBlock:
    """Minimal object mimicking an Anthropic content block."""

    def __init__(self, type: str, **kwargs: Any) -> None:
        self.type = type
        for k, v in kwargs.items():
            setattr(self, k, v)

    def __repr__(self) -> str:
        attrs = {k: v for k, v in self.__dict__.items() if k != "type"}
        return f"FakeBlock(type={self.type!r}, {attrs})"


class _FakeResponse:
    """Mimics an Anthropic messages response with stop_reason and content blocks."""

    def __init__(self, stop_reason: str, content: list[Any]) -> None:
        self.stop_reason = stop_reason
        self.content = content
        self.usage = MagicMock()
        self.usage.input_tokens = 100
        self.usage.output_tokens = 50
        self.usage.cache_read_input_tokens = 0
        self.usage.cache_creation_input_tokens = 0


class FakeAuditedClient:
    """
    Fake AuditedLLMClient for skeptic loop tests.

    Records ALL messages lists it was called with (so tests can assert
    the client-side tool_result protocol is respected).

    Returns a pre-canned sequence of responses.
    """

    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = list(responses)
        self._call_idx = 0
        # All 'messages' kwargs passed to anthropic_messages — for HTTP-400-trap assertions
        self.recorded_messages: list[list[dict]] = []
        self.recorded_tool_choices: list[Any] = []

    async def anthropic_messages(
        self, *, run_id, tenant_id, model, messages, tools, tool_choice=None, **kwargs
    ) -> _FakeResponse:
        self.recorded_messages.append(list(messages))  # shallow copy for assertion
        self.recorded_tool_choices.append(tool_choice)
        if self._call_idx >= len(self._responses):
            raise RuntimeError(
                f"FakeAuditedClient: exhausted canned responses "
                f"(call {self._call_idx + 1} > {len(self._responses)})"
            )
        resp = self._responses[self._call_idx]
        self._call_idx += 1
        return resp


# ---------------------------------------------------------------------------
# Canned response sequences
# ---------------------------------------------------------------------------


def _make_server_tool_response() -> _FakeResponse:
    """
    First turn: model uses a SERVER-side web_search tool.
    The API has already resolved it; the result comes back INLINE in resp.content
    as a web_search_tool_result block — NOT as a client tool_use awaiting dispatch.

    The client MUST NOT append a synthetic tool_result.
    The client MUST append the assistant turn (resp.content) to extend context.
    """
    # Simulate: model emits a tool_use for web_search AND the server resolves it inline
    # In practice the content would contain web_search_tool_result blocks
    search_result_block = _FakeBlock(
        "web_search_tool_result",
        tool_use_id="toolu_search_01",
        content=[{"type": "text", "text": "Found: Company X had $5B revenue in 2025"}],
    )
    return _FakeResponse(
        stop_reason="tool_use",
        content=[search_result_block],
    )


def _make_emit_verdict_response(verdict: str = "support") -> _FakeResponse:
    """
    Second turn: model emits the CLIENT-side emit_verdict tool.
    Loop must terminate and parse the verdict.
    """
    verdict_block = _FakeBlock(
        "tool_use",
        id="toolu_verdict_01",
        name="emit_verdict",
        input={
            "verdict": verdict,
            "confidence": 0.85,
            "evidence_refs": ["Company X had $5B revenue in 2025"],
        },
    )
    return _FakeResponse(
        stop_reason="tool_use",
        content=[verdict_block],
    )


def _make_non_tool_response() -> _FakeResponse:
    """Final forced emit_verdict when max_turns reached."""
    verdict_block = _FakeBlock(
        "tool_use",
        id="toolu_forced_verdict",
        name="emit_verdict",
        input={
            "verdict": "insufficient",
            "confidence": 0.4,
            "evidence_refs": [],
        },
    )
    return _FakeResponse(
        stop_reason="tool_use",
        content=[verdict_block],
    )


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Tools tests (tools.py)
# ---------------------------------------------------------------------------


class TestToolBuilders:
    """Tests for tools.py builder functions and constants."""

    def test_build_web_search_has_correct_type(self):
        from nestor_pulse_sdk.pipeline.tribunal.tools import build_web_search
        tool = build_web_search(max_uses=5)
        assert tool["type"] == "web_search_20250305", (
            f"Expected web_search_20250305, got {tool['type']!r}"
        )

    def test_build_web_search_has_name(self):
        from nestor_pulse_sdk.pipeline.tribunal.tools import build_web_search
        tool = build_web_search(max_uses=5)
        assert tool["name"] == "web_search"

    def test_build_web_search_max_uses(self):
        from nestor_pulse_sdk.pipeline.tribunal.tools import build_web_search
        tool = build_web_search(max_uses=3)
        assert tool["max_uses"] == 3

    def test_build_web_fetch_has_correct_type(self):
        from nestor_pulse_sdk.pipeline.tribunal.tools import build_web_fetch
        tool = build_web_fetch(max_uses=3)
        assert tool["type"] == "web_fetch_20250910", (
            f"Expected web_fetch_20250910, got {tool['type']!r}"
        )

    def test_build_web_fetch_citations_enabled(self):
        """build_web_fetch MUST always set citations.enabled True."""
        from nestor_pulse_sdk.pipeline.tribunal.tools import build_web_fetch
        tool = build_web_fetch(max_uses=3)
        citations = tool.get("citations") or {}
        assert citations.get("enabled") is True, (
            f"citations.enabled must be True; got {citations!r}"
        )

    def test_build_web_fetch_name(self):
        from nestor_pulse_sdk.pipeline.tribunal.tools import build_web_fetch
        tool = build_web_fetch(max_uses=3)
        assert tool["name"] == "web_fetch"

    def test_build_web_fetch_allowed_domains(self):
        from nestor_pulse_sdk.pipeline.tribunal.tools import build_web_fetch
        domains = ["example.com", "trusted.org"]
        tool = build_web_fetch(max_uses=3, allowed_domains=domains)
        assert tool.get("allowed_domains") == domains

    def test_build_web_fetch_max_content_tokens(self):
        from nestor_pulse_sdk.pipeline.tribunal.tools import build_web_fetch
        tool = build_web_fetch(max_uses=3, max_content_tokens=1000)
        assert tool.get("max_content_tokens") == 1000

    def test_emit_verdict_tool_is_client_side(self):
        """EMIT_VERDICT_TOOL must have type 'custom' or no type (client-side tool schema)."""
        from nestor_pulse_sdk.pipeline.tribunal.tools import EMIT_VERDICT_TOOL
        assert EMIT_VERDICT_TOOL["name"] == "emit_verdict"
        # Must NOT be a server-side type
        tool_type = EMIT_VERDICT_TOOL.get("type", "custom")
        assert tool_type not in ("web_search_20250305", "web_fetch_20250910"), (
            "emit_verdict must be a client-side tool, not a server-side type"
        )

    def test_emit_verdict_input_schema_has_verdict(self):
        from nestor_pulse_sdk.pipeline.tribunal.tools import EMIT_VERDICT_TOOL
        schema = EMIT_VERDICT_TOOL.get("input_schema") or {}
        props = schema.get("properties") or {}
        assert "verdict" in props, f"Missing 'verdict' in input_schema properties: {props}"

    def test_emit_verdict_input_schema_verdict_enum(self):
        from nestor_pulse_sdk.pipeline.tribunal.tools import EMIT_VERDICT_TOOL
        schema = EMIT_VERDICT_TOOL.get("input_schema") or {}
        props = schema.get("properties") or {}
        verdict_schema = props.get("verdict") or {}
        enum_vals = verdict_schema.get("enum") or []
        assert set(enum_vals) == {"support", "refute", "insufficient"}, (
            f"verdict enum must be {{support,refute,insufficient}}; got {enum_vals}"
        )

    def test_emit_verdict_input_schema_has_confidence(self):
        from nestor_pulse_sdk.pipeline.tribunal.tools import EMIT_VERDICT_TOOL
        schema = EMIT_VERDICT_TOOL.get("input_schema") or {}
        props = schema.get("properties") or {}
        assert "confidence" in props

    def test_emit_verdict_input_schema_has_evidence_refs(self):
        from nestor_pulse_sdk.pipeline.tribunal.tools import EMIT_VERDICT_TOOL
        schema = EMIT_VERDICT_TOOL.get("input_schema") or {}
        props = schema.get("properties") or {}
        assert "evidence_refs" in props

    def test_force_emit_verdict_returns_tool_choice(self):
        from nestor_pulse_sdk.pipeline.tribunal.tools import force_emit_verdict
        tc = force_emit_verdict()
        assert isinstance(tc, dict), "force_emit_verdict() must return a dict"
        # Must reference the emit_verdict tool
        assert tc.get("name") == "emit_verdict" or (
            tc.get("type") == "tool" and tc.get("name") == "emit_verdict"
        ), f"tool_choice must force emit_verdict; got {tc!r}"

    def test_no_output_config_in_tools_module(self):
        """Grep-equivalent: no output_config / structured-output mode in tools.py."""
        import inspect
        from nestor_pulse_sdk.pipeline.tribunal import tools as tools_mod
        source = inspect.getsource(tools_mod)
        assert "output_config" not in source, (
            "tools.py must NOT contain 'output_config' (citations⊗structured-outputs = HTTP 400)"
        )


# ---------------------------------------------------------------------------
# Skeptic loop tests
# ---------------------------------------------------------------------------


class TestRunSkeptic:
    """Tests for skeptic.run_skeptic() loop protocol."""

    def _make_claim(self) -> dict:
        return {
            "text": "Company X had $5B revenue in 2025",
            "stakes": "high",
            "facet": "B",
        }

    def _make_sources(self) -> list[dict]:
        return [{"url": "https://example.com/report", "snippet": "Revenue data 2025"}]

    def test_happy_path_returns_verdict_dict(self):
        """Standard path: server tool resolves, then emit_verdict fires."""
        from nestor_pulse_sdk.pipeline.tribunal.skeptic import run_skeptic
        fake = FakeAuditedClient([
            _make_server_tool_response(),
            _make_emit_verdict_response("support"),
        ])
        result = _run(run_skeptic(
            claim=self._make_claim(),
            sources=self._make_sources(),
            audited=fake,
            run_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            model="claude-opus-4-8",
        ))
        assert isinstance(result, dict), f"Expected dict, got {type(result)}"
        assert result["verdict"] in {"support", "refute", "insufficient"}, (
            f"verdict must be in {{support,refute,insufficient}}; got {result['verdict']!r}"
        )

    def test_verdict_is_support(self):
        from nestor_pulse_sdk.pipeline.tribunal.skeptic import run_skeptic
        fake = FakeAuditedClient([
            _make_server_tool_response(),
            _make_emit_verdict_response("support"),
        ])
        result = _run(run_skeptic(
            claim=self._make_claim(),
            sources=self._make_sources(),
            audited=fake,
            run_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            model="claude-opus-4-8",
        ))
        assert result["verdict"] == "support"

    def test_verdict_is_refute(self):
        from nestor_pulse_sdk.pipeline.tribunal.skeptic import run_skeptic
        fake = FakeAuditedClient([
            _make_server_tool_response(),
            _make_emit_verdict_response("refute"),
        ])
        result = _run(run_skeptic(
            claim=self._make_claim(),
            sources=self._make_sources(),
            audited=fake,
            run_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            model="claude-opus-4-8",
        ))
        assert result["verdict"] == "refute"

    def test_no_synthetic_tool_result_for_server_tools(self):
        """
        HTTP-400-trap guard: the client MUST NOT append a synthetic tool_result
        for web_search / web_fetch server tools. Only assistant turns are appended
        to extend context when the model uses server tools.

        The recorded messages list must contain NO dicts with:
          {"type": "tool_result", ...} for server tool ids.

        The only messages appended after the initial system+user messages are:
          {"role": "assistant", "content": <resp.content>}
        """
        from nestor_pulse_sdk.pipeline.tribunal.skeptic import run_skeptic
        fake = FakeAuditedClient([
            _make_server_tool_response(),
            _make_emit_verdict_response("support"),
        ])
        _run(run_skeptic(
            claim=self._make_claim(),
            sources=self._make_sources(),
            audited=fake,
            run_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            model="claude-opus-4-8",
        ))
        # Check the second call's messages list for synthetic tool_results
        assert len(fake.recorded_messages) >= 2, (
            "Expected at least 2 calls to anthropic_messages"
        )
        second_call_messages = fake.recorded_messages[1]
        for msg in second_call_messages:
            # Must not have user-role messages with type=tool_result for server tools
            if msg.get("role") == "user":
                content = msg.get("content")
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_result":
                            tool_id = block.get("tool_use_id", "")
                            # Server tool IDs from our fake: "toolu_search_01"
                            # The client must not have synthesised a tool_result for it
                            assert "search" not in tool_id and "fetch" not in tool_id, (
                                f"Found synthetic tool_result for server tool {tool_id!r} "
                                f"— HTTP-400 trap: do NOT dispatch tool_results for server tools"
                            )

    def test_only_assistant_turn_appended_for_server_tool(self):
        """
        After a server-tool response, the implementation MUST append exactly
        {"role": "assistant", "content": <resp.content>} to extend context,
        then re-call. The second call's messages must include this assistant turn.
        """
        from nestor_pulse_sdk.pipeline.tribunal.skeptic import run_skeptic
        fake = FakeAuditedClient([
            _make_server_tool_response(),
            _make_emit_verdict_response("support"),
        ])
        _run(run_skeptic(
            claim=self._make_claim(),
            sources=self._make_sources(),
            audited=fake,
            run_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            model="claude-opus-4-8",
        ))
        second_call_messages = fake.recorded_messages[1]
        # The second call must have an assistant turn that was appended after turn 1
        assistant_turns = [
            m for m in second_call_messages if m.get("role") == "assistant"
        ]
        assert len(assistant_turns) >= 1, (
            "Expected at least one assistant turn in the second call's messages "
            "(appended after the server-tool response to extend context)"
        )

    def test_cache_control_on_shared_block(self):
        """
        The shared claim+sources content block must carry cache_control ephemeral
        so repeated skeptics on the same claim read the prefix at 0.1x cost.
        """
        from nestor_pulse_sdk.pipeline.tribunal.skeptic import run_skeptic
        fake = FakeAuditedClient([
            _make_emit_verdict_response("support"),  # direct emit on first call
        ])
        _run(run_skeptic(
            claim=self._make_claim(),
            sources=self._make_sources(),
            audited=fake,
            run_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            model="claude-opus-4-8",
        ))
        first_call_messages = fake.recorded_messages[0]
        # Flatten all content blocks from all messages
        found_cache_control = False
        for msg in first_call_messages:
            content = msg.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("cache_control"):
                        cc = block["cache_control"]
                        if isinstance(cc, dict) and cc.get("type") == "ephemeral":
                            found_cache_control = True
        assert found_cache_control, (
            "No cache_control={'type':'ephemeral'} found in initial messages — "
            "the shared claim+sources block must carry cache_control ephemeral "
            "to enable prompt-cache reads at 0.1x cost for subsequent skeptics"
        )

    def test_max_turns_forces_emit_verdict(self):
        """
        When max_turns is reached before the model emits emit_verdict,
        the final call MUST use tool_choice=force_emit_verdict().
        """
        from nestor_pulse_sdk.pipeline.tribunal.skeptic import run_skeptic
        from nestor_pulse_sdk.pipeline.tribunal.tools import force_emit_verdict

        expected_tool_choice = force_emit_verdict()

        # max_turns=2: first turn is server tool (no emit_verdict),
        # second turn must be called with force_emit_verdict()
        fake = FakeAuditedClient([
            _make_server_tool_response(),  # turn 1: server tool, no emit_verdict
            _make_emit_verdict_response("insufficient"),  # turn 2: forced emit
        ])
        _run(run_skeptic(
            claim=self._make_claim(),
            sources=self._make_sources(),
            audited=fake,
            run_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            model="claude-opus-4-8",
            max_turns=2,
        ))
        # The final call (index 1) must have tool_choice=force_emit_verdict()
        final_tool_choice = fake.recorded_tool_choices[-1]
        assert final_tool_choice is not None, (
            "Final turn must use tool_choice to force emit_verdict"
        )
        assert final_tool_choice == expected_tool_choice, (
            f"Expected tool_choice={expected_tool_choice!r}, "
            f"got {final_tool_choice!r}"
        )

    def test_max_turns_default_at_most_four(self):
        """Default max_turns must be <= 4 (plan spec)."""
        import inspect
        from nestor_pulse_sdk.pipeline.tribunal import skeptic as skeptic_mod
        source = inspect.getsource(skeptic_mod)
        # Check the default appears in the function signature or as a constant
        # Allow "max_turns=4" or "max_turns=3" or "max_turns=2"
        import re
        match = re.search(r"max_turns\s*=\s*(\d+)", source)
        assert match, "max_turns default not found in skeptic.py source"
        default_val = int(match.group(1))
        assert default_val <= 4, (
            f"max_turns default must be <= 4 (plan spec), got {default_val}"
        )

    def test_result_contains_verdict_confidence_evidence_refs(self):
        """Verdict dict must have verdict, confidence, evidence_refs."""
        from nestor_pulse_sdk.pipeline.tribunal.skeptic import run_skeptic
        fake = FakeAuditedClient([
            _make_emit_verdict_response("support"),
        ])
        result = _run(run_skeptic(
            claim=self._make_claim(),
            sources=self._make_sources(),
            audited=fake,
            run_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            model="claude-opus-4-8",
        ))
        assert "verdict" in result
        assert "confidence" in result
        assert "evidence_refs" in result

    def test_no_claude_agent_sdk_import_in_skeptic(self):
        """Audit-bypass guard: skeptic.py must not import or use claude-agent-sdk."""
        import inspect
        from nestor_pulse_sdk.pipeline.tribunal import skeptic as skeptic_mod
        source = inspect.getsource(skeptic_mod)
        assert "claude-agent-sdk" not in source, (
            "skeptic.py must not reference claude-agent-sdk"
        )
        assert "claude_agent_sdk" not in source, (
            "skeptic.py must not import from claude_agent_sdk"
        )
        assert "from claude_agent" not in source, (
            "skeptic.py must not import from claude_agent"
        )

    def test_no_direct_provider_client_in_skeptic(self):
        """Grep gate: no direct anthropic.AsyncAnthropic/genai.Client/openai construction."""
        import inspect
        from nestor_pulse_sdk.pipeline.tribunal import skeptic as skeptic_mod
        source = inspect.getsource(skeptic_mod)
        import re
        pattern = re.compile(
            r"(anthropic\.AsyncAnthropic\(\)|google\.genai\.Client\(\)|"
            r"openai\.AsyncOpenAI\(\)|AsyncAnthropic\(\)|AsyncOpenAI\(\))"
        )
        matches = pattern.findall(source)
        assert not matches, (
            f"Direct provider client construction found in skeptic.py: {matches}. "
            "All LLM calls must go through AuditedLLMClient."
        )

    def test_audited_anthropic_messages_called(self):
        """Verify the loop uses audited.anthropic_messages (not some other method)."""
        from nestor_pulse_sdk.pipeline.tribunal.skeptic import run_skeptic
        fake = FakeAuditedClient([
            _make_emit_verdict_response("support"),
        ])
        _run(run_skeptic(
            claim=self._make_claim(),
            sources=self._make_sources(),
            audited=fake,
            run_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            model="claude-opus-4-8",
        ))
        assert fake._call_idx >= 1, "anthropic_messages was never called"
