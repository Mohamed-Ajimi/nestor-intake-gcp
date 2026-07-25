"""Gate replay — the phase-closing G-01 CI gate (Phase 15.1, ENGINE-10).

WHY. Run 4cbb5311 (2026-07-22) reported status `completed` while its fact-checking
stage had been gutted: 1,162 claims distilled, an Anthropic usage cap hit in the
middle of verification, and a green-looking run whose research prose still carried
every unexamined passage (only a REFUTATION scrubs a passage, so a claim nobody
checked ships as written — that is how one report published Aral's share at both
16% and 21%). The gates are the fix. This file is the proof that they are wired
correctly end to end.

The recorded 1,162-claim population plus the recorded BLIND answer key are pushed
through the REAL gate machinery — the real batching, the real semaphore, the real
plain-text parser, the real fail-toward-checking fallback, the real funnel
arithmetic — and the funnel has to land on the recorded numbers exactly. Nothing
here stubs `apply_gates`: the production code path is what is under test, because a
gate that is right in principle and mis-wired in practice produces exactly the
silent verification loss this phase exists to close.

THIS FILE MAKES ZERO LLM CALLS. Every provider call is served by
`_AnswerKeyGateAudited`, a hand-written duck-typed fake that reads the gate's own
prompt and answers it from the committed answer key. No network, no database, no
mocking library, no API key, no spend, and nothing that can flake — which matters
twice over while the Anthropic account sits at its monthly cap.

Coverage:
  1. the fixture still carries the recorded population and both answer keys
  2. THE PHASE GATE — the replay reproduces the five gate-computed funnel numbers
  3. every claim carries an accountable gate decision (nothing is unaccounted for)
  4. G-04 step 3 — a cluster survives if ANY member survives
  5. the funnel reaches the pipeline's result carrier and the verification report
  6. the report's three buckets are the replayed funnel's own arithmetic (G-08)
  7. a healthy replay reports bucket 3 == 0 and is NOT degraded (G-08/G-10)
  8. an injected gate outage reports a non-zero bucket 3 in WORDS, and drops nothing
  9. the replay made no live call — the fake answered every batch
 10. the funnel the worker persists onto `run.verification_summary` is that funnel

G-13 BOUNDARY. This gate asserts FIVE gate-computed numbers: distilled, kept,
dropped, selected_verify, skipped_stable (plus the three drop reasons and a zero
gate-error line). The sixth recorded constant counts the group-skeptic passes that
RETURNED during the 2026-07-22 cap incident — it measures an outage, not the
funnel — so it is deliberately not named, not asserted and not referenced anywhere
in this file.

Cloud Build gate:
  gcloud builds submit tribunal --config=tribunal/cloudbuild.test-gates.yaml
"""
from __future__ import annotations

import asyncio
import json
import math
import pathlib
import re
import uuid
from collections import Counter
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nestor_pulse_sdk.pipeline.tribunal import gates
from nestor_pulse_sdk.pipeline.tribunal.gates import apply_gates
from nestor_pulse_sdk.pipeline.tribunal.pipeline import _group_selected
from nestor_pulse_sdk.tests.fixtures.run_4cbb5311 import (
    RECORDED_FUNNEL_COUNTS,
    load_recorded_run,
    load_selection_experiment,
)
from nestor_pulse_sdk.verification.report import shape_verification_report

# Retry COUNTS are exercised by test_gate_failure_modes.py; the wall-clock of the
# backoff is never under test. Zeroing the base sleep keeps the injected-failure
# replay below fast even if a future failure fake raises a transient error.
gates._GATE_BACKOFF_S = 0.0

# The gate truncates every claim to this many characters before putting it in the
# prompt (a SECURITY control in gates._gate_batch, not formatting: truncation plus
# index addressing is what stops injected text in one claim from answering for
# another). The replay map is keyed on the SAME truncation so the prompt text
# round-trips back to a fixture id. If gates.py ever changes the width, the map
# stops matching and `_AnswerKeyGateAudited.unmatched` fills up — which the
# assertions below report by name rather than swallowing into a silent default.
_PROMPT_TRUNCATION = 240

#: The blind selection rule, verbatim from the fixture's kept-claims-EN.md header.
#: "Load-bearing" is only meaningful relative to a decision, and THIS is the
#: decision the recorded 456/424 labels were judged against.
_DECISION_CONTEXT = (
    "falsifiable-specific AND load-bearing for the LUKOIL BeNeLux "
    "dynamic-pricing report"
)

_PIPELINE_SRC = (
    pathlib.Path(__file__).resolve().parents[1]
    / "pipeline" / "tribunal" / "pipeline.py"
).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# The fixture, loaded ONCE at module scope.
#
# `load_selection_experiment()` is the phase's single fixture parser (plan
# 15.1-01): it owns the header/no-header split, the CRLF-vs-LF difference between
# the three TSVs, the maxsplit=2 read that keeps the 74 rows with literal tabs
# inside `evidence` intact, and the 1-based line-number claim id. Re-implementing
# any of that here would be a second, subtly-different reader of the exact data
# this phase's proof rests on.
# ---------------------------------------------------------------------------

_CLAIMS, _CLASSIFIED, _STRICT = load_selection_experiment()


def _prompt_key(text: str) -> str:
    """The prompt-visible form of a claim text: truncated, then whitespace-trimmed.

    Trimming matters: a 240-character cut can land mid-word and leave a trailing
    space, and the prompt line is read back line-wise. Applying the same trim on
    both sides makes the round-trip exact instead of "exact except for 3 claims".
    """
    return (text or "")[:_PROMPT_TRUNCATION].strip()


# text -> 1-based fixture id, built ONCE (1,162 linear scans per batch otherwise).
# First occurrence wins, so the mapping is deterministic; a collision would make
# one claim answer with another's recorded decision and could move the funnel, so
# collisions are collected and asserted on rather than tolerated quietly.
_TEXT_TO_ID: dict[str, int] = {}
_KEY_COLLISIONS: list[str] = []
for _claim in _CLAIMS:
    _key = _prompt_key(_claim["text"])
    if _key in _TEXT_TO_ID:
        _KEY_COLLISIONS.append(_key)
        continue
    _TEXT_TO_ID[_key] = _claim["id"]


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# The answer-key fake. It is NOT a stub of the gate: it is a stand-in for the
# MODEL only. Everything between `apply_gates(...)` and this object — batching,
# concurrency, prompt rendering, line parsing, the inverted default, the funnel —
# is production code doing its real job.
#
# RESEARCH's anti-recommendation, honoured: no injectable classifier parameter was
# added to gates.py. A test-only seam there would be a second production code path
# that skips precisely the machinery this test exists to prove.
# ---------------------------------------------------------------------------

_CLAIMS_MARKER = "\nClaims:\n"
#: Present only in the error-likelihood prompt's instructions — how the fake tells
#: the two gates apart. Read from the prompt HEADER (the text before the claims
#: block) so no claim's own wording can ever misroute an answer.
_STABILITY_MARKER = "STABLE NOTORIOUS FACTS"

_LINE_RE = re.compile(r"^(\d+) \| (.*)$")


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text


class _AnswerKeyGateAudited:
    """Answers each real gate prompt from the recorded blind answer key.

    Per call: split the prompt into header + claims block, work out which gate is
    asking, parse the block's `INDEX | CLAIM_TEXT` lines back out, map each claim
    text to its 1-based fixture id, look up the recorded decision, and render it in
    the gate's OWN plain-text line format. The gate's parser then reads it exactly
    as it would read a model's answer.
    """

    def __init__(self) -> None:
        self.calls = 0
        self.materiality_calls = 0
        self.stability_calls = 0
        self.models: list[str] = []
        #: Claim texts the map could not resolve. Kept rather than defaulted-away:
        #: an unmatched claim silently becomes KEEP+gate_error, which would move the
        #: funnel and read as a gate bug instead of a fixture-drift bug.
        self.unmatched: list[str] = []
        #: Ids the strict answer key does not cover (only the KEEP ids are in it).
        self.missing_strict: list[int] = []

    async def gemini_generate(self, *, run_id, tenant_id, model, contents, **kwargs):
        self.calls += 1
        self.models.append(model)
        header, _, block = contents.rpartition(_CLAIMS_MARKER)
        is_stability = _STABILITY_MARKER in header
        if is_stability:
            self.stability_calls += 1
        else:
            self.materiality_calls += 1
        return _FakeResponse(self._answer(block, is_stability=is_stability))

    def _answer(self, block: str, *, is_stability: bool) -> str:
        lines: list[str] = []
        for raw in block.splitlines():
            m = _LINE_RE.match(raw)
            if not m:
                continue
            index = m.group(1)
            claim_id = _TEXT_TO_ID.get(m.group(2).strip())
            if claim_id is None:
                self.unmatched.append(m.group(2))
                continue
            if is_stability:
                decision = _STRICT.get(claim_id)
                if decision is None:
                    self.missing_strict.append(claim_id)
                    continue
                lines.append(f"{index} | {decision}")
            else:
                reason = _CLASSIFIED[claim_id]
                decision = "KEEP" if reason == "KEEP" else "DROP"
                lines.append(f"{index} | {decision} | {reason}")
        return "\n".join(lines)


class _OutageAnswerKeyGateAudited(_AnswerKeyGateAudited):
    """The same replay, with a slice of MATERIALITY batches hard-failing.

    The failure is a usage-cap 400 on purpose: it is the exact error class of the
    2026-07-22 incident, and gates._is_transient refuses to retry it, so the test
    costs one attempt per failed batch and no backoff sleep.
    """

    def __init__(self, fail_every: int = 5) -> None:
        super().__init__()
        self.fail_every = fail_every
        self.failed_batches = 0

    async def gemini_generate(self, *, run_id, tenant_id, model, contents, **kwargs):
        header, _, block = contents.rpartition(_CLAIMS_MARKER)
        if _STABILITY_MARKER not in header:
            self.materiality_calls += 1
            if self.materiality_calls % self.fail_every == 0:
                self.calls += 1
                self.failed_batches += 1
                self.failed_claims = getattr(self, "failed_claims", 0) + len(
                    [ln for ln in block.splitlines() if _LINE_RE.match(ln)]
                )
                raise RuntimeError(
                    "400 Bad Request: usage limit exceeded for this organization"
                )
            self.calls += 1
            self.models.append(model)
            return _FakeResponse(self._answer(block, is_stability=False))
        return await super().gemini_generate(
            run_id=run_id, tenant_id=tenant_id, model=model,
            contents=contents, **kwargs,
        )


# ---------------------------------------------------------------------------
# The replay itself — run ONCE, read by every test below.
# ---------------------------------------------------------------------------

_REPLAY: dict[str, Any] = {}


def _replay() -> tuple[dict[str, Any], _AnswerKeyGateAudited]:
    """Drive the REAL `apply_gates` over the fixture; cache the single result."""
    if "result" not in _REPLAY:
        claims = [dict(c) for c in _CLAIMS]
        audited = _AnswerKeyGateAudited()
        _REPLAY["result"] = _run(apply_gates(
            claims=claims,
            audited=audited,
            run_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            decision_context=_DECISION_CONTEXT,
        ))
        _REPLAY["audited"] = audited
    return _REPLAY["result"], _REPLAY["audited"]


def _diagnostics(audited: _AnswerKeyGateAudited) -> str:
    """Why a replay assertion failed, in the terms that make it fixable."""
    return (
        f"[replay diagnostics] gate calls={audited.calls} "
        f"(materiality={audited.materiality_calls}, stability={audited.stability_calls}), "
        f"unmatched claim texts={len(audited.unmatched)}, "
        f"ids missing from the strict key={len(audited.missing_strict)}, "
        f"prompt-key collisions={len(_KEY_COLLISIONS)}"
    )


def _pipeline_funnel(gate_funnel: dict[str, Any], *, unchecked: int) -> dict[str, Any]:
    """The gates' nine keys plus the accounting keys the verify stage adds.

    Mirrors what the pipeline publishes for the three keys the REPORT consumes
    (`checked`, `should_have_been_checked`, `verification_degraded`). The fourth
    pipeline-owned key is a recorded throughput pass-through that the report shaper
    never reads and that G-13 keeps out of every gate assertion, so it is not
    referenced here; `test_gate_selector.py` owns the full builder's shape.
    """
    funnel = dict(gate_funnel)
    selected = int(funnel["selected_verify"])
    unchecked = max(0, min(int(unchecked), selected))
    funnel["checked"] = selected - unchecked
    funnel["should_have_been_checked"] = unchecked
    funnel["verification_degraded"] = unchecked > 0
    return funnel


# ===========================================================================
# 1. The fixture still is what the phase's proof assumes it is
# ===========================================================================

def test_fixture_loads_the_recorded_population():
    """1,162 claims, both answer keys, and the KEEP set the strict key covers.

    Every number below is asserted against RECORDED_FUNNEL_COUNTS rather than a
    literal, so the constant stays the single source of the recorded numbers and a
    fixture edit cannot quietly re-baseline the phase gate."""
    assert len(_CLAIMS) == RECORDED_FUNNEL_COUNTS["distilled"], (
        "the replay population changed — the phase gate would then prove the "
        "funnel of a different run"
    )
    assert len(_CLASSIFIED) == RECORDED_FUNNEL_COUNTS["distilled"], (
        "the materiality answer key must cover every distilled claim, or the "
        "replay silently defaults the uncovered ones into the verify queue"
    )
    assert len(_STRICT) == RECORDED_FUNNEL_COUNTS["kept"], (
        "the error-likelihood answer key must cover exactly the surviving claims"
    )

    assert [c["id"] for c in _CLAIMS] == list(range(1, len(_CLAIMS) + 1)), (
        "claim ids are the 1-based line numbers the two answer keys join on; a "
        "gap or a renumbering re-points every recorded decision at the wrong claim"
    )

    keep_ids = {cid for cid, reason in _CLASSIFIED.items() if reason == "KEEP"}
    assert set(_STRICT) == keep_ids, (
        "the strict key must cover the KEEP ids EXACTLY — an extra id would skip "
        "a claim the materiality gate dropped, a missing one would leave a "
        "survivor with no error-likelihood decision"
    )

    reasons = Counter(_CLASSIFIED.values())
    assert reasons == Counter({
        "KEEP": RECORDED_FUNNEL_COUNTS["kept"],
        "NOT_FALSIFIABLE": RECORDED_FUNNEL_COUNTS["not_falsifiable"],
        "NOT_LOAD_BEARING": RECORDED_FUNNEL_COUNTS["not_load_bearing"],
        "BOTH": RECORDED_FUNNEL_COUNTS["both"],
    }), f"materiality answer-key tallies drifted from the recorded funnel: {reasons}"

    strict = Counter(_STRICT.values())
    assert strict == Counter({
        "VERIFY": RECORDED_FUNNEL_COUNTS["selected_verify"],
        "SKIP_STABLE": RECORDED_FUNNEL_COUNTS["skipped_stable"],
    }), f"error-likelihood answer-key tallies drifted: {strict}"

    assert not _KEY_COLLISIONS, (
        f"{len(_KEY_COLLISIONS)} claims share a prompt key after truncation to "
        f"{_PROMPT_TRUNCATION} chars, so at least one claim would be answered with "
        f"another claim's recorded decision and the replayed funnel would no longer "
        f"be the recorded one: {_KEY_COLLISIONS[:3]}"
    )


# ===========================================================================
# 2. THE PHASE GATE
# ===========================================================================

def test_replay_reproduces_the_recorded_funnel():
    """The recorded answer key, through the REAL gates, lands on the recorded funnel.

    This is Success Criterion 1. The five gate-COMPUTED numbers — distilled, kept,
    dropped, selected_verify, skipped_stable — plus the three drop reasons that
    have to account for every drop, plus a clean gate-error line, all produced by
    `apply_gates` itself rather than copied from the fixture.

    G-13: the sixth recorded constant is NOT asserted here. It counts group-skeptic
    passes that returned during the 2026-07-22 usage-cap incident — an outage
    measurement, not a gate output — and demanding that new machinery reproduce an
    outage's session count would make the phase pass for the wrong reason."""
    result, audited = _replay()
    funnel = result["funnel"]
    diag = _diagnostics(audited)

    assert not audited.unmatched, (
        f"{len(audited.unmatched)} claim texts in the gate prompt did not map back "
        f"to a fixture id, so the answer key never reached them and the gate "
        f"defaulted them into the queue. {diag}"
    )
    assert not audited.missing_strict, (
        f"claims reached the error-likelihood gate with no recorded strict "
        f"decision. {diag}"
    )

    for key in ("distilled", "kept", "dropped", "selected_verify", "skipped_stable",
                "not_falsifiable", "not_load_bearing", "both"):
        assert funnel[key] == RECORDED_FUNNEL_COUNTS[key], (
            f"the gate machinery computed {key}={funnel[key]}, the recorded blind "
            f"experiment says {RECORDED_FUNNEL_COUNTS[key]} — the selection this "
            f"phase is measured against is not reproducible. {funnel} · {diag}"
        )

    assert funnel["gate_errors"] == RECORDED_FUNNEL_COUNTS["gate_errors"], (
        f"a clean replay may not book a single gate error; any error means claims "
        f"were guessed into the queue rather than judged. {funnel} · {diag}"
    )

    assert len(result["selected"]) == RECORDED_FUNNEL_COUNTS["selected_verify"], (
        "the selected list and the funnel must describe the SAME queue, or the "
        "report describes a queue that was never run"
    )


# ===========================================================================
# 3. Nothing is unaccounted for
# ===========================================================================

def test_every_claim_carries_a_gate_decision():
    """All 1,162 claims carry a decision, a reason, and a strict field.

    An unlabelled claim is the defect in miniature: downstream it is
    indistinguishable from a claim that passed a check, which is exactly how a
    gutted run reported green."""
    result, _ = _replay()
    claims = result["claims"]
    assert len(claims) == RECORDED_FUNNEL_COUNTS["distilled"], (
        "the gate stage may label the claim list, never shorten it"
    )

    for claim in claims:
        gate = claim.get("gate")
        assert isinstance(gate, dict), (
            f"claim {claim.get('id')} left the gate stage with no decision — it "
            f"would be checked or skipped by accident, with nothing recording which"
        )
        assert gate["decision"] in ("KEEP", "DROP"), gate
        assert gate["reason"] in (
            "KEEP", "NOT_FALSIFIABLE", "NOT_LOAD_BEARING", "BOTH"
        ), f"a drop with no attributable reason is an unaccountable removal: {gate}"
        if gate["decision"] == "DROP":
            assert gate["strict"] is None, (
                f"a dropped claim never reaches the error-likelihood gate, so a "
                f"strict decision on it is fabricated: {gate}"
            )
        else:
            assert gate["strict"] in ("VERIFY", "SKIP_STABLE"), (
                f"a surviving claim must reach either the queue or the skip line: "
                f"{gate}"
            )


# ===========================================================================
# 4. G-04 step 3 — cluster survival
# ===========================================================================

def test_cluster_survives_if_any_member_survives():
    """A cluster is worth a session as soon as ONE member is worth checking.

    The cluster is the unit of WORK (one skeptic session reconciles the whole
    cluster), but the gate decision is per claim. Requiring every member to survive
    would let a load-bearing claim go unchecked purely because it was clustered
    with stable, notorious ones — a silent loss with no line in the funnel.

    Driven by REAL replayed claims, not synthetic ones, so the predicate is proven
    against the objects the gates actually produce."""
    result, _ = _replay()
    claims = result["claims"]

    verified = [c for c in claims if c["gate"]["strict"] == "VERIFY"]
    stable = [c for c in claims if c["gate"]["strict"] == "SKIP_STABLE"]
    dropped = [c for c in claims if c["gate"]["decision"] == "DROP"]
    assert verified and stable and dropped, (
        "the replay must produce all three outcomes or this proof is vacuous"
    )

    mixed = {"claims": [dropped[0], stable[0], verified[0], dropped[1]]}
    assert _group_selected(mixed) is True, (
        "a cluster holding one VERIFY member was skipped — that claim would ship "
        "unexamined because of the company it kept"
    )

    trailing = {"claims": [dropped[0], dropped[1], verified[-1]]}
    assert _group_selected(trailing) is True, (
        "cluster survival must not depend on WHERE the surviving member sits"
    )

    all_dropped = {"claims": dropped[:4]}
    assert _group_selected(all_dropped) is False, (
        "a cluster whose members were all gated out with a named reason is already "
        "counted in bucket 2; checking it anyway would spend the budget the gates "
        "just freed"
    )

    all_stable = {"claims": stable[:2]}
    assert _group_selected(all_stable) is False, (
        "a cluster of stable-notorious facts is a recorded skip, not a session"
    )

    assert _group_selected({"claims": []}) is False, (
        "an empty cluster must not queue a session"
    )


# ===========================================================================
# 5. Propagation — the funnel reaches the surfaces that publish it
# ===========================================================================

def test_funnel_reaches_verification_summary():
    """The replayed funnel survives, key for key, to the report and the carrier.

    Proven without a database: `shape_verification_report` is a pure function and
    `load_recorded_run(session=None)` is pure construction, so the propagation can
    be asserted on the dev box and in a Postgres-free Cloud Build alike."""
    result, _ = _replay()
    funnel = _pipeline_funnel(result["funnel"], unchecked=0)

    assert '"verification_summary"' in _PIPELINE_SRC, (
        "the pipeline's top-level result carrier is gone — the worker reads that "
        "exact key, so its loss means a completed run persists no funnel at all "
        "and the operator report silently reads as 'no gate data'"
    )

    report = shape_verification_report(
        verdict_rows=[],
        funnel=funnel,
        claim_count=RECORDED_FUNNEL_COUNTS["distilled"],
        cost_usd_total=Decimal("43.00"),
        cost_pending=False,
    )
    assert report["funnel"] == funnel, (
        "the report re-shaped the funnel; the feed, the operator report and "
        "run.verification_summary must publish the SAME numbers or the operator "
        "has to guess which surface is telling the truth"
    )
    for key in ("distilled", "kept", "dropped", "selected_verify", "skipped_stable"):
        assert report["funnel"][key] == RECORDED_FUNNEL_COUNTS[key], (
            f"{key} changed value on its way into the report"
        )

    run = load_recorded_run(session=None, tenant_id=uuid.uuid4())
    assert run.verification_summary == RECORDED_FUNNEL_COUNTS, (
        "the fixture path that seeds run.verification_summary drifted from the "
        "recorded constant, so two 15.1 surfaces would disagree about one run"
    )


# ===========================================================================
# 6-7. G-08 accounting on a HEALTHY replay
# ===========================================================================

def test_report_accounting_matches_the_replayed_funnel():
    """The three buckets are arithmetic over the replayed funnel, not a row join.

    A join over verdict rows reports `claims_with_verdict == 0` on the recorded run
    (claim_id is NULL there) and would dump all 1,162 claims into bucket 3 — the
    honest bucket screaming about a failure that never happened."""
    result, _ = _replay()
    funnel = _pipeline_funnel(result["funnel"], unchecked=0)
    report = shape_verification_report(
        verdict_rows=[],
        funnel=funnel,
        claim_count=RECORDED_FUNNEL_COUNTS["distilled"],
        cost_usd_total=Decimal("43.00"),
        cost_pending=False,
    )
    accounting = report["accounting"]
    assert accounting is not None, (
        "a gated run must produce accounting; None means the report renders 'no "
        "gate data' for a run that WAS gated"
    )

    not_checkable = accounting["not_checkable"]
    assert not_checkable["total"] == (
        funnel["dropped"] + funnel["skipped_stable"]
    ), (
        f"bucket 2 must hold exactly the gated-out claims: {accounting}"
    )
    assert not_checkable["not_falsifiable"] == RECORDED_FUNNEL_COUNTS["not_falsifiable"]
    assert not_checkable["not_load_bearing"] == RECORDED_FUNNEL_COUNTS["not_load_bearing"]
    assert not_checkable["both"] == RECORDED_FUNNEL_COUNTS["both"]
    assert not_checkable["stable_known_fact"] == RECORDED_FUNNEL_COUNTS["skipped_stable"]

    total = (
        accounting["checked"]
        + not_checkable["total"]
        + accounting["should_have_been_checked"]
    )
    assert total == RECORDED_FUNNEL_COUNTS["distilled"], (
        f"the three buckets must account for EVERY distilled claim; {total} of "
        f"{RECORDED_FUNNEL_COUNTS['distilled']} means claims fell between the "
        f"buckets and nobody can say what happened to them: {accounting}"
    )


def test_healthy_replay_reports_zero_bucket_three():
    """Everything selected was checked: bucket 3 is 0 and the run is not degraded.

    Bucket 3 counts passages that shipped UNEXAMINED, so a healthy run has to be
    able to say zero — otherwise the marker means nothing when it is non-zero."""
    result, _ = _replay()
    funnel = _pipeline_funnel(result["funnel"], unchecked=0)
    report = shape_verification_report(
        verdict_rows=[],
        funnel=funnel,
        claim_count=RECORDED_FUNNEL_COUNTS["distilled"],
        cost_usd_total=Decimal("43.00"),
        cost_pending=False,
    )

    assert report["accounting"]["should_have_been_checked"] == 0, (
        "a fully-checked replay reported unchecked claims — the phase's most "
        "important number is miscounting in the direction that cries wolf"
    )
    assert report["accounting"]["checked"] == RECORDED_FUNNEL_COUNTS["selected_verify"]
    assert report["accounting"]["gate_errors"] == 0
    assert report["verification_degraded"] is False, (
        "a clean run must not raise the degradation marker; a marker that is "
        "always on is a marker the operator learns to ignore"
    )
    assert report["verification_degraded_text"] is None, report["verification_degraded_text"]


# ===========================================================================
# 8. The operator's headline test — a gutted run must NOT report green
# ===========================================================================

def test_injected_failure_replay_reports_a_non_zero_bucket_three():
    """A gate outage: errors counted, nothing dropped, degradation stated in WORDS.

    This is the failure the phase exists to kill. 776 cap-rejections in 55 seconds
    once produced a run that said `completed` and looked green. Here a slice of
    gate batches hard-fails the same way, and three things must hold: no claim is
    dropped by the failure (G-11 fails toward MORE checking), the errors are
    visible in the funnel, and the report says out loud that its own verification
    is incomplete."""
    claims = [dict(c) for c in _CLAIMS]
    audited = _OutageAnswerKeyGateAudited(fail_every=5)
    result = _run(apply_gates(
        claims=claims,
        audited=audited,
        run_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        decision_context=_DECISION_CONTEXT,
    ))
    funnel = result["funnel"]

    assert audited.failed_batches > 0, "the outage fake never fired — test is vacuous"
    assert funnel["gate_errors"] == getattr(audited, "failed_claims", 0), (
        f"every claim in a failed batch must be booked as a gate error, or the "
        f"funnel under-reports how much of the run was guessed at: {funnel}"
    )
    assert funnel["gate_errors"] > 0, funnel

    assert funnel["distilled"] == RECORDED_FUNNEL_COUNTS["distilled"], (
        f"a gate outage may not lose a claim from the population: {funnel}"
    )
    assert funnel["dropped"] < RECORDED_FUNNEL_COUNTS["dropped"], (
        f"a failed batch must fail toward CHECKING, so the outage run can only "
        f"drop FEWER claims than the clean one, never more: {funnel}"
    )
    assert funnel["selected_verify"] > RECORDED_FUNNEL_COUNTS["selected_verify"], (
        f"the claims of a failed batch must arrive in the verify queue — that is "
        f"what 'fails toward more checking' means: {funnel}"
    )
    for claim in result["claims"]:
        if claim["gate"]["gate_error"]:
            assert claim["gate"]["decision"] == "KEEP", (
                f"a gate error removed a claim from checking, converting a "
                f"transient outage into a permanently unexamined passage: "
                f"{claim['gate']}"
            )

    # Now the operator surface: those selected claims were never checked.
    unchecked = funnel["selected_verify"] - RECORDED_FUNNEL_COUNTS["checked"]
    degraded_funnel = _pipeline_funnel(funnel, unchecked=unchecked)
    report = shape_verification_report(
        verdict_rows=[],
        funnel=degraded_funnel,
        claim_count=RECORDED_FUNNEL_COUNTS["distilled"],
        cost_usd_total=Decimal("43.00"),
        cost_pending=False,
    )

    assert report["accounting"]["should_have_been_checked"] == unchecked, (
        f"bucket 3 must carry the shortfall: {report['accounting']}"
    )
    assert report["verification_degraded"] is True, (
        "a run whose fact-checking was gutted reported green — this is the exact "
        "2026-07-22 failure, reappearing"
    )
    text = report["verification_degraded_text"] or ""
    assert "VERIFICATION DEGRADED" in text, (
        f"G-10 requires the degradation stated in WORDS, not an icon: {text!r}"
    )
    assert "not checked" in text, (
        f"the sentence must name what actually happened: {text!r}"
    )
    assert str(unchecked) in text, (
        f"the sentence must carry the count so the operator can size the damage: "
        f"{text!r}"
    )


# ===========================================================================
# 9. Zero live calls
# ===========================================================================

def test_replay_makes_no_live_llm_calls():
    """The whole phase gate cost nothing: every call was served by the fake.

    Asserted as an exact batch count, not "> 0": a silently-skipped gate would
    otherwise let this file pass while proving nothing. The counts are the only
    literal arithmetic in this module — batch sizes are gate configuration, not
    recorded data."""
    result, audited = _replay()

    expected_materiality = math.ceil(
        RECORDED_FUNNEL_COUNTS["distilled"] / gates._GATE_BATCH
    )
    expected_stability = math.ceil(
        RECORDED_FUNNEL_COUNTS["kept"] / gates._GATE_BATCH
    )
    assert audited.materiality_calls == expected_materiality, (
        f"the materiality gate made {audited.materiality_calls} calls, expected "
        f"{expected_materiality} — a skipped batch means claims were defaulted, "
        f"not judged"
    )
    assert audited.stability_calls == expected_stability, (
        f"the error-likelihood gate made {audited.stability_calls} calls, expected "
        f"{expected_stability}"
    )
    assert audited.calls == expected_materiality + expected_stability, (
        f"unexpected extra gate calls: {audited.calls}"
    )

    assert set(audited.models) == {gates._GATE_MODEL}, (
        f"the gate asked for a model it does not own: {set(audited.models)}"
    )

    assert type(audited).__module__ == __name__, (
        "the object the gates talked to was not defined in this test module — a "
        "real client reached CI, which costs money and, before the cap resets, "
        "returns nothing but 400s"
    )
    for attr in ("_a", "_g", "_audit", "_gcs"):
        assert not hasattr(audited, attr), (
            f"the fake carries {attr!r}, an attribute only the real audited client "
            f"has — this file must instantiate no provider client"
        )
    assert result["funnel"]["distilled"] == RECORDED_FUNNEL_COUNTS["distilled"]


# ===========================================================================
# 10. The column write — the funnel the worker actually persists
# ===========================================================================

def test_worker_persists_the_replayed_funnel_onto_the_run_row():
    """The replayed funnel reaches `run.verification_summary`, in the SAME statement
    that sets status='completed'.

    Closes the gap plan 15.1-08 could not close inside its file boundary: nothing
    asserted that the funnel lands in the COLUMN. It is asserted here with a fake
    session (no database, no LLM, no marker): the worker's completion UPDATE is
    captured and its bound parameter is decoded. Two properties matter and only a
    single-statement write gives both — a run must never be able to read
    `completed` with a missing degradation marker (G-10), and the cancel guard
    (`WHERE ... status='running'`) must still make a cancelled run a no-op."""
    worker_mod = pytest.importorskip("nestor_pulse_sdk.runs.worker")

    result, _ = _replay()
    funnel = _pipeline_funnel(result["funnel"], unchecked=0)

    executed: list[tuple[str, Any]] = []

    class _FakeBeginCtx:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *args):
            return False

    class _FakeSession:
        def begin(self):
            return _FakeBeginCtx()

        async def execute(self, stmt, params=None):
            executed.append((str(stmt), params))
            return MagicMock()

    class _FakeSessionmakerCtx:
        async def __aenter__(self):
            return _FakeSession()

        async def __aexit__(self, *args):
            pass

    def fake_get_sessionmaker():
        def factory():
            return _FakeSessionmakerCtx()
        return factory

    async def fake_set_tenant_context(session, tenant_id):
        return None

    runner = MagicMock()
    runner.run = AsyncMock(return_value={
        "output_text": "report body",
        "verification_summary": funnel,
    })
    claimed = {
        "id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "project_id": uuid.uuid4(),
        "engine": "sdk",
        "brief": "gate replay funnel persistence",
    }

    with patch("nestor_pulse_sdk.runs.worker.set_tenant_context",
               side_effect=fake_set_tenant_context):
        with patch("nestor_pulse_sdk.runs.worker.get_sessionmaker",
                   fake_get_sessionmaker):
            with patch("nestor_pulse_sdk.runs.adapter.dispatch_runner",
                       return_value=runner):
                _run(worker_mod.execute_run(claimed))

    completions = [
        (sql, params) for sql, params in executed if "status='completed'" in sql
    ]
    assert len(completions) == 1, (
        f"expected exactly one completion UPDATE, got {len(completions)}: "
        f"{[sql for sql, _ in executed]}"
    )
    sql, params = completions[0]

    assert "verification_summary" in sql, (
        "the completion UPDATE does not write the funnel column — the run would "
        "report completed while the operator report reads 'this run has no gate "
        "data', which is indistinguishable from a run that was never gated"
    )
    assert "WHERE id=:id AND status='running'" in sql, (
        "the cancel guard is gone from the completion write; a cancelled run "
        "would be overwritten as completed"
    )
    assert params is not None and "vsummary" in params, (
        f"the funnel was not bound to the statement: {params}"
    )
    assert json.loads(params["vsummary"]) == funnel, (
        "the persisted funnel is not the one the gates computed — the column, the "
        "feed and the report would each publish a different set of numbers"
    )
    persisted = json.loads(params["vsummary"])
    for key in ("distilled", "kept", "dropped", "selected_verify", "skipped_stable"):
        assert persisted[key] == RECORDED_FUNNEL_COUNTS[key], (
            f"{key} changed value between the gate stage and the run row"
        )
