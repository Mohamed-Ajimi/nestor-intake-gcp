"""Blind critique judge tests (2026-06-11). No LLM, no DB — fake audited client."""
from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from nestor_pulse_sdk.critique.judge import (
    run_blind_critique,
    sanitize_report,
    _merge_passes,
    _swap_verdict,
)


# ---------------------------------------------------------------------------
# sanitize_report
# ---------------------------------------------------------------------------

class TestSanitize:
    def test_strips_verification_appendix(self):
        body = (
            "## Executive Summary\n\nFindings here.\n\n"
            "---\n\n## Verification\n\n*   **Factual statements:** 29\n*   budget cap fired"
        )
        out = sanitize_report(body)
        assert "Verification" not in out
        assert "Factual statements" not in out
        assert "Findings here." in out

    def test_masks_engine_identity(self):
        body = "The Tribunal engine and the ADK pipeline both ran under Nestor."
        out = sanitize_report(body)
        low = out.lower()
        assert "tribunal" not in low
        assert "adk" not in low
        assert "nestor" not in low

    def test_strips_llm_preamble(self):
        body = "Of course. Here is the report you requested.\n\n## Summary\n\nContent."
        out = sanitize_report(body)
        assert not out.startswith("Of course")
        assert out.startswith("## Summary")

    def test_keeps_normal_content_intact(self):
        body = "## Pricing\n\nShell raised prices 5% [cite: 3]."
        assert sanitize_report(body) == body


# ---------------------------------------------------------------------------
# swap + merge logic
# ---------------------------------------------------------------------------

def _verdict(a, b, winner, topic="market share"):
    return {
        "dimensions": {
            "clarity": {"a": a, "b": b, "rationale": "r", "evidence_a": "qa", "evidence_b": "qb"},
            "content": {"a": a, "b": b, "rationale": "r", "evidence_a": "qa", "evidence_b": "qb"},
            "robustness": {"a": a, "b": b, "rationale": "r", "evidence_a": "qa", "evidence_b": "qb"},
        },
        "conflicting_facts": [
            {"topic": topic, "report_a_says": "10%", "report_b_says": "15%", "severity": "material"},
        ],
        "overall": {"winner": winner, "rationale": "because"},
    }


class TestSwapAndMerge:
    def test_swap_maps_labels_back(self):
        swapped = _swap_verdict(_verdict(8, 4, "A"))
        assert swapped["dimensions"]["clarity"]["a"] == 4
        assert swapped["dimensions"]["clarity"]["b"] == 8
        assert swapped["overall"]["winner"] == "B"
        c = swapped["conflicting_facts"][0]
        assert c["report_a_says"] == "15%" and c["report_b_says"] == "10%"

    def test_merge_averages_scores(self):
        merged = _merge_passes(_verdict(8, 4, "A"), _verdict(6, 6, "A"))
        assert merged["dimensions"]["clarity"]["a"] == 7.0
        assert merged["dimensions"]["clarity"]["b"] == 5.0

    def test_consensus_winner(self):
        merged = _merge_passes(_verdict(8, 4, "A"), _verdict(7, 5, "A"))
        assert merged["overall"]["winner"] == "A"
        assert merged["overall"]["consensus"] is True

    def test_disagreement_means_tie(self):
        merged = _merge_passes(_verdict(8, 4, "A"), _verdict(4, 8, "B"))
        assert merged["overall"]["winner"] == "tie"
        assert merged["overall"]["consensus"] is False

    def test_conflicts_deduped_by_topic(self):
        merged = _merge_passes(
            _verdict(8, 4, "A", topic="Market Share"),
            _verdict(8, 4, "A", topic="market share"),
        )
        assert len(merged["conflicting_facts"]) == 1


# ---------------------------------------------------------------------------
# run_blind_critique end-to-end with fake judge
# ---------------------------------------------------------------------------

class _Block:
    def __init__(self, text):
        self.text = text


class _Resp:
    def __init__(self, text):
        self.content = [_Block(text)]


class FakeAudited:
    """Returns a fixed verdict regardless of order — captures prompts for checks."""

    def __init__(self):
        self.prompts: list[str] = []

    async def anthropic_messages(self, *, run_id, tenant_id, model, **kwargs):
        prompt = kwargs["messages"][0]["content"]
        self.prompts.append(prompt)
        return _Resp(json.dumps(_verdict(8, 5, "A")))


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestRunBlindCritique:
    def _go(self, audited):
        return _run(run_blind_critique(
            brief="Onderzoek X.\n\n[CLARIFICATION ANSWERS]\nextra context",
            reports_by_engine={
                "adk": "## Report\n\nADK says market grew 10%. The Tribunal is great.",
                "tribunal": "## Report\n\nTribunal says market grew 15%.\n\n---\n\n## Verification\n\nstats",
            },
            audited=audited,
            run_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
        ))

    def test_judges_twice_and_returns_label_map(self):
        audited = FakeAudited()
        result = self._go(audited)
        assert len(audited.prompts) == 2, "must double-judge with swapped order"
        assert set(result["label_map"].keys()) == {"A", "B"}
        assert set(result["label_map"].values()) == {"adk", "tribunal"}
        assert result["method"]["order_swapped_double_pass"] is True

    def test_judge_never_sees_engine_names_or_process_metadata(self):
        audited = FakeAudited()
        self._go(audited)
        for prompt in audited.prompts:
            body = prompt.split("=== REPORT A ===", 1)[1]
            low = body.lower()
            assert "tribunal" not in low, "engine name leaked to the judge"
            assert "adk" not in low, "engine name leaked to the judge"
            assert "verification" not in low, "process appendix leaked to the judge"
            assert "[clarification answers]" not in prompt.lower(), \
                "clarification rounds (human-interaction trace) leaked to the judge"

    def test_fixed_verdict_both_orders_means_tie(self):
        """The fake says 'A wins' in BOTH orders — i.e. it favours whichever
        document sits in position A. The swap logic must expose that as a tie."""
        result = self._go(FakeAudited())
        assert result["overall"]["winner"] == "tie"
        assert result["overall"]["consensus"] is False

    def test_requires_exactly_two_reports(self):
        with pytest.raises(ValueError):
            _run(run_blind_critique(
                brief="x", reports_by_engine={"adk": "r"},
                audited=FakeAudited(), run_id=uuid.uuid4(), tenant_id=uuid.uuid4(),
            ))
