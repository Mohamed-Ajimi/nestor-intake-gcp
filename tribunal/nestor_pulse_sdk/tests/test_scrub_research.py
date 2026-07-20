"""Span-based scrub_research tests (skeptic-fix session 2026-06-10).

The scrub is now: LLM proposes verbatim spans (small output) -> Python deletes
them deterministically -> every removed claim's evidence snippet is asserted
gone (with deterministic sentence-deletion fallback). No full-text regeneration.

All tests use a fake audited client — no LLM, no DB.
"""
from __future__ import annotations

import asyncio
import json
import uuid

from nestor_pulse_sdk.pipeline.synthesis.steps import (
    scrub_research,
    _delete_span,
    _delete_sentence_containing,
)


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeAudited:
    def __init__(self, canned_text: str = "[]", fail: bool = False) -> None:
        self._canned = canned_text
        self._fail = fail
        self.calls: list[dict] = []

    async def gemini_generate(self, *, run_id, tenant_id, model, contents, **kwargs):
        self.calls.append({"model": model, "contents": contents, "kwargs": kwargs})
        if self._fail:
            raise RuntimeError("scrub LLM down")
        return _FakeResponse(self._canned)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


REPORT_A = (
    "The European fuel market is growing steadily. "
    "Acme Corp's revenue grew 50% in 2025 according to its press release. "
    "Coffee sales in Belgian stations rose 12% last year."
)
REPORT_B = (
    "Independent analysis shows loyalty apps drive repeat visits. "
    "Acme Corp's revenue grew 50% in 2025 according to its press release. "
    "Dynamic pricing pilots ran in Germany and Poland."
)

DROPPED = [
    {
        "text": "Acme Corp revenue grew 50% in 2025",
        "facet": "competitors",
        "evidence": "Acme Corp's revenue grew 50% in 2025",
    }
]


def _reports():
    return [
        ("gemini", {"status": "success", "report": REPORT_A}),
        ("claude", {"status": "success", "report": REPORT_B}),
    ]


class TestScrubResearch:
    def test_noop_without_removed_claims(self):
        audited = FakeAudited()
        out = _run(scrub_research(
            provider_reports=_reports(), removed_claims=[],
            audited=audited, run_id=uuid.uuid4(), tenant_id=uuid.uuid4(),
        ))
        assert out == _reports()
        assert audited.calls == [], "no LLM call when nothing to remove"

    def test_spans_deleted_per_provider_structure_kept(self):
        span = "Acme Corp's revenue grew 50% in 2025 according to its press release."
        audited = FakeAudited(canned_text=json.dumps([span]))
        out = _run(scrub_research(
            provider_reports=_reports(), removed_claims=DROPPED,
            audited=audited, run_id=uuid.uuid4(), tenant_id=uuid.uuid4(),
        ))
        # provider names preserved (NOT collapsed into one 'scrubbed' blob)
        assert [name for name, _ in out] == ["gemini", "claude"]
        for _name, result in out:
            assert "grew 50%" not in result["report"], "discredited text must be gone"
        # untouched content survives verbatim
        assert "Coffee sales in Belgian stations rose 12%" in out[0][1]["report"]
        assert "Dynamic pricing pilots ran in Germany" in out[1][1]["report"]

    def test_llm_failure_still_scrubs_via_evidence(self):
        """Old behaviour returned UNSCRUBBED text on LLM failure — now layers 2-3
        still remove the discredited sentences deterministically."""
        audited = FakeAudited(fail=True)
        out = _run(scrub_research(
            provider_reports=_reports(), removed_claims=DROPPED,
            audited=audited, run_id=uuid.uuid4(), tenant_id=uuid.uuid4(),
        ))
        for _name, result in out:
            assert "grew 50%" not in result["report"]

    def test_whitespace_tolerant_span_matching(self):
        # LLM quotes the span with a line break where the source has a space
        span = "Acme Corp's revenue grew 50%\nin 2025 according to its press release."
        audited = FakeAudited(canned_text=json.dumps([span]))
        out = _run(scrub_research(
            provider_reports=_reports(), removed_claims=DROPPED,
            audited=audited, run_id=uuid.uuid4(), tenant_id=uuid.uuid4(),
        ))
        for _name, result in out:
            assert "grew 50%" not in result["report"]

    def test_scrub_call_has_token_budget(self):
        """The known truncation bug: the old scrub passed NO config. The span
        call must carry an explicit config (max_output_tokens)."""
        audited = FakeAudited(canned_text="[]")
        _run(scrub_research(
            provider_reports=_reports(), removed_claims=DROPPED,
            audited=audited, run_id=uuid.uuid4(), tenant_id=uuid.uuid4(),
        ))
        assert audited.calls, "scrub must call the LLM when claims were dropped"
        assert "config" in audited.calls[0]["kwargs"]


class TestDeletionHelpers:
    def test_delete_span_exact(self):
        text, removed = _delete_span("aaa REMOVE THIS PASSAGE bbb", "REMOVE THIS PASSAGE")
        assert removed and "REMOVE" not in text and "aaa" in text and "bbb" in text

    def test_delete_span_refuses_tiny_spans(self):
        text, removed = _delete_span("the cat sat on the mat", "the")
        assert not removed and text == "the cat sat on the mat"

    def test_delete_sentence_containing(self):
        text = "Good fact one. Bad number is 99% wrong here. Good fact two."
        out, removed = _delete_sentence_containing(text, "Bad number is 99%")
        assert removed
        assert "99%" not in out
        assert "Good fact one." in out and "Good fact two." in out
