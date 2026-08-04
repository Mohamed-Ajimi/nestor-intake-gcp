"""The yield emitter: it cannot fail a run, and it cannot LOSE a measurement.

WHY THIS FILE EXISTS
--------------------
Three guarantees, one file, and the third one fails SILENTLY.

**IT MAY NEVER RAISE INTO A CALLER.** The call sites are stage boundaries inside
a roughly $45 run. As with `run_events`, the obvious implementation -- wrap the
body in try/except -- reads like it satisfies this and DOES NOT, because A
CALLER'S ARGUMENTS ARE EVALUATED BEFORE THE CALLEE IS ENTERED. The `_safe` trio's
`build` thunk is the fix, and the tests below drive a RAISING `build` and a
MALFORMED `build` through the real wrapper.

**IT MAY NEVER DISCARD A ROW ON THE BASIS OF A FIELD VALUE (D-W5-10).** This is
STRONGER than "never raises" and is the ruling that overturned this plan's first
draft. An out-of-vocabulary `parent_kind` -- or an unusable `provider` -- CLAMPS
to a recorded sentinel and THE ROW IS STILL WRITTEN with every measured column
intact. So the tests assert THE WRITER SEAM WAS CALLED, call count == 1, and not
merely that no exception escaped: A DROP RAISES NOTHING EITHER, so "no exception
escaped" is not evidence. `cost_usd` matters most, because `SUM(cost_usd)` SKIPS
NULL ROWS -- a dropped row silently UNDERSTATES what the run spent.

**THE INSERT AND THE UPDATE MUST BUILD ONE KEY (item 5a).** Three of the four
natural-key members are normalised: `provider` is clamped, `group_id` turns `''`
into NULL, `client_question` is SCRUBBED then clamped. If the completer built its
key from RAW values while the INSERT stored normalised ones, the UPDATE would
match NOTHING -- and the module's own warning reads 0 affected rows as "the
INSERT half never landed", producing a SPECIFIC, CONFIDENT AND WRONG DIAGNOSIS OF
A DIFFERENT FAILURE. The three round-trip tests drive BOTH halves with THE SAME
RAW INPUTS and compare the bound values. THEY ARE THE MOST VALUABLE TESTS IN THIS
FILE: the insert-side failures are loud, and this one is silent.

THIS FILE OPENS NO DATABASE, MAKES ZERO LLM CALLS, USES NO MOCKING LIBRARY AND
NEEDS NO API KEY. The three operations that touch Postgres --
`_assignment_writer`, `_assignment_completer` and `_round_writer` -- are
module-level TEST SEAMS replaced by a hand-written duck-typed recorder. There is
no second harness. Everything between a public call and that recorder --
clamping, scrubbing, key assembly, coercion, warning -- is production code doing
its real job.

⛔ THE `ast`-LIFT HARNESS IS NOT USED ANYWHERE IN THIS FILE, and must never be.
It SUPPLIES MODULE GLOBALS and therefore MANUFACTURES any name the module forgot
to import; it hid a missing import used at four sites through nine plans and "38
lifted tests green". This file does a REAL import of the real module, which is
the only thing that proves name resolution.

Cloud Build invocation (no Postgres and no provider key needed):
  gcloud builds submit tribunal \\
    --config=tribunal/cloudbuild.test-engine.yaml \\
    --project="$GOOGLE_PROJECT"

This plan does NOT add itself to that config: it has exactly ONE owner in phase
15.8 -- plan 15.8-13, wave 4 (D-W5-5).
"""
from __future__ import annotations

import ast
import inspect
import logging
import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from nestor_pulse_sdk.pipeline.tribunal.pii import REDACTED
from nestor_pulse_sdk.runs import yield_records as yr

_LOGGER = "nestor_pulse_sdk.runs.yield_records"


# ---------------------------------------------------------------------------
# The recorder. Duck-typed to the three writers' `(tenant_id, params)` shape --
# it stands in for the DATABASE WRITE only.
# ---------------------------------------------------------------------------
class _Recorder:
    def __init__(self, *, raises: bool = False, rowcount: int = 1) -> None:
        self.calls: list[dict[str, Any]] = []
        self.raises = raises
        self.rowcount = rowcount

    @property
    def count(self) -> int:
        return len(self.calls)

    @property
    def last(self) -> dict[str, Any]:
        assert self.calls, "the writer seam was never called"
        return self.calls[-1]["params"]

    async def __call__(self, tenant_id: Any, params: dict[str, Any]) -> int:
        # Record BEFORE raising: a writer that fails must still be observable.
        self.calls.append({"tenant_id": tenant_id, "params": dict(params)})
        if self.raises:
            raise RuntimeError("the writer is down")
        return self.rowcount


@pytest.fixture
def seams(monkeypatch):
    """Recorders bound to all three Postgres seams. No test reaches a database."""
    bound = SimpleNamespace(
        writer=_Recorder(), completer=_Recorder(), rounds=_Recorder()
    )
    monkeypatch.setattr(yr, "_assignment_writer", bound.writer)
    monkeypatch.setattr(yr, "_assignment_completer", bound.completer)
    monkeypatch.setattr(yr, "_round_writer", bound.rounds)
    return bound


def _run() -> tuple[uuid.UUID, uuid.UUID]:
    return uuid.uuid4(), uuid.uuid4()


def _assignment(**over: Any) -> dict[str, Any]:
    """A full, well-formed assignment payload; override one field per test."""
    base: dict[str, Any] = {
        "provider": "gemini",
        "group_id": "w01",
        "client_question": "How large is the Belgian retrofit market?",
        "parent_kind": "client_question",
        "stakes": "high",
        "fact_list_parsed": True,
        "retry_used": False,
        "claims_kept": 17,
        "resolvable_sources": 9,
        "cost_usd": "0.4831",
        "duration_s": "12.500",
    }
    base.update(over)
    return base


def _round(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "round_no": 7,
        "candidates_in": 22,
        "new_candidates": 3,
        "keep_count": 11,
        "weak_count": 4,
        "kill_count": 2,
        "new_entrants_top_n": 0,
        "barred_drops": 1,
        "round_cost_usd": "0.0620",
    }
    base.update(over)
    return base


# ===========================================================================
# 1. The happy path and the vocabulary
# ===========================================================================


async def test_a_well_formed_assignment_binds_every_contract_column(seams) -> None:
    """One writer call, one parameter dict, every INSERT column bound.

    `claims_surviving_verification` is DELIBERATELY ABSENT: it is not known at
    this point in the run and is filled by `complete_assignment` later.
    """
    run_id, tenant_id = _run()

    await yr.record_assignment(run_id, tenant_id, **_assignment())

    assert seams.writer.count == 1
    params = seams.writer.last
    assert set(params) == {
        "id", "tenant_id", "run_id", "provider", "group_id", "client_question",
        "parent_kind", "stakes", "fact_list_parsed", "retry_used", "claims_kept",
        "resolvable_sources", "cost_usd", "duration_s",
    }
    assert "claims_surviving_verification" not in params
    assert params["run_id"] == str(run_id)
    assert params["tenant_id"] == str(tenant_id)
    assert uuid.UUID(params["id"])  # a fresh, parseable uuid
    assert params["provider"] == "gemini"
    assert params["group_id"] == "w01"
    assert params["parent_kind"] == "client_question"
    assert params["stakes"] == "high"
    assert params["fact_list_parsed"] is True
    assert params["retry_used"] is False
    assert params["claims_kept"] == 17
    assert params["resolvable_sources"] == 9
    assert params["cost_usd"] == Decimal("0.4831")
    assert params["duration_s"] == Decimal("12.500")


def test_neither_sentinel_belongs_to_a_ruled_vocabulary() -> None:
    """`unknown` is queryable AS an engine bug, and never AS a ruled shape.

    A reader asking `parent_kind IN PARENT_KINDS` must get exactly the three
    D-W5-2 shapes; `parent_kind = 'unknown'` is the separate, deliberate query
    that finds the engine bugs.
    """
    assert yr.PARENT_KINDS == (
        "client_question",
        "discovery_rider",
        "cross_cutting",
    )
    assert yr.PARENT_KIND_UNKNOWN not in yr.PARENT_KINDS
    assert yr.PROVIDER_UNKNOWN not in yr.PARENT_KINDS


# ===========================================================================
# 2. THE OVERRULE (D-W5-10): a bad discriminator CLAMPS, and the row SURVIVES
#
# Asserted on the SEAM CALL COUNT, not on "no exception escaped" -- a drop
# raises nothing either, so the weaker assertion would pass on the mutant.
# ===========================================================================


async def test_an_out_of_vocabulary_parent_kind_still_writes_the_row(
    seams, caplog
) -> None:
    """THE ROW IS WRITTEN, the sentinel is bound, EVERY MEASURED COLUMN INTACT.

    `parent_kind` is ENGINE-AUTHORED, so an out-of-vocabulary value means an
    ENGINE BUG -- precisely the run whose telemetry is most worth keeping. And a
    dropped row would SILENTLY UNDERSTATE SPEND, because `SUM(cost_usd)` skips
    NULL rows across four `COALESCE` sites in `runs/worker.py`.

    A MUTANT THAT DROPS THE ROW MUST TURN THIS RED, which is why `count == 1` is
    asserted and not merely that the call returned.
    """
    run_id, tenant_id = _run()
    caplog.set_level(logging.WARNING, logger=_LOGGER)

    await yr.record_assignment(
        run_id, tenant_id, **_assignment(parent_kind="mandate_group")
    )

    assert seams.writer.count == 1  # THE ROW WAS WRITTEN
    params = seams.writer.last
    assert params["parent_kind"] == yr.PARENT_KIND_UNKNOWN
    # ...and nothing else was collateral damage.
    assert params["cost_usd"] == Decimal("0.4831")
    assert params["claims_kept"] == 17
    assert params["resolvable_sources"] == 9
    assert params["duration_s"] == Decimal("12.500")
    assert params["provider"] == "gemini"
    assert "mandate_group" in caplog.text


async def test_an_unusable_provider_still_writes_the_row(seams, caplog) -> None:
    """Same overrule, extended to `provider` -- and here the money is the point.

    A row carrying `provider = 'unknown'` STILL CARRIES ITS DOLLARS. Dropping it
    would remove those dollars from a `SUM` without announcing itself.
    """
    run_id, tenant_id = _run()
    caplog.set_level(logging.WARNING, logger=_LOGGER)

    await yr.record_assignment(run_id, tenant_id, **_assignment(provider="   "))

    assert seams.writer.count == 1  # THE ROW WAS WRITTEN
    params = seams.writer.last
    assert params["provider"] == yr.PROVIDER_UNKNOWN
    assert params["cost_usd"] == Decimal("0.4831")
    assert params["claims_kept"] == 17
    assert "provider" in caplog.text


async def test_neither_discriminator_clamp_can_return_a_skip_value() -> None:
    """Both clamps return `str`, ALWAYS. Neither has a "drop this row" channel.

    Structural backstop to the two behavioural tests above: if a normaliser could
    return `None`, a later caller could reintroduce the drop by branching on it.
    """
    for garbage in (None, "", "   ", 17, object(), [], {}):
        provider = yr._normalise_provider(garbage, run_id="r")
        kind = yr._normalise_parent_kind(garbage, run_id="r", provider="p")
        assert isinstance(provider, str) and provider
        assert isinstance(kind, str) and kind
    assert yr._normalise_parent_kind("cross_cutting", run_id="r", provider="p") == (
        "cross_cutting"
    )


# ===========================================================================
# 3. THE KEY ROUND-TRIP (item 5a) -- the silent one.
#
# Each case drives BOTH halves with THE SAME RAW INPUTS and asserts the
# completer's WHERE parameters equal the inserter's bound key values. A mutant
# that makes `complete_assignment` bind raw values must turn these RED.
# ===========================================================================


async def _round_trip(seams, **over: Any) -> tuple[dict, dict]:
    """Drive INSERT then UPDATE with the SAME RAW arguments; return both dicts."""
    run_id, tenant_id = _run()
    payload = _assignment(**over)

    await yr.record_assignment(run_id, tenant_id, **payload)
    await yr.complete_assignment(
        run_id,
        tenant_id,
        # THE SAME RAW VALUES. A caller never pre-normalises anything.
        provider=payload["provider"],
        group_id=payload["group_id"],
        client_question=payload["client_question"],
        claims_surviving_verification=5,
    )

    inserted = seams.writer.last
    updated = seams.completer.last
    # The key, whatever it turned out to be, must be IDENTICAL on both paths.
    for member in ("run_id", "provider", "group_id", "client_question"):
        assert updated[member] == inserted[member], member
    return inserted, updated


async def test_the_update_finds_a_row_whose_provider_was_clamped(seams) -> None:
    """An uncoercible `provider`: BOTH halves bind the sentinel, not the raw value."""
    inserted, updated = await _round_trip(seams, provider="")

    assert inserted["provider"] == yr.PROVIDER_UNKNOWN
    assert updated["provider"] == yr.PROVIDER_UNKNOWN
    assert updated["claims_surviving_verification"] == 5


async def test_the_update_finds_a_row_whose_client_question_was_scrubbed(
    seams,
) -> None:
    """A question containing an email: BOTH halves bind the SCRUBBED text.

    This is not exotic -- `scrub_pii` rewrites ANY question carrying an email or
    a phone number, and the workshop's own inputs have produced exactly that.
    """
    raw = "Who at hello@example.com owns the retrofit budget?"
    inserted, updated = await _round_trip(seams, client_question=raw)

    assert inserted["client_question"] != raw
    assert REDACTED in inserted["client_question"]
    assert "hello@example.com" not in inserted["client_question"]
    assert updated["client_question"] == inserted["client_question"]


async def test_the_update_finds_a_row_whose_empty_group_id_became_null(
    seams,
) -> None:
    """`group_id=""` stores NULL on the INSERT, and the UPDATE binds NULL too.

    0017's rule: an ABSENT key is NULL and never `''`, because "no key recorded"
    and "recorded as the empty key" are different facts. `IS NOT DISTINCT FROM`
    in the WHERE is what lets that NULL match its own row.
    """
    inserted, updated = await _round_trip(seams, group_id="")

    assert inserted["group_id"] is None
    assert updated["group_id"] is None


async def test_a_cross_cutting_row_with_no_question_still_round_trips(
    seams,
) -> None:
    """The hardest key: TWO nullable members are NULL and it still matches."""
    inserted, updated = await _round_trip(
        seams, client_question=None, group_id=None, parent_kind="cross_cutting"
    )

    assert inserted["client_question"] is None
    assert inserted["group_id"] is None
    assert inserted["parent_kind"] == "cross_cutting"
    assert updated["client_question"] is None
    assert updated["group_id"] is None


# ===========================================================================
# 4. The three D-W5-2 shapes, and the rule that they are NOT interchangeable
# ===========================================================================


@pytest.mark.parametrize(
    "parent_kind,client_question",
    [
        ("cross_cutting", None),
        ("discovery_rider", "Which suppliers dominate heat-pump installs?"),
        ("client_question", "How large is the Belgian retrofit market?"),
    ],
)
async def test_the_three_shapes_each_round_trip_distinctly(
    seams, parent_kind: str, client_question: str | None
) -> None:
    """Each ruled shape binds exactly what it was given -- no inference."""
    run_id, tenant_id = _run()

    await yr.record_assignment(
        run_id,
        tenant_id,
        **_assignment(parent_kind=parent_kind, client_question=client_question),
    )

    params = seams.writer.last
    assert params["parent_kind"] == parent_kind
    if client_question is None:
        assert params["client_question"] is None
    else:
        assert params["client_question"] == client_question


async def test_parent_kind_is_never_derived_from_client_question_being_none(
    seams,
) -> None:
    """THE D-W5-2 RULE, asserted as behaviour rather than left to a docstring.

    A row may legitimately carry `client_question = NULL` with
    `parent_kind = 'client_question'`. The two encode DIFFERENT THINGS, and an
    implementation that inferred one from the other would silently rewrite this
    pair -- and a future reader would conflate them forever after.
    """
    run_id, tenant_id = _run()

    await yr.record_assignment(
        run_id,
        tenant_id,
        **_assignment(client_question=None, parent_kind="client_question"),
    )

    params = seams.writer.last
    assert params["client_question"] is None
    assert params["parent_kind"] == "client_question"  # NOT rewritten to cross_cutting

    # ...and the mirror: a cross_cutting row that DOES carry a question keeps it.
    await yr.record_assignment(
        run_id,
        tenant_id,
        **_assignment(client_question="a real question", parent_kind="cross_cutting"),
    )
    params = seams.writer.last
    assert params["client_question"] == "a real question"
    assert params["parent_kind"] == "cross_cutting"


# ===========================================================================
# 5. Normalisation rules
# ===========================================================================


async def test_scrub_happens_before_clamp_and_the_order_is_the_point(
    seams, monkeypatch
) -> None:
    """D-07 ORDER PROOF, with the counterfactual asserted inline.

    The address is placed so that a CLAMP-THEN-SCRUB order bisects it into
    `someone@ex` -- which has no TLD, so `pii._EMAIL_RE` no longer matches and a
    recognisable fragment is PERSISTED, in a table read long after the run. A
    test that only asserted "the address is gone" would pass on BOTH orders and
    pin nothing.
    """
    monkeypatch.setattr(yr, "MAX_QUESTION_CHARS", 20)
    raw = "x" * 12 + " someone@example.com"
    run_id, tenant_id = _run()

    await yr.record_assignment(run_id, tenant_id, **_assignment(client_question=raw))

    stored = seams.writer.last["client_question"]
    assert "someone@" not in stored
    assert REDACTED in stored

    # THE COUNTERFACTUAL: the wrong order, run inline, leaks a fragment.
    from nestor_pulse_sdk.pipeline.tribunal.pii import scrub_pii

    wrong_order, _removed = scrub_pii(raw[:20])
    assert "someone@ex" in wrong_order  # the scrubber can no longer see it


async def test_a_question_longer_than_the_cap_is_clamped(seams, monkeypatch) -> None:
    """The clamp bounds the column, and marks the cut visibly."""
    monkeypatch.setattr(yr, "MAX_QUESTION_CHARS", 30)
    run_id, tenant_id = _run()

    await yr.record_assignment(
        run_id, tenant_id, **_assignment(client_question="q" * 200)
    )

    stored = seams.writer.last["client_question"]
    assert len(stored) == 31  # 30 + the single ellipsis marking the cut
    assert stored.endswith("…")


@pytest.mark.parametrize("garbage", [None, "seventeen", object(), [], {}, "", True])
async def test_a_garbage_counter_binds_none_and_never_zero(seams, garbage) -> None:
    """"Not recorded" and "measured zero" MUST stay distinguishable.

    This is the one place where copying `workshop_loop._count_of`, which returns
    0, would be WRONG: a fabricated 0 is a MEASUREMENT, and this table exists to
    stop exactly that. `True` is included because `bool` is an `int` subclass and
    would otherwise silently bind 1.
    """
    run_id, tenant_id = _run()

    await yr.record_assignment(run_id, tenant_id, **_assignment(claims_kept=garbage))

    assert seams.writer.count == 1  # still written -- a bad counter is not a drop
    assert seams.writer.last["claims_kept"] is None


async def test_a_real_zero_is_preserved_as_a_measurement(seams) -> None:
    """The other half of the rule: a genuine 0 must NOT become NULL."""
    run_id, tenant_id = _run()

    await yr.record_assignment(
        run_id, tenant_id, **_assignment(claims_kept=0, resolvable_sources=0)
    )

    assert seams.writer.last["claims_kept"] == 0
    assert seams.writer.last["resolvable_sources"] == 0


async def test_cost_and_duration_become_decimal_or_none(seams) -> None:
    """`Decimal` via `str`, never via `float`, and None on anything unparseable.

    Via `str` because `Decimal(0.1)` carries the binary rounding error into a
    NUMERIC column a human will later read as money.
    """
    run_id, tenant_id = _run()

    await yr.record_assignment(run_id, tenant_id, **_assignment(cost_usd="0.4831"))
    assert seams.writer.last["cost_usd"] == Decimal("0.4831")

    await yr.record_assignment(run_id, tenant_id, **_assignment(cost_usd="cheap"))
    assert seams.writer.last["cost_usd"] is None
    assert seams.writer.count == 2  # unparseable cost is STILL not a drop

    await yr.record_assignment(run_id, tenant_id, **_assignment(duration_s=None))
    assert seams.writer.last["duration_s"] is None


async def test_a_boolean_flag_is_coerced_or_left_none(seams) -> None:
    """None stays None; anything else becomes a real bool."""
    run_id, tenant_id = _run()

    await yr.record_assignment(
        run_id, tenant_id, **_assignment(fact_list_parsed=None, retry_used=1)
    )

    assert seams.writer.last["fact_list_parsed"] is None
    assert seams.writer.last["retry_used"] is True


# ===========================================================================
# 6. Never-raises, at the body AND at the call site
# ===========================================================================


async def test_a_raising_writer_leaves_every_public_function_returning(
    monkeypatch, caplog
) -> None:
    """All three writers down; all three public calls return None, warning only.

    The write is NOT retried: a retrying observability path consumes the run it
    observes.
    """
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    writer = _Recorder(raises=True)
    completer = _Recorder(raises=True)
    rounds = _Recorder(raises=True)
    monkeypatch.setattr(yr, "_assignment_writer", writer)
    monkeypatch.setattr(yr, "_assignment_completer", completer)
    monkeypatch.setattr(yr, "_round_writer", rounds)
    run_id, tenant_id = _run()

    assert await yr.record_assignment(run_id, tenant_id, **_assignment()) is None
    assert (
        await yr.complete_assignment(
            run_id,
            tenant_id,
            provider="gemini",
            group_id="w01",
            client_question="q",
            claims_surviving_verification=3,
        )
        is None
    )
    assert await yr.record_round(run_id, tenant_id, **_round()) is None

    # Attempted exactly once each, and never retried.
    assert (writer.count, completer.count, rounds.count) == (1, 1, 1)
    assert caplog.text.count("the writer is down") == 0  # the repr is logged, not raised
    assert "record_assignment failed" in caplog.text
    assert "complete_assignment failed" in caplog.text
    assert "record_round failed" in caplog.text


async def test_a_raising_build_is_caught_and_the_writer_is_never_called(
    seams, caplog
) -> None:
    """THE CONTROL-FLOW POINT: the failure happens while BUILDING the arguments.

    A degrading provider returning a short dict makes `result["facts"]` raise
    `KeyError` AT THE CALL SITE. No defensive code inside `record_assignment`
    could catch that -- only moving the construction inside the wrapper's `try`
    can, which is what the `build` thunk does.
    """
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    run_id, tenant_id = _run()
    degraded: dict[str, Any] = {}  # the provider returned a short dict

    await yr.record_assignment_safe(
        run_id,
        tenant_id,
        build=lambda: _assignment(claims_kept=degraded["facts"]),
    )

    assert seams.writer.count == 0
    assert "KeyError" in caplog.text


@pytest.mark.parametrize(
    "wrapper,seam",
    [
        ("record_assignment_safe", "writer"),
        ("complete_assignment_safe", "completer"),
        ("record_round_safe", "rounds"),
    ],
)
async def test_a_safe_wrapper_logs_rather_than_unpacking_a_non_dict(
    seams, caplog, wrapper: str, seam: str
) -> None:
    """The ONE unwritten-row case in the module -- there is nothing to salvage.

    `**`-unpacking a non-dict would raise HERE, which is the very thing these
    wrappers exist to stop.
    """
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    run_id, tenant_id = _run()

    await getattr(yr, wrapper)(run_id, tenant_id, build=lambda: ["not", "a", "dict"])

    assert getattr(seams, seam).count == 0
    assert "not a dict" in caplog.text or "not\na dict" in caplog.text


async def test_the_safe_wrappers_pass_a_well_formed_build_straight_through(
    seams,
) -> None:
    """The wrappers are not merely guards -- the happy path still writes."""
    run_id, tenant_id = _run()

    await yr.record_assignment_safe(run_id, tenant_id, build=lambda: _assignment())
    await yr.record_round_safe(run_id, tenant_id, build=lambda: _round())
    await yr.complete_assignment_safe(
        run_id,
        tenant_id,
        build=lambda: {
            "provider": "gemini",
            "group_id": "w01",
            "client_question": "q",
            "claims_surviving_verification": 4,
        },
    )

    assert (seams.writer.count, seams.rounds.count, seams.completer.count) == (1, 1, 1)


# ===========================================================================
# 7. The affected-row-count warning, and the round writer
# ===========================================================================


@pytest.mark.parametrize("rowcount", [0, 2])
async def test_complete_assignment_warns_when_the_row_count_is_not_exactly_one(
    monkeypatch, caplog, rowcount: int
) -> None:
    """0 means the INSERT never landed; >1 means the doubled high-stakes copy.

    `divide()`'s focus-area fallback doubles a high-stakes angle with a second
    copy to `_HIGH_REDUNDANCY_PROVIDER`, which can produce two rows sharing the
    natural key -- and a SUM over `claims_surviving_verification` would then
    DOUBLE-COUNT. The live group-dispatch path sends each group to each stream
    exactly once and cannot.
    """
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    completer = _Recorder(rowcount=rowcount)
    monkeypatch.setattr(yr, "_assignment_completer", completer)
    run_id, tenant_id = _run()

    await yr.complete_assignment(
        run_id,
        tenant_id,
        provider="gemini",
        group_id="w01",
        client_question="q",
        claims_surviving_verification=3,
    )

    assert completer.count == 1
    assert "expected" in caplog.text and "exactly 1" in caplog.text


async def test_a_single_affected_row_logs_no_warning(seams, caplog) -> None:
    """The control: the normal case must be SILENT, or the warning is noise."""
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    run_id, tenant_id = _run()

    await yr.complete_assignment(
        run_id,
        tenant_id,
        provider="gemini",
        group_id="w01",
        client_question="q",
        claims_surviving_verification=3,
    )

    assert seams.completer.count == 1
    assert "expected" not in caplog.text


async def test_record_round_binds_all_thirteen_workshop_round_yield_fields(
    seams,
) -> None:
    """Every `workshop_round_yield` column except the server-defaulted timestamp.

    `keep_count` is the KEEP CRITIQUE-VERDICT count and NOT `len(entries)`, and
    `barred_drops` is the BARRED CAUSE ONLY (D-W5-6). This module binds what it
    is given; getting those two right is 15.8-10's obligation.
    """
    run_id, tenant_id = _run()

    await yr.record_round(run_id, tenant_id, **_round())

    assert seams.rounds.count == 1
    params = seams.rounds.last
    assert set(params) == {
        "id", "tenant_id", "run_id", "round_no", "candidates_in",
        "new_candidates", "keep_count", "weak_count", "kill_count",
        "new_entrants_top_n", "barred_drops", "round_cost_usd",
    }
    assert params["round_no"] == 7
    assert params["keep_count"] == 11
    assert params["barred_drops"] == 1
    # A genuine zero survives: "round 7 produced NO new entrant" is THE
    # measurement the whole loop's justification rests on, and a NULL there
    # would erase it.
    assert params["new_entrants_top_n"] == 0
    assert params["round_cost_usd"] == Decimal("0.0620")


# ===========================================================================
# 8. Structural invariants -- read off the module's own source
# ===========================================================================


def _module_tree() -> ast.Module:
    return ast.parse(inspect.getsource(yr))


def test_the_module_imports_no_sqlalchemy_and_no_db_package_at_module_level() -> None:
    """Module scope is stdlib plus `pii` only. This is LOAD-BEARING, not tidy.

    It is what lets this very file import the REAL module on a machine with no
    sqlalchemy -- the only way to defeat the `ast`-lift trap, which supplies
    module globals and manufactures any name a module forgot to import.
    """
    tree = _module_tree()
    top_level = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]

    names: list[str] = []
    for node in top_level:
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        else:
            names.append(node.module or "")

    for name in names:
        assert not name.startswith("sqlalchemy"), name
        assert not name.startswith("nestor_pulse_sdk.db"), name
    assert "nestor_pulse_sdk.pipeline.tribunal.pii" in names


def test_no_sql_statement_is_built_by_string_interpolation() -> None:
    """T-15.8-05-01. Bound parameters only -- no f-string, `%` or `.format()`.

    `client_question` and `group_id` originate in model output built from
    client-authored intake text, so they cross a trust boundary into a durable
    store. They never reach a statement AS TEXT.
    """
    tree = _module_tree()

    for node in ast.walk(tree):
        # No f-string anywhere in the module.
        assert not isinstance(node, ast.JoinedStr), ast.dump(node)
        # No `.format(` on any string.
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr != "format", ast.dump(node)
        # No `%` applied to a string literal.
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
            assert not isinstance(node.left, ast.Constant) or not isinstance(
                node.left.value, str
            ), ast.dump(node)


def _call_sites(tree: ast.AST, name: str) -> int:
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == name
    )


def test_the_natural_key_has_exactly_two_call_sites_and_each_rule_exactly_one() -> None:
    """ITEM 5a, ENFORCED STRUCTURALLY. Two normalisation paths for one key member
    IS the defect.

    `_natural_key` is called from `record_assignment` and from
    `complete_assignment` -- exactly twice. And each key member's rule is reached
    ONLY from inside `_natural_key`, so the INSERT and the UPDATE cannot drift
    apart. A refactor that inlines one call and not the other reintroduces the
    silent-mismatch defect WHILE LOOKING TIDIER, and this test is what catches it.
    """
    tree = _module_tree()

    assert _call_sites(tree, "_natural_key") == 2
    assert _call_sites(tree, "_normalise_provider") == 1
    assert _call_sites(tree, "_normalise_group_id") == 1
    assert _call_sites(tree, "_normalise_question") == 1

    # ...and both of `_natural_key`'s callers are the two public halves.
    callers = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and _call_sites(node, "_natural_key") == 1
    }
    assert callers == {"record_assignment", "complete_assignment"}


@pytest.mark.parametrize(
    "wrapper",
    ["record_assignment_safe", "complete_assignment_safe", "record_round_safe"],
)
def test_each_safe_wrapper_calls_build_inside_its_try(wrapper: str) -> None:
    """`build()` MUST NOT be hoisted above the `try`.

    Assigning `build()` to a local above the try hoists the evaluation back OUT
    of the protected region while looking correct -- reintroducing the entire
    defect the thunk exists to prevent. This is a structural assertion because
    the behavioural one cannot distinguish the two shapes once the wrapper is
    written correctly.
    """
    tree = _module_tree()
    func = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == wrapper
    )

    body = [n for n in func.body if not (isinstance(n, ast.Expr)
                                         and isinstance(n.value, ast.Constant))]
    assert len(body) >= 1
    tries = [n for n in body if isinstance(n, ast.Try)]
    assert len(tries) == 1, f"{wrapper}: expected exactly one try block"
    the_try = tries[0]

    # `build()` is called INSIDE the try...
    assert _call_sites(the_try, "build") == 1
    # ...and NOWHERE in the function outside it.
    assert _call_sites(func, "build") == 1
    # ...and the try also encloses the awaited write that follows.
    assert any(isinstance(n, ast.Await) for n in ast.walk(the_try))


def test_the_public_surface_is_exactly_the_contract() -> None:
    """15.8-09 and 15.8-10 call these and edit NOTHING.

    If either wave-2 plan needs a new function, a new parameter, a changed
    signature, or a normalisation step of its own before calling, this plan is
    not done. `record_assignment` in particular has NO
    `claims_surviving_verification` parameter -- it is not known yet.
    """
    for name in (
        "record_assignment",
        "complete_assignment",
        "record_round",
        "record_assignment_safe",
        "complete_assignment_safe",
        "record_round_safe",
    ):
        assert callable(getattr(yr, name)), name

    params = inspect.signature(yr.record_assignment).parameters
    assert "claims_surviving_verification" not in params
    assert set(params) == {
        "run_id", "tenant_id", "provider", "group_id", "client_question",
        "parent_kind", "stakes", "fact_list_parsed", "retry_used", "claims_kept",
        "resolvable_sources", "cost_usd", "duration_s",
    }

    completer_params = inspect.signature(yr.complete_assignment).parameters
    assert set(completer_params) == {
        "run_id", "tenant_id", "provider", "group_id", "client_question",
        "claims_surviving_verification",
    }

    round_params = inspect.signature(yr.record_round).parameters
    assert set(round_params) == {
        "run_id", "tenant_id", "round_no", "candidates_in", "new_candidates",
        "keep_count", "weak_count", "kill_count", "new_entrants_top_n",
        "barred_drops", "round_cost_usd",
    }
