"""Stakes-based provider assignment in research_division (decision 2026-06-10).

Rules under test:
  - divide(): high -> gemini on the focused copy, claude on the doubled broad copy;
    med -> openai; low -> claude; broadcast fallback -> openai (med).
  - run_angles(): honours the angle's preferred provider when enabled, falls back
    to round-robin over enabled providers when the preference is disabled.

No real LLM calls — provider runners are monkeypatched.
"""
from __future__ import annotations

import uuid

import pytest

from nestor_pulse_sdk.pipeline.tribunal import research_division as rd


# ---------------------------------------------------------------------------
# divide()
# ---------------------------------------------------------------------------

def _brief(*focus_areas: tuple[str, str]) -> dict:
    return {
        "deep_research_prompt": "What is the competitive landscape for X?",
        "focus_areas": [{"focus_area": fa, "stakes": st} for fa, st in focus_areas],
    }


def test_divide_assigns_providers_by_stakes():
    angles = rd.divide(_brief(("Pricing", "high"), ("Trends", "med"), ("History", "low")))

    by_key = [(a["focus_area"], a["stakes"], a["provider"]) for a in angles]
    # High is doubled: focused copy -> gemini, broad copy -> claude
    assert ("Pricing", "high", "gemini") in by_key
    assert ("Pricing", "high", "claude") in by_key
    assert sum(1 for fa, _, _ in by_key if fa == "Pricing") == 2
    # Med -> openai, low -> claude, neither doubled
    assert ("Trends", "med", "openai") in by_key
    assert ("History", "low", "claude") in by_key
    assert len(angles) == 4


def test_divide_broadcast_fallback_uses_med_provider():
    angles = rd.divide({"deep_research_prompt": "general question", "focus_areas": []})
    assert len(angles) == 1
    assert angles[0]["provider"] == "openai"


# ---------------------------------------------------------------------------
# run_angles()
# ---------------------------------------------------------------------------

def _runner_recording(calls: dict, name: str):
    async def _run(*, query, audited, run_id, tenant_id):
        calls.setdefault(name, []).append(query)
        return {"status": "success", "report": f"{name} report for {query[:30]}"}
    return _run


@pytest.mark.asyncio
async def test_run_angles_routes_by_preference(monkeypatch):
    calls: dict = {}
    monkeypatch.setattr(
        rd, "_PROVIDER_RUNNERS",
        {n: _runner_recording(calls, n) for n in ("gemini", "claude", "openai")},
    )
    monkeypatch.setattr(
        rd, "_enabled_providers",
        lambda: [("gemini", None), ("claude", None), ("openai", None)],
    )

    angles = [
        {"query": "q-high-focused", "stakes": "high", "focus_area": "A", "provider": "gemini"},
        {"query": "q-high-broad", "stakes": "high", "focus_area": "A", "provider": "claude"},
        {"query": "q-med", "stakes": "med", "focus_area": "B", "provider": "openai"},
        {"query": "q-low", "stakes": "low", "focus_area": "C", "provider": "claude"},
    ]
    results = await rd.run_angles(
        angles=angles, audited=None, run_id=uuid.uuid4(), tenant_id=uuid.uuid4()
    )

    assert calls["gemini"] == ["q-high-focused"]
    assert sorted(calls["claude"]) == ["q-high-broad", "q-low"]
    assert calls["openai"] == ["q-med"]
    assert len(results) == 4
    # Provider name and angle metadata preserved on results
    providers = sorted(p for p, _ in results)
    assert providers == ["claude", "claude", "gemini", "openai"]


@pytest.mark.asyncio
async def test_run_angles_falls_back_when_preferred_disabled(monkeypatch):
    calls: dict = {}
    monkeypatch.setattr(
        rd, "_PROVIDER_RUNNERS",
        {n: _runner_recording(calls, n) for n in ("gemini", "claude", "openai")},
    )
    # Gemini disabled — high-stakes angle must still run somewhere
    monkeypatch.setattr(
        rd, "_enabled_providers",
        lambda: [("claude", None), ("openai", None)],
    )

    angles = [
        {"query": "q-high", "stakes": "high", "focus_area": "A", "provider": "gemini"},
    ]
    results = await rd.run_angles(
        angles=angles, audited=None, run_id=uuid.uuid4(), tenant_id=uuid.uuid4()
    )

    assert len(results) == 1
    assert "gemini" not in calls
    assert sum(len(v) for v in calls.values()) == 1  # ran exactly once, on a fallback


def test_divide_angle_cap_trims_redundancy_copies_first(monkeypatch):
    monkeypatch.setattr(rd, "_MAX_ANGLES", 6)
    # 5 high-stakes focus areas -> 10 angles uncapped (5 primary + 5 redundancy)
    angles = rd.divide(_brief(*[(f"Topic {i}", "high") for i in range(5)]))
    assert len(angles) == 6
    # ALL 5 primary (gemini) angles must survive; only redundancy copies trimmed
    gemini_angles = [a for a in angles if a["provider"] == "gemini"]
    assert len(gemini_angles) == 5, "every focus area must keep its primary angle"
    fas_covered = {a["focus_area"] for a in angles}
    assert len(fas_covered) == 5, "the cap must never drop a focus area entirely"


def _runner_failing(calls: dict, name: str):
    async def _run(*, query, audited, run_id, tenant_id):
        calls.setdefault(name, []).append(query)
        return {"status": "error", "error_message": f"{name} outage"}
    return _run


@pytest.mark.asyncio
async def test_run_angles_coverage_retry_on_other_provider(monkeypatch):
    """A focus area whose only provider failed is retried on another provider."""
    calls: dict = {}
    monkeypatch.setattr(
        rd, "_PROVIDER_RUNNERS",
        {
            "gemini": _runner_recording(calls, "gemini"),
            "claude": _runner_recording(calls, "claude"),
            "openai": _runner_failing(calls, "openai"),  # med-stakes provider down
        },
    )
    monkeypatch.setattr(
        rd, "_enabled_providers",
        lambda: [("gemini", None), ("claude", None), ("openai", None)],
    )

    angles = [
        {"query": "q-med", "stakes": "med", "focus_area": "B", "provider": "openai"},
        {"query": "q-low", "stakes": "low", "focus_area": "C", "provider": "claude"},
    ]
    results = await rd.run_angles(
        angles=angles, audited=None, run_id=uuid.uuid4(), tenant_id=uuid.uuid4()
    )

    # openai failed once, then the angle was retried on a different provider
    assert len(calls["openai"]) == 1
    covered = {r[1]["_angle"] for r in results}
    assert "B" in covered, "failed focus area must be recovered by the retry"
    assert "C" in covered
    assert len(results) == 2


@pytest.mark.asyncio
async def test_run_angles_defaults_provider_from_stakes_when_missing(monkeypatch):
    """Angles without a 'provider' key (older callers) derive it from stakes."""
    calls: dict = {}
    monkeypatch.setattr(
        rd, "_PROVIDER_RUNNERS",
        {n: _runner_recording(calls, n) for n in ("gemini", "claude", "openai")},
    )
    monkeypatch.setattr(
        rd, "_enabled_providers",
        lambda: [("gemini", None), ("claude", None), ("openai", None)],
    )

    angles = [{"query": "q1", "stakes": "high", "focus_area": "A"}]
    await rd.run_angles(
        angles=angles, audited=None, run_id=uuid.uuid4(), tenant_id=uuid.uuid4()
    )
    assert calls.get("gemini") == ["q1"]
