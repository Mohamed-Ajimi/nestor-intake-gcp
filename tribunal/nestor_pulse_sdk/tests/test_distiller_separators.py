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

  4. `TestReturnedLinesKeptNothing` (plan 15.4-08, D-R1(c)) -- the WARNING that
     would have caught V-01 on day one. The parser fix above stops THIS
     failure; the warning is what makes the NEXT one visible, because the only
     trace of the 278 was a `log.debug` and production does not serve DEBUG.
     Asserted on the RECORD CONTENT, never on "a warning happened".

PURE: no Postgres, no provider key, no network, no LLM. Every function under
test here is a pure string function or `claim_distiller` driven through a
hand-written duck-typed fake client, and the fixture is committed text.

Cloud Build invocation:
  gcloud builds submit tribunal \\
    --config=tribunal/cloudbuild.test-engine.yaml \\
    --project="$GOOGLE_PROJECT"
"""
from __future__ import annotations

import logging
import uuid

import pytest

from nestor_pulse_sdk.pipeline.synthesis import steps as steps_module
from nestor_pulse_sdk.pipeline.synthesis.steps import (
    _DISTILLER_SEPARATORS,
    _build_distiller_prompt,
    _parse_distiller_response,
    _split_distiller_line,
    claim_distiller,
)
from nestor_pulse_sdk.tests.fixtures.run_7dcf51d5.loader import (
    COFFEE_EXPECTED_CLAIMS,
    DISTILLER_CALLS,
    load_all,
    load_distiller_response,
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


# ---------------------------------------------------------------------------
# 5. The replay -- V-01's REAL responses: 278 recovered, 43 and 143 preserved
# ---------------------------------------------------------------------------

def _parse_with_old_tab_only_splitter(
    text: str, focus_area_labels: list[str], *, provider: str = ""
) -> list[dict]:
    """The PRE-15.4-03 parser, reproduced here as the regression oracle.

    Verbatim reproduction of the loop `_parse_distiller_response` used to run:
    a bare `if "\\t" not in line` drop, then `line.split("\\t", 2)`, then the
    same downstream rules. It lives in the test rather than in production
    because dead code kept alive for a test's benefit is how the next reader
    ends up unsure which branch is real.

    Do not "improve" it. Its only job is to reproduce the behaviour that put a
    false statement in a client report, so the fix can be shown to change
    exactly the two calls it should and neither of the other two.
    """
    valid_facets = set(focus_area_labels) if focus_area_labels else set()
    claims: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if "\t" not in line:  # <- THE DEFECT
            continue
        parts = line.split("\t", 2)
        facet = parts[0].strip()
        claim_text = parts[1].strip() if len(parts) > 1 else ""
        evidence = parts[2].strip() if len(parts) > 2 else ""
        if not claim_text or len(claim_text) < 10:
            continue
        if not facet:
            facet = "general"
        elif valid_facets and facet not in valid_facets:
            pass
        claims.append({
            "text": claim_text,
            "facet": facet,
            "evidence": evidence,
            "found_by": [provider] if provider else [],
        })
    return claims


#: The two calls whose claims V-01 lost, and the two that already worked.
COFFEE_CALLS = tuple(c for c in DISTILLER_CALLS if c.separator == "<TAB>")
CONTROL_CALLS = tuple(c for c in DISTILLER_CALLS if c.separator == "\t")


def _replay(call) -> list[dict]:
    return _parse_distiller_response(
        load_distiller_response(call.audit_prefix), [], provider="gemini"
    )


class TestV01Replay:
    """The four RECORDED distiller responses from run 7dcf51d5, 2026-07-28.

    Real model output, pulled from the per-call audit bucket and committed by
    plan 15.4-01. The counts below are RECORDED FACTS reconciled against
    `docs/tribunal-run-reports/run-20260728-7dcf51d5-DIAGNOSTICS.md` at pull
    time. THEY ARE NOT TARGETS. If a parser change makes one of them
    unreachable, the parser is wrong -- never the manifest and never the
    fixture.
    """

    def test_the_fixture_still_holds_all_four_calls(self):
        """A short fixture must FAIL the replay, not pass it vacuously.

        `load_all` raises on a miscount; this asserts the corpus size directly
        as well, so a replay that iterates nothing cannot report green.
        """
        assert len(load_all()) == 4
        assert len(DISTILLER_CALLS) == 4
        assert len(COFFEE_CALLS) == 2
        assert len(CONTROL_CALLS) == 2

    @pytest.mark.parametrize("call", DISTILLER_CALLS, ids=lambda c: c.audit_prefix)
    def test_recorded_call_yields_its_recorded_claim_count(self, call):
        """141, 137, 43, 143 -- four numbers, asserted individually."""
        claims = _replay(call)
        assert len(claims) == call.expected_claims, (
            f"{call.audit_prefix} (idx {call.report_idx}, separator "
            f"{call.separator!r}) must replay to {call.expected_claims} claims, "
            f"got {len(claims)}"
        )

    def test_the_two_coffee_calls_sum_to_the_278_the_client_never_saw(self):
        counts = [len(_replay(c)) for c in COFFEE_CALLS]
        assert counts == [141, 137], f"expected [141, 137], got {counts}"
        assert sum(counts) == COFFEE_EXPECTED_CLAIMS == 278, (
            f"the recovered coffee total must be {COFFEE_EXPECTED_CLAIMS}, "
            f"got {sum(counts)}"
        )

    @pytest.mark.parametrize("call", DISTILLER_CALLS, ids=lambda c: c.audit_prefix)
    def test_every_recovered_claim_carries_evidence(self, call):
        """A count alone can be satisfied by garbage.

        All 278 were three-column and evidence-bearing, which is why they would
        have passed every downstream filter had they ever been parsed.
        """
        empty = [c for c in _replay(call) if not c["evidence"]]
        assert not empty, (
            f"{call.audit_prefix}: {len(empty)} claim(s) recovered with no "
            f"evidence column; first: {empty[:1]}"
        )

    @pytest.mark.parametrize("call", DISTILLER_CALLS, ids=lambda c: c.audit_prefix)
    def test_every_recovered_claim_passes_the_production_length_filter(self, call):
        short = [c for c in _replay(call) if len(c["text"]) < 10]
        assert not short, (
            f"{call.audit_prefix}: {len(short)} claim(s) under 10 chars; "
            f"first: {short[:1]}"
        )

    @pytest.mark.parametrize("call", CONTROL_CALLS, ids=lambda c: c.audit_prefix)
    def test_the_already_working_calls_are_unchanged_by_the_fix(self, call):
        """THE NON-REGRESSION HALF, and it is not optional.

        A separator fix that recovers 278 while quietly changing 43 or 143 is a
        regression, not a fix, and only this control pair can show it. Compared
        against the verbatim old parser, claim list to claim list -- not counts.
        """
        new = _replay(call)
        old = _parse_with_old_tab_only_splitter(
            load_distiller_response(call.audit_prefix), [], provider="gemini"
        )
        assert new == old, (
            f"{call.audit_prefix}: the tolerant splitter changed a response that "
            f"already parsed correctly. {len(old)} claims before, {len(new)} after."
        )
        assert len(new) == call.expected_claims

    @pytest.mark.parametrize("call", COFFEE_CALLS, ids=lambda c: c.audit_prefix)
    def test_the_old_parser_recovered_nothing_from_the_coffee_calls(self, call):
        """The defect itself, reproduced against the real response.

        This is what makes the assertions above a regression proof rather than
        a description: under the parser that shipped, these two responses --
        141 and 137 well-formed claims of real Benelux coffee material --
        yielded ZERO, and the delivered report then told the client the data
        gave no complete picture.
        """
        old = _parse_with_old_tab_only_splitter(
            load_distiller_response(call.audit_prefix), [], provider="gemini"
        )
        assert old == [], (
            f"{call.audit_prefix} is only a regression fixture if the OLD parser "
            f"dropped it entirely; it returned {len(old)} claims"
        )

    @pytest.mark.parametrize("call", DISTILLER_CALLS, ids=lambda c: c.audit_prefix)
    def test_focus_area_labels_never_gate_the_claim_list(self, call):
        """`focus_area_labels` drives a log line, never a drop -- asserted, not assumed.

        Worth pinning here because the facet column in these RECORDED responses
        is a research question truncated to ~120 chars, and one call even
        misspells its own echo of it ("en/or" for "en/of"). If an unknown facet
        could gate a claim, that typo alone would silently cost two claims.
        """
        text = load_distiller_response(call.audit_prefix)
        no_labels = _parse_distiller_response(text, [], provider="gemini")
        wrong_labels = _parse_distiller_response(
            text, ["convenience", "general"], provider="gemini"
        )
        assert no_labels == wrong_labels, (
            f"{call.audit_prefix}: the focus-area label list changed the parsed "
            f"claims ({len(no_labels)} vs {len(wrong_labels)})"
        )


# ---------------------------------------------------------------------------
# 6. D-R1(c) -- returned lines, kept NOTHING, and SAID SO at WARNING
#
# The parser fix above closes the `<TAB>` hole. This section closes the reason
# nobody noticed it for a month: the drop was a `log.debug`, and per D-V01-6
# stdlib logging in this pipeline is served by Python's `lastResort` handler,
# which starts at WARNING. DEBUG and INFO DO NOT EXIST IN PRODUCTION.
#
# Every assertion below is on the record CONTENT -- provider, line count, first
# line. "A warning was logged" is precisely the shape of assertion that lets a
# useless warning survive review, which is the other half of what went wrong on
# V-01 (see section 7).
# ---------------------------------------------------------------------------

#: Substring identifying the D-R1(c) record among everything else claim_distiller
#: logs. Deliberately a phrase from the message rather than a code, so a rewrite
#: that guts the message has to notice this test.
DROP_MARKER = "NOTHING was kept"

#: Five lines carrying NO separator of any accepted kind: no tab, no `<TAB>`,
#: no `|`, no `|||`, and -- the easy one to get wrong -- no run of two or more
#: spaces anywhere, since that is the last-resort separator. Single spaces only.
FIVE_UNPARSEABLE_LINES = "\n".join([
    "De koffieacceptatie bij Benelux-tankstations blijft achter op de verwachting.",
    "Shell zet in op een hybride model van private label en barista-concepten.",
    "Circle K rolde een barista-concept uit op honderdtwintig stations.",
    "TotalEnergies koos voor een franchisemodel met een externe koffieketen.",
    "Q8 rapporteerde een stijging van de koffieomzet in het segment.",
])

#: One line that DOES parse, in the current prompt contract.
ONE_GOOD_LINE = f"{FACET} ||| {CLAIM} ||| {EVIDENCE}"

MISSION_BRIEF_ONE_FACET = {"focus_areas": [{"focus_area": FACET}]}

#: Short enough to be a single `_chunk_text` chunk, so one report == one distiller
#: call == at most one D-R1(c) record. `exactly one` is an assertion in this
#: section, and it would be untestable against a chunked report.
SHORT_REPORT = "Korte onderzoekstekst over koffie bij tankstations in de Benelux."


class _CannedResponse:
    """The `.text` half of a google-genai response object."""

    def __init__(self, text: str) -> None:
        self.text = text


class CannedAudited:
    """Duck-typed `AuditedLLMClient` returning one canned body per provider.

    Keyed by provider name because that is the ONLY per-report signal visible in
    the built prompt (`### Provider: <name>`) -- the report `_angle` is not
    rendered into it. Section 7 depends on that routing to give one facet claims
    and another none.
    """

    def __init__(self, by_provider: dict[str, str], default: str = "") -> None:
        self.by_provider = by_provider
        self.default = default
        self.calls: list[str] = []

    async def gemini_generate(self, *, run_id, tenant_id, model, contents, **kwargs):
        self.calls.append(contents)
        import re as _re

        m = _re.search(r"### Provider: (\w+)", contents)
        name = m.group(1) if m else ""
        return _CannedResponse(self.by_provider.get(name, self.default))


async def _distil(reports, response_by_provider, mission_brief=None):
    """Run the REAL `claim_distiller` over canned responses. Returns its claims."""
    audited = CannedAudited(response_by_provider)
    return await claim_distiller(
        provider_reports=reports,
        mission_brief=mission_brief or MISSION_BRIEF_ONE_FACET,
        audited=audited,
        run_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
    )


def _drop_records(caplog) -> list[logging.LogRecord]:
    """Only the D-R1(c) records -- claim_distiller logs several other things."""
    return [r for r in caplog.records if DROP_MARKER in r.getMessage()]


class TestReturnedLinesKeptNothing:
    """D-R1(c): the model returned output and the parser kept none of it.

    That is a PARSE-CONTRACT FAILURE and it must not read like an empty research
    result -- on V-01 it was reported as one, in a paid client deliverable.
    """

    async def test_five_unparseable_lines_produce_exactly_one_loud_warning(self, caplog):
        with caplog.at_level(logging.WARNING):
            claims = await _distil(
                [("gemini", {"report": SHORT_REPORT, "_angle": FACET})],
                {"gemini": FIVE_UNPARSEABLE_LINES},
            )

        assert claims == [], "the canned lines must genuinely parse to nothing"

        records = _drop_records(caplog)
        assert len(records) == 1, (
            f"expected exactly ONE D-R1(c) record, got {len(records)}: "
            f"{[r.getMessage() for r in records]}"
        )
        record = records[0]
        message = record.getMessage()

        # Four assertions, each named in the failure text. Asserting only that a
        # warning was emitted would pass against a message saying nothing useful.
        assert record.levelno == logging.WARNING, (
            f"D-R1(c) must be WARNING -- production serves nothing below it "
            f"(D-V01-6). Got {record.levelname}."
        )
        assert "gemini" in message, f"the provider must be named: {message!r}"
        assert "5" in message, f"the non-empty line count must appear: {message!r}"
        assert "De koffieacceptatie bij Benelux" in message, (
            f"the first offending line must appear so the shape can be "
            f"diagnosed without the audit bucket: {message!r}"
        )

    async def test_a_response_that_parses_produces_no_such_warning(self, caplog):
        """The control. A warning that also fires on success is noise."""
        with caplog.at_level(logging.WARNING):
            claims = await _distil(
                [("gemini", {"report": SHORT_REPORT, "_angle": FACET})],
                {"gemini": ONE_GOOD_LINE},
            )

        assert claims == [EXPECTED_CLAIM], (
            f"the good line must still produce its claim unchanged, got {claims!r}"
        )
        assert _drop_records(caplog) == [], (
            "a parsed response must NOT warn about dropping everything"
        )

    async def test_empty_text_produces_no_such_warning(self, caplog):
        """Nothing came back at all -- a different event, already covered.

        The distinction is the whole point of the message: `returned output and
        kept nothing` is a parser bug, `returned nothing` is a provider/research
        outcome. Collapsing them would recreate the V-01 misreading.
        """
        with caplog.at_level(logging.WARNING):
            claims = await _distil(
                [("gemini", {"report": SHORT_REPORT, "_angle": FACET})],
                {"gemini": ""},
            )

        assert claims == []
        assert _drop_records(caplog) == [], (
            "an empty response must not be reported as a parse failure"
        )

    async def test_the_first_line_is_truncated_to_200_characters(self, caplog):
        """T-15.4-19: untrusted model output, bounded before it reaches a log.

        V-01s real lines run to several hundred characters and a chunk can be
        60k. Logging one verbatim is a denial of service the operator inflicts
        on themselves.
        """
        # Deliberately NON-REPEATING. A repeated phrase makes the `not in`
        # assertion below vacuous the other way round: a slice taken past
        # character 200 would also occur before it, and the test would go red
        # against a correct truncation.
        long_line = " ".join(f"woord{i:03d}" for i in range(120))  # ~1080 chars
        assert len(long_line) > 400
        assert long_line[220:300] not in long_line[:200], (
            "the fixture must not repeat, or the truncation assertion is a lie"
        )

        with caplog.at_level(logging.WARNING):
            await _distil(
                [("gemini", {"report": SHORT_REPORT, "_angle": FACET})],
                {"gemini": long_line},
            )

        records = _drop_records(caplog)
        assert len(records) == 1
        message = records[0].getMessage()
        assert long_line[:150] in message, (
            "the truncated prefix must survive -- a truncation that logs nothing "
            "useful is as bad as no log at all"
        )
        assert long_line[220:300] not in message, (
            f"the line was NOT truncated at 200 chars; the record carries "
            f"{len(message)} chars"
        )

    async def test_the_v01_coffee_blob_under_the_old_parser_fires_this_warning(
        self, caplog, monkeypatch
    ):
        """THE DEMONSTRATION: this one line would have caught V-01 on day one.

        The parser is reverted to the tab-only version IN THE TEST ONLY (the
        same `_parse_with_old_tab_only_splitter` the replay section uses as its
        oracle) and fed a RECORDED coffee response. That is exactly the
        production state of 2026-07-28: 141 well-formed claims returned, zero
        kept, and the only record a `log.debug` nobody could see.

        With D-R1(c) in place that same state emits a WARNING naming the
        provider, the 141 lines, and the first line of the response.
        """
        call = COFFEE_CALLS[0]
        assert call.non_empty_lines == 141, (
            f"fixture manifest changed under this test: {call.non_empty_lines}"
        )
        blob = load_distiller_response(call.audit_prefix)

        monkeypatch.setattr(
            steps_module, "_parse_distiller_response", _parse_with_old_tab_only_splitter
        )

        with caplog.at_level(logging.WARNING):
            claims = await _distil(
                [("gemini", {"report": SHORT_REPORT, "_angle": FACET})],
                {"gemini": blob},
            )

        assert claims == [], (
            "the reverted parser must reproduce the V-01 total loss, otherwise "
            "this is not a demonstration of anything"
        )
        records = _drop_records(caplog)
        assert len(records) == 1, (
            f"expected one D-R1(c) record, got {len(records)}"
        )
        message = records[0].getMessage()
        assert "141" in message, (
            f"the 141 returned lines must be counted in the record: {message!r}"
        )
        assert "gemini" in message
        assert "Hoe evolueren de koffiestrategie" in message, (
            f"the first recorded line must appear verbatim (truncated): {message!r}"
        )
