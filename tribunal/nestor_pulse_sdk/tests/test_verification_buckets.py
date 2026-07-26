"""
G-08 three-bucket accounting + G-09/G-14 client-appendix containment (Phase 15.1,
plan 15.1-06).

WHY THIS FILE EXISTS
--------------------
The 2026-07-22 run published the same figure at two different values (Aral at 16%
and at 21%) and its honesty appendix could not tell the operator why. The report
shaper computed `unverified = total_claims - claims_with_verdict`, which lumps
together two completely different situations:

  * "this claim was never checkable" (the gates ruled it out, on purpose), and
  * "this claim was selected for checking and the fact-checker died before it
    got there" (crash, Anthropic usage cap, budget exhaustion, gate error).

The second group is the dangerous one, and it is invisible in a two-way sum. An
unchecked claim leaves its supporting passage STANDING in the delivered prose --
only a refutation triggers scrubbing -- so bucket 3 is not an accounting line. It
counts PASSAGES THAT SHIPPED UNEXAMINED.

COVERAGE
--------
  1.  three buckets sum to `distilled` on the recorded incident
  2.  bucket 2 carries the SPECIFIC reason, matching the recorded answer key
  3.  bucket 3 is non-zero on the recorded incident (the headline number)
  4.  bucket 3 is zero, and the run is not degraded, on a healthy funnel
  5.  no funnel (a pre-15.1 run) yields `accounting is None`, not a clean zero
  6.  a `superseded` verdict lands in its own class, not in `insufficient` (G-06)
  7.  the pre-existing top-level `superseded` key keeps its reconciliation
      meaning (RESEARCH Pitfall 2 -- the name collision)
  8.  `unverified` keeps its exact shape (the operator surface binds to it)
  9.  `_verification_appendix` is UNCHANGED by this phase (G-09 / G-14)
  10. no coverage percentage is emitted anywhere (G-09 rationale)
  11. `checked_incidentally` is subtracted from bucket 2, per reason (WR-10)
  12. every distilled claim lands in EXACTLY ONE bucket, on three funnel shapes
  13. bucket 2's printed reasons still sum to its own printed total
  14. a 15.1-shaped funnel (no 15.2 keys) still yields a real accounting block
  15. `_ACCOUNTING_KEYS` provably excludes the 15.2 keys (the trap, below)
  16. the recorded run's three-bucket numbers are unmoved by 15.2
  17. incidental counts are clamped and never go negative
  18. the unresolved-anchor count is stated in words (D-06)
  19. degradation reasons are listed as sentences, deduped and capped (D-12)
  20. producer and consumer agree on the incidental total
  21. the WR-10 member loop is still unfiltered (source guard)
  22. a reason from an early stage reaches BOTH published surfaces

15.2 (WR-10 / D-10) -- WHAT "CHECKED INCIDENTALLY" MEANS
--------------------------------------------------------
Claims are fact-checked in GROUPS, and a group is sent for checking when ANY of
its members is worth checking. The skeptic then returns a verdict for EVERY
member of that group -- including the members the gates had already ruled out as
"not checkable". Those verdicts are not decorative: they go to adjudication, they
can refute the claim, and a refuted claim's passage is then DELETED from the
delivered report.

So the engine was doing MORE checking than it said. The funnel reported those
claims as "never checkable" while their verdicts were quietly scrubbing passages.
That is the one-claim-one-bucket invariant breaking in the under-claiming
direction, and it is the reason the accounting moved rather than the behaviour:
the alternative (stop checking those members) would have stopped removing
passages that get removed today, buying tidier books with a less-verified report.
The operator rejected it. `checked_incidentally` is the fourth accounting line
that makes the books honest instead.

All pure: `session=None`, no Postgres, no LLM, no network.

Cloud Build gate:
  gcloud builds submit tribunal \
    --config=tribunal/cloudbuild.test-gates.yaml \
    --project="$GOOGLE_PROJECT"
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from nestor_pulse_sdk.pipeline.tribunal import group_skeptic as _group_skeptic_mod
from nestor_pulse_sdk.pipeline.tribunal import pipeline as _pipeline_mod
from nestor_pulse_sdk.pipeline.tribunal.pipeline import (
    _build_funnel,
    _count_incidental,
    _normalise_degradation_reasons,
)
from nestor_pulse_sdk.tests.fixtures.run_4cbb5311 import (
    RECORDED_FUNNEL_COUNTS,
    build_verification_summary,
)
from nestor_pulse_sdk.verification.report import (
    _ACCOUNTING_KEYS,
    _INCIDENTAL_KEYS,
    _NOT_CHECKABLE_KEYS,
    shape_verification_report,
)


# ---------------------------------------------------------------------------
# Helpers -- no DB, no fixtures beyond the recorded funnel constant.
# ---------------------------------------------------------------------------

def _shape(*, funnel, rows=None, claim_count: int = 0, cost_pending: bool = False):
    """Run the pure shaper over an explicit funnel (and optional verdict rows)."""
    return shape_verification_report(
        verdict_rows=rows or [],
        funnel=funnel,
        claim_count=claim_count,
        cost_usd_total=Decimal("1.23"),
        cost_pending=cost_pending,
    )


def _module_source(module) -> str:
    """Read a module's own source text.

    Resolved from `module.__file__`, NEVER from a repo-root-relative path: the
    Cloud Build context ships only the `tribunal/` subtree, so a path walking up
    to the repo root does not exist there and the guard would fail for the wrong
    reason (or, worse, be quietly skipped).
    """
    return Path(module.__file__).read_text(encoding="utf-8")


def _row(**kw):
    """A verdict row stand-in: the shaper only reads these five attributes."""
    base = {
        "claim_id": None,
        "verdict": "support",
        "confidence": "high",
        "evidence_refs": None,
        "reconciliation": None,
    }
    base.update(kw)
    return SimpleNamespace(**base)


def _healthy_funnel() -> dict:
    """A funnel from a run where every selected claim actually got checked.

    Internally consistent: kept = selected_verify + skipped_stable,
    dropped = not_falsifiable + not_load_bearing + both, and
    distilled = checked + not_checkable_total + should_have_been_checked.
    """
    return {
        "distilled": 1000,
        "kept": 400,
        "dropped": 600,
        "selected_verify": 380,
        "skipped_stable": 20,
        "verify_sessions": 95,
        "not_falsifiable": 300,
        "not_load_bearing": 280,
        "both": 20,
        "checked": 380,
        "should_have_been_checked": 0,
        "gate_errors": 0,
        "verification_degraded": False,
    }


def _incidental_funnel() -> dict:
    """A healthy funnel where 10 gated-out claims got checked anyway (WR-10).

    Built on `_healthy_funnel()`'s numbers so the only thing that changes between
    the two shapes is the incidental population. Bucket 2's own population here is
    600 dropped + 20 stable = 620, which STRICTLY EXCEEDS the 10 incidental checks
    -- the clamp is therefore not what makes these tests pass.
    """
    funnel = _healthy_funnel()
    funnel.update({
        "checked_incidentally": 10,
        "checked_incidentally_not_falsifiable": 0,
        "checked_incidentally_not_load_bearing": 6,
        "checked_incidentally_both": 0,
        "checked_incidentally_stable": 4,
    })
    return funnel


# ---------------------------------------------------------------------------
# G-08 -- the three buckets
# ---------------------------------------------------------------------------

def test_three_buckets_sum_to_distilled():
    """Every distilled claim lands in exactly one bucket: 198 + 738 + 226 == 1162."""
    funnel = build_verification_summary()
    acc = _shape(funnel=funnel)["accounting"]

    total = (
        acc["checked"]
        + acc["not_checkable"]["total"]
        + acc["should_have_been_checked"]
    )
    assert acc["checked"] == 198
    assert acc["not_checkable"]["total"] == 738
    assert acc["should_have_been_checked"] == 226
    assert total == funnel["distilled"] == 1162, (
        "a claim that falls out of the sum is a claim nobody can account for"
    )


def test_bucket_two_reasons_match_recorded_answer_key():
    """NOT CHECKABLE is never a bare total -- each claim carries its own reason."""
    funnel = build_verification_summary()
    nc = _shape(funnel=funnel)["accounting"]["not_checkable"]

    assert nc["not_falsifiable"] == 358
    assert nc["not_load_bearing"] == 320
    assert nc["both"] == 28
    assert nc["stable_known_fact"] == 32

    # The materiality gates' drops plus the error-likelihood gate's stable skips.
    assert nc["total"] == funnel["dropped"] + funnel["skipped_stable"]
    assert (
        nc["not_falsifiable"] + nc["not_load_bearing"] + nc["both"]
        == funnel["dropped"]
    )


def test_bucket_three_is_the_headline_number():
    """SHOULD HAVE BEEN CHECKED BUT WASN'T is non-zero on the recorded incident.

    226 claims were selected for fact-checking and never reached one, because the
    group-skeptic passes were hard-400'd by the Anthropic monthly usage cap.

    This is NOT an accounting line. An unchecked claim keeps its supporting
    passage in the delivered prose -- only a refutation triggers scrubbing -- so
    this number counts PASSAGES THAT SHIPPED UNEXAMINED. It is the single number
    that tells the superadmin the run's verification cannot be trusted.
    """
    report = _shape(funnel=build_verification_summary())
    acc = report["accounting"]

    assert acc["should_have_been_checked"] == 226
    assert acc["should_have_been_checked"] > 0, (
        "bucket 3 must never be silently empty on a run that lost its checking"
    )
    # Bucket 3 is reported on its own; gate errors are a separate line and never
    # absorb it (the recorded run had no gate stage at all, hence zero).
    assert acc["gate_errors"] == 0


def test_healthy_funnel_reports_zero_bucket_three():
    """On a healthy run every selected claim is checked: bucket 3 == 0, not degraded."""
    report = _shape(funnel=_healthy_funnel())
    acc = report["accounting"]

    assert acc["should_have_been_checked"] == 0
    assert acc["checked"] == 380
    assert report["verification_degraded"] is False
    assert (
        acc["checked"] + acc["not_checkable"]["total"] + acc["should_have_been_checked"]
        == 1000
    )


def test_accounting_is_none_without_a_funnel():
    """A pre-15.1 run has verification_summary NULL -- report 'no gate data', not zeros.

    A dict of zeros would read as a clean bucket 3 and quietly certify a run that
    was never gated at all.
    """
    assert _shape(funnel=None)["accounting"] is None
    assert _shape(funnel=None)["verification_degraded"] is False

    # A funnel from before the gate keys existed is equally unknowable.
    legacy = {"distilled": 1162, "kept": 456, "dropped": 706}
    assert _shape(funnel=legacy)["accounting"] is None


# ---------------------------------------------------------------------------
# G-06 -- the superseded verdict class, and the name collision
# ---------------------------------------------------------------------------

def test_superseded_verdict_is_not_counted_as_insufficient():
    """A `superseded` verdict gets its own class instead of being swallowed.

    Before this branch existed the shaper's `else` swept every unrecognised
    verdict string into `insufficient`, so "this was true and has since changed"
    was reported to the operator as "we could not tell". This is the report-shaper
    half of G-06; the producer half lives in test_superseded_verdict.py (plan
    15.1-03), deliberately split so no two plans own one test file.
    """
    rows = [
        _row(verdict="superseded", evidence_refs=["https://example.test/a"]),
        _row(verdict="support"),
    ]
    report = _shape(funnel=None, rows=rows)

    assert len(report["verdicts"]["superseded"]) == 1
    assert report["verdicts"]["superseded"][0]["verdict"] == "superseded"
    assert report["verdicts"]["insufficient"] == []
    assert report["counts"]["superseded_verdicts"] == 1
    # The class split still covers every row.
    groups = report["verdicts"]
    assert (
        len(groups["support"])
        + len(groups["refute"])
        + len(groups["insufficient"])
        + len(groups["superseded"])
        == report["counts"]["verdicts_total"]
    )


def test_existing_superseded_key_keeps_its_reconciliation_meaning():
    """The TOP-LEVEL `superseded` list is a different thing -- RESEARCH Pitfall 2.

    `report["superseded"]` means "a reconciliation-derived scoped/temporal finding
    carrying a canonical value" and is bound by runs/schemas.py, the frontend
    VerificationReport.tsx and test_verification_report_endpoint.py. The new
    `report["verdicts"]["superseded"]` means "the G-06 verdict class". Same word,
    different question -- unifying them would break a shipped surface.
    """
    scoped = _row(
        verdict="support",
        reconciliation={"relation": "scoped", "canonical": "EUR 3.10 per litre"},
    )
    report = _shape(funnel=None, rows=[scoped])

    assert len(report["superseded"]) == 1, "the reconciliation-derived list still fills"
    assert report["verdicts"]["superseded"] == [], "a support verdict is not a verdict class"
    assert report["counts"]["superseded"] == 1
    assert report["counts"]["superseded_verdicts"] == 0


# ---------------------------------------------------------------------------
# G-09 / G-14 -- nothing new reaches the client-facing surfaces
# ---------------------------------------------------------------------------

def test_unverified_key_shape_unchanged():
    """`unverified` keeps EXACTLY its three keys -- the operator surface binds to it.

    `accounting` was added as a SIBLING, not as a replacement, precisely so this
    shape (and the frontend reading it) needs no change.
    """
    report = _shape(funnel=build_verification_summary(), claim_count=50)
    assert set(report["unverified"].keys()) == {
        "count",
        "claims_with_verdict",
        "total_claims",
    }
    assert report["unverified"]["total_claims"] == 50


def test_client_appendix_unchanged():
    """G-14 negative test: `_verification_appendix` must NOT learn any 15.1 vocabulary.

    Operator ruling (G-14, question closed): the client never receives this
    generated report -- only the final report the superadmin hand-crafts and
    submits. The appendix's "Independently fact-checked" arithmetic is therefore
    explicitly OUT OF SCOPE for 15.1, and this test exists to keep it that way.
    If a future plan wants to fix that line, it must first reopen G-14.

    GAP CLOSURE 2026-07-25 (review WR-11): the operator reopened ONE specific
    sentence — the one describing unverified claims as low-stakes supporting
    detail. G-02 had made it false (stakes stopped selecting anything; the gates
    decide, and the count is now simply "claims with no verdict"), and G-14 was a
    scope ruling about ADDING new vocabulary, not a licence to keep a sentence the
    same phase falsified. The replacement introduces no gate/bucket vocabulary, so
    the containment rule below is UNCHANGED and still fully enforced — do not read
    the extra assertions as G-14 being abandoned.
    """
    from nestor_pulse_sdk.pipeline.tribunal.pipeline import _verification_appendix

    text = _verification_appendix(
        n_claims=100,
        n_survivors=80,
        n_dropped=10,
        n_unverified=20,
        n_contested=2,
        budget_exceeded=True,
        reentry_count=1,
        claims_per_facet={"pricing": 30, "regulation": 0},
        n_unresolved_cites=2,
    )

    for phrase in (
        "should_have_been_checked",
        "not_checkable",
        "verification_degraded",
        "gate_errors",
        "accounting",
        "SHOULD HAVE BEEN CHECKED",
        "NOT CHECKABLE",
    ):
        assert phrase not in text, (
            f"G-14: 15.1 vocabulary ({phrase!r}) leaked into the client-facing appendix"
        )

    # Positive control: the appendix still says what it always said, so the test
    # above is proving containment rather than passing on an empty string.
    assert "## Verification" in text
    assert "**Factual statements extracted and reviewed:** 100" in text
    assert "**Independently fact-checked against the live web:** 80" in text

    # WR-11: the false sentence must never come back. Stakes no longer selects what
    # gets checked (G-02), so describing these claims by their stakes tier misstates
    # the engine to the reader of a report they cannot audit.
    assert "low-stakes" not in text, (
        "WR-11: stakes no longer selects what gets checked (G-02) — the appendix "
        "must not describe unverified claims by a stakes tier"
    )
    assert "Waved through" not in text, (
        "WR-11: stakes no longer selects what gets checked (G-02) — nothing is "
        "'waved through' on a stakes basis any more"
    )
    # Positive control for the replacement (the call above passes n_unverified=20).
    assert "**Not independently fact-checked:** 20" in text


def test_no_coverage_percentage_in_report():
    """No percentage anywhere -- any denominator this surface could offer is false.

    The delivered report is written from SCRUBBED PROSE, not from the claim list,
    so "X of Y statements verified" cannot be computed honestly. That is the
    reason G-09 made this surface superadmin-only instead of client-facing.
    """
    report = _shape(funnel=build_verification_summary(), claim_count=1162)

    def key_names(node):
        if isinstance(node, dict):
            for key, value in node.items():
                yield key
                yield from key_names(value)
        elif isinstance(node, list):
            for item in node:
                yield from key_names(item)

    for key in key_names(report):
        assert not key.endswith("_pct"), f"percentage key {key!r} emitted"
        assert not key.endswith("_percentage"), f"percentage key {key!r} emitted"
        assert "percent" not in key.lower(), f"percentage key {key!r} emitted"

    # Structural values this plan owns carry no percentage strings either.
    for section in (report["accounting"], report["counts"], report["funnel"]):
        for value in section.values():
            assert not (isinstance(value, str) and "%" in value)
    assert "%" not in (report["verification_degraded_text"] or "")


def test_new_keys_survive_the_pydantic_boundary():
    """T-15.1-26: a truth the shaper produces must not vanish on the way out.

    `VerificationReport` has `extra="allow"`, so top-level additions ride through
    free -- but its NESTED models (`VerificationVerdictGroups`,
    `VerificationVerdictItem`, `VerificationUnverified`) have no `model_config`,
    which means pydantic v2's default `extra="ignore"` silently DROPS anything
    not declared as a field. Without the explicit `superseded` field the shaper
    would compute the verdict class correctly and the API would return nothing.
    This test round-trips the shaped dict through the response model.
    """
    from nestor_pulse_sdk.runs.schemas import VerificationReport

    rows = [_row(verdict="superseded", evidence_refs=["https://example.test/a"])]
    report = _shape(funnel=build_verification_summary(), rows=rows, claim_count=1162)

    dumped = VerificationReport(**report).model_dump()

    assert dumped["accounting"]["should_have_been_checked"] == 226
    assert dumped["accounting"]["not_checkable"]["not_falsifiable"] == 358
    assert dumped["verification_degraded"] is True
    assert "not checked" in dumped["verification_degraded_text"].lower()
    assert len(dumped["verdicts"]["superseded"]) == 1, (
        "the verdict class was dropped at the API boundary (missing pydantic field)"
    )
    assert dumped["verdicts"]["superseded"][0]["verdict"] == "superseded"
    # The pre-existing surfaces still cross intact.
    assert set(dumped["unverified"].keys()) == {
        "count",
        "claims_with_verdict",
        "total_claims",
    }
    assert dumped["counts"]["superseded_verdicts"] == 1

    # 15.2: the three new top-level keys and the fourth accounting line must
    # survive the same round trip. `unresolved_anchors` / `unresolved_anchors_text`
    # / `degradation_reasons` are DECLARED on VerificationReport rather than left to
    # ride on `extra="allow"`, for the reason this file's docstring gives: a truth
    # the shaper computes and the boundary drops reads to the operator as "there is
    # no such caveat".
    funnel = _incidental_funnel()
    funnel["unresolved_anchors"] = 3
    funnel["degradation_reasons"] = [
        "Gemini research stream lost -- circuit breaker open."
    ]
    dumped2 = VerificationReport(**_shape(funnel=funnel, claim_count=1000)).model_dump()

    assert dumped2["accounting"]["checked_incidentally"]["total"] == 10
    assert dumped2["unresolved_anchors"] == 3
    assert dumped2["unresolved_anchors_text"] is not None
    assert "3" in dumped2["unresolved_anchors_text"]
    assert dumped2["degradation_reasons"], (
        "the degradation reason list was dropped at the API boundary"
    )


def test_recorded_funnel_constant_is_the_single_source():
    """The accounting numbers come from the recorded constant, not a second copy."""
    acc = _shape(funnel=build_verification_summary())["accounting"]
    assert acc["checked"] == RECORDED_FUNNEL_COUNTS["checked"]
    assert (
        acc["should_have_been_checked"]
        == RECORDED_FUNNEL_COUNTS["should_have_been_checked"]
    )


# ---------------------------------------------------------------------------
# WR-10 / D-10 Option 2 -- the fourth accounting line
# ---------------------------------------------------------------------------

def test_checked_incidentally_is_subtracted_from_bucket_two():
    """A claim that was gated out but checked anyway leaves bucket 2, by reason.

    It does not vanish: it lands in the `checked_incidentally` block, carrying the
    SAME gate reason it had in bucket 2, so the operator can see exactly which
    "not checkable" claims turned out to be checked after all.
    """
    acc = _shape(funnel=_incidental_funnel())["accounting"]

    assert acc["checked_incidentally"]["total"] == 10
    assert acc["checked_incidentally"]["not_load_bearing"] == 6
    assert acc["checked_incidentally"]["stable_known_fact"] == 4

    nc = acc["not_checkable"]
    assert nc["not_load_bearing"] == 274, "280 gated out, 6 of them checked anyway"
    assert nc["stable_known_fact"] == 16, "20 stable skips, 4 of them checked anyway"
    # The two reasons with no incidental checks keep their raw values untouched.
    assert nc["not_falsifiable"] == 300
    assert nc["both"] == 20


def test_every_distilled_claim_lands_in_exactly_one_bucket():
    """THE RECONCILIATION TEST -- the invariant WR-10 broke.

    Every distilled claim must be countable in exactly one place:

        checked + checked_incidentally.total + not_checkable.total
                + should_have_been_checked  ==  distilled

    WR-10 broke this in the UNDER-CLAIMING direction: claims that had actually been
    checked (and whose verdicts were scrubbing passages out of the delivered
    report) were published to the operator as "never checkable". Proven here on all
    three funnel shapes, so neither the recorded run nor a healthy run nor a run
    with real incidental checking can drift out of balance.
    """
    for name, funnel in (
        ("incidental", _incidental_funnel()),
        ("recorded", build_verification_summary()),
        ("healthy", _healthy_funnel()),
    ):
        acc = _shape(funnel=funnel)["accounting"]
        total = (
            acc["checked"]
            + acc["checked_incidentally"]["total"]
            + acc["not_checkable"]["total"]
            + acc["should_have_been_checked"]
        )
        assert total == funnel["distilled"], (
            f"{name} funnel: a claim that falls out of the sum is a claim nobody "
            f"can account for ({total} != {funnel['distilled']})"
        )

    # The recorded run's own arithmetic, spelled out: 198 + 0 + 738 + 226 == 1162.
    acc = _shape(funnel=build_verification_summary())["accounting"]
    assert acc["checked"] == 198
    assert acc["checked_incidentally"]["total"] == 0
    assert acc["not_checkable"]["total"] == 738
    assert acc["should_have_been_checked"] == 226


def test_bucket_two_reasons_still_sum_to_their_own_total():
    """An operator who adds up the printed reasons must get the printed total."""
    nc = _shape(funnel=_incidental_funnel())["accounting"]["not_checkable"]
    assert (
        nc["not_falsifiable"] + nc["not_load_bearing"] + nc["both"]
        + nc["stable_known_fact"]
        == nc["total"]
    ), "bucket 2's total must be the sum of its four REDUCED reasons, not the raw sum"
    assert nc["total"] == 610, "620 gated out, 10 of them checked incidentally"

    # The same rule holds for the incidental block itself.
    inc = _shape(funnel=_incidental_funnel())["accounting"]["checked_incidentally"]
    assert (
        inc["not_falsifiable"] + inc["not_load_bearing"] + inc["both"]
        + inc["stable_known_fact"]
        == inc["total"]
    )


def test_accounting_survives_a_funnel_with_no_incidental_keys():
    """THE TRAP: a 15.1-shaped funnel must still produce a real accounting block.

    `_accounting` returns None when any `_ACCOUNTING_KEYS` member is missing -- that
    is deliberate and load-bearing, because it is how the shaper DETECTS a pre-15.1
    run and reports "no gate data" instead of a dict of zeros that would read as a
    clean bucket 3.

    If `checked_incidentally` (or any of its four reason keys) were added to
    `_ACCOUNTING_KEYS`, EVERY funnel written before 15.2 -- including every run
    already in the database -- would fail that membership test and report
    `accounting: None`. The operator surface would go blank on runs that have
    perfectly good gate data. The new keys are read with `funnel.get(key, 0)`
    precisely so that cannot happen.
    """
    funnel = _healthy_funnel()
    assert not any(key in funnel for key in _INCIDENTAL_KEYS), (
        "this test is only meaningful against a funnel with NO 15.2 keys"
    )

    acc = _shape(funnel=funnel)["accounting"]
    assert acc is not None, "a 15.1 funnel is not a run without gate data"
    assert acc["checked"] == 380
    assert acc["checked_incidentally"]["total"] == 0
    assert acc["not_checkable"]["total"] == 620, "nothing is subtracted when nothing rode along"


def test_accounting_keys_tuple_excludes_the_incidental_keys():
    """The structural guard that makes the trap above unwalkable.

    Asserted on the TUPLE rather than on behaviour, so a future edit that adds a
    15.2 key to `_ACCOUNTING_KEYS` fails here with the reason attached instead of
    silently blanking the accounting block on every historical run.
    """
    assert set(_ACCOUNTING_KEYS) == (
        {"checked", "should_have_been_checked", "gate_errors"} | set(_NOT_CHECKABLE_KEYS)
    ), (
        "_ACCOUNTING_KEYS gained or lost a member. It is the pre-15.1 DETECTOR: "
        "every key in it must be present in a funnel for `accounting` to be a dict "
        "at all, so adding a 15.2 key here reports 'no gate data' for every run "
        "written before 15.2."
    )
    for key in _ACCOUNTING_KEYS:
        assert not key.startswith("checked_incidentally"), (
            f"{key!r} is a 15.2 key and must be read with funnel.get(), not gated on"
        )
        assert key not in ("unresolved_anchors", "degradation_reasons"), (
            f"{key!r} is a 15.2 key and must be read with funnel.get(), not gated on"
        )
    # The two tuples are POSITIONALLY PAIRED -- _accounting zips them.
    assert len(_INCIDENTAL_KEYS) == len(_NOT_CHECKABLE_KEYS)
    for nc_key, inc_key in zip(_NOT_CHECKABLE_KEYS, _INCIDENTAL_KEYS):
        stem = "stable" if nc_key == "skipped_stable" else nc_key
        assert inc_key == f"checked_incidentally_{stem}", (
            "the incidental keys must stay in the same order as the bucket-2 "
            "reasons they are subtracted from, or _accounting subtracts the wrong "
            "count from the wrong reason"
        )


def test_recorded_run_reports_zero_incidental_checks():
    """The recorded numbers must not move: 198 / 738 / 226, and 0 incidental.

    Zero here is a FACT about the recorded run, not a placeholder: it had no gate
    stage at all, so no claim was gate-DROPped or SKIP_STABLE at run time and no
    claim could be checked incidentally.
    """
    acc = _shape(funnel=build_verification_summary())["accounting"]

    assert acc["checked_incidentally"]["total"] == 0
    assert acc["not_checkable"]["total"] == 738
    assert acc["not_checkable"]["not_falsifiable"] == 358
    assert acc["not_checkable"]["not_load_bearing"] == 320
    assert acc["not_checkable"]["both"] == 28
    assert acc["not_checkable"]["stable_known_fact"] == 32


def test_incidental_counts_are_clamped_and_never_negative():
    """A malformed funnel must not drive a bucket-2 reason negative.

    A count above bucket 2's own population is an accounting lie in the other
    direction, and an unclamped subtraction would publish a negative reason count
    and break the one-bucket sum. Clamped per reason, mirroring `_build_funnel`'s
    `min(unchecked_selected, selected)`.
    """
    funnel = _healthy_funnel()
    funnel.update({
        "checked_incidentally": 999,
        "checked_incidentally_not_falsifiable": -5,
        "checked_incidentally_not_load_bearing": 0,
        "checked_incidentally_both": 0,
        "checked_incidentally_stable": 999,
    })
    acc = _shape(funnel=funnel)["accounting"]

    assert acc["not_checkable"]["stable_known_fact"] == 0, "20 stable skips, all of them"
    assert acc["checked_incidentally"]["stable_known_fact"] == 20, "clamped to the population"
    assert acc["checked_incidentally"]["not_falsifiable"] == 0, "a negative count is zero"

    def _ints(node):
        if isinstance(node, dict):
            for value in node.values():
                yield from _ints(value)
        elif isinstance(node, int) and not isinstance(node, bool):
            yield node

    assert all(value >= 0 for value in _ints(acc)), "no accounting value may be negative"

    total = (
        acc["checked"]
        + acc["checked_incidentally"]["total"]
        + acc["not_checkable"]["total"]
        + acc["should_have_been_checked"]
    )
    assert total == funnel["distilled"], "the one-bucket sum survives a malformed funnel"


# ---------------------------------------------------------------------------
# D-06 -- the unresolved-anchor count, in words
# ---------------------------------------------------------------------------

def test_unresolved_anchor_count_is_stated_in_words():
    """D-06 / V-02 #9: the count is a sentence, and a healthy run says nothing."""
    funnel = _healthy_funnel()
    funnel["unresolved_anchors"] = 7
    report = _shape(funnel=funnel)

    assert report["unresolved_anchors"] == 7
    text = report["unresolved_anchors_text"]
    assert isinstance(text, str) and len(text) > 40, (
        "a bare integer is not 'stated in words' (Cross-Cutting Rule 6)"
    )
    assert "7" in text
    assert "%" not in text, "no percentage: every denominator this surface has is false"

    # Absent, and explicitly zero, both say nothing -- a marker that renders on
    # every run is one the operator stops reading.
    assert _shape(funnel=_healthy_funnel())["unresolved_anchors"] == 0
    assert _shape(funnel=_healthy_funnel())["unresolved_anchors_text"] is None
    zeroed = _healthy_funnel()
    zeroed["unresolved_anchors"] = 0
    assert _shape(funnel=zeroed)["unresolved_anchors_text"] is None


# ---------------------------------------------------------------------------
# D-12 -- the degradation reasons, as sentences
# ---------------------------------------------------------------------------

def test_degradation_reasons_names_bucket_three_on_the_recorded_run():
    """The recorded run stores [] and STILL names its degradation to the operator.

    The fixture carries `degradation_reasons: []` because the recorded run has no
    machine-readable reason list -- its degradation was recorded as a boolean plus
    prose. The shaper DERIVES the bucket-3 sentence at read time, which is why the
    pipeline deliberately never writes one: exactly ONE wording of that sentence
    exists in the codebase, so the operator cannot be told the same shortfall twice
    in two dialects.
    """
    report = _shape(funnel=build_verification_summary())

    assert len(report["degradation_reasons"]) == 1
    assert report["degradation_reasons"][0] == report["verification_degraded_text"]
    assert "226" in report["degradation_reasons"][0]


def test_degradation_reasons_carries_pipeline_reasons_and_dedupes():
    """The pipeline's own reasons ride along; junk is dropped and nothing raises."""
    gemini = "Gemini research stream lost -- circuit breaker open."
    funnel = build_verification_summary()
    funnel["degradation_reasons"] = [gemini, "  ", gemini, 42]

    reasons = _shape(funnel=funnel)["degradation_reasons"]

    assert len(reasons) == 2, "the blank, the duplicate and the non-string are dropped"
    assert reasons[0] == _shape(funnel=funnel)["verification_degraded_text"], (
        "the derived bucket-3 sentence leads -- it is the headline shortfall"
    )
    assert reasons[1] == gemini


def test_recovered_retries_and_cost_pending_never_add_a_reason():
    """D-12, verbatim: recovery is not shortfall, and pending is not missing.

    A retry that succeeded is the reliability layer WORKING, and `cost_pending` is
    the designed pending-then-backfill-exact path. Reporting either as degradation
    would drain `completed_degraded` of its meaning long before a real one arrives.
    """
    funnel = _healthy_funnel()
    funnel["verify_sessions"] = 120          # retries bumped the session count
    report = _shape(funnel=funnel, cost_pending=True)

    assert report["degradation_reasons"] == []
    assert report["verification_degraded"] is False
    assert report["true_cost"]["cost_pending"] is True


# ---------------------------------------------------------------------------
# Producer <-> consumer agreement, and the two source guards
# ---------------------------------------------------------------------------

def test_funnel_incidental_total_agrees_with_its_breakdown():
    """The pipeline's counter and the report's accounting must report one number."""
    verify_hit = {"text": "a", "gate": {"decision": "KEEP", "reason": "KEEP", "strict": "VERIFY"}}
    stable_hit = {"text": "b", "gate": {"decision": "KEEP", "reason": "KEEP", "strict": "SKIP_STABLE"}}
    dropped_hit = {
        "text": "c",
        "gate": {"decision": "DROP", "reason": "NOT_LOAD_BEARING", "strict": None},
    }
    dropped_miss = {
        "text": "d",
        "gate": {"decision": "DROP", "reason": "NOT_FALSIFIABLE", "strict": None},
    }
    no_gate = {"text": "e"}
    claims = [verify_hit, stable_hit, dropped_hit, dropped_miss, no_gate]

    verdicts_by_claim = {id(c): [] for c in claims}
    for claim in (verify_hit, stable_hit, dropped_hit):
        verdicts_by_claim[id(claim)] = [{"verdict": "support"}]

    incidental = _count_incidental(claims, verdicts_by_claim)

    assert incidental["checked_incidentally_stable"] == 1
    assert incidental["checked_incidentally_not_load_bearing"] == 1
    assert incidental["checked_incidentally_not_falsifiable"] == 0, (
        "a gated-out claim with NO verdict was never checked at all"
    )
    assert incidental["checked_incidentally_both"] == 0
    assert incidental["checked_incidentally"] == 2, (
        "the total is the sum of the four reasons, computed once so they cannot "
        "disagree"
    )

    gate_funnel = {
        "distilled": 5, "kept": 3, "dropped": 2,
        "not_falsifiable": 1, "not_load_bearing": 1, "both": 0,
        "selected_verify": 1, "skipped_stable": 2, "gate_errors": 0,
    }
    funnel = _build_funnel(
        gate_funnel,
        unchecked_selected=0,
        verify_sessions=1,
        incidental=incidental,
    )
    acc = _shape(funnel=funnel)["accounting"]

    assert funnel["checked_incidentally"] == acc["checked_incidentally"]["total"] == 2, (
        "producer and consumer must publish one number, not two that disagree"
    )
    total = (
        acc["checked"]
        + acc["checked_incidentally"]["total"]
        + acc["not_checkable"]["total"]
        + acc["should_have_been_checked"]
    )
    assert total == funnel["distilled"]


def test_the_wr10_member_loop_is_not_filtered():
    """Option 1 must stay rejected -- a source guard, in the test_gate_selector register.

    Filtering the group-skeptic member loop to gate-selected claims only would make
    the books tidier and the REPORT LESS VERIFIED: passages that are scrubbed today
    (because a gated-out member came back refuted) would silently start shipping.
    The operator rejected that trade.

    If this test goes red because somebody added the filter, the fix is to remove
    the filter, not the test.
    """
    pipeline_src = _module_source(_pipeline_mod)
    skeptic_src = _module_source(_group_skeptic_mod)

    assert "WR-10 / D-10 Option 2" in pipeline_src, (
        "the decision marker vanished from pipeline.py's member loop"
    )
    assert "WR-10 / D-10 Option 2" in skeptic_src, (
        "the decision marker vanished from group_skeptic.py's fill loop"
    )
    for name, src in (("pipeline.py", pipeline_src), ("group_skeptic.py", skeptic_src)):
        assert "# gated out: bucket 2 owns it" not in src, (
            f"{name}: the rejected Option-1 filter marker is present"
        )


def test_a_reason_from_an_early_stage_reaches_both_published_surfaces():
    """THE CROSS-PLAN INTEGRATION TEST -- one accumulator, one normaliser, two surfaces.

    `run()` holds exactly ONE degradation-reason list. A SECOND binding of that name
    anywhere in the function would rebind it to a fresh empty list, so a reason
    appended by an earlier stage -- the question-workshop fallback, a lost
    own-researcher stream, a fact-list fallback -- would be discarded before either
    publisher ever read it, and the run would report clean. No single plan's unit
    tests would catch that, because each tests its own accumulator in isolation.
    This test is what keeps the two surfaces one.

    The top-level result key is what `runs/worker.py` reads and feeds to
    `terminal_state()`; the funnel key is what the superadmin verification report
    reads. Zero LLM, zero DB, zero network: module source text plus two pure calls.
    """
    src = _module_source(_pipeline_mod)
    lines = src.splitlines()

    # (a) exactly ONE binding, and exactly one writer.
    decl_pattern = re.compile(r"^\s*degradation_reasons\s*(:\s*list\[str\]\s*)?=\s*\[\]")
    decl_lines = [i for i, line in enumerate(lines) if decl_pattern.match(line)]
    assert len(decl_lines) == 1, (
        "pipeline.run() must bind `degradation_reasons` exactly once "
        f"(found {len(decl_lines)} bindings at lines {[i + 1 for i in decl_lines]}). "
        "A second binding rebinds the name to a fresh empty list, so a reason from "
        "the workshop fallback, a lost research stream or a fact-list fallback is "
        "discarded before _build_funnel or _write_final_report ever reads it, and "
        "the run reports clean."
    )
    assert src.count("def _note_degradation") == 1, (
        "there must be exactly one writer for the reason list"
    )

    # (b) the binding is EARLY enough -- before the resume-from-cache early return,
    #     so both return paths publish the same shape.
    resume_lines = [
        i for i, line in enumerate(lines) if "cached_spec = await _read_output(" in line
    ]
    assert resume_lines, "the resume-from-cache read moved or was renamed"
    assert decl_lines[0] < resume_lines[0], (
        "the accumulator must exist before the resume-from-cache early return"
    )

    # (c) both surfaces are published FROM that one list.
    assert '"degradation_reasons": degradation_reasons' in src, (
        "the synthesis-bundle surface must carry the accumulator itself"
    )
    assert '"degradation_reasons": _normalise_degradation_reasons(' in src, (
        "the top-level result key must go through the shared normaliser"
    )
    assert "degradation_reasons=degradation_reasons" in src, (
        "the real _build_funnel call site must hand the accumulator to the funnel"
    )

    # (d) the two surfaces carry IDENTICAL content, by construction.
    reason = (
        "Gemini research stream lost -- circuit breaker open, so one of two "
        "research streams is missing from this report."
    )
    assert _normalise_degradation_reasons([reason]) == [reason]
    assert _build_funnel(
        None, unchecked_selected=0, verify_sessions=0, degradation_reasons=[reason]
    )["degradation_reasons"] == [reason]

    # (e) and are capped identically.
    many = ["x" * 400] + [f"distinct degradation reason number {n}" for n in range(9)]
    normalised = _normalise_degradation_reasons(many)
    published = _build_funnel(
        None, unchecked_selected=0, verify_sessions=0, degradation_reasons=many
    )["degradation_reasons"]

    assert published == normalised, "one normaliser, one result, both surfaces"
    for published_list in (normalised, published):
        assert len(published_list) <= 8
        assert all(len(entry) <= 200 for entry in published_list)
