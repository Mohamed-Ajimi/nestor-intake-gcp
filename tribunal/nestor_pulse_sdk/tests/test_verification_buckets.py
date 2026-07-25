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

All pure: `session=None`, no Postgres, no LLM, no network.

Cloud Build gate:
  gcloud builds submit tribunal \
    --config=tribunal/cloudbuild.test-gates.yaml \
    --project="$GOOGLE_PROJECT"
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from nestor_pulse_sdk.tests.fixtures.run_4cbb5311 import (
    RECORDED_FUNNEL_COUNTS,
    build_verification_summary,
)
from nestor_pulse_sdk.verification.report import shape_verification_report


# ---------------------------------------------------------------------------
# Helpers -- no DB, no fixtures beyond the recorded funnel constant.
# ---------------------------------------------------------------------------

def _shape(*, funnel, rows=None, claim_count: int = 0):
    """Run the pure shaper over an explicit funnel (and optional verdict rows)."""
    return shape_verification_report(
        verdict_rows=rows or [],
        funnel=funnel,
        claim_count=claim_count,
        cost_usd_total=Decimal("1.23"),
        cost_pending=False,
    )


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


def test_recorded_funnel_constant_is_the_single_source():
    """The accounting numbers come from the recorded constant, not a second copy."""
    acc = _shape(funnel=build_verification_summary())["accounting"]
    assert acc["checked"] == RECORDED_FUNNEL_COUNTS["checked"]
    assert (
        acc["should_have_been_checked"]
        == RECORDED_FUNNEL_COUNTS["should_have_been_checked"]
    )
