"""Distiller coverage tests (2026-06-11) — the whole-research-checked guarantee.

Root cause being pinned: the old distiller made ONE call over ALL concatenated
reports with max_output_tokens=4096 — extraction silently stopped ~29 claims in,
so on the LUKOIL final run only question 5 was ever fact-checked. Now: one call
per report chunk, in parallel, each with the model-maximum output budget.
"""
from __future__ import annotations

import asyncio
import uuid

from nestor_pulse_sdk.pipeline.synthesis.steps import (
    claim_distiller,
    _chunk_text,
    _DISTILLER_MAX_TOKENS,
)


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeAudited:
    """Each call extracts one claim naming the provider whose chunk it received."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def gemini_generate(self, *, run_id, tenant_id, model, contents, **kwargs):
        self.calls.append(contents)
        # Echo a claim back per chunk, tagged with the provider name in the chunk.
        import re
        m = re.search(r"### Provider: (\w+)", contents)
        name = m.group(1) if m else "unknown"
        snippet = contents.split("--- Research reports ---", 1)[1][:120].strip()
        return _FakeResponse(
            f"general\tFact from {name} chunk\t{snippet[:40]}"
        )


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


MISSION_BRIEF = {"focus_areas": [{"focus_area": "general"}]}


class TestChunkText:
    def test_short_text_is_one_chunk(self):
        assert _chunk_text("hello", 100) == ["hello"]

    def test_splits_on_paragraph_boundaries(self):
        text = ("para one. " * 30 + "\n\n" + "para two. " * 30 + "\n\n" + "para three. " * 30)
        chunks = _chunk_text(text, 400)
        assert len(chunks) >= 2
        assert "".join(c.replace("\n", " ") for c in chunks).replace(" ", "") == \
            text.replace("\n", " ").replace(" ", ""), "no content may be lost"

    def test_hard_cut_when_no_boundaries(self):
        text = "x" * 1000
        chunks = _chunk_text(text, 300)
        assert all(len(c) <= 300 for c in chunks)
        assert "".join(chunks) == text


class TestDistillerCoverage:
    def test_every_report_gets_its_own_call(self):
        """Three providers -> three distill calls; claims from ALL of them."""
        audited = FakeAudited()
        reports = [
            ("gemini", {"report": "Gemini research prose."}),
            ("claude", {"report": "Claude research prose."}),
            ("openai", {"report": "OpenAI research prose."}),
        ]
        claims = _run(claim_distiller(
            provider_reports=reports, mission_brief=MISSION_BRIEF,
            audited=audited, run_id=uuid.uuid4(), tenant_id=uuid.uuid4(),
        ))
        assert len(audited.calls) == 3, "one distill call per report"
        texts = " ".join(c["text"] for c in claims)
        for name in ("gemini", "claude", "openai"):
            assert name in texts, f"claims must cover {name}'s report"

    def test_long_report_is_chunked_into_multiple_calls(self):
        audited = FakeAudited()
        long_report = ("A paragraph of research findings here.\n\n" * 4000)  # ~160K chars
        reports = [("gemini", {"report": long_report})]
        _run(claim_distiller(
            provider_reports=reports, mission_brief=MISSION_BRIEF,
            audited=audited, run_id=uuid.uuid4(), tenant_id=uuid.uuid4(),
        ))
        assert len(audited.calls) >= 3, (
            f"a 160K-char report must be split into multiple distill calls, "
            f"got {len(audited.calls)}"
        )

    def test_one_failed_chunk_does_not_lose_the_rest(self):
        class FlakyAudited(FakeAudited):
            async def gemini_generate(self, *, run_id, tenant_id, model, contents, **kwargs):
                if "claude" in contents:
                    raise RuntimeError("provider 500")
                return await super().gemini_generate(
                    run_id=run_id, tenant_id=tenant_id, model=model,
                    contents=contents, **kwargs,
                )

        audited = FlakyAudited()
        reports = [
            ("gemini", {"report": "Gemini research prose."}),
            ("claude", {"report": "Claude research prose."}),
        ]
        claims = _run(claim_distiller(
            provider_reports=reports, mission_brief=MISSION_BRIEF,
            audited=audited, run_id=uuid.uuid4(), tenant_id=uuid.uuid4(),
        ))
        assert any("gemini" in c["text"] for c in claims), \
            "surviving chunks must still produce claims"

    def test_output_budget_is_model_maximum(self):
        """The 4096 ceiling caused the one-topic-only verification bug."""
        assert _DISTILLER_MAX_TOKENS >= 65535
