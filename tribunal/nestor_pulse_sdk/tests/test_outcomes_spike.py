"""
Tests for ADR-005: Outcomes spike harness (Task 1) + quality_gate package (Task 3).

Test groups:

A. Spike harness smoke tests (Task 1 -- the original 5)
   - test_outcomes_spike_harness_runs_to_completion
   - test_audit_log_records_existing_gate_calls
   - test_existing_quality_gate_port (parametrised)
   - test_spike_result_agreement_field
   - test_spike_result_dataclass_fields

B. Quality-gate factory + protocol tests (Task 3, ACCEPT-WITH-FLAG)
   - test_factory_default_returns_existing_gate
   - test_factory_outcomes_flag_returns_llm_judge
   - test_factory_unknown_flag_falls_back_to_existing
   - test_factory_env_var_selects_gate
   - test_both_gates_implement_protocol

C. Rubric YAML loader tests (Task 3)
   - test_default_rubric_loads
   - test_rubric_has_two_enabled_dimensions
   - test_disabled_dimensions_have_explicit_phase_marker
   - test_enabled_weights_renormalise_to_one
   - test_rubric_rejects_pass_threshold_out_of_range
   - test_rubric_rejects_all_disabled

D. LLMJudgeGate aggregation tests (Task 3, no live API)
   - test_judge_requires_audited_llm_client
   - test_judge_requires_run_id_and_tenant_id
   - test_judge_aggregate_pass_when_all_dims_above_threshold
   - test_judge_aggregate_fail_when_one_dim_below_threshold
   - test_judge_aggregate_weighted_avg_respects_renormalisation
   - test_judge_parses_clean_json_response
   - test_judge_regex_fallback_when_json_malformed
   - test_judge_handles_exception_from_audited_client

E. Live integration test (Task 3) -- marked @pytest.mark.live, opt-in only
   - test_judge_grades_canned_samples_via_audited_client (skipped by default)
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Importorskip guards
# ---------------------------------------------------------------------------

outcomes_spike = pytest.importorskip(
    "nestor_pulse_sdk.pipeline.synthesis.outcomes_spike",
    reason="outcomes_spike lands in Plan 08",
)

sample_data = pytest.importorskip(
    "nestor_pulse_sdk.tests.fixtures.synthesis_samples.sample_data",
    reason="sample_data lands in Plan 08",
)

quality_gate_pkg = pytest.importorskip(
    "nestor_pulse_sdk.pipeline.synthesis.quality_gate",
    reason="quality_gate package lands in Plan 08 Task 3",
)


def run_async(coro):
    """Run a coroutine from synchronous test code."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ===========================================================================
# A. Spike harness smoke tests (Task 1)
# ===========================================================================

def test_outcomes_spike_harness_runs_to_completion():
    """main() returns 5 SpikeResults with valid fields in dry_run mode."""
    outcomes_spike.spike_audit_log.clear()
    results = run_async(outcomes_spike.main(dry_run=True))

    assert isinstance(results, list)
    assert len(results) == 5

    expected_ids = {
        "strategy_healthy", "competitor_bullets", "short_stub",
        "no_headers", "mixed_quality",
    }
    assert {r.sample_id for r in results} == expected_ids

    for result in results:
        assert isinstance(result, outcomes_spike.SpikeResult)
        assert result.existing_verdict in ("pass", "iterate", "fail")
        assert 0.0 <= result.judge_score <= 1.0
        assert isinstance(result.agreement, bool)
        assert isinstance(result.judge_breakdown, dict)


def test_audit_log_records_existing_gate_calls():
    """spike_audit_log records every deterministic gate call (provider='local')."""
    outcomes_spike.spike_audit_log.clear()
    run_async(outcomes_spike.run_spike(dry_run=True))

    local_calls = [
        e for e in outcomes_spike.spike_audit_log if e.get("provider") == "local"
    ]
    assert len(local_calls) == 5

    anthropic_calls = [
        e for e in outcomes_spike.spike_audit_log if e.get("provider") == "anthropic"
    ]
    for entry in anthropic_calls:
        assert entry["cost_usd"] == 0.0
        assert entry["latency_ms"] == 0


@pytest.mark.parametrize("sample_id,expected_verdict", [
    ("strategy_healthy", "pass"),
    ("competitor_bullets", "fail"),
    ("short_stub", "fail"),
    ("no_headers", "fail"),
    ("mixed_quality", "pass"),
])
def test_existing_quality_gate_port(sample_id: str, expected_verdict: str):
    """Ported deterministic gate matches expected per-sample verdict."""
    samples = {s.sample_id: s for s in sample_data.ALL_SAMPLES}
    sample = samples[sample_id]
    verdict, _ = outcomes_spike.existing_quality_gate(sample.synthesis, sample.focus_areas)
    assert verdict == expected_verdict


def test_spike_result_agreement_field():
    """Agreement field reflects pass-vs-not-pass agreement between gate + judge."""
    outcomes_spike.spike_audit_log.clear()
    results = run_async(outcomes_spike.run_spike(dry_run=True))

    for result in results:
        existing_good = result.existing_verdict == "pass"
        judge_good = result.judge_overall_verdict == "pass"
        expected_agreement = existing_good == judge_good
        assert result.agreement == expected_agreement


def test_spike_result_dataclass_fields():
    """SpikeResult exposes the plan-specified fields."""
    import dataclasses
    required = {
        "sample_id", "existing_verdict", "existing_feedback",
        "judge_score", "judge_breakdown", "judge_overall_verdict",
        "cost_usd_judge", "latency_ms_judge", "agreement",
        "outcomes_api_available", "proxy_note",
    }
    actual = {f.name for f in dataclasses.fields(outcomes_spike.SpikeResult)}
    assert required <= actual


# ===========================================================================
# B. Factory + protocol tests (Task 3)
# ===========================================================================

def test_factory_default_returns_existing_gate():
    """No env var, no arg -> ExistingHeuristicGate."""
    gate = quality_gate_pkg.build_quality_gate(flag="existing")
    assert isinstance(gate, quality_gate_pkg.ExistingHeuristicGate)
    assert gate.name == "existing"


def test_factory_outcomes_flag_returns_llm_judge():
    """flag='outcomes' -> LLMJudgeGate."""
    gate = quality_gate_pkg.build_quality_gate(flag="outcomes")
    assert isinstance(gate, quality_gate_pkg.LLMJudgeGate)
    assert gate.name == "outcomes"


def test_factory_unknown_flag_falls_back_to_existing():
    """Unknown flag falls back to existing with a warning (no crash)."""
    gate = quality_gate_pkg.build_quality_gate(flag="not_a_real_flag")
    assert isinstance(gate, quality_gate_pkg.ExistingHeuristicGate)


def test_factory_env_var_selects_gate(monkeypatch):
    """NESTOR_QUALITY_GATE env var routes the factory."""
    monkeypatch.setenv("NESTOR_QUALITY_GATE", "outcomes")
    gate = quality_gate_pkg.build_quality_gate()
    assert isinstance(gate, quality_gate_pkg.LLMJudgeGate)

    monkeypatch.setenv("NESTOR_QUALITY_GATE", "existing")
    gate = quality_gate_pkg.build_quality_gate()
    assert isinstance(gate, quality_gate_pkg.ExistingHeuristicGate)


def test_both_gates_implement_protocol():
    """Both implementations satisfy the QualityGate Protocol (runtime check)."""
    existing = quality_gate_pkg.ExistingHeuristicGate()
    judge = quality_gate_pkg.LLMJudgeGate()
    assert isinstance(existing, quality_gate_pkg.QualityGate)
    assert isinstance(judge, quality_gate_pkg.QualityGate)


def test_existing_gate_protocol_grade_works_without_audited():
    """ExistingHeuristicGate.grade ignores audited/run_id/tenant_id."""
    gate = quality_gate_pkg.ExistingHeuristicGate()
    verdict = run_async(gate.grade(
        synthesis=sample_data.SAMPLE_1.synthesis,
        focus_areas=sample_data.SAMPLE_1.focus_areas,
    ))
    assert isinstance(verdict, quality_gate_pkg.Verdict)
    assert verdict.pass_ is True
    assert verdict.legacy_verdict == "pass"


# ===========================================================================
# C. Rubric YAML loader tests (Task 3)
# ===========================================================================

def test_default_rubric_loads():
    """Default YAML file loads without error."""
    rubric = quality_gate_pkg.load_rubric()
    assert rubric.version == 1
    assert rubric.judge_model == "claude-sonnet-4-6"
    assert rubric.pass_threshold == 3.8
    assert rubric.samples == 1
    assert len(rubric.dimensions) == 6


def test_rubric_has_two_enabled_dimensions():
    """Per ADR-005 ACCEPT-WITH-FLAG: only groundedness + actionability enabled now."""
    rubric = quality_gate_pkg.load_rubric()
    enabled = rubric.enabled_dimensions()
    enabled_ids = {d.id for d in enabled}
    assert enabled_ids == {"groundedness", "actionability"}


def test_disabled_dimensions_have_explicit_phase_marker():
    """Disabled dims (3-6) match the spec — coverage/coherence/precision/conflict."""
    rubric = quality_gate_pkg.load_rubric()
    disabled = {d.id for d in rubric.dimensions if not d.enabled}
    assert disabled == {
        "focus_area_coverage", "coherence",
        "calibrated_precision", "conflict_surfacing",
    }


def test_enabled_weights_renormalise_to_one():
    """Weights renormalise so sum=1.0 over enabled dims, preserving ratios."""
    rubric = quality_gate_pkg.load_rubric()
    weights = rubric.enabled_weights()
    assert pytest.approx(sum(weights.values()), abs=1e-9) == 1.0

    # Ratio between groundedness (0.30) and actionability (0.25) preserved
    raw_ratio = 0.30 / 0.25
    actual_ratio = weights["groundedness"] / weights["actionability"]
    assert pytest.approx(actual_ratio, rel=1e-9) == raw_ratio


def test_enabled_weights_renormalise_with_synthetic_rubric():
    """Manually disable a heavy dim and verify renormalisation arithmetic."""
    from nestor_pulse_sdk.pipeline.synthesis.quality_gate.llm_judge.rubric import (
        Rubric, RubricDimension, RubricAnchor,
    )

    def make_dim(id_: str, enabled: bool, weight: float, threshold: float = 3.0) -> RubricDimension:
        return RubricDimension(
            id=id_, enabled=enabled, weight=weight, threshold=threshold,
            question="?", anchor_bad=RubricAnchor(1, "bad", "why"),
            anchor_good=RubricAnchor(5, "good", "why"),
        )

    r = Rubric(
        version=1, judge_model="x", pass_threshold=3.5, samples=1,
        bias_mitigation={},
        dimensions=(
            make_dim("a", True, 0.40),
            make_dim("b", True, 0.20),
            make_dim("c", False, 0.40),
        ),
    )
    weights = r.enabled_weights()
    assert pytest.approx(weights["a"], abs=1e-9) == 0.40 / 0.60
    assert pytest.approx(weights["b"], abs=1e-9) == 0.20 / 0.60
    assert "c" not in weights


def test_rubric_rejects_pass_threshold_out_of_range():
    """pass_threshold outside [1.0, 5.0] is rejected."""
    from nestor_pulse_sdk.pipeline.synthesis.quality_gate.llm_judge.rubric import Rubric
    with pytest.raises(ValueError, match="pass_threshold"):
        Rubric.from_dict({
            "version": 1, "judge_model": "x", "pass_threshold": 6.0, "samples": 1,
            "bias_mitigation": {},
            "dimensions": [{
                "id": "a", "enabled": True, "weight": 1.0, "threshold": 3.0,
                "question": "?",
                "anchors": {
                    "bad": {"score": 1, "example": "x", "why": "y"},
                    "good": {"score": 5, "example": "x", "why": "y"},
                },
            }],
        })


def test_rubric_rejects_all_disabled():
    """A rubric with zero enabled dims is rejected at load time."""
    from nestor_pulse_sdk.pipeline.synthesis.quality_gate.llm_judge.rubric import Rubric
    with pytest.raises(ValueError, match="enabled"):
        Rubric.from_dict({
            "version": 1, "judge_model": "x", "pass_threshold": 3.0, "samples": 1,
            "bias_mitigation": {},
            "dimensions": [{
                "id": "a", "enabled": False, "weight": 1.0, "threshold": 3.0,
                "question": "?",
                "anchors": {
                    "bad": {"score": 1, "example": "x", "why": "y"},
                    "good": {"score": 5, "example": "x", "why": "y"},
                },
            }],
        })


# ===========================================================================
# D. LLMJudgeGate aggregation tests (no live API)
# ===========================================================================

def _build_fake_anthropic_response(text: str) -> MagicMock:
    """Build an object that mimics anthropic.types.Message with `.content[0].text`."""
    block = MagicMock()
    block.text = text
    msg = MagicMock()
    msg.content = [block]
    return msg


def _build_fake_audited(responses: list[str]) -> MagicMock:
    """
    Fake AuditedLLMClient whose anthropic_messages returns canned responses in order.
    Each call pops the next response from `responses`.
    """
    fake = MagicMock()
    queue = list(responses)

    async def fake_anthropic_messages(*, run_id, tenant_id, model, **kwargs):
        if not queue:
            raise RuntimeError("Fake audited ran out of canned responses")
        return _build_fake_anthropic_response(queue.pop(0))

    async def fake_write_failure(*, run_id, tenant_id, provider, error):
        return None

    fake.anthropic_messages = AsyncMock(side_effect=fake_anthropic_messages)
    fake.write_failure = AsyncMock(side_effect=fake_write_failure)
    return fake


def test_judge_requires_audited_llm_client():
    """LLMJudgeGate.grade raises if audited is not provided."""
    gate = quality_gate_pkg.LLMJudgeGate()
    with pytest.raises(ValueError, match="AuditedLLMClient"):
        run_async(gate.grade(
            synthesis="some text",
            run_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
        ))


def test_judge_requires_run_id_and_tenant_id():
    """LLMJudgeGate.grade raises if run_id or tenant_id are missing."""
    gate = quality_gate_pkg.LLMJudgeGate()
    fake = _build_fake_audited([])
    with pytest.raises(ValueError, match="run_id and tenant_id"):
        run_async(gate.grade(
            synthesis="x", audited=fake,
            run_id=None, tenant_id=uuid.uuid4(),
        ))


def test_judge_aggregate_pass_when_all_dims_above_threshold():
    """Verdict.pass_ True when every enabled dim score >= threshold AND weighted_avg >= pass_threshold."""
    gate = quality_gate_pkg.LLMJudgeGate()
    # Default rubric: groundedness threshold=4.0, actionability threshold=3.5
    # pass_threshold=3.8
    responses = [
        json.dumps({"dimension": "groundedness", "score": 5, "reason": "great", "fixes": []}),
        json.dumps({"dimension": "actionability", "score": 4, "reason": "good", "fixes": []}),
    ]
    fake = _build_fake_audited(responses)

    verdict = run_async(gate.grade(
        synthesis="dummy",
        audited=fake,
        run_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
    ))

    assert verdict.pass_ is True
    assert verdict.legacy_verdict == "pass"
    assert verdict.per_dim_scores["groundedness"] == 5.0
    assert verdict.per_dim_scores["actionability"] == 4.0
    # weighted_avg over renormalised (0.545, 0.455) => 5*0.545 + 4*0.455 = 4.545
    assert pytest.approx(verdict.weighted_avg, abs=0.01) == (5 * 0.30 + 4 * 0.25) / 0.55


def test_judge_aggregate_fail_when_one_dim_below_threshold():
    """Verdict.pass_ False if any enabled dim drops below its per-dim threshold."""
    gate = quality_gate_pkg.LLMJudgeGate()
    # groundedness threshold=4.0; score 3 is below
    responses = [
        json.dumps({"dimension": "groundedness", "score": 3, "reason": "weak", "fixes": ["cite §2"]}),
        json.dumps({"dimension": "actionability", "score": 5, "reason": "great", "fixes": []}),
    ]
    fake = _build_fake_audited(responses)

    verdict = run_async(gate.grade(
        synthesis="dummy", audited=fake,
        run_id=uuid.uuid4(), tenant_id=uuid.uuid4(),
    ))

    assert verdict.pass_ is False
    assert "groundedness" in [f.split(']')[0].strip('[') for f in verdict.fixes]


def test_judge_aggregate_weighted_avg_respects_renormalisation():
    """Weighted average uses renormalised weights, not raw."""
    gate = quality_gate_pkg.LLMJudgeGate()
    responses = [
        json.dumps({"dimension": "groundedness", "score": 4, "reason": "ok", "fixes": []}),
        json.dumps({"dimension": "actionability", "score": 4, "reason": "ok", "fixes": []}),
    ]
    fake = _build_fake_audited(responses)
    verdict = run_async(gate.grade(
        synthesis="dummy", audited=fake,
        run_id=uuid.uuid4(), tenant_id=uuid.uuid4(),
    ))
    # both 4 => weighted_avg must be 4.0 exactly (independent of weight ratio)
    assert pytest.approx(verdict.weighted_avg, abs=1e-9) == 4.0


def test_judge_parses_clean_json_response():
    """JSON without fences parses straight through."""
    gate = quality_gate_pkg.LLMJudgeGate()
    resp = '{"dimension": "groundedness", "score": 4, "reason": "ok", "fixes": []}'
    parsed = gate._parse_judge_response(resp, "groundedness")
    assert parsed["score"] == 4
    assert parsed["dim_id"] == "groundedness"


def test_judge_parses_response_with_markdown_fences():
    """JSON wrapped in ```json fences still parses."""
    gate = quality_gate_pkg.LLMJudgeGate()
    resp = '```json\n{"dimension": "x", "score": 3, "reason": "ok", "fixes": []}\n```'
    parsed = gate._parse_judge_response(resp, "x")
    assert parsed["score"] == 3


def test_judge_regex_fallback_when_json_malformed():
    """Malformed JSON falls back to regex score extraction, doesn't crash."""
    gate = quality_gate_pkg.LLMJudgeGate()
    resp = 'I think this is a 3 because of various reasons. "score": 3, but I forgot the closing brace'
    parsed = gate._parse_judge_response(resp, "x")
    assert parsed["score"] == 3
    assert parsed["raw"].get("parse_status") == "regex_fallback"


def test_judge_handles_exception_from_audited_client():
    """If audited.anthropic_messages raises, that dim gets score=1 + write_failure called."""
    gate = quality_gate_pkg.LLMJudgeGate()
    fake = MagicMock()
    fake.anthropic_messages = AsyncMock(side_effect=RuntimeError("network down"))
    fake.write_failure = AsyncMock(return_value=None)

    verdict = run_async(gate.grade(
        synthesis="dummy", audited=fake,
        run_id=uuid.uuid4(), tenant_id=uuid.uuid4(),
    ))

    # Both enabled dims should have score 1 (since both calls fail)
    assert verdict.per_dim_scores["groundedness"] == 1.0
    assert verdict.per_dim_scores["actionability"] == 1.0
    assert verdict.pass_ is False
    assert verdict.legacy_verdict == "fail"
    # write_failure should be called twice (once per failed dim)
    assert fake.write_failure.call_count == 2


def test_judge_clamps_out_of_range_scores():
    """If the judge returns score>5 or score<1, we clamp instead of crashing."""
    gate = quality_gate_pkg.LLMJudgeGate()
    resp = '{"dimension": "x", "score": 7, "reason": "ok", "fixes": []}'
    parsed = gate._parse_judge_response(resp, "x")
    assert parsed["score"] == 5


# ===========================================================================
# E. Live integration test (opt-in only)
# ===========================================================================

@pytest.mark.live
def test_judge_grades_canned_samples_via_audited_client():
    """
    Real-API integration test. Skipped by default; run with: pytest -m live.

    Grades 2 canned samples via a real LLMJudgeGate + a stub AuditedLLMClient
    that wraps the real anthropic.AsyncAnthropic. Verifies:
      - Judge produces score 1-5 for each enabled dim
      - Verdict.pass_ resolves
      - Total cost > 0 (real API was called)

    Note: this test is NOT run in CI -- it requires ANTHROPIC_API_KEY and
    costs ~$0.02 per run. The spike report (Task 1) provides the canonical
    live-API measurements.
    """
    pytest.skip(
        "Live test placeholder. Real measurements live in 01-08-SPIKE-REPORT.md. "
        "Plan 09 will wire LLMJudgeGate to the real AuditedLLMClient and add "
        "smoke coverage at integration test time."
    )
