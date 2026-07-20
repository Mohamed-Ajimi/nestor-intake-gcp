"""Report-planner + report-spec tests (2026-06-14). No DB; fake audited client."""
from __future__ import annotations

import asyncio
import uuid

import pytest

from nestor_pulse_sdk.pipeline.tribunal.report_planner import (
    build_report_proposal,
    default_proposal,
    normalize_spec,
    _parse,
    LENGTH_OPTIONS,
    TABLE_OPTIONS,
)
from nestor_pulse_sdk.pipeline.synthesis.steps import _spec_directives


_MB = {
    "deep_research_prompt": "x",
    "focus_areas": [
        {"focus_area": "What is an agent harness?", "taxonomy": "C", "stakes": "med"},
        {"focus_area": "Enterprise AI brain like Obsidian", "taxonomy": "D", "stakes": "high"},
    ],
}


class TestParse:
    def test_parses_length_tables_and_focus_lines(self):
        text = (
            "LENGTH_RECOMMENDED: comprehensive\n"
            "TABLES_RECOMMENDED: heavy\n"
            "FOCUS: What is an agent harness? | INCLUDE: yes | DEPTH: rich | RATIONALE: well covered\n"
            "FOCUS: Enterprise AI brain like Obsidian | INCLUDE: no | DEPTH: thin | RATIONALE: sparse\n"
        )
        labels = [fa["focus_area"] for fa in _MB["focus_areas"]]
        p = _parse(text, labels)
        assert p["length"]["recommended"] == "comprehensive"
        assert p["tables"]["recommended"] == "heavy"
        assert len(p["focus_areas"]) == 2
        assert p["focus_areas"][0]["recommended_include"] is True
        assert p["focus_areas"][0]["depth"] == "rich"
        assert p["focus_areas"][1]["recommended_include"] is False
        assert p["focus_areas"][1]["rationale"] == "sparse"

    def test_unknown_values_fall_back_and_all_labels_kept(self):
        # Garbage length/tables -> safe defaults; missing focus line -> kept as include.
        labels = [fa["focus_area"] for fa in _MB["focus_areas"]]
        p = _parse("LENGTH_RECOMMENDED: epic\nTABLES_RECOMMENDED: lots\n", labels)
        assert p["length"]["recommended"] == "standard"
        assert p["tables"]["recommended"] == "key"
        # every canonical focus area still present, defaulted to include
        assert [f["label"] for f in p["focus_areas"]] == labels
        assert all(f["recommended_include"] for f in p["focus_areas"])


class TestNormalizeSpec:
    def test_filters_to_known_focus_areas(self):
        spec = normalize_spec(
            {"included_focus_areas": ["What is an agent harness?", "bogus"],
             "length": "brief", "tables": "none", "instructions": "  punchy  "},
            _MB,
        )
        assert spec["included_focus_areas"] == ["What is an agent harness?"]
        assert spec["length"] == "brief"
        assert spec["tables"] == "none"
        assert spec["instructions"] == "punchy"

    def test_empty_selection_defaults_to_all(self):
        spec = normalize_spec({"included_focus_areas": ["nope"]}, _MB)
        assert spec["included_focus_areas"] == [fa["focus_area"] for fa in _MB["focus_areas"]]
        assert spec["length"] == "standard" and spec["tables"] == "key"

    def test_none_spec_is_safe(self):
        spec = normalize_spec(None, _MB)
        assert len(spec["included_focus_areas"]) == 2
        assert spec["length"] in LENGTH_OPTIONS and spec["tables"] in TABLE_OPTIONS


class TestSpecDirectives:
    def test_none_spec_no_directives(self):
        assert _spec_directives(None) == ""
        assert _spec_directives({}) == ""

    def test_brief_and_no_tables_and_instructions(self):
        out = _spec_directives({"length": "brief", "tables": "none", "instructions": "be terse"})
        assert "TIGHT" in out
        assert "Do NOT use markdown tables" in out
        assert "be terse" in out

    def test_comprehensive_and_heavy_tables(self):
        out = _spec_directives({"length": "comprehensive", "tables": "heavy"})
        assert "COMPREHENSIVE" in out
        assert "liberally" in out


class _Resp:
    def __init__(self, text): self.text = text


class FakeAudited:
    def __init__(self, text): self._text = text
    async def gemini_generate(self, *, run_id, tenant_id, model, contents, **kw):
        return _Resp(self._text)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestBuildProposal:
    def test_uses_llm_output(self):
        text = (
            "LENGTH_RECOMMENDED: brief\nTABLES_RECOMMENDED: key\n"
            "FOCUS: What is an agent harness? | INCLUDE: yes | DEPTH: rich | RATIONALE: ok\n"
            "FOCUS: Enterprise AI brain like Obsidian | INCLUDE: yes | DEPTH: rich | RATIONALE: ok\n"
        )
        cleaned = [("gemini", {"report": "lots of research about harnesses"})]
        p = _run(build_report_proposal(
            mission_brief=_MB, cleaned_reports=cleaned,
            audited=FakeAudited(text), run_id=uuid.uuid4(), tenant_id=uuid.uuid4(),
        ))
        assert p["length"]["recommended"] == "brief"
        assert len(p["focus_areas"]) == 2

    def test_llm_failure_falls_back_to_default(self):
        class Boom:
            async def gemini_generate(self, **kw): raise RuntimeError("nope")
        p = _run(build_report_proposal(
            mission_brief=_MB, cleaned_reports=[("g", {"report": "x"})],
            audited=Boom(), run_id=uuid.uuid4(), tenant_id=uuid.uuid4(),
        ))
        # default proposal: all included, standard/key
        assert p == default_proposal(_MB)

    def test_no_focus_areas_returns_default(self):
        p = _run(build_report_proposal(
            mission_brief={"focus_areas": []}, cleaned_reports=[],
            audited=FakeAudited("anything"), run_id=uuid.uuid4(), tenant_id=uuid.uuid4(),
        ))
        assert p["focus_areas"] == []
