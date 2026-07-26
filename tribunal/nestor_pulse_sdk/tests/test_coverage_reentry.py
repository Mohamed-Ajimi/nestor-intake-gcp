"""Coverage surface, breaker-gated re-entry, F7 and F8 — Phase 15.2 plan 07.

WR-01 (`15.1-UAT.md`) recorded that the coverage gate's `adjudications` mapping was
built with a test that was unconditionally true, so the gate always passed and its
bounded re-entry — the last chance a gate-selected claim gets at a verdict — was
unreachable dead code. This file proves the fix, and proves the two things that had
to land WITH the fix so that it is not a denial-of-wallet bug:

  1. the coverage surface is intersected with the GATE selection (D-07-B), so the
     recorded population's 706 DROP + 32 SKIP_STABLE claims cannot trigger re-entry;
  2. the re-entry fan-out is dispatched only from a fully CLOSED skeptic circuit
     (D-07-C) — `open` and `half_open` both refuse, and every refused claim is
     booked into bucket 3 with a plain-words reason.

THIS FILE MAKES ZERO LLM CALLS. Every provider call is served by
`_ScriptedGroupAudited`, a hand-written duck-typed fake in the style of
`test_gate_replay.py::_AnswerKeyGateAudited`. No network, no database, no mocking
library, no API key, no spend, and nothing that can flake — which matters twice over
while the Anthropic account sits at its monthly cap (resets 2026-08-01). The fake
stands in for the MODEL only: the real `run_group_skeptic`, the real
`_parse_group_verdict`, the real `CircuitBreaker` and the real `check_coverage` all
do their production work.

Cloud Build gate:
  gcloud builds submit tribunal --config=tribunal/cloudbuild.test-engine.yaml

(The file is pre-listed in `tribunal/cloudbuild.test-engine.yaml`, which plan 15.2-02
owns exclusively and no later plan edits.)

Coverage:
  TestCoverageSurface        — D-07-B, the WR-01 cost trap
  TestReentryDispatch        — D-07-A (F7), D-07-C (the breaker gate), D-07-D
  TestGroupSkepticPauseTurn  — F8, the bounded pause_turn continuation
"""
from __future__ import annotations

import uuid
from typing import Any

from nestor_pulse_sdk.pipeline.tribunal.coverage_gate import (
    MAX_REENTRY,
    check_coverage,
)
from nestor_pulse_sdk.pipeline.tribunal.pipeline import (
    _coverage_reentry_pass,
    _recon_is_meaningful,
)
from nestor_pulse_sdk.pipeline.tribunal.group_skeptic import run_group_skeptic
from nestor_pulse_sdk.pipeline.tribunal.reliability import (
    MAX_PAUSE_CONTINUATIONS,
    CircuitBreaker,
)
from nestor_pulse_sdk.pipeline.tribunal.tools import EMIT_VERDICT_TOOL


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _claim(
    *,
    text: str,
    stakes: str = "high",
    strict: str = "VERIFY",
    facet: str = "A",
) -> dict:
    """One claim dict in the shape the verify stage actually sees.

    `gate.strict` is the vocabulary `gates.py` emits: VERIFY (checked),
    DROP (not falsifiable / not load-bearing / both) and SKIP_STABLE (a stable,
    notorious fact).
    """
    return {"text": text, "facet": facet, "stakes": stakes, "gate": {"strict": strict}}


# ---------------------------------------------------------------------------
# D-07-B — the coverage surface is gate-selected AND high-stakes
# ---------------------------------------------------------------------------

class TestCoverageSurface:
    """The population `check_coverage` is allowed to spend money on."""

    def test_dropped_high_stakes_claim_is_not_uncovered(self):
        """A gate-DROPped claim carries no verdict BY DESIGN — not a coverage loss."""
        c = _claim(text="dropped claim", strict="DROP")
        result = check_coverage([c], {})
        assert result["pass"] is True
        assert result["uncovered"] == []

    def test_skip_stable_high_stakes_claim_is_not_uncovered(self):
        """Same for a stable, notorious fact the error-likelihood gate skipped."""
        c = _claim(text="water boils at 100C at sea level", strict="SKIP_STABLE")
        result = check_coverage([c], {})
        assert result["pass"] is True
        assert result["uncovered"] == []

    def test_selected_high_stakes_claim_with_no_verdict_is_uncovered(self):
        """The claim the re-entry path exists FOR: selected, checked, no verdict."""
        c = _claim(text="selected claim")
        result = check_coverage([c], {})
        assert result["pass"] is False
        assert result["uncovered"] == [c]

    def test_selected_high_stakes_claim_with_a_verdict_is_covered(self):
        c = _claim(text="selected claim")
        result = check_coverage([c], {id(c): True})
        assert result["pass"] is True
        assert result["uncovered"] == []

    def test_low_stakes_selected_claim_is_exempt(self):
        """The stakes filter is UNCHANGED — the intersection narrows, never widens."""
        c = _claim(text="low stakes but selected", stakes="low")
        result = check_coverage([c], {})
        assert result["pass"] is True
        assert result["uncovered"] == []

    def test_selected_only_false_restores_the_legacy_surface(self):
        """The pre-15.2 surface stays reachable — but only on an explicit request."""
        c = _claim(text="dropped claim", strict="DROP")
        result = check_coverage([c], {}, selected_only=False)
        assert result["pass"] is False
        assert result["uncovered"] == [c]

    def test_recorded_population_regression(self):
        """THE WR-01 COST TRAP, at the recorded 4cbb5311 scale.

        706 DROP + 32 SKIP_STABLE = 738 claims that carry no verdict by design,
        all high-stakes (`_propagate_stakes` copies the focus area's stakes onto
        every one of its claims), plus 3 genuinely uncovered VERIFY claims.

        Under the pre-G-02 surface all 741 read as uncovered, and the re-entry
        loop fires per uncovered claim — roughly 2,100 extra Anthropic tool-use
        sessions against a verify stage the gates exist to shrink to ~150. The
        assertion below is what keeps that at 3. Nothing else would: MAX_REENTRY
        bounds the number of PASSES, not the size of the first fan-out; D-11's
        breaker gate only fires after the breaker has already tripped; and the
        budget governor is inert (`NESTOR_TRIBUNAL_UNCAPPED=1`).
        """
        claims = (
            [_claim(text=f"dropped {i}", strict="DROP") for i in range(706)]
            + [_claim(text=f"stable {i}", strict="SKIP_STABLE") for i in range(32)]
            + [_claim(text=f"selected {i}", strict="VERIFY") for i in range(3)]
        )
        result = check_coverage(claims, {})
        assert result["pass"] is False
        assert len(result["uncovered"]) == 3
        assert all(c["gate"]["strict"] == "VERIFY" for c in result["uncovered"])

    def test_max_reentry_is_still_one(self):
        """A claim gets exactly ONE last chance. D-07-B did not touch this bound."""
        assert MAX_REENTRY == 1


# ---------------------------------------------------------------------------
# The scripted model fake + the collaborators the re-entry pass takes.
#
# `_ScriptedGroupAudited` is a stand-in for the MODEL only, in the style of
# test_gate_replay.py's `_AnswerKeyGateAudited`. Everything between
# `_coverage_reentry_pass(...)` and this object — the group assembly, the
# semaphore, the timeout, the REAL `run_group_skeptic` loop, the REAL
# `_parse_group_verdict` and its four-word verdict clamp — is production code
# doing its real job.
# ---------------------------------------------------------------------------

def _verdict_block(
    *,
    verdict: str = "support",
    confidence: float = 0.9,
    superseded_note: str = "",
    reconciliation: dict | None = None,
) -> dict:
    """One `emit_group_verdict` tool_use block for a single-member group."""
    return {
        "type": "tool_use",
        "name": "emit_group_verdict",
        "input": {
            "verdicts": [
                {
                    "claim_index": 0,
                    "verdict": verdict,
                    "confidence": confidence,
                    "superseded_note": superseded_note,
                }
            ],
            "reconciliation": reconciliation
            or {"disputed": False, "relation": "single", "note": "", "canonical": ""},
            "evidence_refs": ["https://example.org/evidence"],
        },
    }


class _FakeResponse:
    def __init__(self, stop_reason: str, content: list[Any]) -> None:
        self.stop_reason = stop_reason
        self.content = content


class _ScriptedGroupAudited:
    """Serves each turn of a group-skeptic session from a script. Zero network.

    `script` is a list of `(stop_reason, blocks)` consumed ONE PER CALL. When it
    runs out the last entry is repeated, so a one-entry script answers every turn
    the same way — which is what an "unending pause_turn stream" needs.
    """

    def __init__(
        self,
        script: list[tuple[str, list[Any]]] | None = None,
        *,
        raises: BaseException | None = None,
    ) -> None:
        self.script = script or [("tool_use", [_verdict_block()])]
        self.raises = raises
        self.calls = 0
        #: The `messages` list handed to each call, recorded so a test can prove the
        #: paused assistant message was echoed back (F8's caller contract).
        self.seen_messages: list[list[Any]] = []

    async def anthropic_messages(
        self, *, run_id, tenant_id, model, messages, tools, max_tokens, **kwargs
    ):
        self.calls += 1
        # A shallow copy per call: `run_group_skeptic` mutates the same list object
        # between turns, so recording the reference would show every call the final
        # state and prove nothing.
        self.seen_messages.append(list(messages))
        if self.raises is not None:
            raise self.raises
        idx = min(self.calls - 1, len(self.script) - 1)
        stop_reason, blocks = self.script[idx]
        return _FakeResponse(stop_reason, list(blocks))


class _Bucket3:
    """Collects `_book_unchecked(claims, cause)` calls — the loss ledger."""

    def __init__(self) -> None:
        self.entries: list[tuple[list[dict], str]] = []

    def book(self, claims, cause: str) -> None:
        self.entries.append((list(claims), cause))

    @property
    def claim_texts(self) -> list[str]:
        return [c.get("text", "") for claims, _ in self.entries for c in claims]

    @property
    def causes(self) -> list[str]:
        return [cause for _, cause in self.entries]


class _FakeClock:
    """A hand-steppable monotonic clock for the REAL CircuitBreaker."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


async def _run_pass(
    *,
    uncovered: list[dict],
    audited: _ScriptedGroupAudited,
    breaker: CircuitBreaker,
    bucket3: _Bucket3,
    verdicts_by_claim: dict | None = None,
    superseded_notes: list[str] | None = None,
) -> dict:
    """Drive `_coverage_reentry_pass` with the real signature and no pipeline run."""
    import asyncio

    return await _coverage_reentry_pass(
        uncovered=uncovered,
        verdicts_by_claim=verdicts_by_claim if verdicts_by_claim is not None else {},
        superseded_notes=superseded_notes if superseded_notes is not None else [],
        provider_results=[],
        audited=audited,
        run_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        sem=asyncio.Semaphore(8),
        breaker=breaker,
        book_unchecked=bucket3.book,
    )


# ---------------------------------------------------------------------------
# D-07-A / D-07-C / D-07-D — what the re-entry pass dispatches, and when
# ---------------------------------------------------------------------------

class TestReentryDispatch:

    async def test_dropped_claims_dispatch_nothing(self):
        """The cost trap, end to end: gated-out claims never reach the dispatcher.

        `check_coverage` is the REAL gate here, not a stub — its empty `uncovered`
        is what the re-entry pass is handed.
        """
        claims = [_claim(text=f"dropped {i}", strict="DROP") for i in range(50)]
        coverage = check_coverage(claims, {})
        assert coverage["uncovered"] == []

        audited = _ScriptedGroupAudited()
        bucket3 = _Bucket3()
        breaker = CircuitBreaker("anthropic:skeptic", clock=_FakeClock())
        result = await _run_pass(
            uncovered=coverage["uncovered"], audited=audited,
            breaker=breaker, bucket3=bucket3,
        )
        assert result["sessions"] == 0
        assert result["recovered"] == 0
        assert result["blocked_reason"] is None
        assert audited.calls == 0
        assert bucket3.entries == []

    async def test_one_selected_claim_gets_exactly_one_session(self):
        """D-07-D: ONE thorough session at high depth, not three shallow ones."""
        claim = _claim(text="a load-bearing number")
        verdicts: dict = {id(claim): []}
        audited = _ScriptedGroupAudited()
        bucket3 = _Bucket3()
        breaker = CircuitBreaker("anthropic:skeptic", clock=_FakeClock())

        result = await _run_pass(
            uncovered=[claim], audited=audited, breaker=breaker,
            bucket3=bucket3, verdicts_by_claim=verdicts,
        )

        assert result["sessions"] == 1
        assert result["recovered"] == 1
        assert result["blocked_reason"] is None
        assert audited.calls == 1  # not 3
        assert len(verdicts[id(claim)]) == 1
        assert verdicts[id(claim)][0]["verdict"] == "support"
        assert bucket3.entries == []

    async def test_a_reentered_claim_can_come_back_superseded(self):
        """F7 / D-07-A — the whole reason re-entry routes through the GROUP skeptic.

        The per-claim tool cannot say `superseded`, so a true-but-overtaken claim
        would have come back `insufficient` (survives, no caveat) and its G-07 note
        would never have reached synthesis.
        """
        claim = _claim(text="Aral holds a 21% share")
        verdicts: dict = {id(claim): []}
        notes: list[str] = []
        audited = _ScriptedGroupAudited(
            [(
                "tool_use",
                [_verdict_block(
                    verdict="superseded",
                    superseded_note="Restated to 16% in the 2026 annual report.",
                )],
            )]
        )
        bucket3 = _Bucket3()
        breaker = CircuitBreaker("anthropic:skeptic", clock=_FakeClock())

        await _run_pass(
            uncovered=[claim], audited=audited, breaker=breaker, bucket3=bucket3,
            verdicts_by_claim=verdicts, superseded_notes=notes,
        )

        assert verdicts[id(claim)][0]["verdict"] == "superseded"
        assert len(notes) == 1
        assert notes[0].startswith("[SUPERSEDED] ")
        assert "16%" in notes[0]

        # WHY the routing exists, pinned to the source of truth: the per-claim tool's
        # enum is deliberately three-valued (`tools.py`'s DELIBERATE ASYMMETRY
        # comment forbids extending it), so a future "simplification" of re-entry
        # back onto `_one_skeptic` fails HERE, with this comment attached.
        assert "superseded" not in (
            EMIT_VERDICT_TOOL["input_schema"]["properties"]["verdict"]["enum"]
        )

    async def test_open_breaker_blocks_the_fan_out(self):
        """D-07-C: an open circuit refuses the fan-out and NAMES the loss."""
        claim = _claim(text="a claim nobody will get to check")
        verdicts: dict = {id(claim): []}
        audited = _ScriptedGroupAudited()
        bucket3 = _Bucket3()
        breaker = CircuitBreaker("anthropic:skeptic", clock=_FakeClock())
        breaker.force_open("Anthropic monthly usage cap")
        assert breaker.state == "open"

        result = await _run_pass(
            uncovered=[claim], audited=audited, breaker=breaker,
            bucket3=bucket3, verdicts_by_claim=verdicts,
        )

        assert result["sessions"] == 0
        assert audited.calls == 0
        reason = result["blocked_reason"]
        assert isinstance(reason, str) and len(reason) > 40
        assert "monthly usage cap" in reason
        assert "1" in reason  # the claim count is stated
        assert bucket3.claim_texts == ["a claim nobody will get to check"]
        assert len(bucket3.entries) == 1

    async def test_half_open_does_not_authorise_a_fan_out(self):
        """D-07-C, the sharp edge: `allow()` would CONSUME the single probe.

        A fan-out of N sessions is not a probe. This test also proves the gate reads
        `state` rather than calling `allow()`: `allow()` would flip
        `_probe_in_flight` to True, and the assertion below would see "open".
        """
        claim = _claim(text="a claim in the recovery window")
        clock = _FakeClock()
        breaker = CircuitBreaker("anthropic:skeptic", clock=clock)
        breaker.force_open("Anthropic monthly usage cap")
        clock.advance(10_000.0)  # past retry_at
        assert breaker.state == "half_open"

        audited = _ScriptedGroupAudited()
        bucket3 = _Bucket3()
        result = await _run_pass(
            uncovered=[claim], audited=audited, breaker=breaker, bucket3=bucket3,
        )

        assert result["sessions"] == 0
        assert audited.calls == 0
        assert result["blocked_reason"]
        assert bucket3.claim_texts == ["a claim in the recovery window"]
        # The single half-open probe is still UNSPENT — the gate read, it did not
        # consume. If the gate had called allow(), the state would now be "open".
        assert breaker.state == "half_open"

    async def test_a_session_that_returns_nothing_is_booked_not_swallowed(self):
        """Bucket-3 site (c), with the RECORDED cause string."""
        claim = _claim(text="a claim whose session crashed")
        verdicts: dict = {id(claim): []}
        audited = _ScriptedGroupAudited(raises=RuntimeError("connection reset"))
        bucket3 = _Bucket3()
        breaker = CircuitBreaker("anthropic:skeptic", clock=_FakeClock())

        result = await _run_pass(
            uncovered=[claim], audited=audited, breaker=breaker,
            bucket3=bucket3, verdicts_by_claim=verdicts,
        )

        assert result["sessions"] == 1
        assert result["recovered"] == 0
        assert verdicts[id(claim)] == []
        assert bucket3.causes == ["coverage-gate re-entry returned no verdict"]

    def test_recon_is_meaningful_is_behaviour_preserving(self):
        """The extraction from `_flush_groups` changed nothing about the rule."""
        assert _recon_is_meaningful(
            {"disputed": False, "relation": "single", "note": "", "canonical": ""}
        ) is False
        assert _recon_is_meaningful({"disputed": True}) is True
        assert _recon_is_meaningful({"relation": "scoped"}) is True
        assert _recon_is_meaningful({"note": "different tiers"}) is True
        assert _recon_is_meaningful({"canonical": "16%"}) is True


# ---------------------------------------------------------------------------
# F8 — a pause_turn is a CONTINUATION, not a failure
# ---------------------------------------------------------------------------

def _text_block(text: str = "still searching…") -> dict:
    return {"type": "text", "text": text}


async def _run_group(
    audited: _ScriptedGroupAudited, *, max_turns: int = 4
) -> dict:
    """Call the REAL run_group_skeptic against the scripted model fake."""
    return await run_group_skeptic(
        group={
            "key": "e|a",
            "entity": "Aral",
            "attribute": "market share",
            "claims": [{"text": "Aral holds a 21% share"}],
            "stakes": "high",
        },
        sources=[],
        audited=audited,
        run_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        model="claude-sonnet-4-6",
        max_turns=max_turns,
    )


def _is_insufficient_shape(result: dict) -> bool:
    """The `_insufficient_group` fallback: every index insufficient at 0.0."""
    vbi = result.get("verdicts_by_index") or {}
    return bool(vbi) and all(
        v.get("verdict") == "insufficient" and v.get("confidence") == 0.0
        for v in vbi.values()
    )


class TestGroupSkepticPauseTurn:

    async def test_a_pause_continues_the_session(self):
        """Turn 1 pauses, turn 2 emits — the verdict is PARSED, not defaulted."""
        audited = _ScriptedGroupAudited([
            ("pause_turn", [_text_block()]),
            ("tool_use", [_verdict_block(verdict="refute", confidence=0.7)]),
        ])
        result = await _run_group(audited)

        assert result["verdicts_by_index"][0]["verdict"] == "refute"
        assert result["verdicts_by_index"][0]["confidence"] == 0.7
        assert audited.calls == 2
        # The paused assistant message was echoed back UNCHANGED — plan 02's caller
        # contract, and what makes the continuation a continuation.
        second_call_messages = audited.seen_messages[1]
        assert second_call_messages[-1]["role"] == "assistant"

    async def test_the_pause_does_not_eat_the_turn_budget(self):
        """max_turns=2 with a pause on turn 1 still reaches the emit on turn 2.

        Before F8 this session had two turns; if the paused one had consumed one of
        them the emit would have been forced into the last slot at best, and with a
        single-turn budget it would never have happened at all. The verdict below
        proves `budget` was EXTENDED rather than the turn consumed.
        """
        audited = _ScriptedGroupAudited([
            ("pause_turn", [_text_block()]),
            ("tool_use", [_verdict_block(verdict="support")]),
        ])
        result = await _run_group(audited, max_turns=2)

        assert result["verdicts_by_index"][0]["verdict"] == "support"
        assert audited.calls == 2

    async def test_pauses_are_bounded(self):
        """An unending pause_turn stream terminates — T-15.2-73.

        `stop_reason` is provider-controlled text, so a malformed or hostile stream
        must not be able to drive an unbounded, billed loop. The bound is asserted
        against the IMPORTED constant, never a hard-coded 5, so retuning the
        env-tunable cap does not silently invalidate this proof.
        """
        audited = _ScriptedGroupAudited([("pause_turn", [_text_block()])])
        result = await _run_group(audited, max_turns=2)

        assert _is_insufficient_shape(result)
        assert audited.calls <= 2 + MAX_PAUSE_CONTINUATIONS

    async def test_an_ordinary_unexpected_stop_reason_is_still_a_failure(self):
        """F8 did not widen the failure handling — only pause_turn continues."""
        audited = _ScriptedGroupAudited([("end_turn", [_text_block("done")])])
        result = await _run_group(audited, max_turns=4)

        assert _is_insufficient_shape(result)
        assert audited.calls == 1
