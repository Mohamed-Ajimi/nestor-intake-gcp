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
  21-33  THE DISCOVERY PROVENANCE CLAUSE (phase 15.6): the real producer driven
         into the real consumer, the clause in all four languages, and the three
         ways a conflict must render with NO clause at all
"""
from __future__ import annotations

import json
import re
import uuid

import pytest

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


# ---------------------------------------------------------------------------
# 15-20. The wiring — _write_final_report drives the real production path.
#
# Still zero LLM, no DB, no mocking library: a hand-written duck-typed fake
# records every prompt string it is handed, and `_read_research_gaps` is replaced
# AT THE MODULE BOUNDARY (no test-only parameter is added to production code).
#
# `set_stage` and `_load_citation_context` are NOT patched on purpose: both are
# best-effort, both swallow their own exceptions, and in a gate that provisions no
# DATABASE_URL both fail immediately and log. Leaving them in keeps the real
# production path under test.
#
# Sentinels are strings that cannot occur naturally, so "the model never saw it"
# is a substring search with no false negatives.
# ---------------------------------------------------------------------------

ZZ_GAP_A = "ZZGAP-ALPHA"
ZZ_GAP_B = "ZZGAP-BETA"
ZZ_BRIEF = "ZZBRIEF-GAMMA"
ZZ_RECON = "ZZRECON-DELTA"


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text


class RecordingAudited:
    """Duck-typed stand-in for AuditedLLMClient that records every prompt.

    Deterministic by construction: the reply is a pure function of the prompt, so
    two runs of the same bundle produce the same report body.
    """

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def gemini_generate(self, *, run_id, tenant_id, model, contents, **kwargs):
        self.prompts.append(contents)
        if "Write the remaining framing sections" in contents:
            return _FakeResponse(
                "## Executive Summary\n\nThe bottom line.\n\n"
                "## Cross-cutting Synthesis\n\nThemes interact.\n\n"
                "## Confidence & Gaps\n\nSTRONG on A, LIMITED on B."
            )
        m = re.search(r'focus area \d+ of \d+:\s*"([^"]+)"', contents)
        fa = m.group(1) if m else "Unknown"
        return _FakeResponse(f"## {fa}\n\nFindings for {fa}.")


def make_report_sections_payload() -> dict:
    return {
        "group_reconciliations": [
            {
                "entity": "Aral",
                "attribute": "market share",
                "disputed": True,
                "relation": "scoped",
                "note": f"{ZZ_RECON} — one provider reported 16%, another 21%.",
                "canonical": "",
            }
        ],
        "superseded_notes": [
            "[SUPERSEDED] Gunvor owns the Zeeland refinery: Carlyle acquired the stake."
        ],
        "brief_conflicts": [f"{ZZ_BRIEF} — the brief assumes a Dutch Aral network."],
    }


def make_bundle(with_report_sections: bool = True) -> dict:
    bundle: dict = {
        "mission_brief": {
            "deep_research_prompt": "Research the Dutch fuel retail market.",
            "language": "English",
            "focus_areas": [
                {"focus_area": "Station networks", "taxonomy": "B", "stakes": "high"},
                {"focus_area": "Margin structure", "taxonomy": "B", "stakes": "med"},
            ],
        },
        "cleaned_reports": [
            ["gemini", {"status": "success", "report": "Research prose about networks."}]
        ],
        "contested_notes": ["[DISPUTED] Aral — market share: 16% versus 21%."],
        "rejected_claims": [],
        "verification": {
            "per_claim_verdicts": {},
            "n_claims": 3,
            "survivor_count": 2,
            "dropped_count": 1,
            "n_unverified": 0,
            "contested_count": 1,
            "claims_per_facet": {},
        },
    }
    if with_report_sections:
        bundle["report_sections"] = make_report_sections_payload()
    return bundle


def make_gap_rows() -> dict:
    return {
        "gemini": [f"{ZZ_GAP_A} — no public 2025 throughput figure."],
        "openai": [f"{ZZ_GAP_B} — no named owner for the Rotterdam depot."],
    }


def _patch_gaps(monkeypatch, value):
    async def _fake(run_id, tenant_id):
        return value

    monkeypatch.setattr(
        "nestor_pulse_sdk.pipeline.tribunal.pipeline._read_research_gaps", _fake
    )


async def _write(bundle, audited):
    from nestor_pulse_sdk.pipeline.tribunal.pipeline import _write_final_report

    return await _write_final_report(
        bundle=bundle,
        report_spec=None,
        audited=audited,
        run_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
    )


class TestWriteFinalReportWiring:
    @pytest.mark.asyncio
    async def test_sections_are_appended_in_order_before_the_verification_appendix(
        self, monkeypatch
    ):
        _patch_gaps(monkeypatch, make_gap_rows())
        result = await _write(make_bundle(), RecordingAudited())
        out = result["output_text"]
        assert (
            out.index(EN["disputed_h"])
            < out.index(EN["gaps_h"])
            < out.index("## Verification")
        ), "the three trailing sections have a fixed order"

    @pytest.mark.asyncio
    async def test_the_writing_model_never_sees_either_section(self, monkeypatch):
        """THE D-08 GATE.

        The whole decision is that these sections are appended AFTER synthesis, so
        the writing model cannot omit, merge, truncate or paraphrase an item. That
        is only true if no prompt ever carried them.
        """
        _patch_gaps(monkeypatch, make_gap_rows())
        audited = RecordingAudited()
        result = await _write(make_bundle(), audited)
        out = result["output_text"]

        assert audited.prompts, "the fake recorded nothing — the test proves nothing"
        forbidden = (EN["disputed_h"], EN["gaps_h"], ZZ_GAP_A, ZZ_GAP_B, ZZ_BRIEF)
        for i, prompt in enumerate(audited.prompts):
            for needle in forbidden:
                assert needle not in prompt, (
                    f"prompt {i} carried {needle!r} — the writing model can rewrite "
                    "anything it is shown"
                )
        for needle in forbidden:
            assert needle in out, f"{needle!r} never reached the report"
        # ZZ_RECON is deliberately NOT in the prompt assertion: reconciliation
        # notes legitimately reach synthesis via contested_notes (G-07). It must
        # still reach the deterministic section.
        assert ZZ_RECON in out

    @pytest.mark.asyncio
    async def test_gap_read_failure_is_stated_not_hidden(self, monkeypatch):
        _patch_gaps(monkeypatch, None)
        result = await _write(make_bundle(), RecordingAudited())
        out = result["output_text"]
        assert EN["gaps_unreadable"] in out
        assert EN["gaps_empty"] not in out, (
            "a database error must never be reported as 'no provider reported a gap'"
        )

    @pytest.mark.asyncio
    async def test_missing_report_sections_key_is_tolerated(self, monkeypatch):
        """Resume-path back-compat: a pre-15.2 synthesis_cache row replayed after
        deploy carries no `report_sections` key at all."""
        _patch_gaps(monkeypatch, {})
        result = await _write(make_bundle(with_report_sections=False), RecordingAudited())
        out = result["output_text"]
        assert EN["disputed_h"] in out
        assert EN["gaps_h"] in out
        assert EN["disputed_empty"] in out
        assert EN["gaps_empty"] in out

    @pytest.mark.asyncio
    async def test_two_renders_of_the_same_bundle_are_byte_identical_in_the_appended_region(
        self, monkeypatch
    ):
        _patch_gaps(monkeypatch, make_gap_rows())
        first = (await _write(make_bundle(), RecordingAudited()))["output_text"]
        second = (await _write(make_bundle(), RecordingAudited()))["output_text"]

        def _slice(text: str) -> str:
            return text[text.index(EN["disputed_h"]):text.index("## Verification")]

        assert _slice(first) == _slice(second)
        assert EN["disputed_h"] in _slice(first)

    def test_bundle_report_sections_is_json_serializable(self):
        """_write_output persists the bundle with json.dumps(..., default=str);
        anything on it that cannot survive that round-trip breaks the resume path."""
        payload = {"report_sections": make_report_sections_payload()}
        blob = json.dumps(payload, ensure_ascii=False, default=str)
        assert json.loads(blob) == payload
        assert ZZ_BRIEF in blob


# ---------------------------------------------------------------------------
# 21-33. THE DISCOVERY PROVENANCE CLAUSE (phase 15.6, D-W3-4).
#
# The workshop is FULLY AUTOMATIC (D5 / D-01) — nothing in it pauses for an
# operator — so a question the ENGINE raised cannot be gated on an approval
# click. Transparency is the governance instead: the client is told, in their own
# language and beside the quote and URL that provoked it, which questions they
# asked and which the evidence raised. It is also the Art. 12 audit trail.
#
# WHY THE HAND-OFF TEST IS THE ONE THAT MATTERS. The comment above the flag loop
# in `steps.py` records that this exact producer/consumer pair silently NEVER
# WORKED: `workshop._parse_orientation` emitted `{question, assumption,
# world_says, source_url}`, this section looked only for `note`/`text`/`finding`,
# every real flag rendered as "" and was dropped, and the whole subsection never
# appeared in ANY report. Both sides were tested. Both sides were green. Nobody
# drove the hand-off. So the tests below run the REAL
# `discovery_bracket.allocate_discovery` -> `annotate_conflicts` ->
# `build_disputed_and_changed` chain rather than hand-typing the annotated shape.
#
# `_annotation_key` exists for the same reason: everything except the ONE test
# that deliberately pins the key name DISCOVERS the key from the producer, so a
# rename in `discovery_bracket` cannot leave these tests passing over a report
# that lost its clause.
#
# Still zero LLM, zero DB, zero network: `discovery_bracket` is stdlib-only and
# every function in the chain is pure.
# ---------------------------------------------------------------------------

Q1_LABEL = "Q1 — how often do Dutch fuel prices move?"
Q2_LABEL = "Q2 — is coffee a margin driver?"


def make_orientation_conflicts() -> list[dict]:
    """`brief_conflicts` in the shape the ORIENTATION PASS emits — exactly the
    four keys `workshop._parse_orientation` writes, and no report-side key at all.

    Deliberately short: `_SECTION_ITEM_CHARS` bounds the rendered bullet, and a
    verbose fixture would truncate the very question text these tests assert on.
    """
    return [
        {
            "question": Q1_LABEL,
            "assumption": "ZZASSUME prices move weekly",
            "world_says": "ZZWORLD prices moved twice a day",
            "source_url": "https://x.test/pricing",
        },
        {
            "question": Q1_LABEL,
            "assumption": "ZZASSUME2 the network is company-operated",
            "world_says": "ZZWORLD2 most sites are dealer-owned",
            "source_url": "https://x.test/network",
        },
    ]


def make_unsourced_conflict() -> dict:
    """A real brief-vs-world flag that carries NO fetched http(s) source.

    "No source, no slot" (D-W3-4) means it can never become a research question —
    so the report must state the conflict and must NOT claim it was answered.
    """
    return {
        "question": Q2_LABEL,
        "assumption": "ZZASSUME3 coffee is a side line",
        "world_says": "ZZWORLD3 coffee carries the site margin",
        "source_url": "",
    }


def _dispatch(conflicts: list, labels: list, *, dispatched: slice = slice(None)):
    """Drive the REAL producer. Returns `(annotated_conflicts, questions)`.

    `dispatched` narrows which allocated questions are treated as ACTUALLY
    dispatched, which is how a rider shed for prompt space (plan 15.6-04's GAP A)
    or a cross-cutting question that lost its group to the mandate (GAP B) is
    modelled — `annotate_conflicts`' contract is that only the dispatched subset
    is annotated.
    """
    from nestor_pulse_sdk.pipeline.tribunal import discovery_bracket

    questions, _counts, _notes = discovery_bracket.allocate_discovery(conflicts, labels)
    annotated = discovery_bracket.annotate_conflicts(conflicts, questions[dispatched])
    return annotated, questions


def _annotation_key(annotated: dict, original: dict) -> str:
    """The ONE key the producer added — discovered, never typed.

    Also an assertion in its own right: `annotate_conflicts` must add exactly one
    key and must not drop or rewrite any of the producer's own four.
    """
    extra = set(annotated) - set(original)
    assert len(extra) == 1, f"annotate_conflicts added {sorted(extra)}, expected one key"
    assert all(annotated[k] == original[k] for k in original), "an original field changed"
    return extra.pop()


def _brief_subsection(rendered: str, strings: dict = EN) -> str:
    """The brief-vs-world subsection only. It is rendered LAST of the three."""
    return rendered[rendered.index(strings["sub_brief"]):]


class TestDiscoveryProvenanceClause:
    def test_a_dispatched_discovery_question_reaches_the_report_from_the_real_producer(
        self,
    ):
        """THE HAND-OFF. Producer -> annotator -> renderer, no hand-typed shape.

        This test contains no annotated-key literal on purpose: the key is
        whatever `discovery_bracket` writes, and the chain is what is under test.
        """
        from nestor_pulse_sdk.pipeline.tribunal import discovery_bracket

        conflicts = make_orientation_conflicts()
        annotated, questions = _dispatch(conflicts, [Q1_LABEL])
        assert questions, "the producer dispatched nothing — the test proves nothing"
        assert len(annotated) == len(conflicts), "length and order are the contract"

        out = build_disputed_and_changed(brief_conflicts=annotated, language="English")
        sub = _brief_subsection(out)

        # The clause fired, once per dispatched conflict, in English.
        assert sub.count(EN["brief_raised_question"]) == len(questions)

        # The ENGINE-FRAMED question text reached the client. Derived from the
        # producer rather than pinned as a phrase, so a reworded frame does not
        # make this test lie in either direction.
        framed = discovery_bracket.discovery_question_text(conflicts[0])
        assert framed, "the producer framed nothing"
        head = framed[:60]
        i_clause = sub.index(EN["brief_raised_question"])
        assert sub.index(head, i_clause) > i_clause, (
            "the framed question must follow the clause, not precede it"
        )

        # And the quote and URL that provoked it are still beside it.
        assert "ZZWORLD prices moved twice a day" in sub
        assert "https://x.test/pricing" in sub

    def test_the_report_reads_the_key_the_producer_writes(self):
        """The ONE test that pins the key name. Every other test discovers it.

        A rename on either side is a delivery defect that no rendering test would
        catch on its own — the clause would simply stop appearing.
        """
        conflicts = make_orientation_conflicts()
        annotated, questions = _dispatch(conflicts, [Q1_LABEL])
        assert questions
        key = _annotation_key(annotated[0], conflicts[0])
        assert key == "researched_as", key
        assert isinstance(annotated[0][key], str) and annotated[0][key]

    def test_the_clause_exists_in_all_four_report_languages(self):
        """An English sentence in a Dutch report is a delivery defect, not a nit."""
        conflicts = make_orientation_conflicts()[:1]
        annotated, questions = _dispatch(conflicts, [Q1_LABEL])
        assert questions

        for lang, key in (
            ("English", "english"), ("Dutch", "dutch"),
            ("German", "german"), ("French", "french"),
        ):
            strings = _SECTION_STRINGS[key]
            out = build_disputed_and_changed(brief_conflicts=annotated, language=lang)
            assert strings["brief_raised_question"] in out, lang
            for other in _SECTION_STRINGS:
                if other != key:
                    assert _SECTION_STRINGS[other]["brief_raised_question"] not in out, (
                        f"a {lang} report carried the {other} clause"
                    )

    def test_every_language_carries_the_same_section_string_keys(self):
        """Set-equality across the four, NOT a hardcoded list — so a fifth
        language added later without the clause fails loudly instead of shipping
        an English sentence in someone's report."""
        keysets = {lang: frozenset(v) for lang, v in _SECTION_STRINGS.items()}
        assert len(set(keysets.values())) == 1, {k: sorted(v) for k, v in keysets.items()}
        for lang, strings in _SECTION_STRINGS.items():
            clause = strings["brief_raised_question"]
            assert isinstance(clause, str) and clause.strip(), lang
        clauses = [v["brief_raised_question"] for v in _SECTION_STRINGS.values()]
        assert len(set(clauses)) == len(clauses), "two languages share one clause"

    def test_a_conflict_renders_once_not_twice(self):
        """ANNOTATE, NEVER APPEND. A second row would print the same conflict
        twice — once with the clause and once without — and a client reading it
        twice cannot tell which reading is the true one."""
        conflicts = make_orientation_conflicts()[:1]
        annotated, questions = _dispatch(conflicts, [Q1_LABEL])
        assert questions

        out = build_disputed_and_changed(brief_conflicts=annotated, language="English")
        sub = _brief_subsection(out)
        assert sub.count("*   ") == 1, sub
        assert sub.count(EN["brief_raised_question"]) == 1, sub
        # "The research found:" belongs to the CONSUMER's composed sentence only —
        # the producer's frame says "A source read during orientation says
        # instead:" — so counting it counts how many times this conflict was
        # composed into a bullet. NOT the assumption text: the framed question
        # legitimately quotes that back, so it appears twice on one correct row.
        assert sub.count("The research found:") == 1, (
            "the conflict was composed into more than one bullet"
        )

    def test_an_unsourced_conflict_renders_with_no_clause_because_it_was_never_researched(
        self,
    ):
        """"No source, no slot", seen from the report end. The evidence raised it,
        this run did not research it, and the report must not imply otherwise."""
        conflicts = [make_unsourced_conflict()]
        annotated, questions = _dispatch(conflicts, [Q2_LABEL])
        assert questions == [], "an unsourced conflict must never consume a slot"
        assert annotated[0] == conflicts[0], "nothing was annotated"

        out = build_disputed_and_changed(brief_conflicts=annotated, language="English")
        sub = _brief_subsection(out)
        # The conflict STILL reaches the client — it is simply not claimed as answered.
        assert "ZZWORLD3 coffee carries the site margin" in sub
        assert EN["brief_raised_question"] not in out
        assert sub.count("*   ") == 1

    def test_a_discovery_question_that_never_got_dispatched_renders_with_no_clause(self):
        """A rider shed for prompt space, or a cross-cutting question whose group
        lost its slot to the mandate: allocated, never dispatched. It must render
        as a plain brief-vs-world conflict."""
        conflicts = make_orientation_conflicts()
        annotated, questions = _dispatch(conflicts, [Q1_LABEL], dispatched=slice(0, 1))
        assert len(questions) == 2, "the fixture must allocate two to shed one"

        out = build_disputed_and_changed(brief_conflicts=annotated, language="English")
        sub = _brief_subsection(out)
        assert sub.count("*   ") == 2, "both conflicts render"
        assert sub.count(EN["brief_raised_question"]) == 1, (
            "only the DISPATCHED conflict may carry the clause"
        )
        # The shed one is still reported, with its own quote, and no claim of an answer.
        assert "ZZWORLD2 most sites are dealer-owned" in sub
        shed_bullet = [ln for ln in sub.splitlines() if "ZZWORLD2" in ln]
        assert len(shed_bullet) == 1
        assert EN["brief_raised_question"] not in shed_bullet[0]

    def test_the_clause_also_reaches_the_three_legacy_key_branches(self):
        """A producer that hands over `note` PLUS the annotation is legitimate, so
        the read runs for every dict entry, not only the composed branch."""
        conflicts = make_orientation_conflicts()[:1]
        annotated, _questions = _dispatch(conflicts, [Q1_LABEL])
        key = _annotation_key(annotated[0], conflicts[0])

        for legacy in ("note", "text", "finding"):
            item = {legacy: "ZZLEGACY a flag from an older producer.",
                    key: annotated[0][key]}
            out = build_disputed_and_changed(brief_conflicts=[item], language="Dutch")
            sub = _brief_subsection(out, _SECTION_STRINGS["dutch"])
            assert _SECTION_STRINGS["dutch"]["brief_raised_question"] in sub, legacy
            assert sub.count("*   ") == 1, legacy
            assert "ZZLEGACY" in sub, legacy

    def test_the_no_clause_rendering_is_byte_identical_to_before(self):
        """The exact bytes of an un-annotated conflict, pinned.

        Every conflict that never becomes a question renders through this path —
        the vast majority of them — so a future edit to the composed sentence must
        be a deliberate act with this expectation updated beside it.
        """
        conflict = {
            "question": Q1_LABEL,
            "assumption": "prices move weekly",
            "world_says": "prices moved twice a day",
            "source_url": "https://x.test/p",
        }
        out = build_disputed_and_changed(brief_conflicts=[conflict], language="English")
        assert out == (
            "## Disputed & changed\n"
            "\n"
            "### Where the brief did not match what the research found\n"
            "\n"
            "*   The brief assumes: prices move weekly The research found: "
            "prices moved twice a day (https://x.test/p)"
        ), repr(out)

    def test_a_non_string_annotation_renders_exactly_as_the_no_clause_case(self):
        """The producer only ever writes a `str`, so a non-string cannot have come
        from this engine. Rendering "the research answered it: ['x']" would assert
        a question was researched that was never even framed — and a hostile
        `__str__` reaching the sanitizer would cost the WHOLE section, because
        `_sanitize` calls `str()` outside its own try block."""
        conflicts = make_orientation_conflicts()[:1]
        annotated, _questions = _dispatch(conflicts, [Q1_LABEL])
        key = _annotation_key(annotated[0], conflicts[0])

        reference = build_disputed_and_changed(
            brief_conflicts=[dict(conflicts[0])], language="English"
        )

        class _Hostile:
            def __str__(self):
                raise RuntimeError("hostile __str__")

            def __bool__(self):
                raise RuntimeError("hostile __bool__")

        for value in ("", "   \n\t ", None, 0, False, [], ["x"], {"a": 1}, 7, 1.5,
                      b"x", _Hostile()):
            item = dict(conflicts[0])
            item[key] = value
            out = build_disputed_and_changed(brief_conflicts=[item], language="English")
            assert out == reference, f"{value!r} changed the rendering"
            assert EN["brief_raised_question"] not in out, repr(value)
            # The SECTION survived: this is not the swallow-everything placeholder.
            assert EN["disputed_empty"] not in out, repr(value)

    def test_an_annotation_with_no_conflict_to_attach_to_renders_nothing(self):
        """Half a conflict is not a conflict and is dropped today. The clause must
        not resurrect it as a bullet that names a question and no disagreement."""
        conflicts = make_orientation_conflicts()[:1]
        annotated, _questions = _dispatch(conflicts, [Q1_LABEL])
        key = _annotation_key(annotated[0], conflicts[0])

        for item in (
            {"assumption": "ZZHALF an assumption with nothing against it",
             key: "ZZORPHAN a framed question."},
            {key: "ZZORPHAN a framed question."},
        ):
            out = build_disputed_and_changed(brief_conflicts=[item], language="English")
            assert "ZZORPHAN" not in out, item
            assert EN["brief_raised_question"] not in out, item
            assert EN["disputed_empty"] in out, "nothing renderable -> the placeholder"

    def test_the_item_cap_still_bounds_the_annotated_bullet(self):
        """T-15.6-21. The frame is engine-authored but the fields inside it are
        model-authored. The bound wins over the clause, deliberately: an oversized
        conflict loses the clause to truncation rather than escaping the cap."""
        conflicts = make_orientation_conflicts()[:1]
        annotated, _questions = _dispatch(conflicts, [Q1_LABEL])
        key = _annotation_key(annotated[0], conflicts[0])

        item = dict(conflicts[0])
        item["assumption"] = "L" * 5000
        item[key] = "ZZCUT the framed question."
        out = build_disputed_and_changed(brief_conflicts=[item], language="English")
        bullets = [ln for ln in out.splitlines() if ln.startswith("*   ")]
        assert len(bullets) == 1
        assert len(bullets[0]) <= _SECTION_ITEM_CHARS + 8, len(bullets[0])
        assert bullets[0].endswith("…"), "the cut must be visible"
        assert "ZZCUT" not in out, "the cap must win over the clause"

    def test_the_annotated_section_is_byte_stable_across_two_renders(self):
        """Same input, same bytes — no clock, no model, no set iteration. The
        clause must not have introduced any of the three."""
        first_conflicts = make_orientation_conflicts()
        second_conflicts = make_orientation_conflicts()
        first, _ = _dispatch(first_conflicts, [Q1_LABEL])
        second, _ = _dispatch(second_conflicts, [Q1_LABEL])
        a = build_disputed_and_changed(brief_conflicts=first, language="Dutch")
        b = build_disputed_and_changed(brief_conflicts=second, language="Dutch")
        assert a == b
        assert _SECTION_STRINGS["dutch"]["brief_raised_question"] in a
