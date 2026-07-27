"""The run-event emitter: it cannot fail a run, and it cannot leak an identifier.

WHY THIS FILE EXISTS
--------------------
Two guarantees, one file, and the first one was very nearly shipped broken.

**D-06 -- AN EVENT WRITE MAY NEVER FAIL A RUN.** Not "usually does not"; may
never. The emit sites live inside the paid angle-dispatch loop, where a single
raised exception costs a deep-research run of tens of dollars. The obvious
implementation -- wrap `emit`'s BODY in try/except -- reads like it satisfies
this and DOES NOT, because A CALLER'S ARGUMENTS ARE EVALUATED BEFORE THE CALLEE
IS ENTERED. Written the natural way,

    emit(rid, ..., text=f"Angle {i} done -- {result['facts']} facts")

a degrading provider returning a short dict raises `KeyError` AT THE CALL SITE,
and no defensive code inside `emit` can catch it. `emit_safe`'s `build` thunk is
the fix, and the tests below drive a RAISING `build` and a MALFORMED `build`
through the real `emit_safe` rather than mocking `emit` -- a mocked `emit`
proves nothing about where the evaluation happens.

`test_hoisting_build_above_the_try_would_reintroduce_the_defect` is the
NEGATIVE CONTROL. It builds the one plausible wrong implementation inline and
shows it raises. Without it, the D-06 tests could pass against an
`emit_safe` that never had a defect to prevent, and this repository has a
documented history of gates that were green because they proved nothing.

**D-07 -- SCRUB BEFORE CLAMP, AND THE ORDER IS THE POINT.**
`test_an_email_straddling_the_clamp_boundary_is_fully_removed` places an
address so that a clamp-then-scrub order bisects it into `someone@ex` -- which
has no TLD, so `pii._EMAIL_RE` no longer matches it and a recognisable fragment
is persisted. That test asserts the counterfactual too: it runs the WRONG order
inline and shows the fragment surviving. A test that only asserted "the address
is gone" would pass on both orders and pin nothing.

THIS FILE OPENS NO DATABASE, MAKES ZERO LLM CALLS, USES NO MOCKING LIBRARY AND
NEEDS NO API KEY. The two operations that touch Postgres -- `_writer` and
`_read_max_seq` -- are module-level TEST SEAMS replaced by a hand-written
duck-typed recorder in the `test_feed_enrichment.py::_Recorder` style. There is
no second harness. Everything between an `emit` call and that recorder --
registry, tenant binding, vocabulary clamping, scrubbing, clamping,
whitelisting, sequencing, bounded buffering, batching and draining -- is
production code doing its real job.

Cloud Build invocation (no Postgres and no provider key needed):
    gcloud builds submit tribunal --config=tribunal/cloudbuild.test-engine.yaml \\
        --project="$GOOGLE_PROJECT"
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Optional

import pytest

from nestor_pulse_sdk.pipeline.tribunal.pii import REDACTED, scrub_pii
from nestor_pulse_sdk.runs import run_events as rex

_LOGGER = "nestor_pulse_sdk.runs.run_events"


# ---------------------------------------------------------------------------
# The recorder. Duck-typed to `run_events._insert_events(tenant_id, rows)` -- it
# stands in for the DATABASE WRITE only.
# ---------------------------------------------------------------------------
class _Recorder:
    def __init__(self, *, raises: bool = False) -> None:
        self.batches: list[dict[str, Any]] = []
        self.raises = raises

    @property
    def rows(self) -> list[dict[str, Any]]:
        return [row for batch in self.batches for row in batch["rows"]]

    @property
    def seqs(self) -> list[int]:
        return [int(row["seq"]) for row in self.rows]

    @property
    def texts(self) -> list[str]:
        return [str(row["text"]) for row in self.rows]

    async def __call__(self, tenant_id: Any, rows: list[dict[str, Any]]) -> None:
        # Record BEFORE raising: a writer that fails must still be observable,
        # and test (h) asserts the batch was attempted and then discarded.
        self.batches.append({"tenant_id": tenant_id, "rows": list(rows)})
        if self.raises:
            raise RuntimeError("the writer is down")


@pytest.fixture
async def rec(monkeypatch):
    """A recorder bound to both Postgres seams, with a clean registry."""
    recorder = _Recorder()
    monkeypatch.setattr(rex, "_writer", recorder)

    async def _zero(run_id: Any, tenant_id: Any) -> int:
        return 0

    # No test may reach a real database, not even for the seed read.
    monkeypatch.setattr(rex, "_read_max_seq", _zero)

    rex._RUNS.clear()
    rex._UNOPENED_LOGGED.clear()
    yield recorder
    # Close anything a test left open so no drain task outlives the loop.
    for key in list(rex._RUNS):
        await rex.close_run(key)
    rex._RUNS.clear()
    rex._UNOPENED_LOGGED.clear()


def _new_run() -> tuple[uuid.UUID, uuid.UUID]:
    return uuid.uuid4(), uuid.uuid4()


# ===========================================================================
# The contract itself.
# ===========================================================================


def test_the_vocabulary_is_the_twelve_line_kinds_of_the_design_of_record() -> None:
    """RUN_EVENT_KINDS == `type LineKind`, verbatim and in order.

    The frontend switches on these strings (`ResearchRunImproved.tsx:115-127`),
    so the tuple and that union are ONE contract in two languages. Order is
    asserted, not just membership: the design lists them in render-priority
    order and plans 15.3-02…05 index into this tuple.
    """
    assert rex.RUN_EVENT_KINDS == (
        "thinking",
        "tool",
        "search",
        "plan",
        "streams",
        "dispatch",
        "agent_run",
        "agent_done",
        "agent_retry",
        "agent_fail",
        "summary",
        "divider",
    )
    assert len(rex.RUN_EVENT_KINDS) == 12


def test_the_run_event_model_is_registered_in_base_metadata() -> None:
    """Task 1's own verification, run where it can actually be run.

    The dev machine has no Python, so `python -c "import ...db.models"` is not
    a check anyone can execute locally. Asserting it here means the ORM
    registration -- which is what makes alembic autogenerate aware of the table
    -- is covered by the engine gate instead of by a claim.
    """
    import nestor_pulse_sdk.db.models as models

    assert hasattr(models, "RunEvent")
    assert models.RunEvent.__tablename__ == "run_event"
    assert "run_event" in models.RunEvent.metadata.tables
    columns = set(models.RunEvent.metadata.tables["run_event"].columns.keys())
    assert columns == {
        "id", "tenant_id", "run_id", "seq", "ts", "stage", "kind", "text", "meta"
    }


def test_tunable_defaults_are_the_documented_ones() -> None:
    """The shipped defaults, asserted so a test-local override cannot hide a change."""
    assert rex.MAX_TEXT_CHARS == 400
    assert rex._BATCH == 200
    assert rex._MAX_QUEUE == 5000
    assert rex._FLUSH_S == 1.0


# ===========================================================================
# (a) / (a2) / (a3) -- D-06: nothing here can raise into a run.
# ===========================================================================


async def test_emit_on_an_unopened_run_returns_none_records_nothing_and_logs_once(
    rec, caplog
) -> None:
    """(a) An unopened run drops its events -- it is NEVER opened lazily.

    A lazy open would have no tenant_id, and a tenant-less write is exactly the
    cross-tenant isolation defect this project forbids. The log is once-per-run
    because the alternative is a thousand identical lines from a tight loop.
    """
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    run_id = uuid.uuid4()

    assert rex.emit(run_id, stage="deep_research", kind="tool", text="load") is None
    assert rex.emit(run_id, stage="deep_research", kind="tool", text="load") is None

    assert rec.rows == []
    warnings = [r for r in caplog.records if "was never opened" in r.getMessage()]
    assert len(warnings) == 1, "the unopened warning must be logged once per run"
    assert str(run_id) in warnings[0].getMessage()


async def test_emit_safe_swallows_a_raising_build_and_records_nothing(
    rec, caplog
) -> None:
    """(a2) THE D-06 PROOF, at the emitter.

    `build` raises while COMPOSING the text -- the failure mode a plain `emit`
    cannot catch because it happens before `emit` is entered. Driven through the
    real `emit_safe`; nothing is mocked. The run is OPEN, so "records nothing"
    is a real assertion rather than a vacuous one.
    """
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    run_id, tenant_id = _new_run()
    await rex.open_run(run_id, tenant_id)
    buffer = rex._RUNS[str(run_id)]

    result = {"cost_usd": None}  # a degrading provider's short dict
    assert (
        rex.emit_safe(
            run_id,
            stage="deep_research",
            kind="agent_done",
            # KeyError while composing -- evaluated INSIDE emit_safe's try.
            build=lambda: (f"Angle 1 done -- {result['facts']} facts", None),
        )
        is None
    )
    # ZeroDivisionError, the plan's own runtime probe.
    assert (
        rex.emit_safe(run_id, stage="x", kind="tool", build=lambda: 1 / 0) is None
    )
    # A TypeError raised while formatting a None cost -- the other real shape.
    assert (
        rex.emit_safe(
            run_id,
            stage="deep_research",
            kind="summary",
            build=lambda: (f"cost {result['cost_usd']:.2f}", None),
        )
        is None
    )

    await rex.close_run(run_id)

    assert rec.rows == []
    assert buffer.seq == 0, "a dropped build must not consume a sequence number"
    messages = [r.getMessage() for r in caplog.records]
    assert any("KeyError" in m for m in messages)
    assert any("ZeroDivisionError" in m for m in messages)
    assert any("TypeError" in m for m in messages)
    assert any("agent_done" in m for m in messages), "the log must name the kind"


async def test_emit_safe_drops_a_build_that_did_not_return_a_two_tuple(
    rec, caplog
) -> None:
    """(a3) A malformed `build` result is DROPPED, never unpacked blindly.

    Unpacking a non-pair would raise inside `emit_safe` -- the very thing it
    exists to prevent. A list is deliberately not accepted: the contract is a
    2-tuple of `(text, meta)`.
    """
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    run_id, tenant_id = _new_run()
    await rex.open_run(run_id, tenant_id)

    for bad in ("just a string", ("a", "b", "c"), ["text", None], None, 42, ()):
        assert (
            rex.emit_safe(run_id, stage="x", kind="tool", build=lambda b=bad: b)
            is None
        )

    await rex.close_run(run_id)

    assert rec.rows == []
    assert any("not a 2-tuple" in r.getMessage() for r in caplog.records)


def test_hoisting_build_above_the_try_would_reintroduce_the_defect() -> None:
    """THE NEGATIVE CONTROL. Without this, the D-06 tests could prove nothing.

    The one plausible wrong implementation of `emit_safe` is to assign `build()`
    to a local ABOVE the try -- it reads as correct, it type-checks, and it
    hoists the evaluation straight back out of the protected region. This test
    builds that variant inline, shows it RAISES on the exact input the real
    `emit_safe` swallows, and then shows the real one does not.

    If `run_events.emit_safe` is ever "tidied" that way, the second assertion
    below turns red.
    """

    def emit_safe_WRONG(run_id, *, stage, kind, build):
        built = build()  # HOISTED -- outside the try. This is the defect.
        try:
            text, meta = built
            rex.emit(run_id, stage=stage, kind=kind, text=text, meta=meta)
        except Exception:  # noqa: BLE001
            return None
        return None

    with pytest.raises(ZeroDivisionError):
        emit_safe_WRONG("no-such-run", stage="x", kind="tool", build=lambda: 1 / 0)

    # The shipped one, same input, no exception.
    assert (
        rex.emit_safe("no-such-run", stage="x", kind="tool", build=lambda: 1 / 0)
        is None
    )


async def test_emit_never_raises_on_hostile_arguments(rec, caplog) -> None:
    """(b) Non-str text, non-dict meta and an out-of-vocabulary kind.

    An out-of-vocabulary kind renders as a BLANK LINE in the feed, which is
    worse than an absent one -- so that row is dropped rather than passed
    through. The other two degrade to a usable row.
    """
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    run_id, tenant_id = _new_run()
    await rex.open_run(run_id, tenant_id)

    class _Hostile:
        def __str__(self) -> str:
            raise RuntimeError("this object refuses to be a string")

    assert rex.emit(run_id, stage="x", kind="tool", text=12345) is None
    assert rex.emit(run_id, stage="x", kind="tool", text=None) is None
    assert rex.emit(run_id, stage="x", kind="tool", text=_Hostile()) is None
    assert rex.emit(run_id, stage="x", kind="tool", text="ok", meta="not a dict") is None
    assert rex.emit(run_id, stage=object(), kind="tool", text="coerced stage") is None
    # Dropped: not a member of RUN_EVENT_KINDS.
    assert rex.emit(run_id, stage="x", kind="explosion", text="never rendered") is None

    await rex.close_run(run_id)

    assert "never rendered" not in rec.texts
    assert "12345" in rec.texts
    assert rec.rows, "the survivable rows must still have been written"
    for row in rec.rows:
        assert isinstance(row["text"], str)
        assert row["kind"] in rex.RUN_EVENT_KINDS
        assert isinstance(row["stage"], str)
    assert any("is not one of" in r.getMessage() for r in caplog.records)


async def test_an_unknown_meta_key_is_dropped_with_a_warning(rec, caplog) -> None:
    """The JSONB column is not a free-for-all (T-15.3-05).

    `StageFeed._normalise_row` established this: an unfiltered dict quietly
    grows the column with typo'd keys the UI never reads.
    """
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    run_id, tenant_id = _new_run()
    await rex.open_run(run_id, tenant_id)

    rex.emit(
        run_id,
        stage="deep_research",
        kind="agent_done",
        text="done",
        meta={"cost": 1.25, "angle": 3, "cosr": "typo", "whatever": "no"},
    )
    await rex.close_run(run_id)

    assert len(rec.rows) == 1
    assert rec.rows[0]["meta"] == {"cost": 1.25, "angle": 3}
    messages = [r.getMessage() for r in caplog.records]
    assert any("'cosr'" in m for m in messages)
    assert any("'whatever'" in m for m in messages)


# ===========================================================================
# (c) / (d) -- D-07: redaction, and the ORDER of redaction.
# ===========================================================================


async def test_an_email_and_a_dialling_shaped_number_are_redacted(rec) -> None:
    """(c) Both direct identifiers `pii.scrub_pii` covers, in text AND in meta.

    Meta carries provider names, model ids and free-form sub-lines, so it gets
    the same scrub as `text` (T-15.3-01). A scrub applied to only one of the two
    columns is a scrub with a hole in it.
    """
    run_id, tenant_id = _new_run()
    await rex.open_run(run_id, tenant_id)

    rex.emit(
        run_id,
        stage="deep_research",
        kind="search",
        text="Reach someone@example.com or +32 470 12 34 56 for the filing",
        meta={"sub": "cc: another.person@example.org", "provider": "serpapi"},
    )
    await rex.close_run(run_id)

    assert len(rec.rows) == 1
    row = rec.rows[0]
    assert row["text"].count(REDACTED) == 2
    assert "someone@example.com" not in row["text"]
    assert "+32 470 12 34 56" not in row["text"]
    assert "@" not in row["text"]
    # Meta too.
    assert "another.person@example.org" not in row["meta"]["sub"]
    assert REDACTED in row["meta"]["sub"]
    assert row["meta"]["provider"] == "serpapi"


async def test_an_email_straddling_the_clamp_boundary_is_fully_removed(rec) -> None:
    """(d) THE ORDER IS PINNED HERE, not merely the fact that scrubbing happens.

    The address starts 10 characters before `MAX_TEXT_CHARS`, so a
    clamp-then-scrub order cuts it into `someone@ex` -- no dot, no TLD, and
    therefore no `pii._EMAIL_RE` match, leaving a recognisable fragment in a
    persisted row. The counterfactual is asserted below FIRST, so this test
    fails if the trap it describes ever stops being a trap; then the real
    emitter is shown not to fall into it.
    """
    run_id, tenant_id = _new_run()
    await rex.open_run(run_id, tenant_id)

    # 390 characters ending in a space, so the address is preceded by a word
    # boundary (pii._EMAIL_RE has a look-behind and will not start mid-token).
    filler = ("stakeholder note " * 30)[:389] + " "
    assert len(filler) == 390
    raw = filler + "someone@example.com"
    assert len(raw) == 409

    # THE COUNTERFACTUAL: clamp first, then scrub. The fragment survives.
    naive_clamp_first, _ = scrub_pii(raw[: rex.MAX_TEXT_CHARS])
    assert "someone@ex" in naive_clamp_first, (
        "the wrong order is supposed to leak a fragment -- if this ever stops "
        "being true, the assertion below no longer pins anything"
    )

    rex.emit(run_id, stage="intake", kind="thinking", text=raw)
    await rex.close_run(run_id)

    assert len(rec.rows) == 1
    text = rec.rows[0]["text"]
    assert REDACTED in text
    assert "someone" not in text
    assert "someone@ex" not in text
    assert "@" not in text
    assert len(text) <= rex.MAX_TEXT_CHARS + 1


async def test_long_text_is_clamped_and_visibly_marked_as_cut(rec) -> None:
    """A cut line is marked, not silently shortened (the stage_feed convention)."""
    run_id, tenant_id = _new_run()
    await rex.open_run(run_id, tenant_id)

    rex.emit(run_id, stage="x", kind="thinking", text="a" * 5000)
    await rex.close_run(run_id)

    text = rec.rows[0]["text"]
    assert len(text) == rex.MAX_TEXT_CHARS + 1
    assert text.endswith("…")


# ===========================================================================
# (e) / (f) -- ordering and resume.
# ===========================================================================


async def test_seq_is_strictly_increasing_and_the_batch_preserves_emit_order(
    rec,
) -> None:
    """(e) Ordering is the whole reason this table exists (D-04).

    Two concurrent producers interleave through the event loop; `seq` is
    assigned at emit time, so the persisted order is the order things actually
    happened rather than the order a scheduler got round to them.
    """
    run_id, tenant_id = _new_run()
    await rex.open_run(run_id, tenant_id)

    async def producer(label: str, count: int) -> None:
        for i in range(count):
            rex.emit(run_id, stage="deep_research", kind="agent_run",
                     text=f"{label}-{i}")
            await asyncio.sleep(0)  # yield, so the two producers interleave

    await asyncio.gather(producer("a", 12), producer("b", 12))
    await rex.close_run(run_id)

    seqs = rec.seqs
    assert len(seqs) == 24
    assert seqs == list(range(1, 25)), "seq must be dense and monotonic from 1"
    assert seqs == sorted(seqs)
    # Interleaving actually happened -- otherwise this proves nothing about order.
    labels = [t.split("-")[0] for t in rec.texts]
    assert labels != sorted(labels), "the two producers did not interleave"


async def test_a_resumed_run_continues_its_numbering_from_max_seq(
    rec, monkeypatch
) -> None:
    """(f) open_run seeds from COALESCE(MAX(seq),0), so a resume does not collide."""
    run_id, tenant_id = _new_run()

    async def _forty_one(rid: Any, tid: Any) -> int:
        return 41

    monkeypatch.setattr(rex, "_read_max_seq", _forty_one)
    await rex.open_run(run_id, tenant_id)

    rex.emit(run_id, stage="x", kind="divider", text="resumed")
    rex.emit(run_id, stage="x", kind="divider", text="and again")
    await rex.close_run(run_id)

    assert rec.seqs == [42, 43]


async def test_a_failing_max_seq_read_degrades_to_zero_and_still_emits(
    rec, monkeypatch, caplog
) -> None:
    """A dead seed read costs numbering continuity, never the feed or the run.

    Degraded observability is acceptable; a run that will not start because its
    event table was unreachable is not.
    """
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    run_id, tenant_id = _new_run()

    async def _boom(rid: Any, tid: Any) -> int:
        raise RuntimeError("no database here")

    monkeypatch.setattr(rex, "_read_max_seq", _boom)
    await rex.open_run(run_id, tenant_id)

    rex.emit(run_id, stage="x", kind="divider", text="still flowing")
    await rex.close_run(run_id)

    assert rec.seqs == [1]
    assert any("MAX(seq) read failed" in r.getMessage() for r in caplog.records)


# ===========================================================================
# (g) / (h) -- bounded volume and a broken writer.
# ===========================================================================


async def test_exceeding_the_queue_ceiling_drops_rows_counts_them_and_never_raises(
    rec, monkeypatch, caplog
) -> None:
    """(g) A 24-angle run emitting thousands of events is expected, not anomalous.

    At the ceiling the NEW row is refused rather than letting the deque evict
    the OLDEST: the early events explain how the run got where it is, and a feed
    that silently rotates its own history is the failure mode this table exists
    to end (T-15.3-03).
    """
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    monkeypatch.setattr(rex, "_MAX_QUEUE", 5)

    run_id, tenant_id = _new_run()
    await rex.open_run(run_id, tenant_id)
    buffer = rex._RUNS[str(run_id)]
    assert buffer.queue.maxlen == 5

    # Synchronous burst: no await, so the drain cannot run and relieve the queue.
    for i in range(12):
        assert rex.emit(run_id, stage="x", kind="tool", text=f"event {i}") is None

    assert buffer.dropped == 7
    assert len(buffer.queue) == 5

    await rex.close_run(run_id)

    assert len(rec.rows) == 5
    assert rec.texts == [f"event {i}" for i in range(5)], (
        "the OLDEST events must survive; the newest are the ones refused"
    )
    assert any("queue ceiling" in r.getMessage() for r in caplog.records)
    assert any("INCOMPLETE" in r.getMessage() for r in caplog.records)


async def test_a_writer_that_raises_leaves_emit_and_close_run_returning_normally(
    monkeypatch, caplog
) -> None:
    """(h) A failing batch is DISCARDED, never retried.

    Retrying a failing write forever is how an observability path starts
    consuming the run it observes.
    """
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    broken = _Recorder(raises=True)
    monkeypatch.setattr(rex, "_writer", broken)

    async def _zero(rid: Any, tid: Any) -> int:
        return 0

    monkeypatch.setattr(rex, "_read_max_seq", _zero)
    rex._RUNS.clear()

    run_id, tenant_id = _new_run()
    await rex.open_run(run_id, tenant_id)

    for i in range(3):
        assert rex.emit(run_id, stage="x", kind="tool", text=f"e{i}") is None

    # Must not raise, must not hang retrying.
    await rex.close_run(run_id)

    assert len(broken.batches) == 1, "the batch was attempted exactly once"
    assert any("DISCARDED" in r.getMessage() for r in caplog.records)
    assert str(run_id) not in rex._RUNS


async def test_close_run_is_idempotent(rec) -> None:
    """The pipeline's `finally` and its `done` write can both call it."""
    run_id, tenant_id = _new_run()
    await rex.open_run(run_id, tenant_id)
    rex.emit(run_id, stage="x", kind="divider", text="one")

    await rex.close_run(run_id)
    await rex.close_run(run_id)
    await rex.close_run(uuid.uuid4())  # never opened at all

    assert len(rec.rows) == 1
    # And emitting after close drops rather than resurrecting the run.
    assert rex.emit(run_id, stage="x", kind="divider", text="late") is None
    assert len(rec.rows) == 1


async def test_open_run_never_raises_and_a_second_open_is_a_no_op(
    rec, caplog
) -> None:
    """A double open must not orphan the first buffer's undrained events."""
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    run_id, tenant_id = _new_run()

    await rex.open_run(run_id, tenant_id)
    rex.emit(run_id, stage="x", kind="divider", text="first")
    await rex.open_run(run_id, tenant_id)
    rex.emit(run_id, stage="x", kind="divider", text="second")
    await rex.close_run(run_id)

    assert rec.texts == ["first", "second"]
    assert rec.seqs == [1, 2]
    assert any("already open" in r.getMessage() for r in caplog.records)
