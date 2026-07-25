"""
The PUBLISHING half of the verification report: the caveat reaches the wire, and
the payload cannot contradict itself (Phase 15.1, plan 15.1-12).

WHY THIS FILE EXISTS
--------------------
Two defects made SC2 false, and both were invisible to the existing suite because
every 15.1 test drove `shape_verification_report` with hand-built rows that never
carried the field, or asserted a key set rather than the numbers inside it.

CR-01 leg b -- the caveat that never crossed. `runs/schemas.py` declared
`VerificationVerdictItem.superseded_note` with a comment claiming it "survives the
round trip", the group skeptic was required to supply it with a `superseded`
verdict, and migration 0012 gave it a column. But `_verdict_dto` returned five
keys and never emitted it, so pydantic's `extra="ignore"` had nothing to carry:
the wire value was unconditionally None no matter what was stored. The DTO is the
gate, and nothing tested the gate.

CR-02 -- the payload that disagreed with itself. Nothing in production wrote a
`verification_verdict` row, so `claims_with_verdict` was 0 and the shaper
published `unverified.count == total_claims` in the SAME payload as the honest
`accounting.checked`. The operator read "checked: 380" beside
"unverified: 1162 of 1162" and had no way to tell which number to believe. Plan
15.1-14 lands the writer that stops that in normal operation; the fallback these
tests pin makes it impossible even if that writer regresses, by deriving the
unverified figure from the same funnel the accounting block already uses.

COVERAGE
--------
  1. a stored `superseded_note` reaches the shipped `verdicts.superseded` entry
  2. rows WITHOUT the attribute still shape (the getattr default)
  3. the fallback engages: the unverified figure agrees with the funnel
  4. the fallback clamps -- never a negative count
  5. the fallback does NOT engage when verdict rows exist
  6. the fallback does NOT engage without gate data (a pre-15.1 run)
  7. `unverified` keeps EXACTLY its three keys through the fallback
  8. both new top-level keys, and the caveat, survive the pydantic boundary

All pure: no Postgres, no network, no provider key, no third-party API call.

Cloud Build gate:
  gcloud builds submit tribunal \
    --config=tribunal/cloudbuild.test-gates.yaml \
    --project="$GOOGLE_PROJECT"
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from nestor_pulse_sdk.verification.report import shape_verification_report


# ---------------------------------------------------------------------------
# Helpers -- local by design. Sibling test modules keep their own copies rather
# than importing each other's privates, so one file's edit cannot silently move
# another file's goalposts.
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
    """A verdict row stand-in carrying ONLY the five legacy attributes.

    Deliberately NOT including `superseded_note` in the base: test 2 depends on
    this builder producing a row that does not have the attribute at all, which
    is exactly the shape of the SimpleNamespace fakes in
    test_verification_buckets.py and of the ORM rows built by
    tests/fixtures/run_4cbb5311/loader.py. Pass it explicitly to add it.
    """
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
    """A fully-keyed funnel: every gate key `_ACCOUNTING_KEYS` needs is present.

    `checked: 380` with `should_have_been_checked: 0` and `gate_errors: 0` -- a
    run whose gate stage did its whole job. That is the case that makes the CR-02
    contradiction most glaring: real gate work recorded, zero verdict rows.
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
# CR-01 leg b -- the caveat crosses the DTO
# ---------------------------------------------------------------------------

def test_verdict_dto_carries_superseded_note():
    """A stored G-07 caveat reaches the shipped report, not an unconditional None.

    Asserted through `shape_verification_report` rather than the private
    `_verdict_dto`, because the shipped path is what the API returns: a DTO that
    computed the value correctly but whose key never reached the report would
    still be a caveat the operator never sees.
    """
    note = "applied until 1 April 2026"
    rows = [_row(verdict="superseded", superseded_note=note)]
    report = _shape(funnel=None, rows=rows)

    entries = report["verdicts"]["superseded"]
    assert len(entries) == 1, "the G-06 verdict class must still be classed correctly"
    assert entries[0]["superseded_note"] == note, (
        "the skeptic's caveat (what changed, from when) was dropped between the "
        "persisted row and the report -- CR-01 leg b"
    )


def test_verdict_dto_tolerates_rows_without_the_attribute():
    """A five-attribute row must not raise; the key is present and None.

    The regression guard for the `getattr` default. Rows reach the shaper in
    three shapes and only one of them carries the column: a bare attribute
    access would AttributeError the SimpleNamespace fakes in
    test_verification_buckets.py and the fixture loader's ORM rows.
    """
    legacy = _row(verdict="support")
    assert not hasattr(legacy, "superseded_note"), (
        "this test is worthless if the builder quietly grew the attribute"
    )

    report = _shape(funnel=None, rows=[legacy])
    entry = report["verdicts"]["support"][0]

    assert "superseded_note" in entry, "the key must always be emitted, even as None"
    assert entry["superseded_note"] is None


# ---------------------------------------------------------------------------
# CR-02 -- the payload cannot contradict itself
# ---------------------------------------------------------------------------

def test_unverified_falls_back_to_the_funnel_when_no_verdict_rows():
    """Zero verdict rows + real gate data -> the unverified figure agrees with it.

    This is the headline. Before the fallback, this exact input published
    `unverified.count == total_claims` next to `accounting.checked == 380`.
    """
    report = _shape(funnel=_healthy_funnel(), rows=[], claim_count=400)
    unverified = report["unverified"]

    assert report["accounting"]["checked"] == 380
    assert unverified["claims_with_verdict"] == 380, (
        "the fallback must adopt the funnel's checked count, not the row count"
    )
    assert unverified["count"] == 20
    assert unverified["total_claims"] == 400
    assert report["unverified_from_accounting"] is True
    assert isinstance(report["unverified_note"], str) and report["unverified_note"], (
        "a derived figure must say in WORDS that it is derived"
    )
    assert report["counts"]["verdicts_total"] == 0

    assert unverified["count"] != unverified["total_claims"], (
        "the shipped contradiction is back: a payload cannot publish "
        '"checked: 380" beside "unverified: 1162 of 1162" and expect the '
        "operator to trust either number"
    )


def test_fallback_clamps_when_checked_exceeds_persisted_claims():
    """Never negative: `checked` and `claim_count` have different denominators.

    `claim_count` counts persisted survivor `claim` rows; `checked` counts gated
    claims. An unclamped subtraction would publish a negative unverified count.
    """
    report = _shape(funnel=_healthy_funnel(), rows=[], claim_count=100)
    unverified = report["unverified"]

    assert unverified["claims_with_verdict"] == 100, "clamped to the persisted claims"
    assert unverified["count"] == 0
    assert unverified["count"] >= 0
    assert report["unverified_from_accounting"] is True


def test_fallback_does_not_engage_when_verdict_rows_exist():
    """One verdict row is enough: the row-derived arithmetic stands untouched.

    Pins that this fix did not move the recorded-fixture behaviour asserted by
    test_verification_report_endpoint::test_unverified_is_honest_count, whose
    rows carry `claim_id=None` (the recorded run predates claim linkage) and so
    legitimately report `claims_with_verdict == 0`.
    """
    report = _shape(funnel=_healthy_funnel(), rows=[_row()], claim_count=50)
    unverified = report["unverified"]

    assert report["counts"]["verdicts_total"] == 1
    assert report["unverified_from_accounting"] is False
    assert report["unverified_note"] is None
    assert unverified["claims_with_verdict"] == 0
    assert unverified["count"] == 50, (
        "with verdict rows present the honest row-derived count must survive "
        "untouched, even when it equals total_claims"
    )
    assert unverified["total_claims"] == 50


def test_fallback_does_not_engage_without_gate_data():
    """A pre-15.1 run has no funnel -- do not invent numbers for it.

    `accounting is None` means "we have no gate data", which is not the same as
    "the gate checked nothing". Deriving a figure from absent data would be the
    same class of lie the fallback exists to prevent.
    """
    report = _shape(funnel=None, rows=[], claim_count=400)

    assert report["accounting"] is None
    assert report["unverified_from_accounting"] is False
    assert report["unverified_note"] is None
    assert report["unverified"]["count"] == 400

    # A funnel from before the gate keys existed is equally unknowable.
    legacy = _shape(funnel={"distilled": 1162, "kept": 456}, rows=[], claim_count=400)
    assert legacy["accounting"] is None
    assert legacy["unverified_from_accounting"] is False


def test_unverified_key_shape_survives_the_fallback():
    """The fallback changes VALUES, never KEYS.

    Two existing tests assert this key set exactly, and the shipped operator
    surface binds to those three keys. The caveat is carried by TOP-LEVEL
    siblings precisely so this block never has to change shape.
    """
    report = _shape(funnel=_healthy_funnel(), rows=[], claim_count=400)

    assert report["unverified_from_accounting"] is True, "the fallback must be engaged"
    assert set(report["unverified"].keys()) == {
        "count",
        "claims_with_verdict",
        "total_claims",
    }
    assert "unverified_from_accounting" not in report["unverified"]
    assert "unverified_note" not in report["unverified"]


# ---------------------------------------------------------------------------
# The API boundary -- a truth the shaper produces must not vanish on the way out
# ---------------------------------------------------------------------------

def test_new_top_level_keys_survive_the_pydantic_boundary():
    """Declared, not silently dropped -- and the caveat round trip finally proven.

    `VerificationReport` carries `extra="allow"`, so an undeclared key WOULD ride
    through; the two fields are declared anyway per the file's own
    "Declare, don't assume" rule. `VerificationVerdictItem` is the opposite case:
    it defaults to `extra="ignore"`, so `superseded_note` only crosses because it
    is a declared field AND the DTO now emits it. The comment at
    runs/schemas.py:237 claimed that round trip; nothing proved it until here.
    """
    from nestor_pulse_sdk.runs.schemas import VerificationReport

    note = "applied until 1 April 2026"
    with_rows = _shape(
        funnel=_healthy_funnel(),
        rows=[_row(verdict="superseded", superseded_note=note)],
        claim_count=400,
    )
    dumped = VerificationReport.model_validate(with_rows).model_dump()

    assert "unverified_from_accounting" in dumped
    assert "unverified_note" in dumped
    assert dumped["unverified_from_accounting"] is False
    assert dumped["verdicts"]["superseded"][0]["superseded_note"] == note, (
        "the caveat was dropped at the API boundary -- exactly the failure mode "
        "extra='ignore' produces for a key the DTO does not emit"
    )

    # And the fallback's own words must cross too, or the payload would look
    # authoritative while the sentence explaining its derivation went missing.
    fallback = _shape(funnel=_healthy_funnel(), rows=[], claim_count=400)
    dumped_fallback = VerificationReport.model_validate(fallback).model_dump()

    assert dumped_fallback["unverified_from_accounting"] is True
    assert isinstance(dumped_fallback["unverified_note"], str)
    assert dumped_fallback["unverified_note"], "the caveat sentence must not be empty"
    assert dumped_fallback["unverified"]["count"] == 20
    assert set(dumped_fallback["unverified"].keys()) == {
        "count",
        "claims_with_verdict",
        "total_claims",
    }
