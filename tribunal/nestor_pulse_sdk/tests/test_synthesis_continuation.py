"""Remark 2b: a chapter that stops mid-word, and the ONE call that finishes it.

WHY. Two chapters of run `7784e71c` — a $36.87 run — were delivered ending
mid-sentence: `## WAT verschuift…` stops at "Dit past in een bredere
portfoliologica:" and `## WANNEER…` stops at "Tw". The cause is not a bug in the
sense of a wrong branch: `_SECTION_MAX_TOKENS = 20_000` covers Opus 5's THINKING
AND TEXT TOGETHER, the call comes back with `stop_reason == "max_tokens"`, and
the code logs `it is TRUNCATED` and pastes the cut text anyway — no
continuation, and no marker telling the reader anything is missing.

WHAT THIS FILE PINS, and the order matters:

  * with `NESTOR_SYNTHESIS_CONTINUE_TRUNCATED` unset, NOTHING changes. Same one
    call, same truncated text, same warning. That is the shipped default.
  * with it on, a truncated section gets EXACTLY ONE more call. Not a loop, not
    "until it fits". The bound is the security property (T-23.5-06-D) and the
    cost property (T-23.5-06-COST, ~$4-5 per extra section call), so it is
    asserted as an EQUALITY on the recorded call list, never as `>= 1`.
  * a continuation that itself truncates does NOT get a third call. The reader
    gets a one-line notice in the run's own language instead.
  * a continuation that RAISES costs the improvement, never the run.

THE SDK BOUND IS NOT THE FIX AND IS NOT TOUCHED. `_ANTHROPIC_NONSTREAMING_MAX_TOKENS`
is a CLIENT-SIDE ceiling: anthropic 0.104.1 raises before any HTTP request once
`3600 * max_tokens / 128_000 > 600`. The two ways past it (an explicit
per-call deadline kwarg, and the streaming entry point that
`AuditedLLMClient` does not implement) are RECORDED AND NOT BUILT in `steps.py`,
and this file asserts all three constants unchanged so a later reader cannot
mistake this plan for permission.

ZERO LLM calls, zero network, zero database, no mocking library: a hand-written
duck-typed client that records every call and returns scripted responses, the
convention `test_report_sections.py` established.
"""
from __future__ import annotations

import uuid
from typing import NamedTuple

import pytest

from nestor_pulse_sdk.pipeline.synthesis import steps
from nestor_pulse_sdk.pipeline.synthesis.steps import (
    _ANTHROPIC_NONSTREAMING_MAX_TOKENS,
    _CONTINUATION_MARKER,
    _SECTION_MAX_TOKENS,
    _TRUNCATION_NOTICE,
    _WRAP_MAX_TOKENS,
    _splice_continuation,
    synthesize_report,
)

RUN_ID = uuid.UUID("00000000-0000-4000-8000-0000000000aa")
TENANT_ID = uuid.UUID("00000000-0000-4000-8000-0000000000bb")

#: The section body the model returns when the cap bites. Two COMPLETE
#: paragraphs and then the half one the cap cut — modelled on the measured
#: "Tw" ending.
TRUNCATED_SECTION = (
    "## The one question\n\n"
    "First complete paragraph, with a number: 41% of the market.\n\n"
    "Second complete paragraph, naming a case and a date.\n\n"
    "And then the sentence stops at Tw"
)
HALF_PARAGRAPH = "And then the sentence stops at Tw"
SECTION_CONTINUATION = (
    "And then the sentence stops at Twente, where the third complete paragraph "
    "finishes the thought.\n\n"
    "### What this means\n\nDo the thing."
)

TRUNCATED_WRAP = (
    "## Executive Summary\n\nThe bottom line.\n\n"
    "## Cross-cutting Synthesis\n\nThemes interact.\n\n"
    "## Confidence & Gaps\n\nSTRONG on A, LIMITED on"
)
HALF_WRAP_PARAGRAPH = "STRONG on A, LIMITED on"
WRAP_CONTINUATION = "STRONG on A, LIMITED on B, OPEN on C."


class _FakeResponse:
    """The anthropic messages-response shape, as `_synthesis_text` reads it."""

    def __init__(self, text: str, stop_reason: str = "end_turn") -> None:
        self.content = [{"type": "text", "text": text}]
        self.stop_reason = stop_reason


class _Call(NamedTuple):
    kind: str
    prompt: str


class ScriptedAudited:
    """Duck-typed stand-in that RECORDS EVERY CALL and returns a script.

    An unscripted call is an `AssertionError`, not a default reply. A default
    reply is how "it called three times" reads as green.
    """

    def __init__(self, *, section=(), wrap=(), continuation=()) -> None:
        self.calls: list[_Call] = []
        self._script = {
            "section": list(section),
            "wrap": list(wrap),
            "continuation": list(continuation),
        }

    @staticmethod
    def _classify(prompt: str) -> str:
        # CONTINUATION IS CHECKED FIRST on purpose: a wrap continuation carries
        # the whole wrap prompt inside it, so the wrap test would match too.
        if _CONTINUATION_MARKER in prompt:
            return "continuation"
        if "Write the remaining framing sections" in prompt:
            return "wrap"
        return "section"

    async def anthropic_messages(self, *, run_id, tenant_id, model, **kwargs):
        prompt = kwargs["messages"][0]["content"]
        kind = self._classify(prompt)
        self.calls.append(_Call(kind, prompt))
        script = self._script[kind]
        if not script:
            raise AssertionError(
                f"UNSCRIPTED {kind} call (call #{len(self.calls)}). "
                f"kinds so far: {[c.kind for c in self.calls]}"
            )
        item = script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def of(self, kind: str) -> list[_Call]:
        return [c for c in self.calls if c.kind == kind]

    def excluding(self, kind: str) -> list[_Call]:
        return [c for c in self.calls if c.kind != kind]


def make_brief(language: str = "English") -> dict:
    """ONE focus area, so a call count is never ambiguous about which section."""
    return {
        "deep_research_prompt": "Research the Dutch fuel retail market.",
        "language": language,
        "focus_areas": [{"focus_area": "The one question", "taxonomy": "B"}],
    }


PROVIDER_REPORTS = [("gemini", {"report": "Provider findings about the market."})]


async def run_report(fake: ScriptedAudited, *, language: str = "English") -> str:
    return await synthesize_report(
        mission_brief=make_brief(language),
        provider_reports=PROVIDER_REPORTS,
        audited=fake,
        run_id=RUN_ID,
        tenant_id=TENANT_ID,
    )


@pytest.fixture
def switch_off(monkeypatch):
    monkeypatch.delenv("NESTOR_SYNTHESIS_CONTINUE_TRUNCATED", raising=False)


@pytest.fixture
def switch_on(monkeypatch):
    monkeypatch.setenv("NESTOR_SYNTHESIS_CONTINUE_TRUNCATED", "true")


EN_NOTICE = _TRUNCATION_NOTICE["english"]
NL_NOTICE = _TRUNCATION_NOTICE["dutch"]


# ---------------------------------------------------------------------------
# THE SHIPPED DEFAULT: with the switch off, nothing changed.
# ---------------------------------------------------------------------------


async def test_with_the_switch_off_a_truncated_section_is_pasted_as_it_is_today(
    switch_off,
):
    """Today's behaviour, byte for byte: one call, the cut text, no notice.

    The `log.warning` is deliberately NOT asserted away — it is the live counter
    that told us this was happening at all, and it survives the change.
    """
    fake = ScriptedAudited(
        section=[_FakeResponse(TRUNCATED_SECTION, stop_reason="max_tokens")],
        wrap=[_FakeResponse(TRUNCATED_WRAP)],
    )
    report = await run_report(fake)

    assert len(fake.of("section")) == 1
    assert fake.of("continuation") == []
    # The half-paragraph is delivered exactly as it arrived.
    assert HALF_PARAGRAPH in report
    assert EN_NOTICE not in report


async def test_with_the_switch_off_a_truncated_wrap_is_pasted_as_it_is_today(
    switch_off,
):
    fake = ScriptedAudited(
        section=[_FakeResponse("## The one question\n\nA whole section.")],
        wrap=[_FakeResponse(TRUNCATED_WRAP, stop_reason="max_tokens")],
    )
    report = await run_report(fake)

    assert len(fake.of("wrap")) == 1
    assert fake.of("continuation") == []
    assert HALF_WRAP_PARAGRAPH in report
    assert EN_NOTICE not in report


# ---------------------------------------------------------------------------
# THE BOUND: exactly one extra call, on every path, never a loop.
# ---------------------------------------------------------------------------


async def test_a_truncated_section_gets_exactly_one_continuation_and_is_spliced(
    switch_on,
):
    """THE COST AND DoS BOUND on the section path (T-23.5-06-D / -COST).

    `calls` is every call this section path made — the section call and its
    continuation, with the wrap excluded because the wrap is a different budget
    and has its own test below.
    """
    fake = ScriptedAudited(
        section=[_FakeResponse(TRUNCATED_SECTION, stop_reason="max_tokens")],
        continuation=[_FakeResponse(SECTION_CONTINUATION)],
        wrap=[_FakeResponse(TRUNCATED_WRAP)],
    )
    report = await run_report(fake)

    calls = fake.excluding("wrap")
    assert len(calls) == 2
    assert [c.kind for c in calls] == ["section", "continuation"]
    assert len(fake.calls) == 3  # + the one wrap call

    # The half-sentence the cap produced is GONE, replaced by the continuation's
    # full restatement of that paragraph.
    assert HALF_PARAGRAPH not in report
    assert "finishes the thought" in report
    # The complete paragraphs before it are untouched, and not duplicated.
    assert report.count("First complete paragraph") == 1
    assert report.count("Second complete paragraph") == 1
    assert EN_NOTICE not in report


async def test_a_continuation_that_also_truncates_is_never_continued_again(
    switch_on,
):
    """NEVER THREE. The notice replaces the third call, it does not precede it."""
    fake = ScriptedAudited(
        section=[_FakeResponse(TRUNCATED_SECTION, stop_reason="max_tokens")],
        continuation=[_FakeResponse(SECTION_CONTINUATION, stop_reason="max_tokens")],
        wrap=[_FakeResponse(TRUNCATED_WRAP)],
    )
    report = await run_report(fake)

    calls = fake.excluding("wrap")
    assert len(calls) == 2
    assert "finishes the thought" in report
    assert EN_NOTICE in report


async def test_a_raising_continuation_degrades_the_section_and_never_fails_the_run(
    switch_on,
):
    """THE RAISING PATH. Still exactly two calls, no traceback out of the run,
    and the reader is told the section is short rather than being handed a
    sentence that stops mid-word with no explanation."""
    fake = ScriptedAudited(
        section=[_FakeResponse(TRUNCATED_SECTION, stop_reason="max_tokens")],
        continuation=[RuntimeError("provider 529 overloaded")],
        wrap=[_FakeResponse(TRUNCATED_WRAP)],
    )
    report = await run_report(fake)

    calls = fake.excluding("wrap")
    assert len(calls) == 2
    # Nothing was spliced away: the original truncated text is kept WHOLE,
    # because dropping its last paragraph without a replacement would lose
    # content the client paid for.
    assert HALF_PARAGRAPH in report
    assert EN_NOTICE in report


async def test_a_truncated_wrap_gets_exactly_one_continuation(switch_on):
    """THE WRAP PATH has the same bound and the same splice. `calls` here is
    every call the wrap path made, with the body section excluded."""
    fake = ScriptedAudited(
        section=[_FakeResponse("## The one question\n\nA whole section.")],
        wrap=[_FakeResponse(TRUNCATED_WRAP, stop_reason="max_tokens")],
        continuation=[_FakeResponse(WRAP_CONTINUATION)],
    )
    report = await run_report(fake)

    calls = fake.excluding("section")
    assert len(calls) == 2
    assert [c.kind for c in calls] == ["wrap", "continuation"]
    assert "OPEN on C." in report
    # The exec/tail split still saw a COMPLETE document: the exec summary is
    # above the body and the confidence section below it.
    assert report.index("The bottom line.") < report.index("A whole section.")
    assert report.index("A whole section.") < report.index("OPEN on C.")


async def test_a_section_that_was_not_truncated_is_never_continued(switch_on):
    """The switch is armed; `stop_reason` is `end_turn`; nothing extra is spent."""
    fake = ScriptedAudited(
        section=[_FakeResponse("## The one question\n\nA whole section.")],
        wrap=[_FakeResponse(TRUNCATED_WRAP)],
    )
    await run_report(fake)

    assert fake.of("continuation") == []
    assert len(fake.calls) == 2


async def test_a_refused_section_is_not_continued(switch_on):
    """A refusal is NOT a truncation. `_synthesis_text` reports `refused` first
    (T-dn8-05) and the existing empty-placeholder path is unchanged — continuing
    a refusal would re-send the partial content the refusal exists to discard."""
    fake = ScriptedAudited(
        section=[_FakeResponse("Half a refused answer", stop_reason="refusal")],
        wrap=[_FakeResponse(TRUNCATED_WRAP)],
    )
    report = await run_report(fake)

    assert fake.of("continuation") == []
    assert "Section generation returned no content." in report
    assert "Half a refused answer" not in report


# ---------------------------------------------------------------------------
# THE NOTICE, and the language it is written in.
# ---------------------------------------------------------------------------


async def test_the_notice_is_written_in_the_run_language(switch_on):
    """One language for the whole run (`_language_directive`). A Dutch report
    that explains its own gap in English is the 08-31 localised-contract trap."""
    fake = ScriptedAudited(
        section=[_FakeResponse(TRUNCATED_SECTION, stop_reason="max_tokens")],
        continuation=[_FakeResponse(SECTION_CONTINUATION, stop_reason="max_tokens")],
        wrap=[_FakeResponse(TRUNCATED_WRAP)],
    )
    report = await run_report(fake, language="Dutch")

    assert NL_NOTICE in report
    assert EN_NOTICE not in report


def test_the_notice_map_covers_exactly_the_four_norm_lang_keys():
    """Same keys as `_SECTION_STRINGS`, so adding a language stays a one-entry
    edit in both maps and cannot go half-done."""
    assert set(_TRUNCATION_NOTICE) == set(steps._SECTION_STRINGS)
    assert set(_TRUNCATION_NOTICE) == {"english", "dutch", "german", "french"}
    for key, notice in _TRUNCATION_NOTICE.items():
        assert notice.startswith("*") and notice.endswith("*"), key
        assert "\n" not in notice, key
        assert len(notice) > 20, key
    # Four DISTINCT strings: a copy-paste that left English in a Dutch slot
    # would otherwise pass every assertion above.
    assert len(set(_TRUNCATION_NOTICE.values())) == 4


# ---------------------------------------------------------------------------
# THE SPLICE, as a pure function.
# ---------------------------------------------------------------------------


def test_the_splice_drops_the_half_paragraph_and_keeps_everything_before_it():
    out = _splice_continuation(TRUNCATED_SECTION, SECTION_CONTINUATION)
    assert HALF_PARAGRAPH not in out
    assert "Second complete paragraph, naming a case and a date." in out
    assert out.endswith("Do the thing.")


def test_the_splice_keeps_a_single_paragraph_whole():
    """With no paragraph break there is no LAST COMPLETE paragraph to restart
    from, so dropping the only one would throw the section away."""
    out = _splice_continuation("One paragraph that was cut at Tw", "Twente. Done.")
    assert out == "One paragraph that was cut at Tw\n\nTwente. Done."


def test_the_splice_with_no_continuation_returns_the_partial_unchanged():
    assert _splice_continuation(TRUNCATED_SECTION, "") == TRUNCATED_SECTION
    assert _splice_continuation(TRUNCATED_SECTION, "   ") == TRUNCATED_SECTION


# ---------------------------------------------------------------------------
# THE BOUND THAT WAS NOT MOVED, and the prompt sentence.
# ---------------------------------------------------------------------------


def test_neither_cap_moved_and_the_sdk_bound_is_intact():
    """T-23.5-06-BOUND. Raising the cap is what the two RECORDED AND UNBUILT
    escape hatches are for; this plan builds neither."""
    assert _SECTION_MAX_TOKENS == 20_000
    assert _WRAP_MAX_TOKENS == 20_000
    assert _ANTHROPIC_NONSTREAMING_MAX_TOKENS == 21_333
    assert _SECTION_MAX_TOKENS < _ANTHROPIC_NONSTREAMING_MAX_TOKENS
    assert _WRAP_MAX_TOKENS < _ANTHROPIC_NONSTREAMING_MAX_TOKENS


async def test_the_continuation_reuses_the_sections_own_prompt_and_adds_no_source(
    switch_on,
):
    """T-continuation. The continuation prompt is the section's OWN prompt plus
    the text the SAME model just wrote — no new data source, nothing the section
    did not already have."""
    fake = ScriptedAudited(
        section=[_FakeResponse(TRUNCATED_SECTION, stop_reason="max_tokens")],
        continuation=[_FakeResponse(SECTION_CONTINUATION)],
        wrap=[_FakeResponse(TRUNCATED_WRAP)],
    )
    await run_report(fake)

    section_prompt = fake.of("section")[0].prompt
    cont_prompt = fake.of("continuation")[0].prompt
    assert cont_prompt.startswith(section_prompt)
    assert TRUNCATED_SECTION in cont_prompt
    assert _CONTINUATION_MARKER in cont_prompt


async def test_the_section_contract_forbids_printing_its_numbered_items_as_headings(
    switch_off,
):
    """Run 7784e71c emitted literal `### BOTTOM LINE` / `### ANALYSE` headings
    taken straight out of the contract. Prompt wording only."""
    fake = ScriptedAudited(
        section=[_FakeResponse("## The one question\n\nA whole section.")],
        wrap=[_FakeResponse(TRUNCATED_WRAP)],
    )
    await run_report(fake)

    prompt = fake.of("section")[0].prompt
    assert "not headings" in prompt
    assert "BOTTOM LINE" in prompt
    # The one sub-heading item 3 DOES ask for is still asked for.
    assert "What this means" in prompt
