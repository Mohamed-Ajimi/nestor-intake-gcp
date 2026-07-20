"""Per-focus-area synthesize_report tests (skeptic-fix session 2026-06-10).

One call per focus area + one wrap call + deterministic Sources assembly.
All tests use a fake audited client — no LLM, no DB.
"""
from __future__ import annotations

import asyncio
import uuid

from nestor_pulse_sdk.pipeline.synthesis.steps import (
    synthesize_report,
    _extract_sources_section,
)


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeAudited:
    """Routes responses by prompt content: section calls vs the wrap call."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def gemini_generate(self, *, run_id, tenant_id, model, contents, **kwargs):
        self.calls.append({"model": model, "contents": contents, "kwargs": kwargs})
        if "Write the remaining framing sections" in contents:
            return _FakeResponse(
                "## Executive Summary\n\nKey insights here.\n\n"
                "## Cross-cutting Synthesis\n\nThemes connect.\n\n"
                "## Confidence & Gaps\n\nSolid on A, thin on B."
            )
        # Section call: echo back the assigned focus area
        import re
        m = re.search(r'focus area \d+ of \d+:\s*"([^"]+)"', contents)
        fa = m.group(1) if m else "Unknown"
        return _FakeResponse(
            f"## {fa}\n\nFindings for {fa} with [a source](https://example.com/{fa.replace(' ', '-')})."
        )


MISSION_BRIEF = {
    "deep_research_prompt": "Research X. Answer Q1 in Dutch, Q2 in English.",
    "focus_areas": [
        {"focus_area": "Pricing strategies", "taxonomy": "B", "stakes": "high"},
        {"focus_area": "Coffee offering", "taxonomy": "B", "stakes": "med"},
        {"focus_area": "Loyalty apps", "taxonomy": "A", "stakes": "high"},
    ],
}

PROVIDER_REPORTS = [
    ("gemini", {"status": "success", "report": "Research prose about pricing."}),
    ("claude", {"status": "success", "report": "Research prose about coffee and loyalty."}),
]


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestSynthesizeReport:
    def test_one_section_per_focus_area_plus_wrap(self):
        audited = FakeAudited()
        report = _run(synthesize_report(
            mission_brief=MISSION_BRIEF, provider_reports=PROVIDER_REPORTS,
            audited=audited, run_id=uuid.uuid4(), tenant_id=uuid.uuid4(),
        ))
        # 3 section calls + 1 wrap call
        assert len(audited.calls) == 4
        # Every focus area got its own dedicated section — the Q4-starvation fix
        for fa in ("Pricing strategies", "Coffee offering", "Loyalty apps"):
            assert f"## {fa}" in report, f"missing dedicated section for {fa!r}"

    def test_report_structure_order(self):
        audited = FakeAudited()
        report = _run(synthesize_report(
            mission_brief=MISSION_BRIEF, provider_reports=PROVIDER_REPORTS,
            audited=audited, run_id=uuid.uuid4(), tenant_id=uuid.uuid4(),
        ))
        idx_exec = report.index("## Executive Summary")
        idx_first = report.index("## Pricing strategies")
        idx_cross = report.index("## Cross-cutting Synthesis")
        idx_sources = report.index("## Sources")
        assert idx_exec < idx_first < idx_cross < idx_sources

    def test_sources_section_is_deterministic_and_deduped(self):
        audited = FakeAudited()
        report = _run(synthesize_report(
            mission_brief=MISSION_BRIEF, provider_reports=PROVIDER_REPORTS,
            audited=audited, run_id=uuid.uuid4(), tenant_id=uuid.uuid4(),
        ))
        sources_part = report.split("## Sources")[1]
        assert "example.com/Pricing-strategies" in sources_part
        assert "example.com/Loyalty-apps" in sources_part

    def test_section_failure_is_visible_not_fatal(self):
        class FlakyAudited(FakeAudited):
            async def gemini_generate(self, *, run_id, tenant_id, model, contents, **kwargs):
                if "Loyalty apps" in contents and "remaining framing sections" not in contents:
                    raise RuntimeError("provider 500")
                return await super().gemini_generate(
                    run_id=run_id, tenant_id=tenant_id, model=model,
                    contents=contents, **kwargs,
                )

        audited = FlakyAudited()
        report = _run(synthesize_report(
            mission_brief=MISSION_BRIEF, provider_reports=PROVIDER_REPORTS,
            audited=audited, run_id=uuid.uuid4(), tenant_id=uuid.uuid4(),
        ))
        assert "## Loyalty apps" in report, "failed section must still appear"
        assert "Section generation failed" in report, "failure must be visible in the report"
        assert "## Pricing strategies" in report, "other sections must be unaffected"

    def test_no_focus_areas_falls_back_to_single_call(self):
        class SingleCallAudited(FakeAudited):
            async def gemini_generate(self, *, run_id, tenant_id, model, contents, **kwargs):
                self.calls.append({"contents": contents})
                return _FakeResponse("Full single-call report text.")

        audited = SingleCallAudited()
        report = _run(synthesize_report(
            mission_brief={"deep_research_prompt": "x", "focus_areas": []},
            provider_reports=PROVIDER_REPORTS,
            audited=audited, run_id=uuid.uuid4(), tenant_id=uuid.uuid4(),
        ))
        assert report == "Full single-call report text."
        assert len(audited.calls) == 1


class TestSourcesExtraction:
    def test_dedupes_and_preserves_order(self):
        out = _extract_sources_section(
            "see [A](https://a.com/x) and [B](https://b.com/y)",
            "again [A2](https://a.com/x) plus [C](https://c.com/z)",
        )
        assert out.count("https://a.com/x") == 1
        assert out.index("a.com/x") < out.index("b.com/y") < out.index("c.com/z")

    def test_empty_when_no_links(self):
        out = _extract_sources_section("no links here")
        assert "## Sources" in out
