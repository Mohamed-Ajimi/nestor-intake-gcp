"""Selector tests — G-02 / G-04: the gates select, stakes only sets depth (15.1).

WHY: the engine had TWO filters deciding what got fact-checked, and only one of
them was visible. The visible one was the skeptic stage. The invisible one was
`_group_passes(stakes)`, which returned 0 for every low-stakes group — those
claims were never checked, no verdict row was ever written for them, and the
report counted them as if they had been. G-02 removes that second filter: the
gates become the single answer to "which claims get checked", and stakes keeps
only the DEPTH lever (`_GROUP_DEPTH`).

Two consequences this file pins down, because both are easy to reverse by
accident:

  * A low-stakes claim that the gates keep IS checked now — but at a shallow
    depth that exists by decision, not by a `.get()` fallback landing on MED
    (RESEARCH Pitfall 9). Without the explicit tier, "we now check more claims"
    silently becomes "we now spend more money", against a phase whose bar is
    "~6x cheaper".
  * The queue is corroboration-ASCENDING (D9). A fact only one researcher found
    is the most likely to be wrong and the least backed up, so it is checked
    first; a fact three researchers reported waits. The budget governor
    truncates the queue from the tail, so this order decides what survives a cap.

Coverage:
  1. `triage_claims` has no caller in pipeline.py and no import remains (G-02)
  2. a cluster survives if ANY member verifies (G-04 step 3)
  3. a cluster with no verifying member is skipped — bucket 2, NOT bucket 3
  4. a low-stakes cluster IS selected when the gate keeps it
  5. depth still differentiates: high > med > low on every element
  6. queue order is corroboration-ascending (D9)
  7. queue order is deterministic on ties
  8. the zero-claim path reports the same funnel shape as the full path
  9. the real queue is built from BOTH helpers (a helper nobody calls is a lie)

Pure tests: plain dicts, no DB, no live LLM, no mocking library, no monkeypatch.

Cloud Build gate:
  gcloud builds submit tribunal --config=tribunal/cloudbuild.test-gates.yaml
"""
from __future__ import annotations

import pathlib

from nestor_pulse_sdk.pipeline.tribunal.gates import _FUNNEL_KEYS
from nestor_pulse_sdk.pipeline.tribunal.pipeline import (
    _GROUP_DEPTH,
    _build_funnel,
    _corroboration_order,
    _group_corroboration,
    _group_selected,
)
from nestor_pulse_sdk.tests.fixtures.run_4cbb5311 import RECORDED_FUNNEL_COUNTS

_PIPELINE_SRC = (
    pathlib.Path(__file__).resolve().parents[1]
    / "pipeline" / "tribunal" / "pipeline.py"
).read_text(encoding="utf-8")


def _claim(strict: str | None, *, found_by: list[str] | None = None, text: str = "c") -> dict:
    """A claim as it looks after the gates have run over it."""
    decision = "DROP" if strict is None else "KEEP"
    return {
        "text": text,
        "facet": "general",
        "found_by": list(found_by or []),
        "gate": {
            "decision": decision,
            "reason": "NOT_LOAD_BEARING" if decision == "DROP" else "KEEP",
            "strict": strict,
            "gate_error": False,
        },
    }


def _group(claims: list[dict], stakes: str = "med", key: str = "e|a") -> dict:
    """The group shape grouping.py returns (frozen — group_skeptic reads it)."""
    return {
        "key": key,
        "entity": "e",
        "attribute": "a",
        "claims": claims,
        "stakes": stakes,
    }


# ---------------------------------------------------------------------------
# 1. The hidden second filter is gone
# ---------------------------------------------------------------------------


def test_triage_claims_is_not_called_from_the_verify_path():
    """G-02: prove the stakes triage no longer selects — by ABSENCE, statically.

    A behavioural test cannot prove a negative here: the only way to observe the
    old filter was a live run in which low-stakes claims silently produced no
    verdicts, which is exactly the invisible failure this phase exists to close.
    So the assertion is on the source: the name does not appear, and no import
    of the module survives. triage.py itself stays on disk with its unit tests —
    it lost its production caller, not its existence.
    """
    assert "triage_claims" not in _PIPELINE_SRC, (
        "pipeline.py still references triage_claims — the stakes triage is back "
        "in the selector's seat and low-stakes claims can be waved through "
        "unchecked again (G-02)"
    )
    assert "tribunal.triage import" not in _PIPELINE_SRC, (
        "pipeline.py still imports the triage module — an import is how the "
        "call comes back"
    )
    assert "import triage" not in _PIPELINE_SRC, (
        "pipeline.py still imports the triage module (bare-module form)"
    )


# ---------------------------------------------------------------------------
# 2-4. The cluster-survival rule (G-04 step 3)
# ---------------------------------------------------------------------------


def test_group_selected_true_when_any_member_verifies():
    group = _group([_claim("SKIP_STABLE"), _claim("VERIFY")])
    assert _group_selected(group) is True, (
        "a cluster must be checked as soon as ONE member is worth checking — the "
        "cluster is the unit of WORK, the gate decision is per claim (G-04 step 3)"
    )


def test_group_selected_false_when_no_member_verifies():
    # Bucket 2, NOT bucket 3: these claims were deliberately gated out with a
    # named reason (stable_known_fact / not_load_bearing) and are already
    # accounted for. Counting this skip as bucket 3 would make a healthy run
    # report a verification failure it did not have.
    group = _group([_claim("SKIP_STABLE"), _claim(None)])
    assert _group_selected(group) is False, (
        "a cluster whose every member was gated out must not consume a skeptic "
        "session"
    )


def test_low_stakes_group_is_selected_when_the_gate_keeps_it():
    """The exact case the old `_group_passes` waved through unchecked."""
    group = _group([_claim("VERIFY")], stakes="low")
    assert _group_selected(group) is True, (
        "a low-stakes cluster carrying a load-bearing, falsifiable claim must be "
        "checked — importance to the CLIENT is not the same question as "
        "likelihood of being WRONG (G-02)"
    )


# ---------------------------------------------------------------------------
# 5. Stakes survives as the depth lever
# ---------------------------------------------------------------------------


def test_group_depth_still_differentiates_by_stakes():
    """G-02 keeps stakes — as DEPTH, and with an explicit shallow low tier.

    The "low" entry is deliberate (RESEARCH Pitfall 9). Before G-02 low-stakes
    groups never ran, so the map never needed the key; once the gates let one
    through, `_GROUP_DEPTH.get(stakes, _GROUP_DEPTH["med"])` would have handed it
    MED depth without anybody deciding that. Deleting the tier does not fail
    loudly — it just costs more, quietly.
    """
    assert set(_GROUP_DEPTH) == {"high", "med", "low"}, (
        "all three stakes tiers must be explicit; a missing tier resolves through "
        "the .get() fallback and spends MED money on a low-stakes group"
    )
    high, med, low = _GROUP_DEPTH["high"], _GROUP_DEPTH["med"], _GROUP_DEPTH["low"]
    assert len(high) == len(med) == len(low) == 3, (
        "each tier is (max_turns, max_search_uses, max_fetch_uses)"
    )
    for i, name in enumerate(("max_turns", "max_search_uses", "max_fetch_uses")):
        assert high[i] > med[i] > low[i], (
            f"{name} must fall strictly high > med > low — otherwise stakes has "
            "stopped differentiating effort and the depth lever is decorative"
        )


# ---------------------------------------------------------------------------
# 6-7. Corroboration ordering (G-04 step 4, decision D9)
# ---------------------------------------------------------------------------


def test_queue_order_puts_single_source_claims_first():
    """D9: LOWEST corroboration FIRST. The intuition runs the other way.

    It is tempting to check the well-corroborated facts first because they look
    like the load-bearing ones. D9 says the opposite: a claim only one researcher
    found has nothing backing it up and is the most likely to be wrong, so it
    goes to the head of the queue. Three researchers agreeing is itself evidence,
    and that cluster can afford to wait.
    """
    three = _group([_claim("VERIFY", found_by=["gemini", "claude", "openai"])], key="three")
    one = _group([_claim("VERIFY", found_by=["gemini"])], key="one")
    two = _group([_claim("VERIFY", found_by=["gemini", "claude"])], key="two")

    assert _group_corroboration(three) == 3
    assert _group_corroboration(one) == 1
    assert _group_corroboration(two) == 2

    ordered = _corroboration_order([three, one, two])
    assert [g["key"] for g in ordered] == ["one", "two", "three"], (
        "single-source clusters must be checked first — the budget cap truncates "
        "the queue from the TAIL, so this order decides which checks survive a cap"
    )


def test_corroboration_counts_distinct_providers_across_members():
    # Two members that both name the same two researchers are corroborated by
    # two researchers, not four — a duplicate report is not a second opinion.
    group = _group([
        _claim("VERIFY", found_by=["gemini", "claude"]),
        _claim("VERIFY", found_by=["claude", "gemini"]),
    ])
    assert _group_corroboration(group) == 2, (
        "corroboration counts DISTINCT researchers; counting mentions would let "
        "one chatty provider look like independent agreement"
    )


def test_queue_order_is_deterministic_on_ties():
    a = _group([_claim("VERIFY", found_by=["gemini"])], key="a")
    b = _group([_claim("VERIFY", found_by=["claude"])], key="b")
    c = _group([_claim("VERIFY", found_by=["openai"])], key="c")
    ordered = _corroboration_order([a, b, c])
    assert [g["key"] for g in ordered] == ["a", "b", "c"], (
        "equal corroboration must keep the original index, so two runs over the "
        "same data spend the budget on the same checks"
    )
    # A no-provenance group (found_by absent — a pre-G-12 claim) still sorts,
    # and sorts first, rather than raising or silently landing last.
    plain = _group([{"text": "no provenance", "gate": {"strict": "VERIFY"}}], key="plain")
    assert _corroboration_order([a, plain])[0]["key"] == "plain"


# ---------------------------------------------------------------------------
# 8-9. Funnel shape + the wiring itself
# ---------------------------------------------------------------------------


def test_empty_claims_path_reports_the_gate_funnel_shape():
    """RESEARCH Pitfall 10: the zero-claim path used to report a different shape.

    It hand-built a `verification_report` skeleton with no funnel at all, so a
    consumer had to know which code path produced its input. Both paths now go
    through `_build_funnel`, so drift is structurally impossible.
    """
    empty = _build_funnel(None, unchecked_selected=0, verify_sessions=0)
    full = _build_funnel(
        {"distilled": 10, "kept": 6, "dropped": 4, "not_falsifiable": 2,
         "not_load_bearing": 1, "both": 1, "selected_verify": 5,
         "skipped_stable": 1, "gate_errors": 0},
        unchecked_selected=2,
        verify_sessions=3,
    )
    assert set(empty) == set(full), (
        "the zero-claim path and the full path must publish the same funnel keys"
    )
    assert set(empty) == set(RECORDED_FUNNEL_COUNTS), (
        "the funnel must carry exactly the 13 contract keys — the report shaper "
        "returns None for `accounting` when a gate key is missing, so a dropped "
        "key reads downstream as 'this run has no gate data'"
    )
    assert set(_FUNNEL_KEYS).issubset(set(empty)), (
        "all nine gate-owned keys must survive into the pipeline funnel"
    )
    assert all(empty[k] == 0 for k in _FUNNEL_KEYS), "zero claims means zero of everything"
    assert empty["should_have_been_checked"] == 0
    assert empty["verification_degraded"] is False, (
        "a run with nothing to check is not a degraded run"
    )

    # The full path's own arithmetic: bucket 3 is a SUBSET of the selected queue.
    assert full["checked"] == 3, "checked == selected_verify - should_have_been_checked"
    assert full["should_have_been_checked"] == 2
    assert full["verification_degraded"] is True, (
        "any selected claim that went unchecked must raise the loud marker (G-10)"
    )
    assert "_build_funnel(None, unchecked_selected=0, verify_sessions=0)" in _PIPELINE_SRC, (
        "the zero-claim early return must use the shared builder, not a second "
        "hand-written skeleton"
    )


def test_the_group_queue_is_built_from_the_gate_and_the_order_helper():
    """A selector nobody calls proves nothing — assert the wiring, not just the helper."""
    assert "_corroboration_order(groups) if _group_selected(g)" in _PIPELINE_SRC, (
        "the verify queue must be built from the GATE result in corroboration "
        "order; if this line changed, check that _group_passes has not crept back "
        "into the selector's seat (G-02) and that D9's order still holds"
    )
    assert "total_passes = len(queue)" in _PIPELINE_SRC, (
        "the progress denominator must be the real queue length, or the operator "
        "feed reports a queue that was never run"
    )
