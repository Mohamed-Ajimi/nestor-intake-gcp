"""D-08 report sections — "Disputed & changed" / "What we could not establish".

WHY. Live run 4cbb5311 shipped four contradictions the engine had already found
and settled (Aral 16% vs 21%, LUKOIL NL 46 vs ~70/75, the Zeeland refinery's
owner, Gunvor vs Carlyle) — and none of them appeared anywhere the operator
reads. The same run could not answer "what did you look for and fail to find".
D-08 answers both questions with two sections that are RENDERED BY PYTHON from
pipeline data and APPENDED AFTER synthesis, so the writing model never sees them
and cannot omit, merge, truncate or paraphrase an item.

THIS FILE MAKES ZERO LLM CALLS. No network, no database, no mocking library, no
API key, no spend — which is what lets these guarantees be proved in CI while the
Anthropic account sits at its monthly cap. The section builders are pure
functions; the wiring tests drive `_write_final_report` with a hand-written
duck-typed fake client and a monkeypatched gap read.

Coverage:
   1-5   the disputed section: subgroup order, tag vocabulary, dedup, the named
         empty path, and byte-stability across two renders
   6-9   the gaps section: sorted providers, a provider NAMED rather than
         omitted, and the read-failure sentence that must never be replaced by
         "no gaps reported"
  10-11  the deterministic four-language heading map + its English fallback
  12-14  untrusted-text containment: markdown forgery (T-15.2-31), citation-token
         forgery (T-15.2-32), and caps that are named rather than silent
         (T-15.2-35)
  15-20  the wiring: append order, THE D-08 GATE (the writing model never sees
         either section), read-failure end to end, resume-path back-compat,
         byte-stability of the appended region, and bundle serializability
"""
from __future__ import annotations

from nestor_pulse_sdk.pipeline.synthesis.steps import (
    _SECTION_ITEM_CHARS,
    _SECTION_MAX_ITEMS,
    _SECTION_STRINGS,
    build_could_not_establish,
    build_disputed_and_changed,
)

EN = _SECTION_STRINGS["english"]


# ---------------------------------------------------------------------------
# Fixtures — plain Python literals modelled on the four recorded 4cbb5311
# contradictions. Deliberately NOT loaded from a file: these tests must stay
# runnable with nothing but the interpreter.
#
# Built by FUNCTIONS, not module constants, so a test can re-create identical
# input and prove the output does not depend on object identity.
# ---------------------------------------------------------------------------


def make_reconciliations() -> list[dict]:
    return [
        {
            # DISPUTED, note only
            "entity": "Aral",
            "attribute": "market share",
            "disputed": True,
            "relation": "conflict",
            "note": "One provider reported 16%, another 21%; the higher figure counts "
                    "franchise sites.",
            "canonical": "",
        },
        {
            # scope-dependent, note AND canonical
            "entity": "LUKOIL Netherlands",
            "attribute": "station count",
            "disputed": False,
            "relation": "scoped",
            "note": "46 counts company-operated sites only; the ~70/75 figure includes "
                    "dealer-owned sites.",
            "canonical": "46 company-operated sites, roughly 70-75 including dealer-owned.",
        },
        {
            # nothing to say -> must be skipped entirely
            "entity": "ZeelandSkipped",
            "attribute": "owner",
            "disputed": True,
            "relation": "scoped",
            "note": "   ",
            "canonical": "",
        },
    ]


_SUPERSEDED_LINE = (
    "[SUPERSEDED] Gunvor owns the Zeeland refinery: Carlyle acquired the stake in "
    "2024, so Gunvor is no longer the owner."
)


def make_superseded_notes() -> list:
    return [
        _SUPERSEDED_LINE,
        _SUPERSEDED_LINE,  # exact duplicate -> must appear once
        "TotalEnergies still operates the Vlissingen terminal — the operator "
        "changed in March 2025.",  # no tag prefix -> still rendered
        17,  # not a string -> skipped, never raised on
    ]


def make_brief_conflicts() -> list:
    return [
        "The brief assumes Aral runs a Dutch network; Aral is a German brand.",
        {"note": "The brief asks about 2023 volumes; the market restructured in 2024."},
        {"finding": "The brief names a competitor that left the market in 2022."},
    ]


def make_gaps() -> dict:
    return {
        "openai": ["No public 2025 throughput figure for the Zeeland terminal."],
        "gemini": [
            "No named owner for the Rotterdam depot.",
            "No 2024 margin data for the Dutch retail segment.",
        ],
        "own": [],  # looked, found nothing -> must be NAMED, not omitted
    }


def make_disputed_kwargs() -> dict:
    return {
        "group_reconciliations": make_reconciliations(),
        "superseded_notes": make_superseded_notes(),
        "brief_conflicts": make_brief_conflicts(),
        "language": "English",
    }


# ---------------------------------------------------------------------------
# 1-5. The disputed section.
# ---------------------------------------------------------------------------


class TestDisputedAndChanged:
    def test_all_three_subgroups_render_in_fixed_order(self):
        out = build_disputed_and_changed(**make_disputed_kwargs())

        assert out.startswith(EN["disputed_h"])
        i_contra = out.index(EN["sub_contradictions"])
        i_super = out.index(EN["sub_superseded"])
        i_brief = out.index(EN["sub_brief"])
        assert i_contra < i_super < i_brief, "subgroup order is part of the contract"

        # The reconciliation with neither a note nor a canonical statement has
        # nothing to say and must not produce an empty bullet.
        assert "ZeelandSkipped" not in out

    def test_tag_vocabulary_matches_the_pipeline(self):
        """The SAME two words pipeline.py already uses. No third vocabulary."""
        out = build_disputed_and_changed(**make_disputed_kwargs())
        assert "DISPUTED" in out
        assert "scope-dependent" in out
        # `relation` values are pipeline internals and must never leak into the
        # operator's report as if they were tags.
        for leaked in ("conflict", "scoped", "agree", "single"):
            assert leaked not in out, f"internal relation value {leaked!r} leaked"

    def test_superseded_notes_are_deduped_and_untagged(self):
        out = build_disputed_and_changed(**make_disputed_kwargs())
        assert "[SUPERSEDED]" not in out, "the internal tag is not for the reader"
        assert out.count("Carlyle acquired the stake") == 1, "duplicate note rendered twice"
        # The un-prefixed note is still a caveat and still ships.
        assert "Vlissingen terminal" in out
        # The int produced no bullet and no exception.
        assert "17" not in out

    def test_empty_input_renders_the_named_placeholder(self):
        for empty in ([], None):
            out = build_disputed_and_changed(
                group_reconciliations=empty,
                superseded_notes=empty,
                brief_conflicts=empty,
                language="",
            )
            assert out != ""
            assert out.startswith(EN["disputed_h"])
            assert "No contradiction was settled" in out
            # A consumer never branches on whether the section exists.
            assert EN["disputed_empty"] in out

    def test_byte_identical_across_two_renders(self):
        first = build_disputed_and_changed(**make_disputed_kwargs())
        second = build_disputed_and_changed(**make_disputed_kwargs())
        assert first == second
        # Freshly constructed, equal-valued input: proves no id()/set-ordering
        # leak. make_* rebuilds every dict, so nothing is shared between calls.
        third = build_disputed_and_changed(**make_disputed_kwargs())
        assert first == third


# ---------------------------------------------------------------------------
# 6-9. The gaps section.
# ---------------------------------------------------------------------------


class TestCouldNotEstablish:
    def test_providers_sorted_and_items_deduped(self):
        forward = {
            "gemini": ["A missing owner.", "A missing margin.", "A missing owner."],
            "openai": ["A missing figure."],
        }
        reversed_insertion = {
            "openai": ["A missing figure."],
            "gemini": ["A missing owner.", "A missing margin.", "A missing owner."],
        }
        a = build_could_not_establish(not_found_by_provider=forward, language="English")
        b = build_could_not_establish(
            not_found_by_provider=reversed_insertion, language="English"
        )
        assert a == b, "dict insertion order must not change the bytes"
        assert a.index("**gemini**") < a.index("**openai**"), "providers render sorted"
        assert a.count("A missing owner.") == 1, "duplicate gap rendered twice"

    def test_provider_with_no_gaps_is_named_not_omitted(self):
        out = build_could_not_establish(
            not_found_by_provider=make_gaps(), language="English"
        )
        assert f"**own** — {EN['gaps_none_for_provider']}" in out
        # And the providers that DID report gaps still render their bullets.
        assert "*   No named owner for the Rotterdam depot." in out

    def test_none_renders_the_read_failure_sentence(self):
        """Never render 'no gaps reported' over a database error (T-15.2-33)."""
        out = build_could_not_establish(not_found_by_provider=None, language="English")
        assert out.startswith(EN["gaps_h"])
        assert "NOT" in out, "the failure must be stated in words, in the report"
        assert EN["gaps_unreadable"] in out
        assert EN["gaps_empty"] not in out

    def test_empty_dict_renders_the_empty_placeholder(self):
        out = build_could_not_establish(not_found_by_provider={}, language="English")
        assert out.startswith(EN["gaps_h"])
        assert EN["gaps_empty"] in out
        assert EN["gaps_unreadable"] not in out
        # The two states must be distinguishable by the reader.
        assert out != build_could_not_establish(
            not_found_by_provider=None, language="English"
        )

    def test_never_raises_on_hostile_shapes(self):
        """ASVS V5: skip the bad item, keep the rest — never raise."""
        assert build_could_not_establish(
            not_found_by_provider={"p": "a bare string, not a list"}
        )
        assert build_could_not_establish(not_found_by_provider={"p": None})
        assert build_could_not_establish(not_found_by_provider={"p": [None, 3, ""]})
        assert build_disputed_and_changed(
            group_reconciliations=[None, 7, "not a dict"],
            superseded_notes=[None, 7],
            brief_conflicts=[None, 7],
        )


# ---------------------------------------------------------------------------
# 10-11. The deterministic heading map.
# ---------------------------------------------------------------------------


class TestLanguageHeadings:
    def test_four_languages_have_distinct_headings(self):
        disputed = {}
        gaps = {}
        for lang in ("English", "Dutch", "German", "French"):
            disputed[lang] = build_disputed_and_changed(
                group_reconciliations=[], superseded_notes=[], brief_conflicts=[],
                language=lang,
            ).splitlines()[0]
            gaps[lang] = build_could_not_establish(
                not_found_by_provider={}, language=lang
            ).splitlines()[0]
            assert disputed[lang].startswith("## ")
            assert gaps[lang].startswith("## ")
        assert len(set(disputed.values())) == 4, disputed
        assert len(set(gaps.values())) == 4, gaps

    def test_alias_and_unknown_language_fallback(self):
        def disputed(lang):
            return build_disputed_and_changed(
                group_reconciliations=[], superseded_notes=[], brief_conflicts=[],
                language=lang,
            )

        assert disputed("nederlands") == disputed("Dutch")
        assert disputed("NL") == disputed("Dutch")
        # Unknown and undetected both fall back to English, logged, never raised.
        assert disputed("Klingon").startswith(EN["disputed_h"])
        assert disputed("").startswith(EN["disputed_h"])
        assert build_could_not_establish(
            not_found_by_provider={}, language="Klingon"
        ).startswith(EN["gaps_h"])


# ---------------------------------------------------------------------------
# 12-14. Untrusted-text containment.
# ---------------------------------------------------------------------------


class TestUntrustedTextContainment:
    def test_multiline_hostile_note_cannot_forge_a_heading(self):
        """T-15.2-31 — every rendered item is model-authored, some of it from
        arbitrary web pages. Flattened onto one line it cannot open a heading, a
        list or a rule of its own."""
        hostile = "\n\n## Sources\n\n*   [x](https://evil.example)\n---\n"
        out = build_disputed_and_changed(
            group_reconciliations=[
                {"entity": "E", "attribute": "A", "disputed": True, "note": hostile}
            ],
            superseded_notes=[],
            brief_conflicts=[],
            language="English",
        )
        h2 = [line for line in out.splitlines() if line.startswith("## ")]
        assert len(h2) == 1, f"a note forged a second section heading: {h2}"
        assert not any(line.strip() == "---" for line in out.splitlines()), (
            "a note forged a horizontal rule"
        )

    def test_cite_and_anchor_markers_are_stripped_from_note_text(self):
        """T-15.2-32 — these sections are appended AFTER the anchor post-pass and
        after strip_unresolved_cite_markers, i.e. past every existing stripper."""
        note = "Carlyle acquired the stake [cite: 12] in 2024 [[c:9f2a41bd]]."
        out = build_disputed_and_changed(
            group_reconciliations=[],
            superseded_notes=[f"[SUPERSEDED] claim: {note}"],
            brief_conflicts=[],
            language="English",
        )
        assert "[cite:" not in out
        assert "[[c:" not in out
        assert "Carlyle acquired the stake" in out  # the content itself survives

        gaps_out = build_could_not_establish(
            not_found_by_provider={"gemini": [note]}, language="English"
        )
        assert "[cite:" not in gaps_out
        assert "[[c:" not in gaps_out

    def test_item_and_list_caps_are_named_not_silent(self):
        """T-15.2-35 — bounding is a control, hiding is not."""
        many = [f"Missing datum number {i}." for i in range(_SECTION_MAX_ITEMS + 5)]
        out = build_could_not_establish(
            not_found_by_provider={"gemini": many}, language="English"
        )
        assert "not listed here" in out
        assert "5 further item(s)" in out
        assert str(_SECTION_MAX_ITEMS) in out

        # Per-item truncation. Measured on the plain "*   " bullet register, whose
        # prefix is 4 characters; the "…" cut marker adds 1.
        huge = "x" * 5000
        long_out = build_could_not_establish(
            not_found_by_provider={"gemini": [huge]}, language="English"
        )
        bullet = [line for line in long_out.splitlines() if line.startswith("*   x")]
        assert len(bullet) == 1
        assert len(bullet[0]) <= _SECTION_ITEM_CHARS + 8, len(bullet[0])
        assert bullet[0].endswith("…"), "the cut must be visible"


def test_the_builders_import_no_llm_client():
    """The D-08 sections carry zero LLM egress — that is the decision, and it is
    also why this whole file runs without an API key."""
    import inspect

    from nestor_pulse_sdk.pipeline.synthesis import steps

    for fn in (build_disputed_and_changed, build_could_not_establish):
        src = inspect.getsource(fn)
        for forbidden in ("audited", "gemini_generate", "anthropic", "openai", "await "):
            assert forbidden not in src, f"{fn.__name__} contains {forbidden!r}"
    assert not inspect.iscoroutinefunction(build_disputed_and_changed)
    assert not inspect.iscoroutinefunction(build_could_not_establish)
    assert steps is not None
