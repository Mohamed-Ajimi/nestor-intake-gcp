"""Gate failure-mode tests — G-11: the gate fails toward MORE checking (Phase 15.1).

WHY: everywhere else in this pipeline a failed cheap-LLM batch degrades to a
NEUTRAL default — an untagged claim just becomes its own group and is still
verified. The gate cannot have a neutral default, because its two outcomes are
"checked" and "not checked". If a gate hiccup defaulted to DROP, a transient 503
would convert into a passage that was never examined and that nothing downstream
could distinguish from a passage that passed a check. That is precisely the P1
defect this phase closes, so G-11 inverts the default: a failed, missing or
garbled gate answer sends the claim TO the fact-checkers and books a visible
`gate_errors` line. The budget governor is the backstop if that pushes the queue
back up, and the shortfall then lands honestly in bucket 3.

Coverage:
  1. a batch that fails after retries -> every claim KEEP/VERIFY, counted
  2. a usage-cap 400 is NEVER retried (the 776-error incident)
  3. a transient 429 IS retried, and a recovered retry is not an error
  4. garbled / out-of-range / unknown-word lines default to checking
  5. no failure fake in this file can make a claim disappear
  6. the zero-claim early return is shape-consistent (all nine funnel keys)
  7. a failed SECOND gate never invents a SKIP_STABLE

Pure tests: hand-written duck-typed fakes passed as `audited=`, no DB, no live
LLM, no mocking library.

Cloud Build gate:
  gcloud builds submit tribunal --config=tribunal/cloudbuild.test-gates.yaml
"""
from __future__ import annotations

import asyncio
import uuid

from nestor_pulse_sdk.pipeline.tribunal import gates
from nestor_pulse_sdk.pipeline.tribunal.gates import apply_gates

# Retries are under test here; the WALL-CLOCK of the backoff is not. Zeroing the
# base sleep keeps the suite fast without changing how many attempts are made.
# (A plain module-attribute assignment: the constant is read at call time.)
gates._GATE_BACKOFF_S = 0.0


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _claims(n: int = 3) -> list[dict]:
    return [
        {"text": f"Claim number {i} asserts something checkable.", "facet": "general"}
        for i in range(n)
    ]


def _gate_args(claims: list[dict], audited) -> dict:
    return {
        "claims": claims,
        "audited": audited,
        "run_id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "decision_context": "Should LUKOIL BeNeLux adopt AI-driven dynamic pricing?",
    }


# ---------------------------------------------------------------------------
# Fakes. `SKIP_STABLE` appears only in the second gate's prompt, so its presence
# in `contents` is how a fake tells the two gates apart.
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text


class _GateAudited:
    """Answers each gate call from a canned plain-text block, counting calls."""

    def __init__(self, materiality: str = "", stability: str = "") -> None:
        self.materiality = materiality
        self.stability = stability
        self.calls = 0
        self.prompts: list[str] = []

    async def gemini_generate(self, *, run_id, tenant_id, model, contents, **kwargs):
        self.calls += 1
        self.prompts.append(contents)
        is_stability = "SKIP_STABLE" in contents
        return _FakeResponse(self.stability if is_stability else self.materiality)


class _AlwaysRaises:
    """Every call fails with the same error, whichever gate asked."""

    def __init__(self, message: str) -> None:
        self.message = message
        self.calls = 0

    async def gemini_generate(self, *, run_id, tenant_id, model, contents, **kwargs):
        self.calls += 1
        raise RuntimeError(self.message)


class _FlakyThenGood(_GateAudited):
    """Fails `failures` times with a transient 429, then answers normally."""

    def __init__(self, materiality: str, stability: str, failures: int = 1) -> None:
        super().__init__(materiality, stability)
        self.remaining_failures = failures

    async def gemini_generate(self, *, run_id, tenant_id, model, contents, **kwargs):
        if self.remaining_failures > 0:
            self.remaining_failures -= 1
            self.calls += 1
            raise RuntimeError("429 rate limit exceeded — slow down and retry")
        return await super().gemini_generate(
            run_id=run_id, tenant_id=tenant_id, model=model,
            contents=contents, **kwargs,
        )


class _StabilityGateFails(_GateAudited):
    """Gate 1 answers normally; gate 2 always fails."""

    async def gemini_generate(self, *, run_id, tenant_id, model, contents, **kwargs):
        if "SKIP_STABLE" in contents:
            self.calls += 1
            raise RuntimeError("503 service unavailable")
        return await super().gemini_generate(
            run_id=run_id, tenant_id=tenant_id, model=model,
            contents=contents, **kwargs,
        )


_KEEP_ALL = "0 | KEEP | KEEP\n1 | KEEP | KEEP\n2 | KEEP | KEEP"
_DROP_ALL = "0 | DROP | BOTH\n1 | DROP | BOTH\n2 | DROP | BOTH"
_VERIFY_ALL = "0 | VERIFY\n1 | VERIFY\n2 | VERIFY"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_gate_batch_failure_sends_claims_to_checking():
    """G-11: a batch that fails after retries fails toward MORE checking.

    Every claim in the failed batch is treated as "assume worth checking", enters
    the verify queue, and is counted in `gate_errors` — the shortfall becomes
    visible spend pressure that the budget governor absorbs, and lands honestly in
    bucket 3, instead of becoming an invisible unexamined passage."""
    claims = _claims(3)
    audited = _AlwaysRaises("503 service unavailable")
    result = _run(apply_gates(**_gate_args(claims, audited)))
    funnel = result["funnel"]

    for claim in result["claims"]:
        assert claim["gate"]["decision"] == "KEEP", (
            "a failed gate must never remove a claim from checking — that converts "
            "a transient hiccup into a permanently unexamined passage"
        )
        assert claim["gate"]["strict"] == "VERIFY", (
            "a failed error-likelihood gate must send the claim to the queue, not "
            "invent a skip"
        )
        assert claim["gate"]["gate_error"] is True, (
            "an applied default must be recorded, or the funnel under-reports how "
            "much of the run was guessed at"
        )

    assert funnel["gate_errors"] == 3, funnel
    assert funnel["selected_verify"] == 3, funnel
    assert funnel["dropped"] == 0, (
        f"a gate outage may not drop a single claim, got {funnel}"
    )


def test_usage_cap_400_is_not_retried():
    """A hard usage-cap 400 is a statement about the ACCOUNT, not a blip.

    THE 776-ERROR INCIDENT (run 4cbb5311, 2026-07-22): retrying a capped account
    produced 776 hard HTTP 400s in 55 seconds, no results, and verification
    covering only 198 of 1,162 claims. Retrying a cap error can only produce more
    cap errors, faster — so it costs exactly one attempt per batch."""
    claims = _claims(3)
    audited = _AlwaysRaises(
        "400 Bad Request: usage limit exceeded for this organization"
    )
    result = _run(apply_gates(**_gate_args(claims, audited)))

    # Two batches are attempted (gate 1 over all claims, gate 2 over the claims
    # gate 1 defaulted to KEEP) — exactly ONE call each, no retry.
    assert audited.calls == 2, (
        f"a usage-cap 400 must cost one attempt per gate batch, got "
        f"{audited.calls} calls — that is the 776-error retry storm reappearing"
    )
    assert result["funnel"]["dropped"] == 0, result["funnel"]
    assert result["funnel"]["selected_verify"] == 3, result["funnel"]


def test_transient_error_is_retried_then_succeeds():
    """A 429 IS retried, and a recovered retry is NOT a gate error.

    Gate 1 drops every claim here, so gate 2 has nothing to classify and makes no
    call — the call count is then exactly the gate-1 attempts: one failure plus
    one success."""
    claims = _claims(3)
    audited = _FlakyThenGood(materiality=_DROP_ALL, stability=_VERIFY_ALL, failures=1)
    result = _run(apply_gates(**_gate_args(claims, audited)))

    assert audited.calls == 2, (
        f"a transient 429 must be retried exactly once here, got {audited.calls} calls"
    )
    assert result["funnel"]["gate_errors"] == 0, (
        "a retry that recovered is not a gate error — counting it would inflate "
        "the honesty appendix and hide real outages in the noise"
    )
    assert result["funnel"]["dropped"] == 3, result["funnel"]


def test_garbled_gate_line_defaults_to_checking():
    """Out-of-range indices, missing pipes and unknown words all mean CHECK.

    Claim 0 is answered validly. Claim 1 is never addressed (the model answered
    index 99 instead). Claim 2 is answered with words outside the allowed
    vocabulary. Both unanswered claims must end up checked and counted."""
    claims = _claims(3)
    garbled = (
        "0 | KEEP | KEEP\n"
        "99 | DROP | BOTH\n"          # out of range — addresses nothing
        "this line has no pipe at all\n"
        "2 | MAYBE | WHATEVER\n"      # unknown words in both slots
    )
    audited = _GateAudited(materiality=garbled, stability=_VERIFY_ALL)
    result = _run(apply_gates(**_gate_args(claims, audited)))
    funnel = result["funnel"]

    assert funnel["dropped"] == 0, (
        f"no claim may be dropped on a garbled gate answer, got {funnel}"
    )
    for claim in result["claims"]:
        assert claim["gate"]["strict"] == "VERIFY", claim["gate"]
    assert [c["gate"]["gate_error"] for c in result["claims"]] == [False, True, True], (
        "gate_error must mark exactly the claims whose answer had to be defaulted"
    )
    assert funnel["gate_errors"] == 2, funnel


def test_no_claim_is_ever_silently_dropped():
    """Every failure fake in this file: same claim objects out, funnel balances."""
    fakes = [
        _AlwaysRaises("503 service unavailable"),
        _AlwaysRaises("400 Bad Request: usage limit exceeded"),
        _AlwaysRaises("connection reset by peer"),
        _GateAudited(materiality="", stability=""),                  # empty answer
        _GateAudited(materiality="total garbage", stability="more garbage"),
        _FlakyThenGood(materiality=_KEEP_ALL, stability=_VERIFY_ALL, failures=1),
        _StabilityGateFails(materiality=_KEEP_ALL, stability=_VERIFY_ALL),
    ]
    for audited in fakes:
        claims = _claims(3)
        result = _run(apply_gates(**_gate_args(claims, audited)))
        funnel = result["funnel"]
        assert len(result["claims"]) == len(claims), (
            f"{type(audited).__name__} lost a claim — the gate stage is not "
            f"allowed to reduce the claim list, only to label it"
        )
        assert result["claims"] == claims, (
            f"{type(audited).__name__} returned different objects; decisions must "
            f"be written onto the SAME claim dicts"
        )
        assert funnel["distilled"] == funnel["kept"] + funnel["dropped"], (
            f"{type(audited).__name__} broke the funnel: {funnel}"
        )
        assert funnel["distilled"] == 3, funnel


def test_empty_claim_list_returns_zero_funnel():
    """The zero-claim path must be SHAPE-consistent with the full path.

    A divergent empty-path shape is how a downstream reader ends up with a
    KeyError, or worse, a report that silently omits the funnel entirely."""
    audited = _GateAudited(materiality=_KEEP_ALL, stability=_VERIFY_ALL)
    result = _run(apply_gates(**_gate_args([], audited)))

    assert result["claims"] == []
    assert result["selected"] == []
    assert audited.calls == 0, "an empty claim list must cost nothing"
    expected_keys = {
        "distilled", "kept", "dropped", "not_falsifiable", "not_load_bearing",
        "both", "selected_verify", "skipped_stable", "gate_errors",
    }
    assert set(result["funnel"]) == expected_keys, result["funnel"]
    assert all(v == 0 for v in result["funnel"].values()), result["funnel"]


def test_second_gate_failure_keeps_claims_in_the_queue():
    """Gate 1 succeeds, gate 2 fails: the survivors stay VERIFY, never SKIP_STABLE.

    A failed error-likelihood gate has learned nothing about how stable these
    facts are, so it may not invent a skip. Skipping on ignorance is exactly the
    silent verification loss G-11 forbids."""
    claims = _claims(3)
    audited = _StabilityGateFails(materiality=_KEEP_ALL, stability=_VERIFY_ALL)
    result = _run(apply_gates(**_gate_args(claims, audited)))
    funnel = result["funnel"]

    assert funnel["kept"] == 3, funnel
    for claim in result["claims"]:
        assert claim["gate"]["strict"] == "VERIFY", (
            "a failed stability gate must not invent a SKIP_STABLE — that is a "
            "check silently not performed"
        )
        assert claim["gate"]["gate_error"] is True, claim["gate"]
    assert funnel["skipped_stable"] == 0, funnel
    assert funnel["selected_verify"] == 3, funnel
    assert len(result["selected"]) == 3, funnel
