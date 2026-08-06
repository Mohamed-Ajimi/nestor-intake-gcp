"""The report writer on `claude-opus-5` — quick task 260806-dn8.

Three coupled properties, one file:

  1. THE ANTHROPIC SHAPE. `final_synthesis_audited`, `_one_section` and the wrap
     call reach `audited.anthropic_messages` with EXACTLY `max_tokens` / `system`
     / `messages` (plus the routing trio the audited client itself needs), the
     text is read from every `type == "text"` block in order, and a
     `stop_reason == "refusal"` degrades visibly instead of shipping half a
     section.

  2. THE CAPS. Both synthesis caps are 20,000 and provably below the anthropic
     SDK's non-streaming ceiling, and `claude-opus-5` prices to an exact Decimal
     so the G-7 NULL-`cost_usd` defect cannot recur on the three synthesis rows.

  3. G-10. A focus-area heading renders the client's FULL question when the
     mission brief carries it, and falls back to the 120-char label when it does
     not.

PURE: no provider client, no DB, no network. Every LLM call goes through a
hand-written duck-typed fake.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import re
import uuid
from decimal import Decimal

import pytest

from nestor_pulse_sdk.pipeline.synthesis import steps as S
from nestor_pulse_sdk.pipeline.synthesis.steps import (
    _ANTHROPIC_NONSTREAMING_MAX_TOKENS,
    _SECTION_MAX_TOKENS,
    _SYNTHESIS_SYSTEM,
    _WRAP_MAX_TOKENS,
    FINAL_SYNTHESIS_MODEL,
    extract_focus_areas,
    focus_area_questions,
    relabel_facets,
    synthesize_report,
)

# ---------------------------------------------------------------------------
# Fixtures / fakes
# ---------------------------------------------------------------------------

#: The run-368ff3a0 shape: a ~150-char client question whose 120-char prefix is
#: the focus-area join key. The delivered report headed its section with the
#: prefix, ending mid-word on `...hoe wordt dit operat`.
FULL_QUESTION = (
    "Welke fuel retailers in Europa passen vandaag dynamic pricing toe op "
    "brandstof en/of shopproducten, hoe wordt dit operationeel ingericht en "
    "wat levert het op?"
)
LABEL = FULL_QUESTION[:120]

PROVIDER_REPORTS = [("gemini", {"status": "success", "report": "Research prose."})]

_WRAP_MARKER = "Write the remaining framing sections"


def _brief(focus_areas: list[dict] | None) -> dict:
    return {
        "deep_research_prompt": "Research fuel retail pricing.",
        "focus_areas": focus_areas if focus_areas is not None else [],
    }


BRIEF_WITH_FULL_QUESTION = _brief(
    [
        {
            "focus_area": LABEL,
            "research_prompt": f"{FULL_QUESTION}\n\nBrief context for the researcher.",
        }
    ]
)


class _Block(dict):
    """A content block as a DICT — the shape `_block_get` exists to tolerate."""

    def __init__(self, **kw) -> None:
        super().__init__(**kw)


class _ObjBlock:
    """A content block as an OBJECT — the other shape `_block_get` tolerates."""

    def __init__(self, **kw) -> None:
        self.__dict__.update(kw)


class _Msg:
    def __init__(self, blocks: list, *, stop_reason: str = "end_turn") -> None:
        self.content = list(blocks)
        self.stop_reason = stop_reason


def _text_msg(text: str, *, stop_reason: str = "end_turn") -> _Msg:
    return _Msg([_Block(type="text", text=text)], stop_reason=stop_reason)


class RecordingAudited:
    """Records the FULL kwarg set of every anthropic_messages call.

    `scripted(prompt) -> _Msg | None` lets a test override one answer without
    losing the default section/wrap routing.
    """

    def __init__(self, scripted=None) -> None:
        self.calls: list[dict] = []
        self._scripted = scripted

    async def anthropic_messages(self, **kwargs):
        self.calls.append(dict(kwargs))
        prompt = kwargs["messages"][0]["content"]
        if self._scripted is not None:
            answer = self._scripted(prompt)
            if answer is not None:
                return answer
        if _WRAP_MARKER in prompt:
            return _text_msg(
                "## Executive Summary\n\nBottom line.\n\n"
                "## Cross-cutting Synthesis\n\nThemes."
            )
        m = re.search(r"heading first: ## (.+?)\)\:", prompt, re.DOTALL)
        head = m.group(1) if m else "Unknown"
        return _text_msg(f"## {head}\n\nBody text with [src](https://example.com/a).")

    # -- convenience views --------------------------------------------------

    @property
    def section_calls(self) -> list[dict]:
        return [c for c in self.calls if _WRAP_MARKER not in c["messages"][0]["content"]]

    @property
    def wrap_call(self) -> dict:
        return next(c for c in self.calls if _WRAP_MARKER in c["messages"][0]["content"])


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _synthesize(audited, brief=BRIEF_WITH_FULL_QUESTION):
    return _run(
        synthesize_report(
            mission_brief=brief,
            provider_reports=PROVIDER_REPORTS,
            audited=audited,
            run_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
        )
    )


# ---------------------------------------------------------------------------
# 1. The Anthropic call shape
# ---------------------------------------------------------------------------


class TestAnthropicCallShape:
    def test_a_section_call_passes_exactly_the_six_permitted_keys(self):
        """SET EQUALITY, not containment.

        `anthropic_messages` forwards **kwargs VERBATIM to `messages.create`, so a
        stray `temperature` / `top_p` / `config` is an HTTP 400 on Opus 5 (thinking
        is on by default), not a warning. A containment check would pass on
        exactly the payload that breaks in production.
        """
        audited = RecordingAudited()
        _synthesize(audited)
        for call in audited.calls:
            assert set(call) == {
                "run_id",
                "tenant_id",
                "model",
                "max_tokens",
                "system",
                "messages",
            }, sorted(call)

    def test_the_model_is_opus_5_on_every_synthesis_call(self):
        audited = RecordingAudited()
        _synthesize(audited)
        assert FINAL_SYNTHESIS_MODEL == "claude-opus-5"
        assert {c["model"] for c in audited.calls} == {"claude-opus-5"}

    def test_system_and_messages_carry_the_contract(self):
        audited = RecordingAudited()
        _synthesize(audited)
        call = audited.section_calls[0]
        assert call["system"] == _SYNTHESIS_SYSTEM
        assert isinstance(call["messages"], list) and len(call["messages"]) == 1
        assert call["messages"][0]["role"] == "user"
        assert isinstance(call["messages"][0]["content"], str)

    def test_synthesis_kwargs_is_the_whole_set_and_nothing_else(self):
        kwargs = S._synthesis_kwargs("the prompt", 4321)
        assert set(kwargs) == {"max_tokens", "system", "messages"}
        assert kwargs["max_tokens"] == 4321
        assert kwargs["system"] == _SYNTHESIS_SYSTEM
        assert kwargs["messages"] == [{"role": "user", "content": "the prompt"}]

    def test_the_genai_config_builder_is_gone(self):
        """`_make_synthesis_config` returned an OPTIONAL google-genai config.

        Anthropic REQUIRES max_tokens and messages, so the optional-config shape
        cannot survive the port. Keeping the name with new semantics would be a
        trap; asserting its absence is what keeps a revert honest.
        """
        assert not hasattr(S, "_make_synthesis_config")


class TestSynthesisTextReader:
    def test_all_text_blocks_are_joined_and_thinking_blocks_are_skipped(self):
        """Never `content[0]`: with thinking on, a thinking block comes FIRST."""
        msg = _Msg(
            [
                _Block(type="thinking", thinking="internal reasoning, not report text"),
                _Block(type="text", text="first half. "),
                _Block(type="text", text="second half."),
            ]
        )
        text, refused = S._synthesis_text(msg)
        assert text == "first half. second half."
        assert refused is False
        assert "internal reasoning" not in text

    def test_object_shaped_blocks_read_the_same_as_dict_shaped_ones(self):
        msg = _Msg(
            [
                _ObjBlock(type="thinking", thinking="x"),
                _ObjBlock(type="text", text="A"),
                _ObjBlock(type="text", text="B"),
            ]
        )
        assert S._synthesis_text(msg) == ("AB", False)

    def test_a_refusal_is_reported_even_when_content_is_present(self):
        msg = _Msg([_Block(type="text", text="half a section")], stop_reason="refusal")
        text, refused = S._synthesis_text(msg)
        assert refused is True
        assert text == "half a section", "the reader REPORTS; the caller discards"

    def test_an_unreadable_response_is_an_empty_one_and_never_raises(self):
        class _Exploding:
            @property
            def content(self):
                raise RuntimeError("boom")

        assert S._synthesis_text(_Exploding()) == ("", False)
        assert S._synthesis_text(None) == ("", False)


class TestDegradedPaths:
    def test_a_refusal_with_no_content_yields_the_no_content_placeholder(self):
        audited = RecordingAudited(
            scripted=lambda p: _Msg([], stop_reason="refusal")
            if _WRAP_MARKER not in p
            else None
        )
        report = _synthesize(audited)
        assert "*(Section generation returned no content.)*" in report

    def test_a_refusal_with_PARTIAL_content_takes_the_same_degraded_path(self):
        """T-dn8-05. The refusal is checked BEFORE the content is read, so a
        half-written section is discarded rather than shipped as a whole one."""
        audited = RecordingAudited(
            scripted=lambda p: _Msg(
                [_Block(type="text", text="## A heading\n\nHalf a section, then the")],
                stop_reason="refusal",
            )
            if _WRAP_MARKER not in p
            else None
        )
        report = _synthesize(audited)
        assert "*(Section generation returned no content.)*" in report
        assert "Half a section" not in report

    def test_a_refusal_logs_its_own_distinct_line(self, caplog):
        audited = RecordingAudited(
            scripted=lambda p: _Msg([], stop_reason="refusal")
            if _WRAP_MARKER not in p
            else None
        )
        with caplog.at_level("ERROR"):
            _synthesize(audited)
        assert "REFUSED" in caplog.text, (
            "'no content' and 'the model declined' are different operator problems"
        )

    def test_a_max_tokens_stop_reason_warns_and_names_the_cap(self, caplog):
        """The exact failure the raised cap exists to prevent. Never silent."""
        audited = RecordingAudited(
            scripted=lambda p: _text_msg("## H\n\nBody.", stop_reason="max_tokens")
            if _WRAP_MARKER not in p
            else None
        )
        with caplog.at_level("WARNING"):
            _synthesize(audited)
        assert "max_tokens" in caplog.text
        assert str(_SECTION_MAX_TOKENS) in caplog.text

    def test_a_raising_section_call_still_produces_the_visible_placeholder(self):
        def _boom(prompt):
            if _WRAP_MARKER not in prompt:
                raise RuntimeError("provider 500")
            return None

        audited = RecordingAudited(scripted=_boom)
        report = _synthesize(audited)
        assert "*(Section generation failed: provider 500)*" in report

    def test_a_failing_wrap_still_yields_a_report_from_the_sections_alone(self):
        def _boom(prompt):
            if _WRAP_MARKER in prompt:
                raise RuntimeError("wrap 500")
            return None

        audited = RecordingAudited(scripted=_boom)
        report = _synthesize(audited)
        assert "Executive Summary" not in report
        assert "Body text" in report, "the sections must survive a dead wrap"
        assert "## Sources" in report

    def test_a_refused_wrap_leaves_the_framing_sections_empty(self):
        audited = RecordingAudited(
            scripted=lambda p: _Msg(
                [_Block(type="text", text="## Executive Summary\n\nHalf a summary")],
                stop_reason="refusal",
            )
            if _WRAP_MARKER in p
            else None
        )
        report = _synthesize(audited)
        assert "Half a summary" not in report
        assert "Body text" in report


class TestFinalSynthesisFallback:
    """The zero-focus-area path — `final_synthesis_audited` — moved too."""

    def test_the_fallback_call_is_anthropic_shaped(self):
        audited = RecordingAudited(scripted=lambda p: _text_msg("One-shot report."))
        report = _synthesize(audited, brief=_brief([]))
        assert report == "One-shot report."
        assert len(audited.calls) == 1
        assert set(audited.calls[0]) == {
            "run_id",
            "tenant_id",
            "model",
            "max_tokens",
            "system",
            "messages",
        }
        assert audited.calls[0]["model"] == "claude-opus-5"

    def test_a_refused_fallback_returns_the_empty_string_not_partial_text(self):
        audited = RecordingAudited(
            scripted=lambda p: _Msg(
                [_Block(type="text", text="half a report")], stop_reason="refusal"
            )
        )
        assert _synthesize(audited, brief=_brief([])) == ""


# ---------------------------------------------------------------------------
# 2. The caps and the price row
# ---------------------------------------------------------------------------


class TestSynthesisCaps:
    def test_the_captured_max_tokens_is_20000_on_both_call_kinds(self):
        """Read off the ACTUAL CALL, not off the constant.

        A constant that no call site passes is instrumentation that is inert at
        readout — the failure class this repository keeps booking.
        """
        audited = RecordingAudited()
        _synthesize(audited)
        assert audited.section_calls[0]["max_tokens"] == 20_000
        assert audited.wrap_call["max_tokens"] == 20_000

    def test_both_caps_sit_under_the_sdk_non_streaming_ceiling(self):
        assert _SECTION_MAX_TOKENS <= _ANTHROPIC_NONSTREAMING_MAX_TOKENS
        assert _WRAP_MAX_TOKENS <= _ANTHROPIC_NONSTREAMING_MAX_TOKENS

    def test_the_ceiling_is_the_arithmetic_and_not_a_copied_literal(self):
        """anthropic 0.104.1 `_base_client._calculate_nonstreaming_timeout` raises
        when `3600 * max_tokens / 128_000 > 600`. Spell the arithmetic so the
        bound is CHECKABLE rather than copied."""
        maximum_time = 60 * 60
        default_time = 60 * 10
        assert _ANTHROPIC_NONSTREAMING_MAX_TOKENS == int(
            default_time * 128_000 / maximum_time
        )
        assert _ANTHROPIC_NONSTREAMING_MAX_TOKENS == 21_333
        # The bound bites exactly where the SDK's guard does.
        assert maximum_time * _ANTHROPIC_NONSTREAMING_MAX_TOKENS / 128_000 <= default_time
        assert maximum_time * (_ANTHROPIC_NONSTREAMING_MAX_TOKENS + 1) / 128_000 > default_time

    def test_the_zero_focus_area_fallback_default_is_also_inside_the_bound(self):
        import inspect

        default = inspect.signature(S.final_synthesis_audited).parameters[
            "max_tokens"
        ].default
        assert default <= _ANTHROPIC_NONSTREAMING_MAX_TOKENS


_PRICES_PATH = (
    pathlib.Path(S.__file__).resolve().parents[2] / "audit" / "cost_prices.json"
)


class TestOpus5PriceRow:
    """G-7 regression guard.

    `compute()` returns None for an unknown model, the caller writes NULL
    `cost_usd`, and `SUM(cost_usd)` silently skips it. Moving synthesis to a
    model with no price row would have re-opened exactly that defect on the three
    most expensive rows of the run.
    """

    def test_compute_returns_a_real_decimal_for_opus_5(self):
        cost_table = pytest.importorskip(
            "nestor_pulse_sdk.audit.cost_table",
            reason="cost_table must be importable to price a synthesis row",
        )
        got = cost_table.compute(
            provider="anthropic",
            model="claude-opus-5",
            prompt_tokens=1_000_000,
            completion_tokens=1_000_000,
            cached_tokens=0,
        )
        assert got is not None, (
            "G-7: an unpriced model writes NULL cost_usd and SUM(cost_usd) skips "
            "it — the run total would silently exclude the report writer"
        )
        assert got == Decimal("30.0"), got  # $5 in + $25 out

    def test_the_row_carries_every_rate_field(self):
        prices = json.loads(_PRICES_PATH.read_text(encoding="utf-8"))
        opus5 = prices["anthropic/claude-opus-5"]
        opus45 = prices["anthropic/claude-opus-4-5"]
        assert set(opus5) == set(opus45), (
            "a missing rate field degrades to 0 with a warning inside _rate(); "
            "this row must never take that branch"
        )
        assert (opus5["prompt"], opus5["completion"]) == (5.0, 25.0)

    def test_the_cache_rates_are_the_published_multipliers_of_prompt(self):
        """Not independent readings — Anthropic's 0.1x / 1.25x multipliers, the
        same derivation every other anthropic/* row in the file uses."""
        opus5 = json.loads(_PRICES_PATH.read_text(encoding="utf-8"))[
            "anthropic/claude-opus-5"
        ]
        assert opus5["cache_read"] == pytest.approx(opus5["prompt"] * 0.1)
        assert opus5["cache_creation_5m"] == pytest.approx(opus5["prompt"] * 1.25)

    def test_the_source_comment_is_present(self):
        prices = json.loads(_PRICES_PATH.read_text(encoding="utf-8"))
        assert "_claude_opus_5_source" in prices
        assert "2026-08-06" in prices["_claude_opus_5_source"]


# ---------------------------------------------------------------------------
# 3. G-10 — the full client question, not the join key
# ---------------------------------------------------------------------------


class TestG10FocusAreaQuestions:
    def test_the_heading_renders_the_full_question_not_the_truncated_label(self):
        """RED against the pre-change code: the shipped report of run 368ff3a0
        headed this section `...hoe wordt dit operat`."""
        audited = RecordingAudited()
        report = _synthesize(audited)
        heads = [ln for ln in report.splitlines() if ln.startswith("## ")]
        assert f"## {FULL_QUESTION}" in heads, heads
        assert f"## {LABEL}" not in heads, "the truncated join key is not a title"
        assert len(FULL_QUESTION) > 120, "the fixture must actually exceed the label cap"

    def test_the_section_prompt_quotes_the_full_question(self):
        audited = RecordingAudited()
        _synthesize(audited)
        prompt = audited.section_calls[0]["messages"][0]["content"]
        assert FULL_QUESTION in prompt, (
            "a label is not something a model should be asked to answer (CR-08)"
        )

    def test_the_resolver_maps_label_to_full_question(self):
        assert focus_area_questions(BRIEF_WITH_FULL_QUESTION) == {LABEL: FULL_QUESTION}

    def test_extract_focus_areas_still_returns_the_LABELS(self):
        """The facet / join key must NOT move — only the display strings do."""
        assert extract_focus_areas(BRIEF_WITH_FULL_QUESTION) == [LABEL]

    # -- degradation, one assertion per degenerate shape --------------------

    def test_a_focus_area_with_no_research_prompt_falls_back_to_the_label(self):
        brief = _brief([{"focus_area": LABEL}])
        assert focus_area_questions(brief) == {}
        report = _synthesize(RecordingAudited(), brief=brief)
        assert f"## {LABEL}" in report.splitlines()

    def test_a_research_prompt_that_does_not_start_with_the_label_is_refused(self):
        """The `intake.py` brief shape: a multi-line assignment, not a question."""
        brief = _brief(
            [
                {
                    "focus_area": LABEL,
                    "research_prompt": "ASSIGNMENT\n\nInvestigate the market.",
                }
            ]
        )
        assert focus_area_questions(brief) == {}
        report = _synthesize(RecordingAudited(), brief=brief)
        assert f"## {LABEL}" in report.splitlines()

    def test_a_question_less_brief_whose_first_paragraph_IS_the_brief_is_refused(self):
        """F6: `_compose_parent_assignment` returns `q or b`, so on an empty
        question half the first paragraph is the BRIEF."""
        brief = _brief(
            [{"focus_area": LABEL, "research_prompt": "Just the brief body.\n\nMore."}]
        )
        assert focus_area_questions(brief) == {}
        report = _synthesize(RecordingAudited(), brief=brief)
        assert f"## {LABEL}" in report.splitlines()

    def test_a_brief_with_no_focus_areas_at_all_resolves_to_nothing(self):
        assert focus_area_questions(_brief([])) == {}
        assert focus_area_questions(None) == {}
        assert focus_area_questions({"focus_areas": "not a list"}) == {}

    def test_a_research_prompt_equal_to_the_label_is_refused(self):
        """`full != label` — re-keying a map onto identical keys is a no-op that
        would only hide a real truncation."""
        brief = _brief([{"focus_area": LABEL, "research_prompt": LABEL}])
        assert focus_area_questions(brief) == {}

    def test_the_label_whitespace_is_collapsed_before_the_prefix_test(self):
        """The stored full text is collapsed by `_compose_parent_assignment`; a
        label carrying an interior newline (ordinary in a form textarea) must
        still match. Same class as CR-01."""
        full = "Wat is de marge  op koffie in tankstations en hoe evolueert die?"
        collapsed = " ".join(full.split())
        label = "Wat is de marge\n op koffie"
        brief = _brief(
            [{"focus_area": label, "research_prompt": f"{collapsed}\n\nBrief."}]
        )
        assert focus_area_questions(brief) == {label: collapsed}


class TestG10RelabelFacets:
    def test_the_facet_counts_are_rekeyed_onto_the_full_question(self):
        assert relabel_facets({LABEL: 3}, BRIEF_WITH_FULL_QUESTION) == {FULL_QUESTION: 3}

    def test_unmapped_keys_are_left_exactly_as_they_are_and_order_is_preserved(self):
        counts = {LABEL: 3, "Other facet": 1, "Third": 7}
        got = relabel_facets(counts, BRIEF_WITH_FULL_QUESTION)
        assert list(got) == [FULL_QUESTION, "Other facet", "Third"]
        assert got["Other facet"] == 1 and got["Third"] == 7

    def test_a_brief_with_no_mapping_returns_the_input_unchanged(self):
        assert relabel_facets({LABEL: 1}, None) == {LABEL: 1}
        assert relabel_facets({LABEL: 1}, _brief([])) == {LABEL: 1}

    def test_it_never_raises_on_a_hostile_shape(self):
        assert relabel_facets({}, {"focus_areas": [None, 3, "str"]}) == {}
        assert relabel_facets(None, BRIEF_WITH_FULL_QUESTION) in (None, {})


class TestImportGraphStaysLight:
    def test_importing_steps_pulls_in_no_provider_sdk_at_module_scope(self):
        """`_block_get` is imported FUNCTION-LOCALLY on purpose (steps.py's import
        graph is kept light). Proved by DOING it in a fresh interpreter rather
        than by reading the source."""
        import subprocess
        import sys

        code = (
            "import sys; import nestor_pulse_sdk.pipeline.synthesis.steps; "
            "bad=[m for m in ('anthropic','google.genai','openai') if m in sys.modules]; "
            "print(bad)"
        )
        out = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            cwd=str(pathlib.Path(S.__file__).resolve().parents[3]),
        )
        assert out.returncode == 0, out.stderr
        assert out.stdout.strip() == "[]", out.stdout
