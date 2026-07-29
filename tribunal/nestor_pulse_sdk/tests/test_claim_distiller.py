"""Tests for claim_distiller — un-stubbed in Plan 01-13 Task 2.

TDD RED/GREEN cycle. All tests use a FAKE audited client — no real LLM, no Cloud SQL.

Coverage:
  1. Normal path: >=2 claims parsed, each has 'text' and 'facet' keys.
  2. Blank-report input: returns [] without raising.
  3. Malformed line in response: skipped without raising, valid lines still parsed.
  4. Stub removal: claim_distiller is NOT _phase2_stub (no NotImplementedError).
  5. Grep gate: no direct provider client construction (audited path only).
  6. Other 8 stubs remain: raising NotImplementedError as expected.

G-12 (phase 15.1) — stop deleting the corroboration signal that already exists.
Two live bugs closed here, both proven by SYNTHETIC multi-provider inputs:

  Bug 1: `claim_distiller` builds `units: list[(provider_name, chunk)]` and knows
         exactly which researcher produced each chunk — then discarded the name.
         Claims came back as {text, facet, evidence} only, and `facet` is not a
         usable substitute (it falls back to the provider name only when no
         focus-area label matched). Now every claim carries `found_by`.

  Bug 2: `_dedupe_claims` collapsed near-identical facts from DIFFERENT
         researchers and threw the duplicates away (2,976 raw -> 1,162). Three
         researchers independently confirming a fact looked identical to one
         researcher asserting it alone. Now duplicates MERGE into `found_by`.

Corroboration = len(claim["found_by"]). Consumed by the queue ordering in plan
15.1-07, where LOW corroboration is checked FIRST.

The recorded run fixture has no provider column and holds only post-dedupe
claims, so it CANNOT prove `found_by` — hence the synthetic fakes below. Count
preservation against the recorded run is proven in plan 15.1-09's replay test.

Cloud Build invocation (no Postgres needed — these tests touch no DB):
  gcloud builds submit tribunal \\
    --config=tribunal/cloudbuild.test-gates.yaml \\
    --project="$GOOGLE_PROJECT"
"""
from __future__ import annotations

import asyncio
import copy
import re
import uuid
from datetime import date

import pytest

# This import will fail until Task 2 un-stubs claim_distiller
from nestor_pulse_sdk.pipeline.synthesis.steps import (
    claim_distiller,
    extract_focus_areas,
    _dedupe_claims,
    # The remaining stubs — still should raise NotImplementedError
    chunker_prime,
    chunk_guard,
    claim_guard,
    relevance_gate,
    conflict_detector,
    topic_clustering,
    topic_synthesis,
)


# ---------------------------------------------------------------------------
# Fake LLM response objects
# ---------------------------------------------------------------------------

class _FakeResponse:
    """Minimal google-genai response shape."""

    def __init__(self, text: str) -> None:
        self.text = text


# ---------------------------------------------------------------------------
# Fake AuditedLLMClient
# ---------------------------------------------------------------------------

class FakeAudited:
    """Records calls and returns canned responses. No DB, no GCS, no network."""

    def __init__(self, canned_text: str) -> None:
        self._canned_text = canned_text
        self.calls: list[dict] = []

    async def gemini_generate(self, *, run_id, tenant_id, model, contents, **kwargs):
        self.calls.append(
            {"run_id": run_id, "model": model, "contents": contents, "kwargs": kwargs}
        )
        return _FakeResponse(self._canned_text)


# ---------------------------------------------------------------------------
# Canned multi-line claim responses (plain-text line format)
# ---------------------------------------------------------------------------

# Three valid claims, columns separated by a REAL TAB (U+0009).
#
# THIS FIXTURE STAYS TAB-SEPARATED ON PURPOSE (phase 15.4, plan 15.4-03). The
# distiller PROMPT contract is now `FACET ||| CLAIM_TEXT ||| EVIDENCE` — the old
# prompt described its separator as the placeholder `<TAB>`, a model copied
# those five characters back as data, and 278 V-01 coffee claims were discarded
# on a string comparison. The PARSER still accepts a real tab, first in its
# priority order, and keeping this fixture tab-separated is how that back-compat
# stays a behaviour UNDER TEST rather than an accident. `GOOD_RESPONSE_PIPES`
# below is the same three claims in the new contract; they must parse alike.
GOOD_RESPONSE = (
    "Belgian IT market share trends\tCronos holds ~18% of Belgian IT services market by revenue in 2024.\n"
    "Key competitor strategies\tCapgemini Belgium expanded its public-sector practice by 30% YoY.\n"
    "Belgian IT market share trends\tCloud migration projects grew 45% across Cronos client portfolio in 2025.\n"
)

# The SAME three claims in the current `|||` prompt contract. A model answering
# the prompt as written now sends this shape; it must produce claims identical
# to GOOD_RESPONSE's.
GOOD_RESPONSE_PIPES = (
    "Belgian IT market share trends ||| Cronos holds ~18% of Belgian IT services market by revenue in 2024.\n"
    "Key competitor strategies ||| Capgemini Belgium expanded its public-sector practice by 30% YoY.\n"
    "Belgian IT market share trends ||| Cloud migration projects grew 45% across Cronos client portfolio in 2025.\n"
)

# Response with one malformed line (NO separator of any accepted kind — no tab,
# no `<TAB>`, no `|||`, no `|`, and single spaces only) mixed with valid lines.
MIXED_RESPONSE = (
    "Belgian IT market share trends\tCronos holds ~18% market share in Belgian IT services.\n"
    "THIS LINE IS MALFORMED NO TAB SEPARATOR\n"
    "Key competitor strategies\tAccenture Belgium targets mid-market with AI-first services.\n"
)

# Blank / empty report
EMPTY_RESPONSE = ""
WHITESPACE_RESPONSE = "\n  \n   \n"


# ---------------------------------------------------------------------------
# Mission brief fixture
# ---------------------------------------------------------------------------

MISSION_BRIEF = {
    "deep_research_prompt": "Analyse Cronos competitive position in Belgian IT",
    "focus_areas": [
        {"focus_area": "Belgian IT market share trends", "taxonomy": "C", "stakes": "high"},
        {"focus_area": "Key competitor strategies", "taxonomy": "B", "stakes": "high"},
    ],
    "needs_clarification": False,
    "clarifying_questions": [],
}

PROVIDER_REPORTS = [
    ("gemini", {"status": "success", "report": "Cronos holds significant market share..."}),
    ("claude", {"status": "success", "report": "Competitor expansion is accelerating..."}),
]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Stub removal check
# ---------------------------------------------------------------------------

class TestClaimDistillerIsReal:
    def test_claim_distiller_is_not_phase2_stub(self):
        """claim_distiller must NOT raise NotImplementedError (it's un-stubbed)."""
        # The stub raises NotImplementedError on any call.
        # The real implementation is async and takes keyword args.
        # We verify it's async (coroutine function) rather than a stub closure.
        import inspect
        assert inspect.iscoroutinefunction(claim_distiller), (
            "claim_distiller must be an async function, not a _phase2_stub closure"
        )


class TestOtherStubsUntouched:
    """The remaining stubs must still raise NotImplementedError.

    conflict_detector was un-stubbed (now a real audited async function) — it is
    asserted real in TestConflictDetectorIsReal below.
    """

    @pytest.mark.parametrize("stub_fn", [
        chunker_prime, chunk_guard, claim_guard,
        relevance_gate, topic_clustering, topic_synthesis,
    ])
    def test_stub_raises_not_implemented(self, stub_fn):
        with pytest.raises(NotImplementedError):
            stub_fn()


class TestConflictDetectorIsReal:
    def test_conflict_detector_is_not_phase2_stub(self):
        """conflict_detector must be a real async function, not a _phase2_stub closure."""
        import inspect
        from nestor_pulse_sdk.pipeline.synthesis.steps import conflict_detector as cd
        assert inspect.iscoroutinefunction(cd), (
            "conflict_detector must be an async function, not a _phase2_stub closure"
        )


# ---------------------------------------------------------------------------
# Normal path
# ---------------------------------------------------------------------------

class TestClaimDistillerNormalPath:
    def setup_method(self):
        self.run_id = uuid.uuid4()
        self.tenant_id = uuid.uuid4()
        self.audited = FakeAudited(GOOD_RESPONSE)

    def _call(self, provider_reports=None):
        return _run(
            claim_distiller(
                provider_reports=provider_reports or PROVIDER_REPORTS,
                mission_brief=MISSION_BRIEF,
                audited=self.audited,
                run_id=self.run_id,
                tenant_id=self.tenant_id,
            )
        )

    def test_returns_list(self):
        result = self._call()
        assert isinstance(result, list)

    def test_at_least_two_claims(self):
        result = self._call()
        assert len(result) >= 2, f"Expected >= 2 claims, got {len(result)}: {result}"

    def test_each_claim_has_text_key(self):
        result = self._call()
        for claim in result:
            assert "text" in claim, f"Claim missing 'text' key: {claim}"
            assert isinstance(claim["text"], str)
            assert len(claim["text"]) >= 1

    def test_each_claim_has_facet_key(self):
        result = self._call()
        for claim in result:
            assert "facet" in claim, f"Claim missing 'facet' key: {claim}"
            assert isinstance(claim["facet"], str)

    def test_audited_gemini_called_with_flash(self):
        self._call()
        assert len(self.audited.calls) >= 1
        for call in self.audited.calls:
            assert call["model"] == "gemini-2.5-flash", (
                f"Expected gemini-2.5-flash, got {call['model']!r}"
            )

    def test_thinking_disabled_in_kwargs(self):
        """The call must pass config that disables thinking."""
        self._call()
        call = self.audited.calls[0]
        assert "config" in call["kwargs"], (
            "gemini_generate must receive a 'config' kwarg to disable thinking"
        )


class TestPipeSeparatedResponseMatchesTabSeparated:
    """15.4-03: the `|||` prompt contract and the tab back-compat agree.

    The distiller prompt now asks for `FACET ||| CLAIM_TEXT ||| EVIDENCE`. The
    parser still accepts a real tab, because the old prompt asked for one and
    because dropping that acceptance is how V-01's already-working 43 and 143
    claim blobs would have been lost while "fixing" the 278 broken ones.

    Both canned responses are driven through the REAL `claim_distiller`, so this
    covers the whole path and not just the splitter.
    """

    def setup_method(self):
        self.run_id = uuid.uuid4()
        self.tenant_id = uuid.uuid4()

    def _claims_for(self, canned: str) -> list[dict]:
        return _run(
            claim_distiller(
                provider_reports=PROVIDER_REPORTS,
                mission_brief=MISSION_BRIEF,
                audited=FakeAudited(canned),
                run_id=self.run_id,
                tenant_id=self.tenant_id,
            )
        )

    def test_pipe_separated_response_produces_claims(self):
        claims = self._claims_for(GOOD_RESPONSE_PIPES)
        assert len(claims) >= 2, (
            f"the `|||` contract the prompt now asks for must parse, got {claims}"
        )

    def test_pipe_and_tab_responses_produce_identical_claims(self):
        """Equality, not "both produced something" — that weaker assertion is
        the shape that let the `<TAB>` defect survive a full paid run."""
        tabbed = self._claims_for(GOOD_RESPONSE)
        piped = self._claims_for(GOOD_RESPONSE_PIPES)
        assert piped == tabbed, (
            f"the same three claims written with ||| and with a tab must parse "
            f"identically.\n  tab : {tabbed}\n  pipe: {piped}"
        )

    def test_the_two_fixtures_really_are_different_strings(self):
        """Non-vacuity: the equality above must not be comparing a string to itself."""
        assert GOOD_RESPONSE != GOOD_RESPONSE_PIPES
        assert "\t" in GOOD_RESPONSE and "|||" not in GOOD_RESPONSE
        assert "|||" in GOOD_RESPONSE_PIPES and "\t" not in GOOD_RESPONSE_PIPES


# ---------------------------------------------------------------------------
# Blank / empty report
# ---------------------------------------------------------------------------

class TestBlankReport:
    def setup_method(self):
        self.run_id = uuid.uuid4()
        self.tenant_id = uuid.uuid4()

    def _call_with_response(self, canned_text):
        audited = FakeAudited(canned_text)
        return _run(
            claim_distiller(
                provider_reports=[("gemini", {"status": "success", "report": "some text"})],
                mission_brief=MISSION_BRIEF,
                audited=audited,
                run_id=self.run_id,
                tenant_id=self.tenant_id,
            )
        )

    def test_empty_llm_response_returns_empty_list(self):
        result = self._call_with_response(EMPTY_RESPONSE)
        assert result == [], f"Empty response should yield [], got: {result}"

    def test_whitespace_only_response_returns_empty_list(self):
        result = self._call_with_response(WHITESPACE_RESPONSE)
        assert result == [], f"Whitespace response should yield [], got: {result}"

    def test_no_provider_reports_returns_empty_list(self):
        """Zero provider reports — nothing to distil."""
        audited = FakeAudited(EMPTY_RESPONSE)
        result = _run(
            claim_distiller(
                provider_reports=[],
                mission_brief=MISSION_BRIEF,
                audited=audited,
                run_id=self.run_id,
                tenant_id=self.tenant_id,
            )
        )
        assert result == [], f"No provider reports should yield [], got: {result}"


# ---------------------------------------------------------------------------
# Malformed line tolerance
# ---------------------------------------------------------------------------

class TestMalformedLineTolerance:
    def setup_method(self):
        self.run_id = uuid.uuid4()
        self.tenant_id = uuid.uuid4()

    def test_malformed_line_skipped_without_raising(self):
        """Mixed response: malformed lines skipped, valid ones parsed."""
        audited = FakeAudited(MIXED_RESPONSE)
        # Must NOT raise
        result = _run(
            claim_distiller(
                provider_reports=PROVIDER_REPORTS,
                mission_brief=MISSION_BRIEF,
                audited=audited,
                run_id=self.run_id,
                tenant_id=self.tenant_id,
            )
        )
        # Should still get the 2 valid claims
        assert len(result) >= 1, f"Should parse valid lines, got: {result}"
        for claim in result:
            assert "text" in claim
            assert "facet" in claim


# ---------------------------------------------------------------------------
# G-12: provenance (found_by) + merging dedupe
# ---------------------------------------------------------------------------

G12_MISSION_BRIEF = {"focus_areas": [{"focus_area": "general"}]}


class ProviderTaggingAudited:
    """Content-aware fake: answers each chunk with one claim naming the researcher
    whose report that chunk came from.

    Mirrors test_distiller_coverage.py's fake — it reads the `### Provider: {name}`
    header the real prompt builder emits, so the REAL claim_distiller is driven end
    to end. Hand-written duck-typed fake, per the suite convention.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def gemini_generate(self, *, run_id, tenant_id, model, contents, **kwargs):
        self.calls.append(contents)
        m = re.search(r"### Provider: (\w+)", contents)
        name = m.group(1) if m else "unknown"
        return _FakeResponse(
            f"general\tFact reported by {name} about the Belgian IT market\t"
            f"verbatim {name} evidence sentence"
        )


class EchoAudited:
    """Fake that replays one canned response for EVERY chunk, so the same fact
    arrives from each researcher — the corroboration case."""

    def __init__(self, canned_text: str) -> None:
        self._canned_text = canned_text
        self.calls: list[str] = []

    async def gemini_generate(self, *, run_id, tenant_id, model, contents, **kwargs):
        self.calls.append(contents)
        return _FakeResponse(self._canned_text)


def _old_dedupe(claims: list[dict]) -> list[dict]:
    """Verbatim pre-15.1 DISCARD implementation, kept as the property-test oracle.

    Do not "improve" this — its only job is to reproduce the behaviour the merge
    rewrite must not change.
    """
    seen: set[str] = set()
    out: list[dict] = []
    for c in claims:
        norm = re.sub(r"[^a-z0-9 ]", "", (c.get("text") or "").lower())
        norm = re.sub(r"\s+", " ", norm).strip()
        if not norm or norm in seen:
            continue
        seen.add(norm)
        out.append(c)
    return out


def _claim(text: str, found_by: list[str] | None = None) -> dict:
    return {
        "text": text,
        "facet": "general",
        "evidence": "",
        **({"found_by": list(found_by)} if found_by is not None else {}),
    }


# Exercises every branch the merge touches: exact duplicates, whitespace-only
# variants, punctuation/casing-only variants, an empty-text claim, a text that
# normalises to nothing, a claim with NO found_by key at all, and uniques.
MIXED_CLAIMS = [
    _claim("Cronos holds 18% of the Belgian IT market.", ["gemini"]),
    _claim("Cronos holds 18% of the Belgian IT market.", ["claude"]),      # exact dup
    _claim("Cronos  holds   18%  of the Belgian IT market.", ["openai"]),  # whitespace
    _claim("cronos holds 18 of the belgian it market!!!", ["gemini"]),     # punctuation
    _claim("Capgemini Belgium grew its public sector practice.", ["claude"]),
    _claim("", ["gemini"]),                                                # empty text
    _claim("!!! ??? ...", ["claude"]),                                     # normalises away
    _claim("Accenture Belgium targets the mid-market with AI."),           # no found_by
    _claim("Accenture Belgium targets the mid-market with AI.", ["openai"]),
]


class TestClaimProvenance:
    """G-12 bug 1: every claim names the researcher that produced it."""

    def test_claims_carry_producing_provider(self):
        audited = ProviderTaggingAudited()
        reports = [
            ("gemini", {"status": "success", "report": "Gemini research prose."}),
            ("claude", {"status": "success", "report": "Claude research prose."}),
            ("openai", {"status": "success", "report": "OpenAI research prose."}),
        ]
        claims = _run(claim_distiller(
            provider_reports=reports,
            mission_brief=G12_MISSION_BRIEF,
            audited=audited,
            run_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
        ))

        assert claims, "three provider reports must produce claims"
        for c in claims:
            assert c.get("found_by"), f"claim has no provenance: {c}"

        union = {p for c in claims for p in c["found_by"]}
        assert union == {"gemini", "claude", "openai"}, (
            f"every researcher must be named in found_by, got {union}"
        )

    def test_single_source_claim_has_corroboration_one(self):
        """A fact seen once ends with len(found_by) == 1, so the 15.1-07 queue
        ordering can tell it apart from a multiply-corroborated fact."""
        audited = ProviderTaggingAudited()
        reports = [("gemini", {"status": "success", "report": "Gemini research prose."})]
        claims = _run(claim_distiller(
            provider_reports=reports,
            mission_brief=G12_MISSION_BRIEF,
            audited=audited,
            run_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
        ))

        assert claims, "one provider report must still produce claims"
        for c in claims:
            assert len(c["found_by"]) == 1, (
                f"single-source claim must have corroboration 1, got {c['found_by']}"
            )
            assert c["found_by"] == ["gemini"]


class TestDedupeMerges:
    """G-12 bug 2: duplicates merge into found_by instead of vanishing."""

    def test_dedupe_merges_preserving_count(self):
        # RESEARCH Pitfall 5: the discard->merge rewrite must not change WHICH
        # claims survive, only what provenance they carry. If this drifts, the
        # recorded-run replay premise of the whole phase collapses (1,162 must
        # stay 1,162). Compared against the verbatim old implementation.
        new_out = _dedupe_claims(copy.deepcopy(MIXED_CLAIMS))
        old_out = _old_dedupe(copy.deepcopy(MIXED_CLAIMS))

        assert len(new_out) == len(old_out), (
            f"merge changed the surviving claim count: "
            f"{len(new_out)} vs {len(old_out)}"
        )
        assert [c["text"] for c in new_out] == [c["text"] for c in old_out], (
            "merge changed which claims survived, or their order"
        )

    def test_dedupe_unions_found_by(self):
        """The same fact from three researchers collapses to ONE claim naming all
        three, in first-seen order, with no duplicates."""
        claims = [
            _claim("Cronos holds 18% of the Belgian IT market.", ["gemini"]),
            _claim("cronos holds 18 of the belgian it market", ["claude"]),
            _claim("Cronos  holds  18%  of the Belgian IT market!!", ["openai"]),
            _claim("Cronos holds 18% of the Belgian IT market.", ["gemini"]),  # repeat
        ]
        out = _dedupe_claims(claims)

        assert len(out) == 1, f"all four variants normalise to one fact, got {out}"
        assert out[0]["found_by"] == ["gemini", "claude", "openai"], (
            f"found_by must be the first-seen-order union, got {out[0]['found_by']}"
        )
        assert out[0]["text"] == "Cronos holds 18% of the Belgian IT market.", (
            "the FIRST occurrence must be the one kept"
        )

    def test_dedupe_merges_corroboration_across_providers_end_to_end(self):
        """Drive the REAL distiller: three researchers all report the same fact,
        so one claim survives carrying all three names."""
        same_fact = (
            "general\tCronos holds 18% of the Belgian IT services market\t"
            "verbatim evidence sentence"
        )
        audited = EchoAudited(same_fact)
        reports = [
            ("gemini", {"status": "success", "report": "Gemini research prose."}),
            ("claude", {"status": "success", "report": "Claude research prose."}),
            ("openai", {"status": "success", "report": "OpenAI research prose."}),
        ]
        claims = _run(claim_distiller(
            provider_reports=reports,
            mission_brief=G12_MISSION_BRIEF,
            audited=audited,
            run_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
        ))

        assert len(claims) == 1, f"one fact reported thrice is ONE claim, got {claims}"
        assert sorted(claims[0]["found_by"]) == ["claude", "gemini", "openai"], (
            f"corroboration lost: {claims[0]['found_by']}"
        )
        assert len(claims[0]["found_by"]) == 3, "corroboration count must be 3"

    def test_dedupe_tolerates_claims_without_found_by(self):
        """Defensive: some call paths build claims by hand with no provenance."""
        claims = [
            _claim("A fact with no provenance attached at all."),
            _claim("A fact with no provenance attached at all.", ["gemini"]),
        ]
        out = _dedupe_claims(claims)

        assert len(out) == 1
        assert out[0]["found_by"] == ["gemini"], (
            f"a later provider must still register on the kept claim, got {out[0]}"
        )


# ---------------------------------------------------------------------------
# D-W2-3 (phase 15.5 wave 2): the merge rule for the three attribution columns.
#
# FIRST-WINS, and it needed NO PRODUCTION CODE — `_dedupe_claims` already keeps
# the first occurrence's dict whole and mutates only the fields it unions. These
# tests pin that emergent behaviour so a future "tidy-up" of the function has to
# turn a named test red before it can change it, and they pin the byte-identity
# of the `claim_distiller` path through the same function.
#
# Nothing below modifies `_old_dedupe`, `MIXED_CLAIMS` or any existing test. If
# one of those goes red, the production change was not additive and belongs
# fixed there, not accommodated here.
# ---------------------------------------------------------------------------

#: A claim in the shape `collect_provider_facts` now produces — the nine older
#: keys are irrelevant to the merge, so only the ones under test are set.
def _attributed(text, *, found_by, sub_question, corroboration_key, as_of=None):
    return {
        "text": text,
        "facet": "general",
        "evidence": "",
        "found_by": list(found_by),
        "sub_question": sub_question,
        "corroboration_key": corroboration_key,
        "as_of": as_of,
    }


class TestDedupeAttributionIsFirstWins:
    """D-W2-3. The first occurrence's attribution survives the cross-stream merge."""

    def test_dedupe_first_wins_silently_loses_the_second_claims_sub_question(self):
        """THE ACCEPTED INFORMATION LOSS, named in the test rather than found later.

        Two streams state the same fact under DIFFERENT sub-questions. They merge
        to one claim carrying the FIRST sub-question, and the second is gone with
        no warning — the cross-key-merge warning was explicitly DECLINED for this
        wave. That is a recorded decision, not an oversight; do not add it back
        without reopening D-W2-3.
        """
        claims = [
            _attributed("Cronos holds 18% of the Belgian IT market.",
                        found_by=["gemini"], sub_question="How big is Cronos?",
                        corroboration_key="w01"),
            _attributed("cronos holds 18 of the belgian it market",
                        found_by=["claude"], sub_question="Who leads Belgian IT?",
                        corroboration_key="w02"),
        ]
        out = _dedupe_claims(claims)

        assert len(out) == 1, "both variants normalise to one fact"
        assert out[0]["sub_question"] == "How big is Cronos?", "the FIRST wins"
        assert out[0]["sub_question"] != "Who leads Belgian IT?", (
            "the second sub-question is silently lost — that is the accepted cost"
        )
        # The corroboration signal itself still survives, in found_by.
        assert out[0]["found_by"] == ["gemini", "claude"]

    def test_dedupe_first_wins_attributes_a_cross_group_merge_to_the_first_group(self):
        """Same rule, the column that actually joins the corroboration query.

        A claim merged across two corroboration groups is attributed to the
        first. `provider_quality_by_url`'s first-to-introduce-owns-it is the
        precedent this follows.
        """
        claims = [
            _attributed("Cronos holds 18% of the Belgian IT market.",
                        found_by=["gemini"], sub_question="q", corroboration_key="w01"),
            _attributed("Cronos  holds  18%  of the Belgian IT market!!",
                        found_by=["openai"], sub_question="q", corroboration_key="w07"),
        ]
        out = _dedupe_claims(claims)

        assert len(out) == 1
        assert out[0]["corroboration_key"] == "w01", "the FIRST group wins"
        assert out[0]["corroboration_key"] != "w07"

    def test_dedupe_keeps_a_none_first_occurrence_over_a_later_real_value(self):
        """First-wins working AS SPECIFIED, not a bug — and bounded by ORDERING.

        `collect_provider_facts` calls `_dedupe_claims(d8_claims +
        fallback_claims)`, with the ATTRIBUTED fact-list claims FIRST. So in the
        real pipeline the unattributed distiller paraphrase is the duplicate and
        never the survivor, and this case only arises where nothing was recorded
        for either. Asserted anyway, because the mitigation is an ordering
        convention in another function and conventions drift.
        """
        claims = [
            _attributed("Cronos holds 18% of the Belgian IT market.",
                        found_by=["claude"], sub_question=None,
                        corroboration_key=None),
            _attributed("cronos holds 18 of the belgian it market",
                        found_by=["gemini"], sub_question="How big is Cronos?",
                        corroboration_key="w01", as_of=date(2021, 3, 4)),
        ]
        out = _dedupe_claims(claims)

        assert len(out) == 1
        assert out[0]["sub_question"] is None, "first-wins, even when the first is None"
        assert out[0]["corroboration_key"] is None
        assert out[0]["as_of"] is None
        # `is None`, not falsiness: the empty string is falsy too, and D-W2-2
        # exists precisely to keep "absent" and "the empty key" apart.
        assert out[0]["corroboration_key"] != ""

    def test_dedupe_invents_no_attribution_key_on_the_claim_distiller_path(self):
        """THE BYTE-IDENTITY ASSERTION for the path that carries none of these keys.

        `_dedupe_claims` runs over RAW distiller claims at the end of
        `claim_distiller`, BEFORE `_normalise_fact_claim` has ever been reached —
        so those claims have no `sub_question`, no `corroboration_key` and no
        `as_of` key at all. Not `None`: ABSENT. A merge that invented one would
        change what that path produces, and this wave changes nothing.
        """
        claims = [
            _claim("Cronos holds 18% of the Belgian IT market.", ["gemini"]),
            _claim("cronos holds 18 of the belgian it market", ["claude"]),
            _claim("Capgemini Belgium grew its public sector practice.", ["openai"]),
        ]
        before_keys = [set(c) for c in claims]
        assert all(
            k not in keys
            for keys in before_keys
            for k in ("sub_question", "corroboration_key", "as_of")
        ), "the fixture's own premise: distiller claims carry none of the three"

        out = _dedupe_claims(claims)

        assert len(out) == 2
        for survivor in out:
            for invented in ("sub_question", "corroboration_key", "as_of"):
                assert invented not in survivor, (
                    f"_dedupe_claims invented {invented!r} on a distiller claim: "
                    f"{sorted(survivor)}"
                )

    def test_dedupe_of_distiller_shaped_claims_still_matches_the_old_implementation(self):
        """The same oracle `test_dedupe_merges_preserving_count` uses, aimed at
        the distiller shape specifically.

        Count, order and texts must be what the verbatim pre-15.1 DISCARD
        implementation produced. If this drifts, the recorded-run replay premise
        collapses and so does the phase 15.8 measuring run's one held-still
        variable.
        """
        new_out = _dedupe_claims(copy.deepcopy(MIXED_CLAIMS))
        old_out = _old_dedupe(copy.deepcopy(MIXED_CLAIMS))

        assert len(new_out) == len(old_out)
        assert [c["text"] for c in new_out] == [c["text"] for c in old_out]
        # And no survivor grew a key that the old implementation's survivor lacks.
        for new_claim, old_claim in zip(new_out, old_out):
            gained = set(new_claim) - set(old_claim)
            assert gained <= {"found_by", "provider_quality_by_url"}, (
                f"the merge invented key(s) {sorted(gained)} on a distiller claim"
            )
