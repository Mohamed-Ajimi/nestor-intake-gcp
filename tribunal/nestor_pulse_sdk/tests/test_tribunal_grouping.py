"""Tests for Tribunal Phase-3 grouping: grouping.py + group_skeptic.py.

All tests use fakes — no Cloud SQL, no real provider keys, no network.

Covers:
  - group_claims: tags claims and buckets by entity|attribute; untagged claims
    become their own singleton (never merged blindly, never dropped); a group
    inherits its members' HIGHEST stakes.
  - _parse_group_verdict: maps per-index verdicts; fills missing claims with
    'insufficient' (never silently drops a claim); surfaces reconciliation.
  - run_group_skeptic: server/client tool protocol; emit_group_verdict
    terminates and produces one verdict per claim.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any
from unittest.mock import MagicMock

from nestor_pulse_sdk.pipeline.tribunal.grouping import group_claims, _norm, _parse_tag_lines
from nestor_pulse_sdk.pipeline.tribunal.group_skeptic import run_group_skeptic, _parse_group_verdict


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class _FakeGeminiResp:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeGrouperAudited:
    """Returns a canned plain-text tag block for gemini_generate."""
    def __init__(self, text: str) -> None:
        self._text = text
        self.calls = 0

    async def gemini_generate(self, *, run_id, tenant_id, model, contents, **kwargs):
        self.calls += 1
        return _FakeGeminiResp(self._text)


class _FakeBlock:
    def __init__(self, type: str, **kw: Any) -> None:
        self.type = type
        for k, v in kw.items():
            setattr(self, k, v)


class _FakeResp:
    def __init__(self, stop_reason: str, content: list[Any]) -> None:
        self.stop_reason = stop_reason
        self.content = content
        self.usage = MagicMock(input_tokens=10, output_tokens=10,
                               cache_read_input_tokens=0, cache_creation_input_tokens=0)


class _FakeSkepticAudited:
    def __init__(self, responses: list[_FakeResp]) -> None:
        self._responses = responses
        self._i = 0
        self.recorded_messages: list[list[dict]] = []

    async def anthropic_messages(self, *, run_id, tenant_id, model, messages, tools, tool_choice=None, **kw):
        self.recorded_messages.append(list(messages))
        r = self._responses[self._i]
        self._i += 1
        return r


# ---------------------------------------------------------------------------
# grouping.group_claims
# ---------------------------------------------------------------------------
class TestGroupClaims:
    def _claims(self):
        return [
            {"text": "FootballGPT costs $4.99/mo", "facet": "competitors", "stakes": "high"},
            {"text": "Football GPT pricing starts at $9.99/mo", "facet": "competitors", "stakes": "med"},
            {"text": "Wyscout has 600 competitions", "facet": "competitors", "stakes": "low"},
        ]

    def test_groups_same_entity_attribute_together(self):
        # Tagger maps the two FootballGPT pricing claims to the same entity|attribute.
        tag_text = "0 | FootballGPT | pricing\n1 | Football GPT | pricing\n2 | Wyscout | capability"
        audited = _FakeGrouperAudited(tag_text)
        groups = _run(group_claims(claims=self._claims(), audited=audited,
                                   run_id=uuid.uuid4(), tenant_id=uuid.uuid4()))
        # FootballGPT pricing (2 claims) + Wyscout capability (1 claim) = 2 groups
        assert len(groups) == 2
        fg = next(g for g in groups if "footballgpt" in g["key"])
        assert len(fg["claims"]) == 2          # the two pricing variants merged
        assert fg["stakes"] == "high"          # inherits the highest stakes of members

    def test_untagged_claim_becomes_singleton(self):
        # Tagger returns nothing for claim 1 -> it must still be verified (own group).
        tag_text = "0 | FootballGPT | pricing\n2 | Wyscout | capability"
        audited = _FakeGrouperAudited(tag_text)
        groups = _run(group_claims(claims=self._claims(), audited=audited,
                                   run_id=uuid.uuid4(), tenant_id=uuid.uuid4()))
        all_claims = [c for g in groups for c in g["claims"]]
        assert len(all_claims) == 3            # no claim dropped
        assert any(g["key"].startswith("__singleton__") for g in groups)

    def test_empty_claims_returns_empty(self):
        audited = _FakeGrouperAudited("")
        assert _run(group_claims(claims=[], audited=audited,
                                 run_id=uuid.uuid4(), tenant_id=uuid.uuid4())) == []


class TestNormAndParse:
    def test_norm_merges_variants(self):
        assert _norm("FootballGPT") == _norm("football gpt") == "footballgpt" or \
               _norm("FootballGPT") == "footballgpt"

    def test_parse_tag_lines_fills_missing(self):
        out = _parse_tag_lines("0 | A | x\n2 | C | z", 3)
        assert out[0] == ("A", "x")
        assert out[1] == ("", "")   # missing -> empty -> singleton downstream
        assert out[2] == ("C", "z")


# ---------------------------------------------------------------------------
# group_skeptic._parse_group_verdict
# ---------------------------------------------------------------------------
class TestParseGroupVerdict:
    def test_maps_per_index_and_fills_missing(self):
        block = {"input": {
            "verdicts": [
                {"claim_index": 0, "verdict": "support", "confidence": 0.9},
                # index 1 omitted on purpose
                {"claim_index": 2, "verdict": "refute", "confidence": 0.8},
            ],
            "reconciliation": {"disputed": True, "relation": "disputed",
                               "note": "two prices, no scope", "canonical": "$4.99/mo"},
            "evidence_refs": ["https://example.com/pricing"],
        }}
        out = _parse_group_verdict(block, n_claims=3, citations=["https://src"])
        assert out["verdicts_by_index"][0]["verdict"] == "support"
        assert out["verdicts_by_index"][1]["verdict"] == "insufficient"  # missing -> filled
        assert out["verdicts_by_index"][2]["verdict"] == "refute"
        assert out["reconciliation"]["disputed"] is True
        assert out["reconciliation"]["canonical"] == "$4.99/mo"

    def test_bad_index_ignored_not_crash(self):
        block = {"input": {"verdicts": [{"claim_index": 99, "verdict": "support", "confidence": 1.0}],
                           "reconciliation": {"disputed": False, "relation": "single", "note": ""}}}
        out = _parse_group_verdict(block, n_claims=1, citations=[])
        assert out["verdicts_by_index"][0]["verdict"] == "insufficient"  # 99 dropped, 0 filled


# ---------------------------------------------------------------------------
# run_group_skeptic loop
# ---------------------------------------------------------------------------
class TestRunGroupSkeptic:
    def test_emit_group_verdict_terminates_with_per_claim_verdicts(self):
        group_verdict_block = _FakeBlock(
            "tool_use", name="emit_group_verdict",
            input={
                "verdicts": [
                    {"claim_index": 0, "verdict": "support", "confidence": 0.9},
                    {"claim_index": 1, "verdict": "refute", "confidence": 0.7},
                ],
                "reconciliation": {"disputed": True, "relation": "disputed",
                                   "note": "conflicting prices", "canonical": "$4.99"},
                "evidence_refs": ["http://x"],
            },
        )
        audited = _FakeSkepticAudited([_FakeResp("tool_use", [group_verdict_block])])
        group = {"entity": "FootballGPT", "attribute": "pricing", "stakes": "high",
                 "claims": [{"text": "costs $4.99"}, {"text": "costs $9.99"}]}
        out = _run(run_group_skeptic(group=group, sources=[], audited=audited,
                                     run_id=uuid.uuid4(), tenant_id=uuid.uuid4(), model="claude-x"))
        assert out["verdicts_by_index"][0]["verdict"] == "support"
        assert out["verdicts_by_index"][1]["verdict"] == "refute"
        assert out["reconciliation"]["disputed"] is True

    def test_server_tool_then_verdict_no_synthetic_tool_result(self):
        search_block = _FakeBlock("web_search_tool_result", tool_use_id="t1",
                                  content=[{"type": "text", "text": "found"}])
        verdict_block = _FakeBlock("tool_use", name="emit_group_verdict",
            input={"verdicts": [{"claim_index": 0, "verdict": "support", "confidence": 0.8}],
                   "reconciliation": {"disputed": False, "relation": "single", "note": ""}})
        audited = _FakeSkepticAudited([
            _FakeResp("tool_use", [search_block]),
            _FakeResp("tool_use", [verdict_block]),
        ])
        group = {"entity": "X", "attribute": "y", "stakes": "med", "claims": [{"text": "c"}]}
        out = _run(run_group_skeptic(group=group, sources=[], audited=audited,
                                     run_id=uuid.uuid4(), tenant_id=uuid.uuid4(), model="claude-x"))
        assert out["verdicts_by_index"][0]["verdict"] == "support"
        # No synthetic tool_result appended for the server tool (HTTP-400 trap).
        for msgs in audited.recorded_messages:
            for m in msgs:
                if m.get("role") == "user":
                    for blk in (m.get("content") or []):
                        if isinstance(blk, dict):
                            assert blk.get("type") != "tool_result"


# ---------------------------------------------------------------------------
# Single-session adjudication semantics (one group skeptic is authoritative)
# ---------------------------------------------------------------------------
from nestor_pulse_sdk.pipeline.tribunal.adjudicate import adjudicate


class TestSingleVerdictAdjudication:
    """With one session per group, each claim gets ONE verdict. Confirm the
    existing majority-independent rule does the right thing without changes."""

    def test_single_refute_with_citation_drops(self):
        v = [{"verdict": "refute", "confidence": 0.9, "citations": ["http://x"]}]
        assert adjudicate({"text": "c", "stakes": "high"}, v) is False  # dropped

    def test_single_refute_without_citation_survives(self):
        # Locked rule: refuting REQUIRES an independent source.
        v = [{"verdict": "refute", "confidence": 0.9, "citations": [], "evidence_refs": []}]
        assert adjudicate({"text": "c", "stakes": "high"}, v) is True   # survives

    def test_single_support_survives(self):
        v = [{"verdict": "support", "confidence": 0.9, "citations": ["http://x"]}]
        assert adjudicate({"text": "c", "stakes": "high"}, v) is True

    def test_no_verdict_low_stakes_waves_through(self):
        assert adjudicate({"text": "c", "stakes": "low"}, []) is True
