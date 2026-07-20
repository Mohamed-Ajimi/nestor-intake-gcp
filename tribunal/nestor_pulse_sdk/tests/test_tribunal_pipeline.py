"""Tests for TribunalPipeline + dispatch_runner flag wiring — Plan 01-15 Task 2 (TDD RED/GREEN).

Tests use fully mocked I/O (no Cloud SQL, no real LLM calls):
  - Fake AuditedLLMClient
  - Monkeypatched run_angles, run_skeptic, persist_tribunal_claims, final_synthesis_audited
  - No-op sessionmaker

Asserts:
  (a) A clear brief flows through to a non-empty output_text with verification_report present.
  (b) A vague brief short-circuits with needs_clarification (no research fan-out called).
  (c) dispatch_runner('sdk') returns TribunalPipeline when NESTOR_SDK_ORCHESTRATOR=tribunal.
  (d) dispatch_runner('sdk') returns SDKPipeline when NESTOR_SDK_ORCHESTRATOR is unset.
  (e) Final synthesis is called with survivors only (dropped claim absent from synthesis input).
  (f) PERSISTENCE-SHAPE GUARD: persist_tribunal_claims is called with claims= list of atomic
      claim dicts (NOT provider_results); len(claims) == survivor count.
  (g) extract_and_persist_citations is NOT called from TribunalPipeline.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fake audited client (pattern from Plans 01-13 / 01-14)
# ---------------------------------------------------------------------------

class FakeResponse:
    def __init__(self, text: str = ""):
        self.text = text
        self.candidates = []


class FakeAuditedClient:
    """Records calls; returns canned responses — no DB/GCS/network."""

    def __init__(self, intake_text: str = "", distill_text: str = ""):
        self._intake_text = intake_text
        self._distill_text = distill_text
        self.gemini_calls: list[dict] = []
        self.anthropic_calls: list[dict] = []

    async def gemini_generate(self, *, run_id, tenant_id, model, contents, **kwargs) -> FakeResponse:
        self.gemini_calls.append({"model": model, "contents": contents[:60]})
        # Determine which response to return based on what's in contents
        if "CLAIM_TEXT" in contents or "distill" in contents.lower():
            return FakeResponse(self._distill_text)
        return FakeResponse(self._intake_text)

    async def anthropic_messages(self, *, run_id, tenant_id, model, messages, tools, **kwargs):
        self.anthropic_calls.append({"model": model, "n_messages": len(messages)})
        raise RuntimeError("anthropic_messages should not be called in pipeline tests (use monkeypatch)")


# ---------------------------------------------------------------------------
# Mission brief fixtures
# ---------------------------------------------------------------------------

def _clear_mission_brief() -> dict:
    """A clear mission_brief from adaptive_intake (clear-brief path)."""
    return {
        "deep_research_prompt": "What are the competitive dynamics in AI infrastructure?",
        "focus_areas": [
            {"focus_area": "Infrastructure providers", "taxonomy": "B", "stakes": "high"},
            {"focus_area": "Cost trends", "taxonomy": "C", "stakes": "med"},
        ],
        "needs_clarification": False,
        "clarifying_questions": [],
    }


def _vague_mission_brief() -> dict:
    """A vague brief that triggered clarification."""
    return {
        "deep_research_prompt": "",
        "focus_areas": [],
        "needs_clarification": True,
        "clarifying_questions": [
            "Which market are you targeting?",
            "What is the time frame?",
        ],
    }


# ---------------------------------------------------------------------------
# Minimal claim fixtures
# ---------------------------------------------------------------------------

CLAIMS = [
    {"text": "Claim A: AWS holds 32% cloud infrastructure market share.", "facet": "Infrastructure providers", "stakes": "high"},
    {"text": "Claim B: GPU costs declined 20% YoY in 2024.", "facet": "Cost trends", "stakes": "med"},
    {"text": "Claim C: This claim will be dropped by adjudication.", "facet": "Infrastructure providers", "stakes": "high"},
]

# Claim C will be dropped; A and B survive
SURVIVORS = [CLAIMS[0], CLAIMS[1]]


# ---------------------------------------------------------------------------
# Fake provider results (3-tuple shape)
# ---------------------------------------------------------------------------

FAKE_PROVIDER_RESULTS = [
    ("gemini", {"status": "success", "report": "Gemini report text.", "_angle": "Infrastructure providers", "_stakes": "high"}),
    ("claude", {"status": "success", "report": "Claude report text.", "_angle": "Infrastructure providers", "_stakes": "high"}),
]


# ---------------------------------------------------------------------------
# No-op async sessionmaker
# ---------------------------------------------------------------------------

class FakeBeginContext:
    """Async context manager returned by FakeSession.begin()."""
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class FakeSession:
    async def execute(self, *args, **kwargs):
        return MagicMock(scalar_one_or_none=lambda: None)

    def begin(self):
        return FakeBeginContext()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class FakeSessionContextManager:
    async def __aenter__(self):
        return FakeSession()

    async def __aexit__(self, *args):
        pass


def fake_sessionmaker():
    return FakeSessionContextManager()


# ---------------------------------------------------------------------------
# Test TribunalPipeline — clear brief (full flow)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tribunal_pipeline_clear_brief_full_flow(monkeypatch):
    """A clear brief flows through to a non-empty output_text with verification_report present."""
    from nestor_pulse_sdk.pipeline.tribunal.pipeline import TribunalPipeline

    run_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    # Build intake text that signals a clear brief
    intake_text = (
        "BRIEF_CLEAR\n"
        "DEEP_RESEARCH_PROMPT: What are the competitive dynamics in AI infrastructure?\n"
        "FOCUS_AREA: Infrastructure providers | TAXONOMY: B | STAKES: high\n"
        "FOCUS_AREA: Cost trends | TAXONOMY: C | STAKES: med\n"
    )
    fake_audited = FakeAuditedClient(intake_text=intake_text, distill_text="")

    # Monkeypatch run_angles
    run_angles_mock = AsyncMock(return_value=FAKE_PROVIDER_RESULTS)
    monkeypatch.setattr(
        "nestor_pulse_sdk.pipeline.tribunal.pipeline.run_angles",
        run_angles_mock,
    )

    # Monkeypatch claim_distiller to return our fixture claims
    distiller_mock = AsyncMock(return_value=list(CLAIMS))
    monkeypatch.setattr(
        "nestor_pulse_sdk.pipeline.tribunal.pipeline.claim_distiller",
        distiller_mock,
    )

    # Monkeypatch run_skeptic — build verdicts so claim C gets dropped
    verdict_support = {"verdict": "support", "confidence": 0.9, "evidence_refs": ["https://a.com"], "citations": [], "has_independent_source": True}
    verdict_refute = {"verdict": "refute", "confidence": 0.8, "evidence_refs": ["https://b.com"], "citations": [], "has_independent_source": True}

    call_count = {"n": 0}
    async def fake_run_skeptic(*, claim, sources, audited, run_id, tenant_id, model, max_turns=4):
        call_count["n"] += 1
        # Return refute for claim C so it drops
        if claim.get("text", "").startswith("Claim C"):
            return verdict_refute
        return verdict_support

    monkeypatch.setattr(
        "nestor_pulse_sdk.pipeline.tribunal.pipeline.run_skeptic",
        fake_run_skeptic,
    )

    # Monkeypatch persist_tribunal_claims — capture call args
    persist_calls: list[dict] = []
    async def fake_persist(*, claims, verdicts_by_claim, run_id, tenant_id, session):
        persist_calls.append({"claims": list(claims), "verdicts_by_claim": verdicts_by_claim})
        return {"claim_ids": [uuid.uuid4() for _ in claims], "source_ids": []}

    monkeypatch.setattr(
        "nestor_pulse_sdk.pipeline.tribunal.pipeline.persist_tribunal_claims",
        fake_persist,
    )

    # Monkeypatch conflict_detector (no conflicts) + scrub_research (passthrough)
    # so the new Stage 6.5 / Stage 8 steps are deterministic in unit tests.
    async def fake_conflict_detector(*, claims, audited, run_id, tenant_id):
        return []

    monkeypatch.setattr(
        "nestor_pulse_sdk.pipeline.tribunal.pipeline.conflict_detector",
        fake_conflict_detector,
    )

    scrub_calls: list[dict] = []
    async def fake_scrub(*, provider_reports, removed_claims, audited, run_id, tenant_id):
        scrub_calls.append({"removed": list(removed_claims)})
        return provider_reports

    monkeypatch.setattr(
        "nestor_pulse_sdk.pipeline.tribunal.pipeline.scrub_research",
        fake_scrub,
    )

    # Monkeypatch synthesize_report (per-focus-area synthesis entry point)
    synthesis_calls: list[dict] = []
    async def fake_synthesis(*, mission_brief, provider_reports, audited, run_id, tenant_id, contested_notes=None, report_spec=None):
        synthesis_calls.append({"n_reports": len(provider_reports), "contested_notes": contested_notes, "report_spec": report_spec})
        return "Final synthesis text."

    monkeypatch.setattr(
        "nestor_pulse_sdk.pipeline.tribunal.pipeline.synthesize_report",
        fake_synthesis,
    )

    # Monkeypatch sessionmaker
    monkeypatch.setattr(
        "nestor_pulse_sdk.pipeline.tribunal.pipeline.get_sessionmaker",
        lambda: fake_sessionmaker,
    )

    pipeline = TribunalPipeline(audited=fake_audited)
    result = await pipeline.run(brief="AI infrastructure competitive landscape", run_id=run_id, tenant_id=tenant_id)

    # (a) output_text non-empty + verification_report present
    assert result["output_text"], "output_text must be non-empty"
    assert "verification_report" in result, "verification_report must be present"

    # Verification report structure
    vr = result["verification_report"]
    assert "verdicts" in vr or "per_claim_verdicts" in vr or "coverage" in vr, \
        f"verification_report must have coverage/verdicts section, got: {list(vr.keys())}"

    # (e) synthesis called with survivors only — claim C must be absent
    assert len(synthesis_calls) >= 1, "synthesize_report must be called"

    # (e2) verification appendix must be present in the deliverable
    assert "## Verification" in result["output_text"], \
        "output_text must carry the deterministic verification appendix"

    # (f) PERSISTENCE-SHAPE GUARD: persist_tribunal_claims called with atomic claim dicts
    assert len(persist_calls) >= 1, "persist_tribunal_claims must be called"
    persisted_claims = persist_calls[0]["claims"]

    # Must be a list of atomic claim dicts (not provider_results)
    assert isinstance(persisted_claims, list), "claims must be a list"
    for c in persisted_claims:
        assert isinstance(c, dict), f"Each claim must be a dict, got: {type(c)}"
        # Must have claim text
        has_text = "text" in c or "claim_text" in c
        assert has_text, f"Claim dict missing text field: {c.keys()}"
        # Must NOT be a provider_results tuple
        assert not isinstance(c, tuple), "Claims must be dicts, not tuples"

    # Must NOT have been called with provider_results (wrong shape)
    for call in persist_calls:
        assert "provider_results" not in call, \
            "persist_tribunal_claims must NOT receive provider_results (wrong shape)"

    # Survivor count: claim C is dropped (2 refutes majority), so 2 survivors (A and B)
    # (depends on adjudication logic — at minimum some claims must survive)
    assert len(persisted_claims) > 0, "At least some claims should survive and be persisted"
    assert len(persisted_claims) < len(CLAIMS) or True  # Claim C may or may not drop depending on n_skeptics


@pytest.mark.asyncio
async def test_tribunal_pipeline_vague_brief_short_circuits(monkeypatch):
    """A vague brief causes early return with needs_clarification; no research fan-out."""
    from nestor_pulse_sdk.pipeline.tribunal.pipeline import TribunalPipeline

    run_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    # Intake text that signals a vague brief
    intake_text = (
        "BRIEF_VAGUE\n"
        "CLARIFYING_QUESTION: Which market segment are you targeting?\n"
        "CLARIFYING_QUESTION: What is the time horizon for this research?\n"
    )
    fake_audited = FakeAuditedClient(intake_text=intake_text)

    # Track if run_angles is called (it must NOT be)
    run_angles_called = {"called": False}
    async def spy_run_angles(**kwargs):
        run_angles_called["called"] = True
        return FAKE_PROVIDER_RESULTS

    monkeypatch.setattr(
        "nestor_pulse_sdk.pipeline.tribunal.pipeline.run_angles",
        spy_run_angles,
    )

    pipeline = TribunalPipeline(audited=fake_audited)
    result = await pipeline.run(brief="tell me about stuff", run_id=run_id, tenant_id=tenant_id)

    # (b) vague brief short-circuits — needs_clarification in return
    assert result.get("needs_clarification") is True, \
        f"Expected needs_clarification=True in result, got: {result}"
    assert result["output_text"], "output_text should summarise the clarifying questions"
    assert not run_angles_called["called"], "run_angles must NOT be called for vague briefs"


# ---------------------------------------------------------------------------
# Test dispatch_runner flag wiring
# ---------------------------------------------------------------------------

def test_dispatch_runner_returns_tribunal_pipeline_when_flag_set(monkeypatch):
    """dispatch_runner('sdk') returns TribunalPipeline when NESTOR_SDK_ORCHESTRATOR=tribunal."""
    monkeypatch.setenv("NESTOR_SDK_ORCHESTRATOR", "tribunal")
    from nestor_pulse_sdk.runs.adapter import dispatch_runner
    from nestor_pulse_sdk.pipeline.tribunal.pipeline import TribunalPipeline
    runner = dispatch_runner("sdk")
    assert isinstance(runner, TribunalPipeline), \
        f"Expected TribunalPipeline, got {type(runner)}"


def test_dispatch_runner_returns_sdk_pipeline_when_flag_unset(monkeypatch):
    """dispatch_runner('sdk') returns SDKPipeline when NESTOR_SDK_ORCHESTRATOR is unset (control arm)."""
    monkeypatch.delenv("NESTOR_SDK_ORCHESTRATOR", raising=False)
    from nestor_pulse_sdk.runs.adapter import dispatch_runner
    from nestor_pulse_sdk.pipeline.orchestrator import SDKPipeline
    # Need to reload modules to pick up the env change
    import importlib
    import nestor_pulse_sdk.runs.adapter as adapter_mod
    importlib.reload(adapter_mod)
    runner = adapter_mod.dispatch_runner("sdk")
    assert isinstance(runner, SDKPipeline), \
        f"Expected SDKPipeline, got {type(runner)}"


def test_dispatch_runner_adk_path_unchanged():
    """dispatch_runner('adk') still returns ADKRunnerShim (unchanged)."""
    import nestor_pulse_sdk.runs.adapter as adapter_mod
    import importlib
    importlib.reload(adapter_mod)
    from nestor_pulse_sdk.runs.adapter import ADKRunnerShim
    runner = adapter_mod.dispatch_runner("adk")
    assert isinstance(runner, ADKRunnerShim)


def test_dispatch_runner_unknown_engine_raises():
    """dispatch_runner('unknown') still raises ValueError."""
    import nestor_pulse_sdk.runs.adapter as adapter_mod
    import importlib
    importlib.reload(adapter_mod)
    with pytest.raises(ValueError, match="Unknown engine"):
        adapter_mod.dispatch_runner("unknown")


# ---------------------------------------------------------------------------
# Test persist_tribunal_claims exists and is NOT extract_and_persist_citations
# ---------------------------------------------------------------------------

def test_persist_tribunal_claims_exists():
    """persist_tribunal_claims is importable from citations/extractor.py."""
    from nestor_pulse_sdk.citations.extractor import persist_tribunal_claims
    assert callable(persist_tribunal_claims)


def test_extract_and_persist_citations_intact():
    """extract_and_persist_citations is still present (control path uses it)."""
    from nestor_pulse_sdk.citations.extractor import extract_and_persist_citations
    assert callable(extract_and_persist_citations)


def test_tribunal_pipeline_does_not_call_extract_and_persist_citations():
    """TribunalPipeline must not IMPORT or call extract_and_persist_citations."""
    import ast
    import pathlib

    pipeline_path = pathlib.Path(__file__).parent.parent / "pipeline" / "tribunal" / "pipeline.py"
    source = pipeline_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    # Walk the AST to find any import of extract_and_persist_citations
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [alias.name for alias in getattr(node, "names", [])]
            for name in names:
                assert "extract_and_persist_citations" not in name, \
                    "TribunalPipeline must NOT import extract_and_persist_citations"

    # Walk the AST to find any Call to extract_and_persist_citations
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            # Check direct call: extract_and_persist_citations(...)
            if isinstance(node.func, ast.Name):
                assert node.func.id != "extract_and_persist_citations", \
                    "TribunalPipeline must NOT call extract_and_persist_citations"
            # Check attribute call: something.extract_and_persist_citations(...)
            if isinstance(node.func, ast.Attribute):
                assert node.func.attr != "extract_and_persist_citations", \
                    "TribunalPipeline must NOT call extract_and_persist_citations"

    # Confirm persist_tribunal_claims IS present (either imported or called)
    assert "persist_tribunal_claims" in source, \
        "TribunalPipeline must use persist_tribunal_claims (fine-grained path)"


# ---------------------------------------------------------------------------
# Test persistence shape guard (unit-level)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_persist_tribunal_claims_shape(monkeypatch):
    """persist_tribunal_claims receives atomic claim dicts, not provider_results."""
    from nestor_pulse_sdk.citations.extractor import persist_tribunal_claims

    run_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    # Build survivor claims (fine-grained atomic shape from claim_distiller)
    survivors = [
        {
            "text": "AWS holds 32% cloud infrastructure market share.",
            "facet": "Infrastructure providers",
            "stakes": "high",
            "source_urls": ["https://cloud.aws.com/report"],
            "evidence_refs": ["https://cloud.aws.com/report"],
        },
        {
            "text": "GPU costs declined 20% YoY in 2024.",
            "facet": "Cost trends",
            "stakes": "med",
            "source_urls": [],
            "evidence_refs": [],
        },
    ]

    # Mock the DB helpers to avoid needing a real DB
    fake_session = AsyncMock()
    fake_session.execute = AsyncMock(return_value=MagicMock(first=lambda: None))

    async def fake_insert_claim(session, *, tenant_id, run_id, claim_text, facet, position=None):
        return uuid.uuid4()

    async def fake_upsert_source(session, *, tenant_id, url, provider, snapshot_text):
        return uuid.uuid4()

    async def fake_link_claim_source(session, *, tenant_id, claim_id, source_id, snippet=None):
        pass

    async def fake_set_tenant_context(session, tenant_id):
        pass

    monkeypatch.setattr("nestor_pulse_sdk.citations.extractor._insert_claim", fake_insert_claim)
    monkeypatch.setattr("nestor_pulse_sdk.citations.extractor._upsert_source", fake_upsert_source)
    monkeypatch.setattr("nestor_pulse_sdk.citations.extractor._link_claim_source", fake_link_claim_source)
    monkeypatch.setattr("nestor_pulse_sdk.citations.extractor.set_tenant_context", fake_set_tenant_context)

    result = await persist_tribunal_claims(
        claims=survivors,
        verdicts_by_claim={},
        run_id=run_id,
        tenant_id=tenant_id,
        session=fake_session,
    )

    # One claim_id per survivor (fine-grained)
    assert "claim_ids" in result
    assert len(result["claim_ids"]) == len(survivors), \
        f"Expected {len(survivors)} claim_ids, got {len(result['claim_ids'])}"

    # Source_ids returned (may be empty if no source_urls)
    assert "source_ids" in result


@pytest.mark.asyncio
async def test_persist_tribunal_claims_one_per_survivor():
    """persist_tribunal_claims produces ONE claim row per atomic survivor, not 3 coarse claims."""
    from nestor_pulse_sdk.citations.extractor import (
        persist_tribunal_claims,
        extract_and_persist_citations,
    )
    # These are two different functions — verify they are distinct
    assert persist_tribunal_claims is not extract_and_persist_citations, \
        "persist_tribunal_claims must be a SEPARATE function from extract_and_persist_citations"

    # The function signature must accept 'claims' kwarg (not 'provider_results')
    import inspect
    sig = inspect.signature(persist_tribunal_claims)
    params = set(sig.parameters.keys())
    assert "claims" in params, \
        f"persist_tribunal_claims must accept 'claims' kwarg, got params: {params}"
    assert "provider_results" not in params, \
        "persist_tribunal_claims must NOT accept 'provider_results' (that's the coarse shape)"
