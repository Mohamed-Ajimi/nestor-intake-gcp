"""
Opaque citation anchor tests (Phase 15.2 ENGINE-11, D-05 / D-06).

Layer 1 only: PURE. No DB, no API key, no network, no mocking library -- so the
whole file runs in the keyless, Postgres-less 15.2 fast gate
(`cloudbuild.test-engine.yaml`).

What is proved here:
  * D-05 ROUND TRIP  -- the model marks `[[c:xxxxxxxx]]`, Python writes `[n]`.
  * D-06 STRIP+COUNT -- an anchor that does not resolve is removed AND COUNTED.
  * NON-COLLISION    -- `[[c:...]]`, the provider's `[cite: N]` and markdown links
                        are three separate mechanisms that do not touch each other.
                        Asserted, never assumed: building a second cite-stripper
                        that eats the wrong markers is the dominant failure mode
                        this phase is guarding against.
  * PREFIX COLLISION -- two claims sharing an 8-hex prefix resolve to NEITHER.
                        A wrong match cites the wrong source, which is worse than
                        no citation (D-05's own rationale).
  * NEVER RAISES     -- garbled/truncated/non-string input degrades, never throws.
  * PITFALL 2        -- the anchor rule reaches the prompts `synthesize_report`
                        ACTUALLY sends (see TestBothPromptSites).
"""

from __future__ import annotations

import re
import uuid

import pytest

from nestor_pulse_sdk.citations.anchors import (
    ANCHOR_RE,
    ANCHOR_RULE_SECTION,
    ANCHOR_RULE_WRAP,
    _ANCHORS_ENABLED,
    _LEDGER_CHARS,
    _LEDGER_MAX_LINES,
    _LEDGER_INJECTION_RULE,
    anchor_number_map,
    anchor_token,
    apply_citation_anchors,
    build_ledger,
    claim_prefix,
    collision_free_prefixes,
    count_model_numbers,
    render_fact_ledger,
)

# Two ids that deliberately SHARE the first 8 hex characters.
COLLIDE_A = "deadbeef-0000-4000-8000-000000000001"
COLLIDE_B = "deadbeef-0000-4000-8000-000000000002"


def _cid(i: int) -> str:
    """A deterministic claim id whose 8-hex prefix is unique per `i`.

    uuid4() would make the 120-line cap test flaky at ~1e-6 (a birthday collision
    silently drops an entry from the ledger); the top 32 bits are set explicitly
    instead so every prefix in a test run is distinct by construction.
    """
    return str(uuid.UUID(int=(i + 1) << 96))


# ---------------------------------------------------------------------------
# D-05 round trip + D-06 strip-and-count.
# ---------------------------------------------------------------------------


class TestApplyCitationAnchors:
    def test_resolvable_anchor_becomes_the_python_assigned_number(self):
        cid = uuid.uuid4()
        text = f"Aral holds 16% of the market{anchor_token(cid)}."
        out, unresolved = apply_citation_anchors(text, {claim_prefix(cid): 3})
        assert out == "Aral holds 16% of the market[3]."
        assert unresolved == 0

    def test_unresolved_anchor_is_stripped_AND_counted(self):
        """D-06: never a silent delete. The sentence survives, the count travels."""
        out, unresolved = apply_citation_anchors(
            "Aral holds 16% [[c:deadbeef]].", {}
        )
        assert out == "Aral holds 16%."
        assert unresolved == 1

    def test_leading_whitespace_goes_with_a_stripped_anchor(self):
        # Exact-string assertions: the `pre` group is LOCAL to the match, so a
        # stripped anchor never leaves "word ." behind and no global whitespace
        # tidy is ever applied.
        assert apply_citation_anchors("Aral holds 16% [[c:deadbeef]].", {}) == (
            "Aral holds 16%.",
            1,
        )
        assert apply_citation_anchors(
            "Aral holds 16% [[c:deadbeef]].", {"deadbeef": 3}
        ) == ("Aral holds 16% [3].", 0)
        assert apply_citation_anchors("spaced  text .", {}) == ("spaced  text .", 0)

    def test_upper_case_hex_from_the_model_still_resolves(self):
        out, unresolved = apply_citation_anchors("x [[c:DEADBEEF]] y", {"deadbeef": 7})
        assert out == "x [7] y"
        assert unresolved == 0

    def test_mixed_resolved_and_unresolved_in_one_pass(self):
        out, unresolved = apply_citation_anchors(
            "A [[c:aaaaaaaa]] and B [[c:bbbbbbbb]] and C [[c:cccccccc]].",
            {"aaaaaaaa": 1, "cccccccc": 2},
        )
        assert out == "A [1] and B and C [2]."
        assert unresolved == 1

    def test_determinism_across_50_calls(self):
        text = "A [[c:aaaaaaaa]] B [[c:bbbbbbbb]] C [cite: 4] D [x](https://a.example)."
        mapping = {"aaaaaaaa": 1}
        first = apply_citation_anchors(text, mapping)
        for _ in range(50):
            assert apply_citation_anchors(text, mapping) == first

    @pytest.mark.parametrize(
        "bad",
        [
            None,
            "",
            123,
            ["not", "a", "string"],
            "[[c:zzzz]]",
            "[[c:]]",
            "[[c:9f2a41bd",
            "[[c:9f2a41]]",  # 6 hex, not 8
            "[[c:9f2a41bdd]]",  # 9 hex
        ],
    )
    def test_never_raises_on_garbage(self, bad):
        out, unresolved = apply_citation_anchors(bad, {"deadbeef": 1})
        assert out == bad
        assert unresolved == 0

    def test_garbled_number_map_entries_are_ignored_not_fatal(self):
        out, unresolved = apply_citation_anchors(
            "x [[c:deadbeef]] y", {"deadbeef": "not-a-number"}
        )
        assert out == "x y"
        assert unresolved == 1


# ---------------------------------------------------------------------------
# The non-collision trio -- three mechanisms, never conflated.
# ---------------------------------------------------------------------------


class TestNonCollisionTrio:
    def test_a_strip_unresolved_cite_markers_leaves_anchors_byte_unchanged(self):
        from nestor_pulse_sdk.audit.audited_llm_client import (
            strip_unresolved_cite_markers,
        )

        text = "x [[c:9f2a41bd]] y"
        assert strip_unresolved_cite_markers(text) == (text, 0)

    def test_b_apply_citation_anchors_leaves_provider_cite_markers_untouched(self):
        text = "Aral holds 16% [cite: 12] of the market [cite_4]."
        assert apply_citation_anchors(text, {"deadbeef": 1}) == (text, 0)

    def test_c_markdown_links_survive_both_directions(self):
        from nestor_pulse_sdk.pipeline.synthesis.steps import _MD_LINK_RE

        text = "see [Aral](https://a.example/x) [[c:9f2a41bd]] and [B](https://b.example/y)"
        assert _MD_LINK_RE.findall(text) == [
            ("Aral", "https://a.example/x"),
            ("B", "https://b.example/y"),
        ]
        link_only = "[label](https://example.com/a)"
        assert apply_citation_anchors(link_only, {}) == (link_only, 0)

    def test_c2_an_anchor_inside_a_link_hides_it_from_MD_LINK_RE(self):
        """Pins WHY build_graded_sources_section strips anchors before scanning.

        `_MD_LINK_RE` needs `](` adjacency. A model that drops its anchor between
        the label and the URL writes `[Aral][[c:9f2a41bd]](https://...)`, which
        matches NOTHING -- the URL would silently vanish from `## Sources`. The
        graded builder therefore removes anchors from its SCAN COPY first; the
        report text itself is never touched by that.
        """
        from nestor_pulse_sdk.pipeline.synthesis.steps import _MD_LINK_RE

        broken = "see [Aral][[c:9f2a41bd]](https://a.example/x) end"
        assert _MD_LINK_RE.findall(broken) == []
        cleaned = ANCHOR_RE.sub("", broken)
        assert _MD_LINK_RE.findall(cleaned) == [("Aral", "https://a.example/x")]


# ---------------------------------------------------------------------------
# Prefix collision safety.
# ---------------------------------------------------------------------------


class TestPrefixCollision:
    def test_colliding_prefix_is_excluded_from_the_map(self):
        usable = collision_free_prefixes([COLLIDE_A, COLLIDE_B, _cid(0)])
        assert "deadbeef" not in usable
        assert len(usable) == 1

    def test_colliding_claims_are_excluded_from_the_ledger(self):
        rows = [
            {"claim_id": COLLIDE_A, "text": "fact A", "facet": "f", "position": 0},
            {"claim_id": COLLIDE_B, "text": "fact B", "facet": "f", "position": 1},
        ]
        assert build_ledger(rows) == []

    def test_a_colliding_anchor_strips_and_counts_rather_than_mis_citing(self):
        prefix_to_n = anchor_number_map({COLLIDE_A: 1, COLLIDE_B: 2})
        assert prefix_to_n == {}
        out, unresolved = apply_citation_anchors(
            f"Claim A{anchor_token(COLLIDE_A)}.", prefix_to_n
        )
        assert out == "Claim A."
        assert unresolved == 1

    def test_repeating_the_same_id_is_not_a_collision(self):
        usable = collision_free_prefixes([COLLIDE_A, COLLIDE_A])
        assert usable == {"deadbeef": COLLIDE_A}


# ---------------------------------------------------------------------------
# anchor_number_map -- ledger and resolver share one exclusion rule.
# ---------------------------------------------------------------------------


class TestAnchorNumberMap:
    def test_reduces_full_claim_ids_to_prefixes(self):
        a, b = _cid(0), _cid(1)
        out = anchor_number_map({a: 1, b: 2})
        assert out == {claim_prefix(a): 1, claim_prefix(b): 2}

    def test_empty_and_none_are_safe(self):
        assert anchor_number_map(None) == {}
        assert anchor_number_map({}) == {}


# ---------------------------------------------------------------------------
# count_model_numbers -- T-15.2-24, count only, never strip.
# ---------------------------------------------------------------------------


class TestCountModelNumbers:
    def test_counts_bare_bracketed_numbers(self):
        assert count_model_numbers("see [7] and [12]") == 2

    def test_an_anchor_is_not_a_number(self):
        assert count_model_numbers("[[c:9f2a41bd]]") == 0

    def test_provider_cite_markers_are_not_counted(self):
        assert count_model_numbers("x [cite: 12] y") == 0

    def test_safe_on_garbage(self):
        assert count_model_numbers(None) == 0
        assert count_model_numbers("") == 0
        assert count_model_numbers(42) == 0


# ---------------------------------------------------------------------------
# The fact ledger (prompt side).
# ---------------------------------------------------------------------------


def _rows(n: int, facet: str = "alpha", text: str = "fact", start: int = 0) -> list[dict]:
    return [
        {"claim_id": _cid(start + i), "text": f"{text} {i}", "facet": facet, "position": i}
        for i in range(n)
    ]


@pytest.mark.skipif(
    not _ANCHORS_ENABLED, reason="NESTOR_TRIBUNAL_ANCHORS kill switch is off"
)
class TestRenderFactLedger:
    def test_empty_ledger_renders_nothing(self):
        assert render_fact_ledger([]) == ""
        assert render_fact_ledger(None) == ""

    def test_carries_the_injection_control_line_and_sentinels(self):
        out = render_fact_ledger(build_ledger(_rows(2)))
        assert _LEDGER_INJECTION_RULE in out
        assert "--- FACT LEDGER ---" in out
        assert "--- END FACT LEDGER ---" in out

    def test_one_line_per_fact_with_its_anchor(self):
        rows = _rows(3)
        ledger = build_ledger(rows)
        out = render_fact_ledger(ledger)
        for row in rows:
            assert f"{anchor_token(row['claim_id'])} {row['text']}" in out

    def test_facet_filter_scopes_the_ledger(self):
        rows = _rows(2, facet="alpha", text="A") + _rows(
            2, facet="beta", text="B", start=100
        )
        ledger = build_ledger(rows)
        assert len(ledger) == 4, "distinct ids: nothing may be deduped away"
        out = render_fact_ledger(ledger, facet="Alpha")
        assert "A 0" in out
        assert "B 0" not in out

    def test_facet_miss_falls_back_to_the_full_ledger(self):
        """Never silently drop the ledger and leave an unobeyable anchor rule."""
        out = render_fact_ledger(build_ledger(_rows(2, facet="alpha")), facet="nope")
        assert "fact 0" in out

    def test_long_facts_are_truncated(self):
        long_text = "z" * (_LEDGER_CHARS + 200)
        rows = [{"claim_id": _cid(0), "text": long_text, "facet": "f", "position": 0}]
        out = render_fact_ledger(build_ledger(rows))
        assert "z" * _LEDGER_CHARS in out
        assert "z" * (_LEDGER_CHARS + 1) not in out

    def test_newlines_inside_a_fact_are_collapsed(self):
        rows = [
            {"claim_id": _cid(0), "text": "one\ntwo\n\nthree", "facet": "f", "position": 0}
        ]
        out = render_fact_ledger(build_ledger(rows))
        assert "one two three" in out

    def test_cap_keeps_the_first_N_and_states_the_omitted_count_in_words(self):
        over = _LEDGER_MAX_LINES + 7
        out = render_fact_ledger(build_ledger(_rows(over)))
        body = out.split(_LEDGER_INJECTION_RULE, 1)[1]
        assert "fact 0" in body
        assert f"fact {over - 1}" not in body
        assert "7 further fact(s) were left out" in body


class TestBuildLedger:
    def test_preserves_input_order_and_shape(self):
        rows = _rows(3)
        ledger = build_ledger(rows)
        assert [e["claim_id"] for e in ledger] == [r["claim_id"] for r in rows]
        assert set(ledger[0]) == {"anchor", "prefix", "claim_id", "text", "facet"}
        assert ANCHOR_RE.fullmatch(ledger[0]["anchor"]) is not None

    def test_empty_text_rows_are_skipped(self):
        rows = [
            {"claim_id": _cid(0), "text": "   ", "facet": "f", "position": 0},
            {"claim_id": _cid(1), "text": "real", "facet": "f", "position": 1},
        ]
        ledger = build_ledger(rows)
        assert len(ledger) == 1
        assert ledger[0]["text"] == "real"

    def test_none_and_empty_are_safe(self):
        assert build_ledger(None) == []
        assert build_ledger([]) == []


# ---------------------------------------------------------------------------
# Token shape.
# ---------------------------------------------------------------------------


class TestTokenShape:
    def test_prefix_is_lower_hex_without_hyphens(self):
        assert claim_prefix("DEADBEEF-0000-4000-8000-000000000001") == "deadbeef"

    def test_anchor_token_matches_ANCHOR_RE(self):
        token = anchor_token(uuid.uuid4())
        m = ANCHOR_RE.fullmatch(token)
        assert m is not None
        assert re.fullmatch(r"[0-9a-f]{8}", m.group("pfx"))


# ---------------------------------------------------------------------------
# PITFALL 2: the anchor rule must reach the prompts synthesize_report ACTUALLY
# sends. Prompt-capturing fake, cloned from test_synthesize_report.py::FakeAudited
# -- no DB, no key, no network, no mocking library.
# ---------------------------------------------------------------------------

FA_A = "Pricing strategies"
FA_B = "Coffee offering"

#: The literal both prompt rules share. If this string stops appearing in all
#: three captured prompts, the anchor instruction is not reaching the model.
ANCHOR_RULE_MARKER = "CITATION ANCHORS (non-negotiable):"

MISSION_BRIEF = {
    "deep_research_prompt": "Research the forecourt retail market.",
    "focus_areas": [
        {"focus_area": FA_A, "taxonomy": "B", "stakes": "high"},
        {"focus_area": FA_B, "taxonomy": "B", "stakes": "med"},
    ],
}

PROVIDER_REPORTS = [("gemini", {"status": "success", "report": "Research prose."})]


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text


class CapturingAudited:
    """Records the `contents=` of every gemini_generate call."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def gemini_generate(self, *, run_id, tenant_id, model, contents, **kwargs):
        self.prompts.append(contents)
        if "Write the remaining framing sections" in contents:
            return _FakeResponse(
                "## Executive Summary\n\nBottom line.\n\n"
                "## Cross-cutting Synthesis\n\nThemes.\n\n"
                "## Confidence & Gaps\n\nSolid."
            )
        m = re.search(r'focus area \d+ of \d+:\s*"([^"]+)"', contents)
        fa = m.group(1) if m else "Unknown"
        return _FakeResponse(f"## {fa}\n\nFindings for {fa}.")

    @property
    def section_prompts(self) -> list[str]:
        return [p for p in self.prompts if "Write the remaining framing sections" not in p]

    @property
    def wrap_prompt(self) -> str:
        return next(p for p in self.prompts if "Write the remaining framing sections" in p)


def _ledger_for_two_focus_areas() -> list[dict]:
    return build_ledger(
        [
            {"claim_id": _cid(1), "text": "Fuel margin is 6 cents", "facet": FA_A,
             "position": 0},
            {"claim_id": _cid(2), "text": "Coffee attach rate is 18%", "facet": FA_B,
             "position": 1},
        ]
    )


async def _synthesize(audited, **kwargs):
    from nestor_pulse_sdk.pipeline.synthesis.steps import synthesize_report

    return await synthesize_report(
        mission_brief=MISSION_BRIEF,
        provider_reports=PROVIDER_REPORTS,
        audited=audited,
        run_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        **kwargs,
    )


@pytest.mark.skipif(
    not _ANCHORS_ENABLED, reason="NESTOR_TRIBUNAL_ANCHORS kill switch is off"
)
async def test_anchor_rule_reaches_both_prompt_sites():
    """PITFALL 2 -- the headline of this plan.

    CONTEXT.md pointed the anchor instruction at synthesis prompt line 229, which
    lives in `final_synthesis_audited`. `synthesize_report` calls that ONLY when
    the mission brief carries zero focus areas (the broadcast/control fallback).
    Every real run has focus areas and therefore goes down the
    `_one_section` x N + `wrap_prompt` path, so patching line 229 would have been
    a silent no-op on every real run -- green tests, zero anchors in production.

    This asserts the rule reaches ALL THREE prompts actually sent: one per focus
    area, plus the wrap.
    """
    audited = CapturingAudited()
    await _synthesize(audited, anchor_ledger=_ledger_for_two_focus_areas())

    assert len(audited.prompts) == 3, "2 section calls + 1 wrap call"
    for prompt in audited.prompts:
        assert ANCHOR_RULE_MARKER in prompt


@pytest.mark.skipif(
    not _ANCHORS_ENABLED, reason="NESTOR_TRIBUNAL_ANCHORS kill switch is off"
)
async def test_section_ledger_is_scoped_to_its_own_focus_area():
    audited = CapturingAudited()
    await _synthesize(audited, anchor_ledger=_ledger_for_two_focus_areas())

    prompt_a = next(p for p in audited.section_prompts if f'"{FA_A}"' in p)
    assert "Fuel margin is 6 cents" in prompt_a
    assert "Coffee attach rate is 18%" not in prompt_a


@pytest.mark.skipif(
    not _ANCHORS_ENABLED, reason="NESTOR_TRIBUNAL_ANCHORS kill switch is off"
)
async def test_wrap_prompt_gets_the_rule_but_NOT_the_ledger():
    """Cost control (T-15.2-25): the wrap reuses the body's anchors."""
    audited = CapturingAudited()
    await _synthesize(audited, anchor_ledger=_ledger_for_two_focus_areas())

    wrap = audited.wrap_prompt
    assert "already carry opaque anchor tokens" in wrap  # ANCHOR_RULE_WRAP
    assert "--- FACT LEDGER ---" not in wrap
    # And the section rule's ledger-specific wording never leaks into the wrap.
    assert "A FACT LEDGER is supplied below" not in wrap


async def test_back_compat_no_ledger_means_no_rule_and_no_sentinel():
    """With anchors off the prompts are byte-identical to the pre-15.2 ones."""
    audited = CapturingAudited()
    await _synthesize(audited, anchor_ledger=None)

    assert len(audited.prompts) == 3
    for prompt in audited.prompts:
        assert ANCHOR_RULE_MARKER not in prompt
        assert "--- FACT LEDGER ---" not in prompt


# ---------------------------------------------------------------------------
# The graded ## Sources list (D13 / D-07).
# ---------------------------------------------------------------------------


def _numbered(**overrides) -> dict:
    entry = {
        "n": 1,
        "source_id": "s1",
        "title": "Aral annual report",
        "url": "https://www.sec.gov/aral",
        "provider": "google",
        "publication_date": "2026-07-26T12:00:00+00:00",
        "quality_tier": 1,
        "single_source": False,
        "first_claim_id": "c1",
        "first_claim_position": 0,
    }
    entry.update(overrides)
    return entry


class TestGradedSourcesSection:
    def test_renders_tier_retrieval_date_and_single_source_flag(self):
        from nestor_pulse_sdk.pipeline.synthesis.steps import (
            build_graded_sources_section,
        )

        out = build_graded_sources_section(
            [
                _numbered(),
                _numbered(n=2, title=None, url="https://www.reuters.com/x",
                          quality_tier=2, single_source=True),
                _numbered(n=3, title=None, url="https://blog.example/y",
                          quality_tier=3, publication_date=None),
            ],
            "body text",
        )
        assert "1. [Aral annual report](https://www.sec.gov/aral) — official source" in out
        assert "retrieved 2026-07-26" in out
        assert "published" not in out, "fetched_at is a RETRIEVAL proxy (C1)"
        # title=None falls back to the display domain, www. stripped.
        assert "2. [reuters.com](https://www.reuters.com/x) — established press" in out
        assert "single-source" in out
        assert "3. [blog.example](https://blog.example/y) — other source · retrieved date unknown" in out
        # single_source=False must NOT render the flag or a dangling separator:
        # the whole line is asserted, not a substring of it.
        assert (
            "1. [Aral annual report](https://www.sec.gov/aral) — "
            "official source · retrieved 2026-07-26"
        ) in out.splitlines()

    def test_entry_without_a_url_renders_as_plain_text_not_a_broken_link(self):
        from nestor_pulse_sdk.pipeline.synthesis.steps import (
            build_graded_sources_section,
        )

        out = build_graded_sources_section([_numbered(url=None)], "")
        assert "1. Aral annual report — official source" in out
        assert "]()" not in out

    def test_falsy_numbered_is_byte_identical_to_the_legacy_builder(self):
        from nestor_pulse_sdk.pipeline.synthesis.steps import (
            _extract_sources_section,
            build_graded_sources_section,
        )

        text = "see [x](https://a.example) and [y](https://b.example)"
        assert build_graded_sources_section(None, text) == _extract_sources_section(text)
        assert build_graded_sources_section([], text) == _extract_sources_section(text)

    def test_append_only_rescue_keeps_a_prose_url_that_has_no_claim(self):
        from nestor_pulse_sdk.pipeline.synthesis.steps import (
            build_graded_sources_section,
        )

        out = build_graded_sources_section(
            [_numbered()],
            "cited [Aral](https://www.sec.gov/aral) plus [Stray](https://stray.example/z)",
        )
        assert "https://stray.example/z" in out
        assert "carry no verified claim link" in out
        # The already-numbered URL is not listed twice.
        assert out.count("https://www.sec.gov/aral") == 1

    def test_an_anchor_inside_a_link_does_not_lose_the_url(self):
        """The scan copy is anchor-stripped, so `[L][[c:..]](url)` still lists."""
        from nestor_pulse_sdk.pipeline.synthesis.steps import (
            build_graded_sources_section,
        )

        out = build_graded_sources_section(
            None, "see [Aral][[c:9f2a41bd]](https://www.sec.gov/aral) end"
        )
        assert "https://www.sec.gov/aral" in out
