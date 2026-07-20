"""Tests for tribunal package: adaptive_intake + taxonomy.

Plan 01-13 Task 1 — TDD RED/GREEN cycle.

All tests use a FAKE audited client — no real LLM, no Cloud SQL, no network.
The fake returns pre-canned LLM responses so we can drive both the
clear-brief and vague-brief paths deterministically.

Coverage:
  1. clear-brief path: needs_clarification=False, >=1 stakes-tagged focus area,
     taxonomy in {A,B,C,D}, stakes in {low,med,high}.
  2. vague-brief path: needs_clarification=True, 2-3 clarifying questions emitted,
     no fabricated focus_areas.
  3. backward-compat: every focus_area dict has a 'focus_area' str key so
     extract_focus_areas() from synthesis.steps returns non-empty strings.
  4. taxonomy constants: TAXONOMY and STAKES_TIERS are importable from
     nestor_pulse_sdk.pipeline.tribunal.taxonomy.
"""
from __future__ import annotations

import asyncio
import uuid

import pytest

from nestor_pulse_sdk.pipeline.tribunal import adaptive_intake
from nestor_pulse_sdk.pipeline.tribunal.taxonomy import TAXONOMY, STAKES_TIERS
from nestor_pulse_sdk.pipeline.synthesis.steps import extract_focus_areas


# ---------------------------------------------------------------------------
# Fake LLM response objects
# ---------------------------------------------------------------------------

class _FakeResponse:
    """Minimal object that mirrors the google-genai response shape."""

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
# Canned LLM outputs
# ---------------------------------------------------------------------------

# Clear-brief response: sharpened prompt + 3 focus areas with taxonomy + stakes
CLEAR_BRIEF_RESPONSE = """\
BRIEF_CLEAR
DEEP_RESEARCH_PROMPT: Analyse Cronos Group's competitive positioning in the Belgian IT services market, focusing on market share trends, key competitor strategies, and emerging tech adoption patterns for 2025-2026.
FOCUS_AREA: Belgian IT market share trends | TAXONOMY: C | STAKES: high
FOCUS_AREA: Key competitor strategies | TAXONOMY: B | STAKES: high
FOCUS_AREA: Emerging tech adoption 2025-2026 | TAXONOMY: A | STAKES: med
"""

# Vague-brief response: underspecified → questions, no focus_areas
VAGUE_BRIEF_RESPONSE = """\
BRIEF_VAGUE
CLARIFYING_QUESTION: Which specific geographic markets or client segments are most important to your analysis?
CLARIFYING_QUESTION: Are you focused on a particular technology domain (cloud, AI, cybersecurity) or the full-service portfolio?
CLARIFYING_QUESTION: What is the primary use case for this research — competitive bid, strategic planning, or M&A due diligence?
"""


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Taxonomy constants tests
# ---------------------------------------------------------------------------

class TestTaxonomyConstants:
    def test_taxonomy_has_abcd_keys(self):
        assert set(TAXONOMY.keys()) == {"A", "B", "C", "D"}

    def test_taxonomy_values(self):
        assert TAXONOMY["A"] == "Customer"
        assert TAXONOMY["B"] == "Competitor"
        assert TAXONOMY["C"] == "Trend"
        assert TAXONOMY["D"] == "Strategy"

    def test_stakes_tiers(self):
        assert set(STAKES_TIERS) == {"low", "med", "high"}


# ---------------------------------------------------------------------------
# Clear-brief path
# ---------------------------------------------------------------------------

class TestClearBrief:
    def setup_method(self):
        self.run_id = uuid.uuid4()
        self.tenant_id = uuid.uuid4()
        self.audited = FakeAudited(CLEAR_BRIEF_RESPONSE)
        self.brief = (
            "Analyse Cronos Group's competitive positioning in the Belgian IT services "
            "market — market share, competitor strategies, and tech adoption for 2025-2026."
        )

    def _call(self):
        return _run(
            adaptive_intake(
                brief=self.brief,
                audited=self.audited,
                run_id=self.run_id,
                tenant_id=self.tenant_id,
            )
        )

    def test_needs_clarification_false(self):
        result = self._call()
        assert result["needs_clarification"] is False

    def test_has_deep_research_prompt(self):
        result = self._call()
        assert result.get("deep_research_prompt")
        assert isinstance(result["deep_research_prompt"], str)
        assert len(result["deep_research_prompt"]) >= 10

    def test_has_focus_areas(self):
        result = self._call()
        fas = result.get("focus_areas") or []
        assert len(fas) >= 1

    def test_focus_area_dicts_have_required_keys(self):
        result = self._call()
        for fa in result["focus_areas"]:
            assert "focus_area" in fa, f"Missing focus_area key in {fa}"
            assert "taxonomy" in fa, f"Missing taxonomy key in {fa}"
            assert "stakes" in fa, f"Missing stakes key in {fa}"

    def test_taxonomy_values_in_abcd(self):
        result = self._call()
        for fa in result["focus_areas"]:
            assert fa["taxonomy"] in {"A", "B", "C", "D"}, (
                f"taxonomy={fa['taxonomy']!r} not in {{A,B,C,D}}"
            )

    def test_stakes_values_in_valid_set(self):
        result = self._call()
        for fa in result["focus_areas"]:
            assert fa["stakes"] in {"low", "med", "high"}, (
                f"stakes={fa['stakes']!r} not in {{low,med,high}}"
            )

    def test_no_clarifying_questions(self):
        result = self._call()
        assert not result.get("clarifying_questions"), (
            "Clear brief should not return clarifying_questions"
        )

    def test_audited_gemini_generate_called_once(self):
        self._call()
        assert len(self.audited.calls) == 1
        call = self.audited.calls[0]
        assert call["model"] == "gemini-2.5-flash"

    def test_thinking_disabled_in_kwargs(self):
        """The call must pass config that disables thinking."""
        self._call()
        call = self.audited.calls[0]
        # The config kwarg must be present (passed via **kwargs to gemini_generate)
        assert "config" in call["kwargs"], (
            "gemini_generate must receive a 'config' kwarg to disable thinking"
        )


# ---------------------------------------------------------------------------
# Vague-brief path
# ---------------------------------------------------------------------------

class TestVagueBrief:
    def setup_method(self):
        self.run_id = uuid.uuid4()
        self.tenant_id = uuid.uuid4()
        self.audited = FakeAudited(VAGUE_BRIEF_RESPONSE)
        self.brief = "Tell me about technology."  # underspecified

    def _call(self):
        return _run(
            adaptive_intake(
                brief=self.brief,
                audited=self.audited,
                run_id=self.run_id,
                tenant_id=self.tenant_id,
            )
        )

    def test_needs_clarification_true(self):
        result = self._call()
        assert result["needs_clarification"] is True

    def test_has_clarifying_questions(self):
        result = self._call()
        qs = result.get("clarifying_questions") or []
        assert 2 <= len(qs) <= 3, (
            f"Expected 2-3 clarifying questions, got {len(qs)}: {qs}"
        )

    def test_clarifying_questions_are_strings(self):
        result = self._call()
        for q in result["clarifying_questions"]:
            assert isinstance(q, str)
            assert len(q) >= 10

    def test_no_fabricated_focus_areas(self):
        result = self._call()
        fas = result.get("focus_areas") or []
        assert len(fas) == 0, (
            f"Vague-brief path must not fabricate focus_areas; got: {fas}"
        )


# ---------------------------------------------------------------------------
# Backward-compatibility: extract_focus_areas still works
# ---------------------------------------------------------------------------

class TestBackwardCompat:
    def test_extract_focus_areas_returns_strings(self):
        """extract_focus_areas(intake_output) must return non-empty list of strings."""
        audited = FakeAudited(CLEAR_BRIEF_RESPONSE)
        result = _run(
            adaptive_intake(
                brief="Analyse Cronos competitive positioning in Belgian IT",
                audited=audited,
                run_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
            )
        )
        strings = extract_focus_areas(result)
        assert len(strings) >= 1, "extract_focus_areas returned empty list"
        for s in strings:
            assert isinstance(s, str)
            assert len(s) >= 1


# ---------------------------------------------------------------------------
# Coverage check: explicit multi-question briefs must not lose questions
# ---------------------------------------------------------------------------

from nestor_pulse_sdk.pipeline.tribunal.intake import detect_explicit_questions


FIVE_QUESTION_BRIEF = """\
Research briefing for LUKOIL Belgium. Answer V1-V4 in Dutch, V5 in English.

V1. Welke dynamische prijsstrategieen gebruiken Europese tankstations vandaag?
V2. Hoe positioneren concurrenten hun koffie-aanbod in Belgische tankstations?
V3. Welke shop- en gemaksconcepten werken het best voor tankstations?
V4. Welke loyaliteitsapps gebruiken Belgische consumenten en wat zijn de scan-ratios?
V5. Which AI tools are fuel retailers adopting for pricing and operations?
"""

# First intake attempt: only 4 focus areas (drops loyalty — the documented failure)
DROPPED_Q4_RESPONSE = """\
BRIEF_CLEAR
DEEP_RESEARCH_PROMPT: LUKOIL Belgium fuel retail strategy research. Answer V1-V4 in Dutch, V5 in English.
FOCUS_AREA: Dynamische prijsstrategieen Europese tankstations | TAXONOMY: B | STAKES: high
FOCUS_AREA: Koffie-aanbod Belgische tankstations | TAXONOMY: B | STAKES: med
FOCUS_AREA: Shop- en gemaksconcepten | TAXONOMY: C | STAKES: med
FOCUS_AREA: AI tools for fuel retail pricing | TAXONOMY: C | STAKES: high
"""

# Retry attempt: all 5 (what the coverage correction must force)
FULL_5_RESPONSE = """\
BRIEF_CLEAR
DEEP_RESEARCH_PROMPT: LUKOIL Belgium fuel retail strategy research. Answer V1-V4 in Dutch, V5 in English.
FOCUS_AREA: Dynamische prijsstrategieen Europese tankstations | TAXONOMY: B | STAKES: high
FOCUS_AREA: Koffie-aanbod Belgische tankstations | TAXONOMY: B | STAKES: med
FOCUS_AREA: Shop- en gemaksconcepten | TAXONOMY: C | STAKES: med
FOCUS_AREA: Loyaliteitsapps Belgische consumenten scan-ratios | TAXONOMY: A | STAKES: high
FOCUS_AREA: AI tools for fuel retail pricing | TAXONOMY: C | STAKES: high
"""


class FakeAuditedSequence:
    """Returns a different canned response per call (1st, 2nd, ...)."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def gemini_generate(self, *, run_id, tenant_id, model, contents, **kwargs):
        self.calls.append({"model": model, "contents": contents})
        idx = min(len(self.calls) - 1, len(self._responses) - 1)
        return _FakeResponse(self._responses[idx])


class TestQuestionDetection:
    def test_detects_enumerated_questions(self):
        detected = detect_explicit_questions(FIVE_QUESTION_BRIEF)
        assert len(detected) == 5, f"Expected 5 detected questions, got: {detected}"

    def test_free_prose_brief_detects_nothing(self):
        brief = (
            "Analyse Cronos Group's competitive positioning in the Belgian IT services "
            "market — market share, competitor strategies, and tech adoption for 2025-2026."
        )
        assert detect_explicit_questions(brief) == []

    def test_short_bullets_are_not_questions(self):
        # headers / 1-2 word bullets must not count
        brief = "Research plan:\n- Intro\n- Scope\n- Timing"
        assert detect_explicit_questions(brief) == []


class TestCoverageRetry:
    def test_dropped_question_triggers_retry_and_recovers(self):
        audited = FakeAuditedSequence([DROPPED_Q4_RESPONSE, FULL_5_RESPONSE])
        result = _run(
            adaptive_intake(
                brief=FIVE_QUESTION_BRIEF,
                audited=audited,
                run_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
            )
        )
        assert len(audited.calls) == 2, "coverage failure must force exactly one retry"
        assert len(result["focus_areas"]) == 5, (
            f"retry must recover all 5 questions, got {len(result['focus_areas'])}"
        )
        labels = " ".join(fa["focus_area"].lower() for fa in result["focus_areas"])
        assert "loyaliteit" in labels, "the dropped loyalty question must be recovered"
        # The retry prompt must list the detected questions explicitly
        assert "COVERAGE CORRECTION" in audited.calls[1]["contents"]

    def test_full_coverage_first_try_means_no_retry(self):
        audited = FakeAuditedSequence([FULL_5_RESPONSE])
        result = _run(
            adaptive_intake(
                brief=FIVE_QUESTION_BRIEF,
                audited=audited,
                run_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
            )
        )
        assert len(audited.calls) == 1, "full coverage must not trigger a retry"
        assert len(result["focus_areas"]) == 5

    def test_failed_retry_keeps_better_attempt(self):
        # Retry returns the same 4-FA response — keep it, don't loop, don't crash
        audited = FakeAuditedSequence([DROPPED_Q4_RESPONSE, DROPPED_Q4_RESPONSE])
        result = _run(
            adaptive_intake(
                brief=FIVE_QUESTION_BRIEF,
                audited=audited,
                run_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
            )
        )
        assert len(audited.calls) == 2
        assert len(result["focus_areas"]) == 4  # best available, exactly one retry

    def test_vague_brief_skips_coverage_check(self):
        audited = FakeAuditedSequence([VAGUE_BRIEF_RESPONSE])
        result = _run(
            adaptive_intake(
                brief=FIVE_QUESTION_BRIEF,
                audited=audited,
                run_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
            )
        )
        assert result["needs_clarification"] is True
        assert len(audited.calls) == 1


# ---------------------------------------------------------------------------
# Per-angle RESEARCH_PROMPT (plan item 1.1 — answer-enriched, scoped queries)
# ---------------------------------------------------------------------------

# Clear-brief response that includes a self-contained RESEARCH_PROMPT after each
# FOCUS_AREA. The labels stay verbatim (coverage key); the research_prompt is the
# rewritten, answer-enriched brief the researcher actually receives.
CLEAR_BRIEF_WITH_RESEARCH_PROMPTS = """\
BRIEF_CLEAR
DEEP_RESEARCH_PROMPT: Cronos Group Belgian IT services competitive positioning, 2025-2026.
FOCUS_AREA: Belgian IT market share trends | TAXONOMY: C | STAKES: high
RESEARCH_PROMPT: Research Belgian IT services market share trends for 2025-2026, focused on cloud and managed services for mid-market clients (per the client's clarification). Research ONLY market share dynamics; competitor strategy is covered separately.
FOCUS_AREA: Key competitor strategies | TAXONOMY: B | STAKES: med
RESEARCH_PROMPT: Research the go-to-market and pricing strategies of Cronos Group's top Belgian competitors in IT services. Research ONLY competitor strategy.
"""


class TestResearchPromptParsing:
    def setup_method(self):
        self.audited = FakeAudited(CLEAR_BRIEF_WITH_RESEARCH_PROMPTS)
        self.brief = "Cronos Group Belgian IT services — market share and competitor strategy."

    def _call(self):
        return _run(
            adaptive_intake(
                brief=self.brief,
                audited=self.audited,
                run_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
            )
        )

    def test_research_prompt_attached_to_each_focus_area(self):
        fas = self._call()["focus_areas"]
        assert len(fas) == 2
        assert fas[0]["research_prompt"].startswith("Research Belgian IT services market share")
        assert "mid-market" in fas[0]["research_prompt"]
        assert fas[1]["research_prompt"].startswith("Research the go-to-market")

    def test_label_stays_verbatim_not_overwritten_by_prompt(self):
        fas = self._call()["focus_areas"]
        # The label is the short coverage key, distinct from the long research_prompt.
        assert fas[0]["focus_area"] == "Belgian IT market share trends"
        assert fas[0]["research_prompt"] != fas[0]["focus_area"]

    def test_missing_research_prompt_defaults_to_empty(self):
        # The legacy response (no RESEARCH_PROMPT lines) must still parse, with
        # research_prompt == "" so divide() falls back gracefully.
        audited = FakeAudited(CLEAR_BRIEF_RESPONSE)
        fas = _run(
            adaptive_intake(
                brief="x", audited=audited, run_id=uuid.uuid4(), tenant_id=uuid.uuid4(),
            )
        )["focus_areas"]
        assert all(fa.get("research_prompt", "") == "" for fa in fas)


class TestDivideUsesResearchPrompt:
    def test_divide_sends_research_prompt_as_query(self):
        from nestor_pulse_sdk.pipeline.tribunal.research_division import divide
        mission_brief = {
            "deep_research_prompt": "shared one-liner that should NOT be the query",
            "focus_areas": [
                {
                    "focus_area": "Belgian IT market share trends",
                    "taxonomy": "C",
                    "stakes": "med",
                    "research_prompt": "Research Belgian IT services market share for mid-market cloud clients, 2025-2026. Research ONLY this.",
                },
            ],
        }
        angles = divide(mission_brief)
        assert len(angles) == 1
        assert angles[0]["query"].startswith("Research Belgian IT services market share")
        # The verbatim label survives as the coverage/display key.
        assert angles[0]["focus_area"] == "Belgian IT market share trends"
        # The shared one-liner must NOT have leaked into the query.
        assert "shared one-liner" not in angles[0]["query"]

    def test_divide_falls_back_to_label_plus_base_when_no_research_prompt(self):
        from nestor_pulse_sdk.pipeline.tribunal.research_division import divide
        mission_brief = {
            "deep_research_prompt": "base context",
            "focus_areas": [
                {"focus_area": "Competitor strategy", "taxonomy": "B", "stakes": "med"},
            ],
        }
        angles = divide(mission_brief)
        assert angles[0]["query"] == "Competitor strategy: base context"

    def test_divide_high_stakes_research_prompt_broad_copy_is_distinct(self):
        from nestor_pulse_sdk.pipeline.tribunal.research_division import divide
        mission_brief = {
            "deep_research_prompt": "base",
            "focus_areas": [
                {
                    "focus_area": "Pricing strategy",
                    "taxonomy": "B",
                    "stakes": "high",
                    "research_prompt": "Research competitor pricing strategy. Research ONLY this.",
                },
            ],
        }
        angles = divide(mission_brief)
        # High-stakes is doubled: focused copy + a distinct broad copy.
        assert len(angles) == 2
        assert angles[0]["query"] != angles[1]["query"]
        assert "broader" in angles[1]["query"].lower()


# ---------------------------------------------------------------------------
# One-language-per-run (no mixed language)
# ---------------------------------------------------------------------------

# Clear-brief response WITH a LANGUAGE line (the single run language).
CLEAR_BRIEF_NL_RESPONSE = """\
BRIEF_CLEAR
LANGUAGE: Dutch
DEEP_RESEARCH_PROMPT: Onderzoek de concurrentiepositie van Cronos Group in 2026.
FOCUS_AREA: Marktaandeel-trends | TAXONOMY: C | STAKES: high
RESEARCH_PROMPT: Onderzoek de marktaandeel-trends. Onderzoek ALLEEN deze vraag.
FOCUS_AREA: Concurrentstrategieën | TAXONOMY: B | STAKES: high
RESEARCH_PROMPT: Onderzoek de concurrentstrategieën. Onderzoek ALLEEN deze vraag.
"""


class TestOneLanguagePerRun:
    def setup_method(self):
        self.run_id = uuid.uuid4()
        self.tenant_id = uuid.uuid4()

    def test_intake_parses_single_language(self):
        audited = FakeAudited(CLEAR_BRIEF_NL_RESPONSE)
        mb = _run(adaptive_intake(
            brief="Onderzoek Cronos Group.", audited=audited,
            run_id=self.run_id, tenant_id=self.tenant_id,
        ))
        assert mb["language"] == "Dutch"
        # focus-area labels stay in the run language (single language, never mixed).
        assert mb["focus_areas"][0]["focus_area"] == "Marktaandeel-trends"

    def test_missing_language_line_defaults_empty(self):
        # Back-compat: a response without a LANGUAGE line yields "" (infer downstream).
        audited = FakeAudited(CLEAR_BRIEF_RESPONSE)
        mb = _run(adaptive_intake(
            brief="x", audited=audited, run_id=self.run_id, tenant_id=self.tenant_id,
        ))
        assert mb.get("language") == ""

    def test_language_directive_enforces_single_language(self):
        from nestor_pulse_sdk.pipeline.synthesis.steps import _language_directive
        d = _language_directive({"language": "Dutch"})
        assert "Dutch" in d and "ONLY Dutch" in d and "Never mix" in d
        # No language -> still a one-language instruction (no mixing).
        d0 = _language_directive({"language": ""})
        assert "ONE language" in d0 and "Never mix" in d0

    def test_distiller_prompt_carries_run_language(self):
        from nestor_pulse_sdk.pipeline.synthesis.steps import _build_distiller_prompt
        reports = [("gemini", {"report": "Some English research text."})]
        with_lang = _build_distiller_prompt(reports, ["Marktaandeel-trends"], "Dutch")
        assert "TRANSLATE the claim into Dutch" in with_lang
        # EVIDENCE must never be translated (it is used to locate/scrub the source).
        assert "do NOT translate EVIDENCE" in with_lang
        # No language -> no translate rule.
        without = _build_distiller_prompt(reports, ["Marktaandeel-trends"], "")
        assert "TRANSLATE the claim" not in without
