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
    _build_distiller_prompt,
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


# ---------------------------------------------------------------------------
# 4. The prompt contract -- THE COVERAGE THAT DID NOT EXIST
# ---------------------------------------------------------------------------

PROMPT_CONTRACT = "FACET ||| CLAIM_TEXT ||| EVIDENCE"
MINIMAL_REPORTS = [("gemini", {"status": "success", "report": "Some research prose."})]
MINIMAL_LABELS = [FACET]

# The exact canned-response shape `test_claim_distiller.py::GOOD_RESPONSE` uses:
# columns separated by a REAL TAB. The prompt no longer names the tab; the
# parser must still accept it, and that is what the round-trip below says.
TAB_CANNED_RESPONSE = (
    f"{FACET}\tCronos holds ~18% of Belgian IT services market by revenue in 2024.\n"
    f"{FACET}\tCapgemini Belgium expanded its public-sector practice by 30% YoY.\n"
)


class TestDistillerPromptContract:
    """The assertion that was BELIEVED to exist and did not.

    `_build_distiller_prompt`'s docstring used to state that
    `test_claim_distiller.py` and `test_distiller_coverage.py` pin this prompt
    BYTE-IDENTICALLY. **NEITHER FILE PINS IT, AND NEITHER EVER DID** — verified
    by reading both on 2026-07-29. `test_distiller_coverage.py` asserts nothing
    at all about the prompt; `test_claim_distiller.py` matches only the
    `### Provider:` header its fake client routes on. So before this class
    existed, changing the separator contract — or reintroducing the `<TAB>`
    placeholder that cost V-01 278 claims — turned NOTHING red, and a green
    engine gate proved nothing whatsoever about this prompt.

    This class is that missing coverage. Assertions 1 and 2 are separate named
    tests on purpose: a failure must say WHICH half of the contract broke, not
    merely that "the prompt changed".
    """

    def test_prompt_states_the_pipe_contract(self):
        """Assertion 1: the prompt tells the model the format it must emit."""
        prompt = _build_distiller_prompt(MINIMAL_REPORTS, MINIMAL_LABELS)
        assert PROMPT_CONTRACT in prompt, (
            f"the built prompt must state {PROMPT_CONTRACT!r}; without it the "
            f"model is guessing at the column separator"
        )

    def test_prompt_contains_no_literal_TAB_placeholder(self):
        """Assertion 2: THE regression that cost 278 claims.

        A placeholder describing a control character is a token the model can
        render as characters. It did, twice in one batch at temperature 0.0,
        and `_parse_distiller_response` discarded every claim in both
        responses. Never name an invisible character in a prompt.
        """
        prompt = _build_distiller_prompt(MINIMAL_REPORTS, MINIMAL_LABELS)
        assert "<TAB>" not in prompt, (
            "the distiller prompt contains the literal placeholder <TAB>. This "
            "is the exact V-01 defect: the model copies those five characters "
            "back as data and every claim in the response is discarded. Use "
            f"{PROMPT_CONTRACT!r}."
        )

    @pytest.mark.parametrize("variant", ["full_extraction", "language", "both"])
    def test_the_optional_rule_fragments_cannot_smuggle_the_placeholder_back(
        self, variant: str
    ):
        """Assertion 3: D-14 and the language rule are covered too.

        Both are empty-string-by-default fragments, so a `<TAB>` added to
        EITHER would be invisible in the default prompt the other tests build.
        """
        kwargs: dict = {}
        language = ""
        if variant in ("full_extraction", "both"):
            kwargs["full_extraction"] = True
        if variant in ("language", "both"):
            language = "Nederlands"

        prompt = _build_distiller_prompt(
            MINIMAL_REPORTS, MINIMAL_LABELS, language, **kwargs
        )
        assert PROMPT_CONTRACT in prompt, f"{variant}: contract missing"
        assert "<TAB>" not in prompt, (
            f"{variant}: the <TAB> placeholder reached the prompt through an "
            f"optional rule fragment"
        )

    def test_a_real_tab_response_still_round_trips(self):
        """Assertion 4: the prompt stopped naming the tab; the parser still takes it.

        This is what keeps V-01's already-working 43- and 143-claim blobs
        working, and it is deliberately independent of the new separators — it
        passes against the OLD tab-only splitter too. Its teeth come from the
        companion proof that deleting "\\t" from `_DISTILLER_SEPARATORS` turns
        it RED.
        """
        claims = _parse_distiller_response(
            TAB_CANNED_RESPONSE, MINIMAL_LABELS, provider="gemini"
        )
        assert len(claims) == 2, (
            f"a tab-separated canned response must still parse to its 2 claims, "
            f"got {len(claims)}: {claims!r}"
        )
        assert all(c["facet"] == FACET for c in claims)
        assert all(len(c["text"]) >= 10 for c in claims)
        assert claims[0]["text"].startswith("Cronos holds")
