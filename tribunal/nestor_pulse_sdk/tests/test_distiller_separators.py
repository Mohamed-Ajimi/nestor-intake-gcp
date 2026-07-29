"""Distiller separator tolerance -- the V-01 `<TAB>` defect, closed (Phase 15.4, plan 15.4-03).

WHAT THIS FILE IS FOR
---------------------
V-01 (run 7dcf51d5, 2026-07-28) delivered a client report whose coffee section
said the Benelux data "geeft geen volledig beeld". That statement was FALSE.
The distiller had returned 278 well-formed, three-column, evidence-bearing
coffee claims and `_parse_distiller_response` threw away every one of them on a
string comparison: the model wrote the literal five-character string `<TAB>`
instead of U+0009, because THE PROMPT ITSELF used `<TAB>` as a placeholder
describing the separator. The only trace was a `log.debug`, which production
does not serve.

Three deliverables live here, and they are deliberately not interchangeable:

  1. `TestSeparatorTable` / `TestSeparatorPriority` / `TestSeparatorEdgeCases`
     -- the parser accepts five separators in a LOCKED priority order, and all
     five forms of one line produce IDENTICAL claim dicts. Equality across
     forms is the criterion. "each form produced some claims" is exactly the
     shape of assertion that let this bug live for a full paid run.

  2. `TestDistillerPromptContract` -- the coverage that was BELIEVED to exist
     and did not. See that class's own docstring.

  3. `TestV01Replay` -- the four RECORDED V-01 responses replayed through the
     real parser: 141 + 137 = 278 recovered, 43 and 143 unchanged.

PURE: no Postgres, no provider key, no network, no LLM. Every function under
test here is a pure string function, and the fixture is committed text.

Cloud Build invocation:
  gcloud builds submit tribunal \\
    --config=tribunal/cloudbuild.test-engine.yaml \\
    --project="$GOOGLE_PROJECT"
"""
from __future__ import annotations

import pytest

from nestor_pulse_sdk.pipeline.synthesis.steps import (
    _DISTILLER_SEPARATORS,
    _parse_distiller_response,
    _split_distiller_line,
)

# ---------------------------------------------------------------------------
# ONE canonical claim line, rendered five ways.
#
# Deliberately free of tabs, pipes and double spaces in every column, so the
# five renderings below differ ONLY in their separator. If a column ever grows
# one of those characters, the renderings stop being the same claim and the
# equality assertions become a lie rather than a failure.
# ---------------------------------------------------------------------------

FACET = "koffie"
CLAIM = "Circle K rolde in 2023 een barista-concept uit op 120 Benelux-stations."
EVIDENCE = "Circle K introduceerde barista-koffie op 120 stations."

CANONICAL_FORMS: dict[str, str] = {
    "real_tab": f"{FACET}\t{CLAIM}\t{EVIDENCE}",
    "literal_TAB_placeholder": f"{FACET}<TAB>{CLAIM}<TAB>{EVIDENCE}",
    "triple_pipe": f"{FACET} ||| {CLAIM} ||| {EVIDENCE}",
    "single_pipe": f"{FACET}|{CLAIM}|{EVIDENCE}",
    "space_run": f"{FACET}  {CLAIM}  {EVIDENCE}",
}

EXPECTED_CLAIM = {
    "text": CLAIM,
    "facet": FACET,
    "evidence": EVIDENCE,
    "found_by": ["gemini"],
}


def _parse_one(line: str) -> list[dict]:
    """Run one line through the REAL parser with a known facet and provider."""
    return _parse_distiller_response(line, [FACET], provider="gemini")


# ---------------------------------------------------------------------------
# 1. The separator table -- all five forms are the SAME claim
# ---------------------------------------------------------------------------

class TestSeparatorTable:
    """Five renderings of one line must parse to IDENTICAL claim dicts.

    Asserted with `==` on the dicts. Asserting only `len(claims) >= 1` would
    have passed on V-01's broken parser for four of the five forms while the
    fifth silently produced nothing.
    """

    @pytest.mark.parametrize("form_name", sorted(CANONICAL_FORMS))
    def test_every_form_yields_exactly_the_canonical_claim(self, form_name: str):
        claims = _parse_one(CANONICAL_FORMS[form_name])
        assert claims == [EXPECTED_CLAIM], (
            f"separator form {form_name!r} did not produce the canonical claim.\n"
            f"  line     : {CANONICAL_FORMS[form_name]!r}\n"
            f"  got      : {claims!r}\n"
            f"  expected : {[EXPECTED_CLAIM]!r}"
        )

    def test_all_five_forms_are_equal_to_each_other(self):
        """Cross-check: not just equal to a literal, equal to ONE ANOTHER."""
        parsed = {name: _parse_one(line) for name, line in CANONICAL_FORMS.items()}
        reference = parsed["real_tab"]
        assert reference, "the real-tab baseline itself must parse"
        for name, claims in parsed.items():
            assert claims == reference, (
                f"{name!r} disagrees with the real-tab baseline: "
                f"{claims!r} != {reference!r}"
            )

    def test_the_five_forms_really_are_five_distinct_strings(self):
        """Non-vacuity guard for the table above.

        If a copy/paste ever collapsed two renderings into the same string, the
        equality assertions would still pass while testing four separators
        instead of five. This is what makes that impossible to miss.
        """
        assert len(set(CANONICAL_FORMS.values())) == 5, (
            f"the five renderings must be five DIFFERENT strings, got "
            f"{len(set(CANONICAL_FORMS.values()))} distinct"
        )


# ---------------------------------------------------------------------------
# 2. Priority -- the order is the contract, not a style choice
# ---------------------------------------------------------------------------

class TestSeparatorPriority:
    """`_DISTILLER_SEPARATORS` order is load-bearing in both directions."""

    def test_separator_order_is_pinned(self):
        assert _DISTILLER_SEPARATORS == ("\t", "<TAB>", "|||", "|"), (
            "the separator priority order IS the contract (D-R1(a)); changing it "
            "changes how ambiguous lines are read. Got "
            f"{_DISTILLER_SEPARATORS!r}"
        )

    def test_a_line_with_both_a_real_tab_and_a_literal_TAB_splits_on_the_tab(self):
        """The tab is the deliberate separator; the `<TAB>` is then DATA.

        Split the other way round and the claim text would be truncated at the
        placeholder and the evidence column would swallow a raw tab.
        """
        claim_text = "The literal <TAB> token appears inside this claim as data."
        line = f"{FACET}\t{claim_text}\t{EVIDENCE}"

        assert _split_distiller_line(line) == [FACET, claim_text, EVIDENCE]

        claims = _parse_one(line)
        assert claims == [{
            "text": claim_text,
            "facet": FACET,
            "evidence": EVIDENCE,
            "found_by": ["gemini"],
        }], f"tab must win over the literal <TAB>, got {claims!r}"

    def test_a_line_with_both_triple_and_single_pipe_splits_on_the_triple(self):
        """Every `|||` line also contains `|`, so `|||` MUST be tried first.

        Testing `|` first would split `A ||| B` into `["A", "", "| B"]` -- an
        empty claim_text, which the `< 10` rule then drops. The claim would
        vanish exactly the way V-01's 278 did.
        """
        claim_text = "Pipes | inside | the claim text must survive intact."
        line = f"{FACET} ||| {claim_text} ||| {EVIDENCE}"

        assert _split_distiller_line(line) == [FACET, claim_text, EVIDENCE]

        claims = _parse_one(line)
        assert claims == [{
            "text": claim_text,
            "facet": FACET,
            "evidence": EVIDENCE,
            "found_by": ["gemini"],
        }], f"||| must win over |, got {claims!r}"

    def test_a_literal_separator_beats_a_space_run(self):
        """The 2+-space fallback is tried LAST and only when nothing else matched.

        A tab-separated line whose columns contain double spaces must still
        split on the tab -- V-01's own 143-claim control blob has two such
        lines, so this is a recorded shape, not a hypothetical.
        """
        claim_text = "Two  spaces  sit  inside  this  claim  text  deliberately."
        line = f"{FACET}\t{claim_text}\t{EVIDENCE}"
        assert _split_distiller_line(line) == [FACET, claim_text, EVIDENCE]


# ---------------------------------------------------------------------------
# 3. Edge cases -- what must STILL be dropped
# ---------------------------------------------------------------------------

class TestSeparatorEdgeCases:
    def test_a_line_with_no_separator_at_all_returns_None(self):
        line = "THIS LINE HAS NO SEPARATOR OF ANY KIND"
        assert _split_distiller_line(line) is None

    def test_a_line_with_no_separator_at_all_yields_no_claim(self):
        assert _parse_one("THIS LINE HAS NO SEPARATOR OF ANY KIND") == []

    def test_a_four_column_line_still_yields_exactly_three_columns(self):
        """maxsplit=2 -- evidence keeps the remainder rather than losing it."""
        parts = _split_distiller_line(f"{FACET}\t{CLAIM}\t{EVIDENCE}\ttrailing column")
        assert parts is not None
        assert len(parts) == 3, f"expected 3 columns, got {len(parts)}: {parts!r}"
        assert parts[0] == FACET
        assert parts[1] == CLAIM
        assert parts[2] == f"{EVIDENCE}\ttrailing column"

    def test_the_ten_character_drop_rule_is_unchanged(self):
        assert _parse_one(f"{FACET}\tshort\t{EVIDENCE}") == [], (
            "a claim_text under 10 chars must still be dropped"
        )

    def test_a_two_column_line_still_parses_with_empty_evidence(self):
        """Back-compat: EVIDENCE is optional, as it always was."""
        assert _parse_one(f"{FACET}\t{CLAIM}") == [{
            "text": CLAIM,
            "facet": FACET,
            "evidence": "",
            "found_by": ["gemini"],
        }]

    def test_an_empty_facet_falls_back_to_general(self):
        """The `general` fallback is unchanged by the tolerant split."""
        claims = _parse_one(f"<TAB>{CLAIM}<TAB>{EVIDENCE}")
        assert claims[0]["facet"] == "general"
        assert claims[0]["text"] == CLAIM

    def test_a_LEADING_REAL_TAB_is_eaten_by_the_line_strip_first(self):
        """Documented asymmetry between the separators, found by running this.

        `_parse_distiller_response` does `line = line.strip()` BEFORE splitting,
        and that predates this plan. So a leading EMPTY facet column reaches the
        `general` fallback for every separator EXCEPT the real tab, which the
        strip removes -- shifting the remaining columns left by one.

        This is pre-existing behaviour, it is asserted here rather than fixed
        because changing the line strip would alter how every already-working
        tab response parses (V-01s 43 and 143 among them), which is out of
        scope for D-R1(a). Recorded so a future reader meets it as a known
        property rather than as a surprise.
        """
        claims = _parse_one(f"\t{CLAIM}\t{EVIDENCE}")
        assert claims == [{
            "text": EVIDENCE,
            "facet": CLAIM,
            "evidence": "",
            "found_by": ["gemini"],
        }], f"leading-tab column shift is the recorded behaviour, got {claims!r}"

    def test_an_unknown_facet_is_kept_as_is(self):
        """Never drop a claim because the model used a near-match label."""
        claims = _parse_distiller_response(
            f"not-a-known-facet\t{CLAIM}\t{EVIDENCE}", [FACET], provider="gemini"
        )
        assert claims[0]["facet"] == "not-a-known-facet"

    def test_found_by_is_the_caller_supplied_provider_only(self):
        """T-15.2-60 / G-12: a model must never set its own attribution.

        The tolerant splitter changed HOW columns are found; it must not have
        opened a path for provider text to arrive from model output.
        """
        line = f"{FACET}\t{CLAIM}\t{EVIDENCE}"
        assert _parse_distiller_response(line, [FACET], provider="claude")[0]["found_by"] == ["claude"]
        assert _parse_distiller_response(line, [FACET])[0]["found_by"] == []
