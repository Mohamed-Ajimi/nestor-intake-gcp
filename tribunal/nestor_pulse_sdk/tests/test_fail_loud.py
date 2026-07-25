"""
G-10 fail-loud marker: a gutted run says so in WORDS (Phase 15.1, plan 15.1-06).

WHY THIS FILE EXISTS
--------------------
The 2026-07-22 run finished with status `completed` after 776 of its ~950
fact-checking passes were hard-400'd by the Anthropic monthly usage cap. Nothing
in the run's own output said so. A run that lost its verification and still
reports green is the repudiation failure this phase exists to close.

G-10's ruling is deliberately narrow, and this file pins both halves of it:

  * The status vocabulary does NOT change. Four API endpoints gate on
    `status == "completed"` (report download, audit bundle, verification report);
    adding `completed_degraded` now would lock the superadmin out of precisely
    the runs they most need to inspect, and it would front-run 15.2's R6, which
    defines all four terminal states together.
  * What DOES change is that the verification report states the degradation in a
    full sentence, at the top, carrying the bucket-3 count. Not an icon, not a
    colour, not a subtle badge -- words.

COVERAGE
--------
  1. the run-status vocabulary is untouched (no `completed_degraded`)
  2. a degraded run's report says so in words, with the count
  3. a healthy run carries no degradation text at all
  4. gate errors are reported ALONGSIDE bucket 3, never instead of it
  5. the marker is derived when the funnel predates the explicit key

All pure: no Postgres, no LLM, no network.

Cloud Build gate:
  gcloud builds submit tribunal \
    --config=tribunal/cloudbuild.test-gates.yaml \
    --project="$GOOGLE_PROJECT"
"""

from __future__ import annotations

from decimal import Decimal
from typing import get_args

from nestor_pulse_sdk.runs.schemas import RunStatus
from nestor_pulse_sdk.tests.fixtures.run_4cbb5311 import build_verification_summary
from nestor_pulse_sdk.verification.report import shape_verification_report


def _shape(funnel):
    return shape_verification_report(
        verdict_rows=[],
        funnel=funnel,
        claim_count=0,
        cost_usd_total=Decimal("45.00"),
        cost_pending=False,
    )


def _healthy_funnel() -> dict:
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


def test_degraded_run_still_reports_completed_status():
    """G-10: no new run status. The marker lives in the report, not the vocabulary.

    Rejected in G-10: a `completed_degraded` status. Four endpoints gate on the
    literal `"completed"`, the DB's ck_run_status CHECK constraint would have to
    move with it, and a status literal missing from this Literal turns reads of
    such a run into HTTP 500s (CR-03). 15.2's R6 promotes this marker into a real
    terminal state, together with the other three.
    """
    statuses = set(get_args(RunStatus))
    assert statuses == {
        "queued",
        "running",
        "completed",
        "failed",
        "cancelled",
        "needs_input",
        "needs_report_spec",
    }
    assert "completed_degraded" not in statuses
    assert "degraded" not in statuses
    assert "completed" in statuses, (
        "a degraded run keeps status completed -- that is what makes the report's "
        "own marker load-bearing"
    )


def test_degraded_report_states_it_in_words():
    """The recorded (degraded) run's report says so, in a sentence, with the count."""
    report = _shape(build_verification_summary())

    assert report["verification_degraded"] is True
    text = report["verification_degraded_text"]
    assert isinstance(text, str) and text, "a degraded run must carry an explanation"

    assert "226" in text, "the bucket-3 count must be stated, not implied"
    assert "not checked" in text.lower(), (
        "the operator must be told these claims were NOT checked, in plain words"
    )
    assert len(text) > 40, "this must be a sentence a human reads, not a code"
    assert "DEGRADED" in text.upper()


def test_healthy_report_has_no_degradation_text():
    """A healthy run says nothing -- the marker must not become background noise."""
    report = _shape(_healthy_funnel())
    assert report["verification_degraded"] is False
    assert report["verification_degraded_text"] is None


def test_gate_errors_alone_do_not_hide_bucket_three():
    """A gate-error line never absorbs bucket 3 -- both numbers are reported.

    G-11 sends a gate batch that fails after retries toward MORE checking, with a
    visible gate-error line. That line is additional information, not a substitute
    for the count of claims that never got checked.

    WR-02 (plan 15.1-12) -- the unit, not just the number. `gate_errors` is a
    per-CLAIM counter: gates.py:557-558 bumps it once for every claim whose gate
    decision was defaulted, and test_gate_failure_modes.py:168 pins that (3 claims
    -> 3). The sentence used to render it in batch units, so at the default
    _GATE_BATCH = 40 a single failed batch was reported to the operator as forty
    of them -- a 40x overstatement of how much of the gate stage broke. The
    original `"3" in text` assertion below could not catch that: the digit was
    right and only the noun was wrong. The two assertions added at the end pin
    the noun, so a regression fails here rather than reaching an operator.
    """
    funnel = _healthy_funnel()
    funnel.update(
        {
            "checked": 300,
            "should_have_been_checked": 80,
            "gate_errors": 3,
            "verification_degraded": True,
        }
    )
    report = _shape(funnel)
    acc = report["accounting"]

    assert acc["gate_errors"] == 3
    assert acc["should_have_been_checked"] == 80, (
        "the gate-error count must not be subtracted from, or merged into, bucket 3"
    )
    assert report["verification_degraded"] is True
    text = report["verification_degraded_text"]
    assert "80" in text and "3" in text
    # WR-02: the counter is per CLAIM, so the sentence must say claims.
    assert "claim(s) were sent for checking on a defaulted gate answer" in text, (
        "the gate-error line must state the count in CLAIM units -- the counter "
        "is incremented once per claim, not once per batch"
    )
    assert "gate batch" not in text, (
        "reporting a per-claim count in batch units overstates the gate failure "
        "by up to 40x at the default _GATE_BATCH = 40"
    )
    # Buckets still account for every distilled claim.
    assert acc["checked"] + acc["not_checkable"]["total"] + acc["should_have_been_checked"] == (
        funnel["distilled"]
    )


def test_marker_is_derived_when_funnel_omits_it():
    """An older gated funnel with no explicit marker still reports degraded.

    Degradation must not depend on a writer remembering to set a flag: a non-zero
    bucket 3 IS the degradation. Omission cannot be a way to read green.
    """
    funnel = _healthy_funnel()
    funnel.pop("verification_degraded")
    funnel.update({"checked": 330, "should_have_been_checked": 50})

    report = _shape(funnel)
    assert report["verification_degraded"] is True
    assert "50" in report["verification_degraded_text"]

    # And the converse: no explicit key, nothing unchecked -> not degraded.
    clean = _healthy_funnel()
    clean.pop("verification_degraded")
    assert _shape(clean)["verification_degraded"] is False
