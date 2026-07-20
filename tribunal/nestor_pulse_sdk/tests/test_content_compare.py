"""Deep content-compare tests (2026-06-14). No LLM, no DB — fake audited client.

Covers: blind content masking, verifier selection for the rejected-claims
cross-check, index-mapping of cross-check results, and the kept-by-other count.
"""
from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from nestor_pulse_sdk.critique.content_compare import run_content_comparison


_CONTENT = {
    "shared": ["both define an agent harness"],
    "only_a": [{"point": "Klarna $60M ROI", "decision_relevant": True, "note": "hard number"}],
    "only_b": [{"point": "GraphRAG 35-45%", "decision_relevant": True, "note": "quantified"}],
    "redundancy": {"a": "repeats scaffold twice", "b": "single pass"},
    "size_characterization": "A is longer mostly due to repeated scaffolding, not new facts.",
    "coverage_gaps": ["A omits the air-gapped VRAM figure"],
}


class _Block:
    def __init__(self, text): self.text = text


class _Resp:
    def __init__(self, text): self.content = [_Block(text)]


class FakeAudited:
    """First call -> content JSON; second call (if any) -> cross-check JSON."""

    def __init__(self):
        self.prompts: list[str] = []

    async def anthropic_messages(self, *, run_id, tenant_id, model, **kwargs):
        prompt = kwargs["messages"][0]["content"]
        self.prompts.append(prompt)
        if "REJECTED CLAIMS" in prompt:
            # claim 1 present in other, claim 2 absent
            return _Resp(json.dumps({"results": [
                {"index": 1, "present": True, "evidence": "ADK also says the market grew 99%."},
                {"index": 2, "present": False, "evidence": ""},
            ]}))
        return _Resp(json.dumps(_CONTENT))


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _go(audited, rejected_by_engine):
    return _run(run_content_comparison(
        brief="Onderzoek X.\n\n[CLARIFICATION ANSWERS]\nextra",
        reports_by_engine={
            "adk": "## Report\n\nADK says the market grew 99%. The Tribunal is great.",
            "tribunal": "## Report\n\nTribunal says 15%.\n\n---\n\n## Verification\n\nstats",
        },
        rejected_by_engine=rejected_by_engine,
        audited=audited,
        run_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
    ))


class TestRunContentComparison:
    def test_content_pass_returns_buckets_and_label_map(self):
        result = _go(FakeAudited(), rejected_by_engine={})
        assert set(result["label_map"].keys()) == {"A", "B"}
        assert set(result["label_map"].values()) == {"adk", "tribunal"}
        assert result["content"]["shared"] == _CONTENT["shared"]
        assert result["rejected_crosscheck"] is None  # no rejected claims => no cross-check

    def test_content_pass_is_blind(self):
        audited = FakeAudited()
        _go(audited, rejected_by_engine={})
        body = audited.prompts[0].split("=== REPORT A ===", 1)[1].lower()
        assert "tribunal" not in body and "adk" not in body
        assert "verification" not in body
        assert "[clarification answers]" not in audited.prompts[0].lower()

    def test_crosscheck_runs_for_verifier_with_rejected_claims(self):
        audited = FakeAudited()
        rejected = {"tribunal": [
            {"text": "market grew 99%", "facet": "Q1", "reason": "failed_factcheck"},
            {"text": "some unverifiable thing", "facet": "Q1", "reason": "lost_conflict"},
        ]}
        result = _go(audited, rejected_by_engine=rejected)
        xc = result["rejected_crosscheck"]
        assert xc is not None
        assert xc["verifier"] == "tribunal" and xc["other"] == "adk"
        assert xc["total_rejected"] == 2
        assert len(xc["claims"]) == 2
        # claim 1 was kept by the other report, claim 2 was not
        assert xc["claims"][0]["present_in_other"] is True
        assert xc["claims"][0]["evidence"].startswith("ADK also says")
        assert xc["claims"][1]["present_in_other"] is False
        assert xc["kept_by_other_count"] == 1
        # reasons preserved
        assert xc["claims"][0]["reason"] == "failed_factcheck"
        assert xc["claims"][1]["reason"] == "lost_conflict"

    def test_no_crosscheck_when_no_engine_rejected_anything(self):
        result = _go(FakeAudited(), rejected_by_engine={"adk": [], "tribunal": []})
        assert result["rejected_crosscheck"] is None

    def test_requires_two_reports(self):
        with pytest.raises(ValueError):
            _run(run_content_comparison(
                brief="x", reports_by_engine={"adk": "r"}, rejected_by_engine={},
                audited=FakeAudited(), run_id=uuid.uuid4(), tenant_id=uuid.uuid4(),
            ))
