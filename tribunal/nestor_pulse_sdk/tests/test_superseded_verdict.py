"""Producer-side proof for the fourth verdict word: `superseded` (G-06 / G-07).

WHY this file exists
--------------------
The verdict vocabulary used to be three words — support / refute / insufficient.
The KPAnG case (live run 4cbb5311, 2026-07-22) therefore came back as six "support"
verdicts on true-but-obsolete claims, with the nuance stranded in a free-text
reconciliation note that synthesis was free to ignore. G-06 makes `superseded` a
verdict so the skeptic must choose it and every downstream count can see it. G-07
requires the caveat text ("applied until 1 April 2026") to travel as PIPELINE DATA,
so the writing model presents it rather than phrasing it from memory.

Covers:
  - EMIT_GROUP_VERDICT_TOOL offers four verdicts plus a `superseded_note` property,
    while the per-claim EMIT_VERDICT_TOOL deliberately keeps three (plan 15.1-07
    owns the per-claim path's fate).
  - `_parse_group_verdict` preserves `superseded` and its note verbatim.
  - An out-of-vocabulary verdict string is normalised at the parse boundary instead
    of reaching the free-TEXT database column.
  - A superseded claim SURVIVES adjudication carrying its caveat (G-07), proven as a
    regression on unchanged code.
  - The refute drop rule is unweakened by the fourth word.
  - The all-failed group fallback carries the note key on every index.

All tests are pure: no DB, no network, no live LLM, no mocking library.

Cloud Build invocation:
    gcloud builds submit tribunal --config=tribunal/cloudbuild.test-gates.yaml
(Until plan 15.1-01's gates config lands, the full-suite config runs it too:
    gcloud builds submit tribunal --config=tribunal/cloudbuild.test.yaml)
"""
from __future__ import annotations

from typing import Any

from nestor_pulse_sdk.pipeline.tribunal.adjudicate import adjudicate
from nestor_pulse_sdk.pipeline.tribunal.group_skeptic import (
    _insufficient_group,
    _parse_group_verdict,
)
from nestor_pulse_sdk.pipeline.tribunal.tools import (
    EMIT_GROUP_VERDICT_TOOL,
    EMIT_VERDICT_TOOL,
)


# ---------------------------------------------------------------------------
# Fakes — duck-typed, matching test_tribunal_grouping.py:48-53. No mocking library.
# ---------------------------------------------------------------------------
class _FakeBlock:
    def __init__(self, type: str, **kw: Any) -> None:
        self.type = type
        for k, v in kw.items():
            setattr(self, k, v)


def _group_verdict_props() -> dict[str, Any]:
    """The per-verdict object schema inside EMIT_GROUP_VERDICT_TOOL."""
    return EMIT_GROUP_VERDICT_TOOL["input_schema"]["properties"]["verdicts"]["items"]["properties"]


# ---------------------------------------------------------------------------
# 1. Tool schema
# ---------------------------------------------------------------------------
def test_tool_enum_offers_four_verdicts():
    props = _group_verdict_props()
    assert props["verdict"]["enum"] == ["support", "refute", "insufficient", "superseded"]

    # G-07: the caveat has a home in the schema, and is optional so that a plain
    # support/refute verdict need not carry an empty string.
    assert "superseded_note" in props
    assert props["superseded_note"]["type"] == "string"
    required = EMIT_GROUP_VERDICT_TOOL["input_schema"]["properties"]["verdicts"]["items"]["required"]
    assert "superseded_note" not in required

    # DELIBERATE ASYMMETRY (plan 15.1-03 Task 1): the per-claim tool is NOT extended.
    # Its only callers are the NESTOR_TRIBUNAL_GROUP_VERIFY=false fallback branch and
    # the coverage-gate re-entry, whose fate plan 15.1-07 owns.
    per_claim_enum = EMIT_VERDICT_TOOL["input_schema"]["properties"]["verdict"]["enum"]
    assert per_claim_enum == ["support", "refute", "insufficient"]
    assert len(per_claim_enum) == 3


# ---------------------------------------------------------------------------
# 2. Parser preserves the fourth word
# ---------------------------------------------------------------------------
# KPAnG case (live run 4cbb5311, 2026-07-22): six "support" verdicts on an intraday
# pricing pattern the reconciliation note itself called "superseded since 1 April 2026".
def test_parser_preserves_superseded():
    block = _FakeBlock(
        "tool_use",
        name="emit_group_verdict",
        input={
            "verdicts": [
                {
                    "claim_index": 0,
                    "verdict": "superseded",
                    "confidence": 0.9,
                    "superseded_note": "applied until 1 April 2026",
                },
            ],
            "reconciliation": {
                "disputed": False,
                "relation": "scoped",
                "note": "true until the 1 April 2026 rule change",
                "canonical": "",
            },
        },
    )
    out = _parse_group_verdict(block, n_claims=1, citations=["https://src"])

    assert out["verdicts_by_index"][0]["verdict"] == "superseded"
    assert out["verdicts_by_index"][0]["superseded_note"] == "applied until 1 April 2026"


# ---------------------------------------------------------------------------
# 3. Out-of-vocabulary strings never reach the database
# ---------------------------------------------------------------------------
# KPAnG case (live run 4cbb5311, 2026-07-22): six "support" verdicts on an intraday
# pricing pattern the reconciliation note itself called "superseded since 1 April 2026".
# `verification_verdict.verdict` is free TEXT with no enum and no CHECK constraint, so
# an unrecognised model string would otherwise be written straight through and
# miscounted by every downstream bucket. This boundary is the only validation there is.
def test_unknown_verdict_string_normalises_to_insufficient():
    block = {
        "input": {
            "verdicts": [
                {"claim_index": 0, "verdict": "supersede", "confidence": 0.9},  # typo
                {"claim_index": 1, "verdict": {"nested": "object"}, "confidence": 0.5},
                {"claim_index": 2, "verdict": None, "confidence": 0.5},
            ],
            "reconciliation": {"disputed": False, "relation": "agree", "note": ""},
        }
    }
    out = _parse_group_verdict(block, n_claims=3, citations=[])

    assert out["verdicts_by_index"][0]["verdict"] == "insufficient"
    assert out["verdicts_by_index"][1]["verdict"] == "insufficient"
    assert out["verdicts_by_index"][2]["verdict"] == "insufficient"
    # The raw string is never written through under any key.
    assert "supersede" not in out["verdicts_by_index"][0].values()

    # Casing / whitespace from the model is tolerated, not rejected.
    block_case = {
        "input": {
            "verdicts": [{"claim_index": 0, "verdict": "  SUPERSEDED ", "confidence": 0.9}],
            "reconciliation": {"disputed": False, "relation": "single", "note": ""},
        }
    }
    out_case = _parse_group_verdict(block_case, n_claims=1, citations=[])
    assert out_case["verdicts_by_index"][0]["verdict"] == "superseded"


# ---------------------------------------------------------------------------
# 4. G-07 — the claim survives and its caveat is reachable
# ---------------------------------------------------------------------------
# KPAnG case (live run 4cbb5311, 2026-07-22): six "support" verdicts on an intraday
# pricing pattern the reconciliation note itself called "superseded since 1 April 2026".
def test_superseded_survives_and_carries_caveat():
    # (a) REGRESSION TEST ON UNCHANGED CODE. adjudicate.py is deliberately NOT edited
    # by plan 15.1-03: only "refute" can drop a claim, so a superseded claim survives
    # BY CONSTRUCTION. Surviving means it never reaches scrub_research's
    # removed_claims, so it stays in the report body — exactly what G-07 requires.
    verdicts = [{"verdict": "superseded", "confidence": 0.9, "citations": ["http://x"]}]
    assert adjudicate({"text": "c", "stakes": "high"}, verdicts) is True

    # (b) The caveat text is reachable as pipeline data, so synthesis can be handed
    # the words instead of the writing model inventing them from memory.
    note = "this pattern applied until 1 April 2026"
    block = {
        "input": {
            "verdicts": [
                {
                    "claim_index": 0,
                    "verdict": "superseded",
                    "confidence": 0.9,
                    "superseded_note": note,
                },
            ],
            "reconciliation": {"disputed": False, "relation": "scoped", "note": ""},
        }
    }
    parsed = _parse_group_verdict(block, n_claims=1, citations=["https://src"])
    carried = parsed["verdicts_by_index"][0]["superseded_note"]
    assert carried
    assert carried == note


# ---------------------------------------------------------------------------
# 5. Control — the drop rule is not weakened by the fourth word
# ---------------------------------------------------------------------------
def test_majority_refute_still_drops():
    verdicts = [{"verdict": "refute", "confidence": 0.9, "citations": ["http://x"]}]
    assert adjudicate({"text": "c", "stakes": "high"}, verdicts) is False

    # A superseded verdict is not a refuter and cannot tip the majority.
    mixed = [
        {"verdict": "refute", "confidence": 0.9, "citations": ["http://x"]},
        {"verdict": "superseded", "confidence": 0.9, "citations": ["http://y"]},
    ]
    assert adjudicate({"text": "c", "stakes": "high"}, mixed) is True  # 1/2 is not a majority


# ---------------------------------------------------------------------------
# 6. Fallback shape — consumers never need a .get default
# ---------------------------------------------------------------------------
def test_all_failed_group_fallback_carries_note_key():
    out = _insufficient_group(3, ["https://src"])
    for i in range(3):
        assert out["verdicts_by_index"][i]["superseded_note"] == ""
        assert out["verdicts_by_index"][i]["verdict"] == "insufficient"


# ---------------------------------------------------------------------------
# 7. Fill-missing path also carries the key
# ---------------------------------------------------------------------------
def test_filled_missing_claim_carries_note_key():
    block = {
        "input": {
            "verdicts": [{"claim_index": 0, "verdict": "support", "confidence": 0.9}],
            "reconciliation": {"disputed": False, "relation": "agree", "note": ""},
        }
    }
    out = _parse_group_verdict(block, n_claims=2, citations=[])

    # index 1 was never emitted by the model — it is filled, not dropped.
    assert out["verdicts_by_index"][1]["verdict"] == "insufficient"
    assert out["verdicts_by_index"][0]["superseded_note"] == ""
    assert out["verdicts_by_index"][1]["superseded_note"] == ""


# ---------------------------------------------------------------------------
# 8. A note attached to a non-superseded verdict is not carried
# ---------------------------------------------------------------------------
def test_note_ignored_when_verdict_is_not_superseded():
    block = {
        "input": {
            "verdicts": [
                {
                    "claim_index": 0,
                    "verdict": "support",
                    "confidence": 0.9,
                    "superseded_note": "stray note the model attached anyway",
                },
            ],
            "reconciliation": {"disputed": False, "relation": "single", "note": ""},
        }
    }
    out = _parse_group_verdict(block, n_claims=1, citations=[])
    assert out["verdicts_by_index"][0]["verdict"] == "support"
    assert out["verdicts_by_index"][0]["superseded_note"] == ""
