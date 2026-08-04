"""The `assignment_yield` writer: attribution, aggregation, and the two seams.

WHAT BREAKS IN PRODUCTION IF THIS FILE FIRES. One of three things, and all three
are silent: the one measuring run's `assignment_yield` table is EMPTY (nothing
was written), or it is WRONG (a provider's claims and spend attributed to the
wrong assignment, believed because nothing contradicts it), or THE WRITER TAKES
THE RUN DOWN WITH IT — a ~$45 single-shot run ended by a telemetry write.

The whole table exists to answer ONE question ONCE: *which provider actually
yields surviving claims per dollar*. There is no second run to check it against.

WHAT THIS FILE DOES NOT TEST, stated so it is not assumed. The seams themselves
live inside `TribunalPipeline._run_staged`, a very long async method that cannot
be driven without a live pipeline. The seam PLACEMENT — the one property of them
that is load-bearing and cannot be re-derived by reading — is asserted over the
module's source text instead, at the bottom of this file.
"""
from __future__ import annotations

import ast
import io
import tokenize

import pytest

from nestor_pulse_sdk.pipeline.tribunal import pipeline as _pipeline_mod


# ---------------------------------------------------------------------------
# Fixtures. Result shape = the `_enriched` dict `run_angles` returns, paired with
# its provider; claim shape = `synthesis.steps._normalise_fact_claim`'s output.
# ---------------------------------------------------------------------------

def _result(provider, group_id, client_question, **over):
    payload = {
        "status": "success",
        "_corroboration_key": group_id,
        "_client_question": client_question,
        "_parent_kind": "client_question",
        "_stakes": "high",
        "_duration_s": 12.5,
        "_retry_used": False,
        "cost_usd": "1.25",
    }
    payload.update(over)
    return (provider, payload)


def _claim(text, found_by, group_id, facet="Q1", fact_source="fact_list", urls=()):
    return {
        "text": text,
        "found_by": list(found_by),
        "corroboration_key": group_id,
        "facet": facet,
        "fact_source": fact_source,
        "source_urls": list(urls),
    }


#: The field contract, written out so a reader can see it without chasing a
#: signature. It is NOT the authority -- see `_emitter_keywords()` below, which
#: reads the real one.
_FIELDS = {
    "provider", "group_id", "client_question", "parent_kind", "stakes",
    "fact_list_parsed", "retry_used", "claims_kept", "resolvable_sources",
    "cost_usd", "duration_s",
}


def _emitter_keywords() -> set[str]:
    """The KEYWORD-ONLY parameters of `record_assignment`, read from the function.

    THE AUTHORITY IS THE EMITTER, NOT THE LITERAL ABOVE. `record_assignment_safe`
    does `await record_assignment(run_id, tenant_id, **built)`, so the set of keys
    this module's row builder produces must equal that function's keyword-only
    parameters or the call raises `TypeError` -- which the emitter catches and
    logs, leaving an EMPTY TABLE behind a green run.

    `record_assignment` lives in `runs/yield_records.py`, which plan 15.8-05 owns,
    while `_assignment_yield_rows` lives in `pipeline.py`, which 15.8-09 owns.
    Those were written in SEPARATE worktrees that could not see each other, so a
    hand-copied literal here would agree with the emitter only by luck and would
    go on agreeing with itself forever after the emitter changed.
    """
    import inspect

    from nestor_pulse_sdk.runs import yield_records

    params = inspect.signature(yield_records.record_assignment).parameters
    return {
        name
        for name, p in params.items()
        if p.kind is inspect.Parameter.KEYWORD_ONLY
    }


# ---------------------------------------------------------------------------
# ONE ROW PER SUCCESSFUL ASSIGNMENT
# ---------------------------------------------------------------------------

def test_two_groups_by_three_streams_produce_exactly_six_rows():
    """If this fires, the table under- or over-counts the run's assignments."""
    results = [
        _result(p, g, "Q%s" % g[-1])
        for g in ("g1", "g2")
        for p in ("gemini", "openai", "claude")
    ]

    rows = _pipeline_mod._assignment_yield_rows(results, [])

    assert len(rows) == 6
    keys = {(r["provider"], r["group_id"], r["client_question"]) for r in rows}
    assert len(keys) == 6


def test_every_row_carries_exactly_the_emitter_keyword_set():
    """If this fires, `record_assignment_safe` raises TypeError on **unpacking.

    The emitter swallows it and logs a warning, so the failure mode is an EMPTY
    TABLE with a green run — the inert-instrumentation class this phase exists
    to end.

    THE COMPARISON IS AGAINST THE EMITTER'S REAL SIGNATURE, not against the
    `_FIELDS` literal alone. Asserting only `set(rows[0]) == _FIELDS` compares
    this module against a copy of the contract that lives in the same file: both
    sides move together, so the assertion stays green precisely when
    `record_assignment` has changed underneath it — the failure this test names
    in its own first line. The literal is kept as a THIRD party, pinned to both,
    which is what makes a disagreement attributable rather than merely visible.
    """
    rows = _pipeline_mod._assignment_yield_rows([_result("gemini", "g1", "Q1")], [])
    emitter = _emitter_keywords()

    assert set(rows[0]) == emitter, (
        "the row builder and `record_assignment` disagree -- `**built` will "
        f"raise TypeError. builder-only={sorted(set(rows[0]) - emitter)}, "
        f"emitter-only={sorted(emitter - set(rows[0]))}"
    )
    assert emitter == _FIELDS, (
        "the emitter's keyword set changed and the documented contract in this "
        f"file was not updated with it: {sorted(emitter ^ _FIELDS)}"
    )


# ---------------------------------------------------------------------------
# ATTRIBUTION
# ---------------------------------------------------------------------------

def test_claims_kept_counts_provider_and_group_together():
    """If this fires, a provider is credited with another provider's claims."""
    results = [_result("gemini", "g1", "Q1"), _result("openai", "g1", "Q1")]
    claims = [_claim("c%d" % i, ["gemini"], "g1") for i in range(3)]

    rows = {r["provider"]: r for r in _pipeline_mod._assignment_yield_rows(results, claims)}

    assert rows["gemini"]["claims_kept"] == 3
    assert rows["openai"]["claims_kept"] == 0


def test_a_claim_found_by_two_providers_counts_for_both():
    """DELIBERATE DOUBLE ATTRIBUTION, pinned so nobody "fixes" it.

    The statement really did come out of both assignments. A SUM of `claims_kept`
    across providers therefore EXCEEDS the claim count by design — see the
    docstring on `_assignment_yield_rows`, and the reader-side rules in the plan
    summary.
    """
    results = [_result("gemini", "g1", "Q1"), _result("openai", "g1", "Q1")]

    rows = _pipeline_mod._assignment_yield_rows(
        results, [_claim("shared", ["gemini", "openai"], "g1")]
    )

    assert [r["claims_kept"] for r in rows] == [1, 1]


def test_a_claim_from_another_group_counts_for_neither():
    """If this fires, group boundaries stop meaning anything in the table."""
    results = [_result("gemini", "g1", "Q1"), _result("gemini", "g2", "Q2")]

    rows = _pipeline_mod._assignment_yield_rows(results, [_claim("x", ["gemini"], "g9")])

    assert [r["claims_kept"] for r in rows] == [0, 0]


def test_cross_cutting_row_matches_on_group_id_alone():
    """THE MUTANT ROW. If this fires, the whole `d1` group is credited to Q1.

    A cross-cutting assignment records `client_question = NULL` by ruling
    (D-W5-2), while its claims file under `labels[0]` through `_group_angle`'s
    orphan rule. An implementation that matched on `facet` would sweep the entire
    cross-cutting group — and its spend — onto client question 1.
    """
    results = [_result("gemini", "d1", None, _parent_kind="cross_cutting")]

    rows = _pipeline_mod._assignment_yield_rows(
        results, [_claim("x", ["gemini"], "d1", facet="Q1")]
    )

    assert rows[0]["claims_kept"] == 1
    assert rows[0]["client_question"] is None
    assert rows[0]["parent_kind"] == "cross_cutting"


def test_focus_area_row_requires_a_null_key_and_a_matching_facet():
    """If this fires, the fallback path's rows collect claims that are not theirs."""
    results = [_result("gemini", None, "Q4")]
    rows = _pipeline_mod._assignment_yield_rows

    assert rows(results, [_claim("x", ["gemini"], None, facet="Q4")])[0]["claims_kept"] == 1
    assert rows(results, [_claim("x", ["gemini"], None, facet="other")])[0]["claims_kept"] == 0
    # A claim that HAS a group key belongs to that group, not to the fallback row.
    assert rows(results, [_claim("x", ["gemini"], "g1", facet="Q4")])[0]["claims_kept"] == 0


# ---------------------------------------------------------------------------
# CR-01: `fact_list_parsed` and `resolvable_sources` are NOT RECORDED
#
# Both columns used to be derived per-provider from the matching claims. Both
# were WRONG for the shape the redesigned engine actually emits — a claim two
# streams both found carries a MERGED `found_by` and a UNIONED `source_urls`, and
# `_claim_matches_assignment` hands that one dict to every provider in it. The
# error is systematically FLATTENING: it is worst exactly when corroboration
# works, which is what the redesign is for.
#
# These four tests are the guard on the replacement. THREE OF THEM ARE ABOUT WHY
# A CHEAPER FIX DOES NOT EXIST, because the obvious cheaper fix looks correct.
# ---------------------------------------------------------------------------

def test_the_two_contaminated_columns_are_not_recorded_rather_than_guessed():
    """THE FABRICATED-MEASUREMENT GUARD. If this fires, the column started lying.

    A NULL is the honest record of "not recorded" in a table read exactly once.
    A number derived from post-merge claims is a measurement nobody took, and it
    is indistinguishable from a real one at query time.
    """
    results = [_result("gemini", "g1", "Q1")]
    claims = [
        _claim("a", ["gemini"], "g1", fact_source="fact_list", urls=["u1", "u2"]),
        _claim("b", ["gemini"], "g1", fact_source="distiller_fallback", urls=["u3"]),
    ]

    row = _pipeline_mod._assignment_yield_rows(results, claims)[0]

    assert row["fact_list_parsed"] is None
    assert row["resolvable_sources"] is None
    # The columns that ARE recorded must be untouched by the removal.
    assert row["claims_kept"] == 2


def test_two_providers_sharing_a_merged_claim_do_not_report_each_others_evidence():
    """CR-01's REGRESSION TEST — RED on unfixed source (both rows read 3 / True).

    This is the shape D-R4/D-W3-1 dispatch exists to produce and the shape NO
    fixture in this file had: one claim, `found_by` naming two providers, holding
    the UNION of their URLs and the FIRST one's `fact_source`. openai here cited
    one link and fell back to the distiller; before the fix its row read
    `resolvable_sources=3` and `fact_list_parsed=True` — gemini's evidence,
    reported as openai's.
    """
    results = [_result("gemini", "g1", "Q1"), _result("openai", "g1", "Q1")]
    merged = _claim(
        "x", ["gemini", "openai"], "g1",
        fact_source="fact_list",
        urls=["http://g-a", "http://g-b", "http://o-a"],
    )

    rows = _pipeline_mod._assignment_yield_rows(results, [merged])

    assert len(rows) == 2
    assert [r["provider"] for r in rows] == ["gemini", "openai"]
    for row in rows:
        assert row["resolvable_sources"] is None, (
            "both providers were reporting the UNION of everyone's URLs — this "
            "column existed to compare how much citable ground EACH provider "
            "covered, and a union answers a different question entirely"
        )
        assert row["fact_list_parsed"] is None, (
            "the merged dict keeps the FIRST provider's fact_source, so a stream "
            "that fell back to the distiller read True off its partner's D8 block"
        )
    # The merged claim still counts for BOTH assignments — ruled design,
    # imprecision 2 in the docstring, and NOT what CR-01 changed.
    assert [r["claims_kept"] for r in rows] == [1, 1]


def test_a_shallow_pre_dedupe_snapshot_would_not_have_helped():
    """WHY THE OBVIOUS FIX IS INERT. Drives the REAL `_dedupe_claims`.

    The natural repair is `predupe = list(claims)` before the dedupe call and
    deriving the two columns from `predupe`. It does nothing: `_dedupe_claims`
    MUTATES the surviving dict IN PLACE, so the snapshot holds the SAME OBJECT
    and shows the merged `found_by` and the unioned `source_urls` afterwards.

    If this test ever goes red because `_dedupe_claims` became non-mutating, the
    per-provider derivation becomes available again and CR-01 can be reopened
    properly — that is the point of pinning it here rather than in a comment.
    """
    from nestor_pulse_sdk.pipeline.synthesis.steps import _dedupe_claims

    gemini = _claim("X fact", ["gemini"], "g1", urls=["http://g-a", "http://g-b"])
    openai = _claim("X fact.", ["openai"], "g1",
                    fact_source="distiller_fallback", urls=["http://o-a"])
    claims = [gemini, openai]
    snapshot = list(claims)

    out = _dedupe_claims(claims)

    assert len(out) == 1 and out[0] is gemini, "the two texts must actually merge"
    assert snapshot[0] is gemini, "a shallow copy shares the dicts, by definition"
    assert snapshot[0]["found_by"] == ["gemini", "openai"]
    assert snapshot[0]["source_urls"] == ["http://g-a", "http://g-b", "http://o-a"]


def test_the_merge_has_already_run_before_this_module_sees_a_claim():
    """WHY EVEN A DEEP PRE-DEDUPE COPY WOULD NOT HAVE HELPED, read off the source.

    `collect_provider_facts` calls `_dedupe_claims(d8_claims + fallback_claims)`
    and returns the RESULT as `ProviderFactsResult.claims`, which is what
    `pipeline.py` binds. The `_dedupe_claims` call at the merge stage is therefore
    the near-no-op its own comment says it is, and there is no pre-merge claim
    list in `pipeline.py` at any depth of copy. Restoring the two columns needs
    `synthesis/steps.py` to carry the pre-merge list out.

    Asserted over the source text because the alternative is driving
    `collect_provider_facts`, which needs live providers.
    """
    from nestor_pulse_sdk.pipeline.synthesis import steps as _steps_mod

    steps_src = _executable_source(_steps_mod)

    assert "claims = _dedupe_claims(d8_claims + fallback_claims)" in steps_src
    assert "claims=claims" in steps_src, "the deduped list is what is returned"

    pipeline_src = _executable_source(_pipeline_mod)
    assert "claims = list(facts_result.claims)" in pipeline_src


# ---------------------------------------------------------------------------
# COUNTS
# ---------------------------------------------------------------------------

def test_zero_claims_kept_is_a_measurement_and_the_row_is_still_written():
    """If this fires, "this provider kept nothing" becomes indistinguishable from
    "nothing was recorded" — which is the one distinction this table is built on."""
    rows = _pipeline_mod._assignment_yield_rows(
        [_result("gemini", "g1", "Q1")], [_claim("a", ["openai"], "g1")]
    )

    assert len(rows) == 1
    assert rows[0]["claims_kept"] == 0
    assert rows[0]["claims_kept"] is not None


# ---------------------------------------------------------------------------
# NO SECOND COERCION AUTHORITY (the emitter owns every rule)
# ---------------------------------------------------------------------------

def test_values_are_passed_through_raw_and_never_coerced_here():
    """If this fires, two modules now disagree about what a NULL means.

    `runs/yield_records` owns coercion, the PII scrub-then-clamp on
    `client_question` (whose ORDER is load-bearing) and the label clamps, AND it
    builds the natural key from its own normalisation on BOTH paths. A caller
    that "helpfully" cleaned a value first would break that key symmetry — and
    the completer's 0-row warning would then blame a missing INSERT.
    """
    rows = _pipeline_mod._assignment_yield_rows(
        [_result("gemini", "g1", "Q1", cost_usd="1.25", _duration_s=12.5)], []
    )

    assert rows[0]["cost_usd"] == "1.25"  # still a str, not a Decimal
    assert rows[0]["duration_s"] == 12.5


def test_a_result_missing_optional_keys_still_produces_a_row_with_nones():
    """A degrading provider costs its labels, never its row."""
    results = [("gemini", {"status": "success", "_corroboration_key": "g1",
                           "_client_question": "Q1"})]

    row = _pipeline_mod._assignment_yield_rows(results, [])[0]

    assert set(row) == _FIELDS
    assert row["cost_usd"] is None       # NOT 0 — the emitter's rule, not ours
    assert row["duration_s"] is None
    assert row["retry_used"] is None
    assert row["parent_kind"] is None
    assert row["stakes"] is None


def test_an_out_of_vocabulary_parent_kind_is_not_filtered_out(caplog):
    """D-W5-10. If this fires, an ENGINE BUG erases its own telemetry.

    The writer applies NO filter on `parent_kind`. An out-of-vocabulary value
    reaches the emitter's sentinel clamp and the row is written with `cost_usd`
    and `claims_kept` INTACT — and a dropped row would also SILENTLY UNDERSTATE
    SPEND, because `SUM()` skips NULLs without announcing it.
    """
    results = [_result("gemini", "g1", "Q1", _parent_kind="nonsense")]

    rows = _pipeline_mod._assignment_yield_rows(results, [_claim("a", ["gemini"], "g1")])

    assert len(rows) == 1
    assert rows[0]["parent_kind"] == "nonsense"  # handed through, NOT dropped
    assert rows[0]["cost_usd"] == "1.25"
    assert rows[0]["claims_kept"] == 1


# ---------------------------------------------------------------------------
# PURE AND NEVER RAISES
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "results, claims",
    [
        (17, []),
        (None, None),
        ("xx", "yy"),
        ([("gemini",)], []),                       # wrong arity
        ([("gemini", "notadict")], []),            # non-dict result
        ([17, None, "x"], []),
    ],
)
def test_aggregator_never_raises_on_hostile_input(results, claims):
    """If this fires, a data-shape defect ends a run whose money is spent."""
    assert isinstance(_pipeline_mod._assignment_yield_rows(results, claims), list)


def test_one_malformed_result_costs_its_own_row_and_not_the_batch():
    results = [_result("gemini", "g1", "Q1"), ("openai",), _result("claude", "g1", "Q1")]

    rows = _pipeline_mod._assignment_yield_rows(results, [])

    assert [r["provider"] for r in rows] == ["gemini", "claude"]


def test_non_dict_claims_are_tolerated():
    rows = _pipeline_mod._assignment_yield_rows(
        [_result("gemini", "g1", "Q1")], ["notadict", 17, None]
    )

    assert rows[0]["claims_kept"] == 0


@pytest.mark.parametrize("claim", [17, None, "x", {}, {"found_by": "gemini"}])
def test_claim_matcher_never_raises_and_returns_false(claim):
    assert _pipeline_mod._claim_matches_assignment(
        claim, provider="gemini", group_id="g1", client_question="Q1"
    ) is False


def test_an_empty_corroboration_key_on_a_claim_reads_as_absent():
    """`''` and NULL must not be two different facts on the claim side either."""
    assert _pipeline_mod._claim_matches_assignment(
        _claim("a", ["gemini"], "", facet="Q1"),
        provider="gemini", group_id=None, client_question="Q1",
    ) is True


# ---------------------------------------------------------------------------
# DUPLICATE NATURAL KEYS ARE NOT COLLAPSED (T-15.8-09-06)
# ---------------------------------------------------------------------------

def test_a_duplicate_natural_key_yields_two_rows():
    """If this fires, the condition the completer's warning exists to surface is
    hidden before it can be surfaced.

    A RESUMED run's restored angle and `divide()`'s doubled high-stakes fallback
    copy each write two rows on one natural key. There is no UNIQUE constraint by
    ruling — a uniqueness violation inside a paid run is worse than a duplicate
    row. READER-SIDE RULE: dedupe on the natural key before any SUM.
    """
    results = [_result("gemini", "g1", "Q1"), _result("gemini", "g1", "Q1")]

    assert len(_pipeline_mod._assignment_yield_rows(results, [])) == 2


# ---------------------------------------------------------------------------
# THE COMPLETION HALF: SURVIVOR COUNTING ON THE SAME RULE
# ---------------------------------------------------------------------------

def _survivors_for(row, survivors):
    """Exactly the count the completion seam computes, via the SAME rule."""
    return sum(
        1 for s in survivors
        if _pipeline_mod._claim_matches_assignment(
            s, provider=row["provider"], group_id=row["group_id"],
            client_question=row["client_question"],
        )
    )


def test_survivors_are_counted_by_the_same_rule_as_claims_kept():
    """If this fires, the numerator and the denominator stop being comparable."""
    row = _pipeline_mod._assignment_yield_rows([_result("gemini", "g1", "Q1")], [])[0]
    survivors = [_claim("a", ["gemini"], "g1"), _claim("b", ["openai"], "g1")]

    assert _survivors_for(row, survivors) == 1


def test_a_survivor_found_by_two_providers_counts_for_both_assignments():
    """Consistently with `claims_kept` — otherwise the ratio exceeds 1."""
    rows = _pipeline_mod._assignment_yield_rows(
        [_result("gemini", "g1", "Q1"), _result("openai", "g1", "Q1")], []
    )
    survivors = [_claim("shared", ["gemini", "openai"], "g1")]

    assert [_survivors_for(r, survivors) for r in rows] == [1, 1]


def test_an_assignment_whose_claims_all_died_completes_with_zero_not_none():
    """If this fires, "verification kept nothing" reads as "never verified".

    `verified_at` being set with a `0` is what distinguishes a bad provider from
    a broken pipeline. A `None` here would erase that distinction — and this is
    the column that tells the two apart.
    """
    row = _pipeline_mod._assignment_yield_rows(
        [_result("gemini", "g1", "Q1")], [_claim("a", ["gemini"], "g1")]
    )[0]

    assert row["claims_kept"] == 1
    assert _survivors_for(row, []) == 0


def test_an_assignment_that_produced_no_claims_completes_with_zero():
    row = _pipeline_mod._assignment_yield_rows([_result("gemini", "g1", "Q1")], [])[0]

    assert row["claims_kept"] == 0
    assert _survivors_for(row, [_claim("a", ["openai"], "g9")]) == 0


def test_cross_cutting_survivors_are_counted_on_the_group_id():
    row = _pipeline_mod._assignment_yield_rows(
        [_result("gemini", "d1", None, _parent_kind="cross_cutting")], []
    )[0]

    assert _survivors_for(row, [_claim("x", ["gemini"], "d1", facet="Q1")]) == 1


def test_the_completion_half_uses_the_captured_rows_not_a_re_derivation():
    """THE MUTANT ROW for the two-halves-agree property.

    The completion seam loops the row set the INSERT seam captured. Re-deriving it
    from `provider_results` would let ANY mid-run change to that list orphan a
    row — and the emitter's `0 rows affected` warning reads 0 as "the INSERT half
    never landed", a confident and completely WRONG diagnosis in the one run there
    is. This test models both strategies and shows they DIVERGE.
    """
    provider_results = [_result("gemini", "g1", "Q1"), _result("openai", "g1", "Q1")]
    captured = _pipeline_mod._assignment_yield_rows(provider_results, [])

    # Something later in the run drops a provider result (a degraded stream is
    # pruned, a list is filtered). The captured rows are unaffected.
    provider_results.pop()
    re_derived = _pipeline_mod._assignment_yield_rows(provider_results, [])

    def keys(rows):
        return {(r["provider"], r["group_id"], r["client_question"]) for r in rows}

    assert len(captured) == 2
    assert keys(re_derived) != keys(captured), (
        "the two strategies must be distinguishable, or this test proves nothing"
    )
    # The seam must address every key the INSERT half wrote.
    assert keys(captured) >= keys(re_derived)


# ---------------------------------------------------------------------------
# SOURCE-TEXT DISCIPLINE
#
# These are CODE-REVIEW guards over the module's EXECUTABLE source, and are
# labelled as such. Docstrings AND comments are stripped, because the prose
# explaining WHY the plain call form is banned would otherwise satisfy a search
# for that very form and turn the guard vacuous on CORRECT source — the
# self-invalidating-criterion trap.
# ---------------------------------------------------------------------------

def _executable_source(module) -> str:
    src = open(module.__file__, encoding="utf-8").read()
    kept = [
        tok for tok in tokenize.generate_tokens(io.StringIO(src).readline)
        if tok.type != tokenize.COMMENT
    ]
    tree = ast.parse(tokenize.untokenize(kept))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            body = node.body
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                body.pop(0)
    return ast.unparse(tree)


def test_the_pipeline_calls_only_the_safe_wrappers():
    """If this fires, a KeyError can escape at the call site and end a paid run.

    A CALLER'S ARGUMENTS ARE EVALUATED BEFORE THE CALLEE IS ENTERED, so wrapping
    the emitter's body protects nothing about the expression that produced its
    arguments. The `_safe` form takes a zero-argument callable and builds the row
    INSIDE its own try.

    Note that `record_assignment(` is NOT a substring of
    `record_assignment_safe(` — the trailing parenthesis is what distinguishes
    them, so no negative lookahead is needed.
    """
    source = _executable_source(_pipeline_mod)

    assert source.count("record_assignment(") == 0
    assert source.count("complete_assignment(") == 0
    assert source.count("record_assignment_safe(") >= 1
    assert source.count("complete_assignment_safe(") >= 1


def test_neither_yield_seam_emits_a_run_events_line():
    """D-W5-1. If this fires, the measurement is being routed back into the feed
    that cannot carry it.

    `RUN_EVENT_KINDS` is a CLOSED twelve-value tuple and an out-of-vocabulary
    `kind` is dropped SILENTLY at `emit`; `_normalise_meta` drops every key not in
    its allowlist, and NOT ONE yield key is in it. Routing this measurement
    through that feed is the inert-instrumentation failure the table exists to
    end.

    SCOPED TO THE TWO SEAM REGIONS, not to the whole module: `pipeline.py` emits
    dozens of legitimate `run_events` lines, so a module-wide assertion would be
    guarding nothing at all. A naive "the string `assignment_yield` never appears"
    check is also wrong — it goes RED on CORRECT source, because the seams' own
    `log.info` lines name the table they write.
    """
    source = _executable_source(_pipeline_mod)

    insert_region = source[
        source.index("record_assignment_safe("):
        source.index("groups: list[dict[str, Any]] = []")
    ]
    completion_region = source[
        source.index("complete_assignment_safe("):
        source.index("rejected_claims: list[dict[str, str]] = []")
    ]

    assert insert_region and completion_region, "the seam markers must be present"
    assert "run_events" not in insert_region
    assert "run_events" not in completion_region


def test_the_insert_seam_sits_before_the_groups_rebind():
    """`groups` is REBOUND from the workshop's question groups to CLAIM groups.

    Anything below that line reading `groups` reads claim groups. The seam sits
    above it so that stays obviously true.
    """
    source = _executable_source(_pipeline_mod)

    insert = source.index("record_assignment_safe(")
    rebind = source.index("groups: list[dict[str, Any]] = []")

    assert insert < rebind


def test_the_completion_seam_sits_after_the_final_survivors_binding():
    """THE ORDERING MUTANT. If this fires, every assignment that lost a conflict
    is over-counted.

    `survivors` is bound three times — by `adjudicate_all`, again after the
    coverage re-entry, and again by conflict resolution. Only the last is final.
    """
    source = _executable_source(_pipeline_mod)

    last_rebind = source.rindex("survivors = kept")
    seam = source.index("complete_assignment_safe(")
    ledger = source.index("rejected_claims: list[dict[str, str]] = []")

    assert seam > last_rebind
    assert seam < ledger
