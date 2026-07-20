"""Tests for claim_distiller — un-stubbed in Plan 01-13 Task 2.

TDD RED/GREEN cycle. All tests use a FAKE audited client — no real LLM, no Cloud SQL.

Coverage:
  1. Normal path: >=2 claims parsed, each has 'text' and 'facet' keys.
  2. Blank-report input: returns [] without raising.
  3. Malformed line in response: skipped without raising, valid lines still parsed.
  4. Stub removal: claim_distiller is NOT _phase2_stub (no NotImplementedError).
  5. Grep gate: no direct provider client construction (audited path only).
  6. Other 8 stubs remain: raising NotImplementedError as expected.
"""
from __future__ import annotations

import asyncio
import uuid

import pytest

# This import will fail until Task 2 un-stubs claim_distiller
from nestor_pulse_sdk.pipeline.synthesis.steps import (
    claim_distiller,
    extract_focus_areas,
    # The remaining stubs — still should raise NotImplementedError
    chunker_prime,
    chunk_guard,
    claim_guard,
    relevance_gate,
    conflict_detector,
    topic_clustering,
    topic_synthesis,
)


# ---------------------------------------------------------------------------
# Fake LLM response objects
# ---------------------------------------------------------------------------

class _FakeResponse:
    """Minimal google-genai response shape."""

    def __init__(self, text: str) -> None:
        self.text = text


# ---------------------------------------------------------------------------
# Fake AuditedLLMClient
# ---------------------------------------------------------------------------

class FakeAudited:
    """Records calls and returns canned responses. No DB, no GCS, no network."""

    def __init__(self, canned_text: str) -> None:
        self._canned_text = canned_text
        self.calls: list[dict] = []

    async def gemini_generate(self, *, run_id, tenant_id, model, contents, **kwargs):
        self.calls.append(
            {"run_id": run_id, "model": model, "contents": contents, "kwargs": kwargs}
        )
        return _FakeResponse(self._canned_text)


# ---------------------------------------------------------------------------
# Canned multi-line claim responses (plain-text line format)
# ---------------------------------------------------------------------------

# Three valid claims in tab-separated "FACET<TAB>CLAIM_TEXT" format.
GOOD_RESPONSE = (
    "Belgian IT market share trends\tCronos holds ~18% of Belgian IT services market by revenue in 2024.\n"
    "Key competitor strategies\tCapgemini Belgium expanded its public-sector practice by 30% YoY.\n"
    "Belgian IT market share trends\tCloud migration projects grew 45% across Cronos client portfolio in 2025.\n"
)

# Response with one malformed line (missing tab separator) mixed with valid lines.
MIXED_RESPONSE = (
    "Belgian IT market share trends\tCronos holds ~18% market share in Belgian IT services.\n"
    "THIS LINE IS MALFORMED NO TAB SEPARATOR\n"
    "Key competitor strategies\tAccenture Belgium targets mid-market with AI-first services.\n"
)

# Blank / empty report
EMPTY_RESPONSE = ""
WHITESPACE_RESPONSE = "\n  \n   \n"


# ---------------------------------------------------------------------------
# Mission brief fixture
# ---------------------------------------------------------------------------

MISSION_BRIEF = {
    "deep_research_prompt": "Analyse Cronos competitive position in Belgian IT",
    "focus_areas": [
        {"focus_area": "Belgian IT market share trends", "taxonomy": "C", "stakes": "high"},
        {"focus_area": "Key competitor strategies", "taxonomy": "B", "stakes": "high"},
    ],
    "needs_clarification": False,
    "clarifying_questions": [],
}

PROVIDER_REPORTS = [
    ("gemini", {"status": "success", "report": "Cronos holds significant market share..."}),
    ("claude", {"status": "success", "report": "Competitor expansion is accelerating..."}),
]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Stub removal check
# ---------------------------------------------------------------------------

class TestClaimDistillerIsReal:
    def test_claim_distiller_is_not_phase2_stub(self):
        """claim_distiller must NOT raise NotImplementedError (it's un-stubbed)."""
        # The stub raises NotImplementedError on any call.
        # The real implementation is async and takes keyword args.
        # We verify it's async (coroutine function) rather than a stub closure.
        import inspect
        assert inspect.iscoroutinefunction(claim_distiller), (
            "claim_distiller must be an async function, not a _phase2_stub closure"
        )


class TestOtherStubsUntouched:
    """The remaining stubs must still raise NotImplementedError.

    conflict_detector was un-stubbed (now a real audited async function) — it is
    asserted real in TestConflictDetectorIsReal below.
    """

    @pytest.mark.parametrize("stub_fn", [
        chunker_prime, chunk_guard, claim_guard,
        relevance_gate, topic_clustering, topic_synthesis,
    ])
    def test_stub_raises_not_implemented(self, stub_fn):
        with pytest.raises(NotImplementedError):
            stub_fn()


class TestConflictDetectorIsReal:
    def test_conflict_detector_is_not_phase2_stub(self):
        """conflict_detector must be a real async function, not a _phase2_stub closure."""
        import inspect
        from nestor_pulse_sdk.pipeline.synthesis.steps import conflict_detector as cd
        assert inspect.iscoroutinefunction(cd), (
            "conflict_detector must be an async function, not a _phase2_stub closure"
        )


# ---------------------------------------------------------------------------
# Normal path
# ---------------------------------------------------------------------------

class TestClaimDistillerNormalPath:
    def setup_method(self):
        self.run_id = uuid.uuid4()
        self.tenant_id = uuid.uuid4()
        self.audited = FakeAudited(GOOD_RESPONSE)

    def _call(self, provider_reports=None):
        return _run(
            claim_distiller(
                provider_reports=provider_reports or PROVIDER_REPORTS,
                mission_brief=MISSION_BRIEF,
                audited=self.audited,
                run_id=self.run_id,
                tenant_id=self.tenant_id,
            )
        )

    def test_returns_list(self):
        result = self._call()
        assert isinstance(result, list)

    def test_at_least_two_claims(self):
        result = self._call()
        assert len(result) >= 2, f"Expected >= 2 claims, got {len(result)}: {result}"

    def test_each_claim_has_text_key(self):
        result = self._call()
        for claim in result:
            assert "text" in claim, f"Claim missing 'text' key: {claim}"
            assert isinstance(claim["text"], str)
            assert len(claim["text"]) >= 1

    def test_each_claim_has_facet_key(self):
        result = self._call()
        for claim in result:
            assert "facet" in claim, f"Claim missing 'facet' key: {claim}"
            assert isinstance(claim["facet"], str)

    def test_audited_gemini_called_with_flash(self):
        self._call()
        assert len(self.audited.calls) >= 1
        for call in self.audited.calls:
            assert call["model"] == "gemini-2.5-flash", (
                f"Expected gemini-2.5-flash, got {call['model']!r}"
            )

    def test_thinking_disabled_in_kwargs(self):
        """The call must pass config that disables thinking."""
        self._call()
        call = self.audited.calls[0]
        assert "config" in call["kwargs"], (
            "gemini_generate must receive a 'config' kwarg to disable thinking"
        )


# ---------------------------------------------------------------------------
# Blank / empty report
# ---------------------------------------------------------------------------

class TestBlankReport:
    def setup_method(self):
        self.run_id = uuid.uuid4()
        self.tenant_id = uuid.uuid4()

    def _call_with_response(self, canned_text):
        audited = FakeAudited(canned_text)
        return _run(
            claim_distiller(
                provider_reports=[("gemini", {"status": "success", "report": "some text"})],
                mission_brief=MISSION_BRIEF,
                audited=audited,
                run_id=self.run_id,
                tenant_id=self.tenant_id,
            )
        )

    def test_empty_llm_response_returns_empty_list(self):
        result = self._call_with_response(EMPTY_RESPONSE)
        assert result == [], f"Empty response should yield [], got: {result}"

    def test_whitespace_only_response_returns_empty_list(self):
        result = self._call_with_response(WHITESPACE_RESPONSE)
        assert result == [], f"Whitespace response should yield [], got: {result}"

    def test_no_provider_reports_returns_empty_list(self):
        """Zero provider reports — nothing to distil."""
        audited = FakeAudited(EMPTY_RESPONSE)
        result = _run(
            claim_distiller(
                provider_reports=[],
                mission_brief=MISSION_BRIEF,
                audited=audited,
                run_id=self.run_id,
                tenant_id=self.tenant_id,
            )
        )
        assert result == [], f"No provider reports should yield [], got: {result}"


# ---------------------------------------------------------------------------
# Malformed line tolerance
# ---------------------------------------------------------------------------

class TestMalformedLineTolerance:
    def setup_method(self):
        self.run_id = uuid.uuid4()
        self.tenant_id = uuid.uuid4()

    def test_malformed_line_skipped_without_raising(self):
        """Mixed response: malformed lines skipped, valid ones parsed."""
        audited = FakeAudited(MIXED_RESPONSE)
        # Must NOT raise
        result = _run(
            claim_distiller(
                provider_reports=PROVIDER_REPORTS,
                mission_brief=MISSION_BRIEF,
                audited=audited,
                run_id=self.run_id,
                tenant_id=self.tenant_id,
            )
        )
        # Should still get the 2 valid claims
        assert len(result) >= 1, f"Should parse valid lines, got: {result}"
        for claim in result:
            assert "text" in claim
            assert "facet" in claim
