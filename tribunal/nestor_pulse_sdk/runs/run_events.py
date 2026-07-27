"""
Run events -- the best-effort, in-process emitter behind the run page's feed.

THIS MODULE NEVER RAISES INTO A CALLER. Not from `emit`, not from `emit_safe`,
not from `open_run`, not from `close_run`, and not from the drain task. A run
that loses events is DEGRADED; a run that dies because of an event write is a
REGRESSION (D-06). Every entry point below swallows its own failures and logs
them at WARNING, inheriting the contract `runs/stages.py::set_stage` already
states -- and it is never SILENTLY green either: every dropped row, clamped
value, unknown meta key, refused kind and discarded batch is logged with run /
stage / kind identity.

WHY THESE ROWS EXIST AT ALL (D-04). `set_stage` writes
`stage_detail = COALESCE(stage_detail,'{}') || CAST(:entry AS JSONB)`, and `||`
is a MERGE KEYED BY STAGE -- a stage that reports twice OVERWRITES ITSELF.
There is no ordering and no history, so the intermediate states a feed is made
of are gone before anything reads them. These rows are append-only with a
monotonic `seq`, which is what makes closing and reopening the run page show
real history instead of a snapshot. `stage_detail` is not replaced; these rows
are written ALONGSIDE it.

WHY `emit` IS SYNCHRONOUS. Its call sites are inside the paid angle-dispatch
loop and inside per-poll provider code. A synchronous call cannot be forgotten
with a missing `await`, cannot yield the event loop at a point the caller did
not choose, and cannot leave a pending coroutine behind on a failure path. It
touches NO database: it appends to a bounded in-memory deque and returns. The
DB write happens on a separate drain task that the caller never waits for.

WHY `tenant_id` IS BOUND ONCE, AT `open_run`. The six pipeline modules that
emit do not carry a tenant id and must not have to. Binding it once also means
the tenant GUC is set in exactly ONE place here (`_insert_events`), the same
single-place discipline `StageFeed` keeps by delegating to `set_stage`. A run
that was never opened has NO tenant id, so `emit` DROPS its events rather than
opening lazily -- a tenant-less write is precisely the isolation defect this
project forbids.

TEST SEAMS, NAMED AS SUCH. `_writer` and `_read_max_seq` are module-level names
so `tests/test_run_events.py` can monkeypatch the two operations that touch
Postgres and drive everything else -- registry, sequencing, scrubbing, clamping,
whitelisting, batching, draining -- as real production code. They are TEST
SEAMS, not production seams: no pipeline caller passes or replaces them, exactly
as `StageFeed(writer=...)` documents for itself.

Cloud Build invocation for this module's suite (no Postgres, no provider key):
    gcloud builds submit tribunal --config=tribunal/cloudbuild.test-engine.yaml \
        --project="$GOOGLE_PROJECT"
"""
from __future__ import annotations

import asyncio
import collections
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from nestor_pulse_sdk.pipeline.tribunal.pii import scrub_pii

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# THE VOCABULARY. The twelve line kinds of the design of record
# (`docs/design/prototypes/ResearchRunImproved.tsx`, `type LineKind`), verbatim
# and IN THAT ORDER. The frontend switches on these strings, so this tuple and
# that union are one contract in two languages: adding a kind here without
# adding it there renders a blank line, which is worse than an absent one.
# ---------------------------------------------------------------------------
RUN_EVENT_KINDS: tuple[str, ...] = (
    "thinking",     # brain -- agent reasoning aloud
    "tool",         # wrench -- skill / tool loaded
    "search",       # magnifier -- web fetch / search
    "plan",         # branch -- routing / planning
    "streams",      # layers -- stream config
    "dispatch",     # bold zap line -- "Dispatching N agents"
    "agent_run",    # indented spinner -- live agent
    "agent_done",   # indented check -- agent complete
    "agent_retry",  # indented retry -- agent retrying
    "agent_fail",   # indented x -- agent failed
    "summary",      # "Worked for X" stats line
    "divider",      # subtle phase label
)

# ---------------------------------------------------------------------------
# Tunables. Same `os.environ.get(name, default)` idiom as stage_feed.py:60-62,
# so a retune needs no code change.
#   _FLUSH_S        seconds between drain passes.
#   _BATCH          rows written per multi-row INSERT.
#   _MAX_QUEUE      rows buffered per run before new events are refused.
#   MAX_TEXT_CHARS  characters of `text` persisted per row.
# ---------------------------------------------------------------------------
_FLUSH_S = float(os.environ.get("NESTOR_RUN_EVENT_FLUSH_S", "1.0"))
_BATCH = int(os.environ.get("NESTOR_RUN_EVENT_BATCH", "200"))
_MAX_QUEUE = int(os.environ.get("NESTOR_RUN_EVENT_QUEUE_MAX", "5000"))
MAX_TEXT_CHARS = int(os.environ.get("NESTOR_RUN_EVENT_TEXT_MAX", "400"))

#: Hard bound on the registry, mirroring `pipeline.py::_STAGE_LOG_MAX_RUNS`, so
#: a run that is never closed cannot grow it without limit.
_MAX_RUNS = 64

#: Characters of `stage` kept. Every real ENGINE_STAGES key is under 20; this is
#: only here so a mistyped caller cannot put an unbounded string in the column
#: that the feed groups by.
_MAX_STAGE_CHARS = 64

#: Keys a caller may set in `meta`. Anything else is dropped with a WARNING,
#: exactly as `StageFeed._normalise_row` does for row fields -- the column is
#: JSONB, so an unfiltered dict would quietly grow it with typo'd keys the UI
#: never reads (T-15.3-05).
_META_FIELDS = (
    "sub", "is_live", "worked", "actions", "items", "cost", "audit_id",
    "provider", "model", "angle", "attempt", "max", "wait_s",
)

#: How often a repeated queue-overflow drop is re-logged, after the first one.
_DROP_LOG_EVERY = 500


class _RunBuffer:
    """One open run's event buffer. Created by `open_run`, popped by `close_run`."""

    def __init__(self, run_id: Any, tenant_id: Any, start_seq: int) -> None:
        self.run_id = run_id
        self.tenant_id = tenant_id
        #: Last issued seq. The first event of the run is `start_seq + 1`.
        self.seq = int(start_seq)
        #: `maxlen` is belt AND braces: `emit` refuses at capacity (below), and
        #: the deque itself can never exceed it even if that check is ever wrong.
        self.queue: collections.deque = collections.deque(maxlen=int(_MAX_QUEUE))
        #: Serialises the periodic drain against `close_run`'s final drain, so
        #: the same rows cannot be taken twice. `emit` needs no lock: it is
        #: synchronous and never awaits, so it cannot interleave with a drain
        #: that is mid-await.
        self.lock = asyncio.Lock()
        self.task: Optional[asyncio.Task] = None
        #: Events refused at the queue ceiling. Counted, never ignored.
        self.dropped = 0
        self.dropped_logged_at = 0


#: run-id (str) -> that run's buffer.
_RUNS: dict[str, _RunBuffer] = {}

#: run-ids already warned about for emitting while unopened, so a tight loop
#: against a closed run logs once rather than a thousand times.
_UNOPENED_LOGGED: set[str] = set()


# ===========================================================================
# The two operations that touch Postgres. Both are TEST SEAMS (see the module
# docstring): they are looked up as module globals at call time so the suite
# can replace them, and no production caller passes or replaces either.
# ===========================================================================


async def _read_max_seq(run_id: Any, tenant_id: Any) -> int:
    """`COALESCE(MAX(seq), 0)` for this run, under the tenant GUC.

    Read ONCE, at `open_run`, so a RESUMED run continues its own numbering
    instead of restarting at 1 and colliding with the history it already wrote.
    """
    from sqlalchemy import text as sql_text

    from nestor_pulse_sdk.db.base import get_sessionmaker
    from nestor_pulse_sdk.db.rls import set_tenant_context

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        async with session.begin():
            await set_tenant_context(session, tenant_id)
            row = (
                await session.execute(
                    sql_text(
                        "SELECT COALESCE(MAX(seq), 0) FROM run_event "
                        "WHERE run_id = :id"
                    ),
                    {"id": str(run_id)},
                )
            ).first()
    return int(row[0]) if row and row[0] is not None else 0


async def _insert_events(tenant_id: Any, rows: list[dict[str, Any]]) -> None:
    """Write one batch as a SINGLE multi-row INSERT under the tenant GUC.

    Own session + `session.begin()` + `set_tenant_context`, the same pattern
    `set_stage` uses, so tenant binding lives in exactly one place in this
    module.
    """
    import json

    from sqlalchemy import text as sql_text

    from nestor_pulse_sdk.db.base import get_sessionmaker
    from nestor_pulse_sdk.db.rls import set_tenant_context

    params = [
        {
            "id": str(row["id"]),
            "tenant_id": str(tenant_id),
            "run_id": str(row["run_id"]),
            "seq": int(row["seq"]),
            "ts": row["ts"],
            "stage": row["stage"],
            "kind": row["kind"],
            "text": row["text"],
            "meta": json.dumps(row["meta"]) if row["meta"] is not None else None,
        }
        for row in rows
    ]

    stmt = sql_text(
        "INSERT INTO run_event "
        "(id, tenant_id, run_id, seq, ts, stage, kind, text, meta) VALUES "
        "(:id, :tenant_id, :run_id, :seq, :ts, :stage, :kind, :text, "
        "CAST(:meta AS JSONB))"
    )

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        async with session.begin():
            await set_tenant_context(session, tenant_id)
            await session.execute(stmt, params)


#: TEST SEAM. Rebound by tests/test_run_events.py to a recorder. Never rebound
#: in production.
_writer: Callable[..., Any] = _insert_events


# ===========================================================================
# Public surface. Plans 15.3-03/04/05 call `emit_safe` and NOTHING else here.
# ===========================================================================


async def open_run(run_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
    """Bind a run's tenant, seed its sequence, and start its drain task.

    Best-effort like everything else here. On failure the run is left UNOPENED
    and every later `emit` for it is dropped with one WARNING: degrading to "no
    events" is acceptable, raising into the pipeline is not (D-06).
    """
    key = str(run_id)
    try:
        if key in _RUNS:
            log.warning(
                "run_events.open_run: run %s is already open -- the existing "
                "buffer is kept and this call is a no-op (a second open would "
                "orphan the first buffer's undrained events)",
                run_id,
            )
            return

        if len(_RUNS) >= _MAX_RUNS:
            # Insertion-ordered: evict the oldest rather than grow forever. Say
            # it out loud -- an eviction means some run was never closed.
            oldest = next(iter(_RUNS))
            log.warning(
                "run_events: registry cap %d reached -- evicting run %s, which "
                "was never closed. Its undrained events are being flushed now; "
                "any emitted after this point are dropped.",
                _MAX_RUNS, oldest,
            )
            await close_run(oldest)

        try:
            start_seq = int(await _read_max_seq(run_id, tenant_id))
        except Exception as exc:  # noqa: BLE001 -- see below
            # DEGRADED, NOT DEAD. Without the MAX read a resumed run restarts
            # its numbering and may repeat seq values it already wrote, so the
            # feed can show two lines at the same position. That is a cosmetic
            # loss; refusing to open the run would cost the whole feed, and
            # raising would cost the run.
            log.warning(
                "run_events.open_run: MAX(seq) read failed (run=%s): %r -- "
                "numbering restarts at 1, so a RESUMED run may repeat seq "
                "values it already persisted. Events still flow.",
                run_id, exc,
            )
            start_seq = 0

        buffer = _RunBuffer(run_id=run_id, tenant_id=tenant_id, start_seq=start_seq)
        _RUNS[key] = buffer
        buffer.task = asyncio.create_task(_drain_loop(key))
        _UNOPENED_LOGGED.discard(key)
    except Exception as exc:  # noqa: BLE001 -- an open must never fail a run
        _RUNS.pop(key, None)
        log.warning(
            "run_events.open_run failed (run=%s): %r -- this run emits NO "
            "events; the pipeline is unaffected",
            run_id, exc,
        )


def emit(
    run_id: Any,
    *,
    stage: str,
    kind: str,
    text: str,
    meta: Optional[dict] = None,
) -> None:
    """Queue one event. SYNCHRONOUS, no `await`, no database, never raises.

    Prefer `emit_safe` at every pipeline call site. This function is public
    only because `emit_safe` delegates to it and the unit tests drive it
    directly -- wrapping THIS body does not protect the ARGUMENTS a caller
    builds, which is the whole point of `emit_safe`.
    """
    try:
        key = str(run_id)

        # (1) The buffer, which is also the tenant binding. NEVER opened lazily:
        #     a lazy open has no tenant_id, and a tenant-less write is exactly
        #     the isolation defect this project forbids.
        buffer = _RUNS.get(key)
        if buffer is None:
            if key not in _UNOPENED_LOGGED:
                if len(_UNOPENED_LOGGED) >= _MAX_RUNS * 4:
                    _UNOPENED_LOGGED.clear()
                _UNOPENED_LOGGED.add(key)
                log.warning(
                    "run_events.emit: run %s was never opened (or is already "
                    "closed) -- its events are DROPPED, logged once. First "
                    "dropped event was stage=%r kind=%r.",
                    run_id, stage, kind,
                )
            return None

        # (2) Vocabulary. An out-of-vocabulary kind renders as a blank line in
        #     the feed, which is worse than an absent one -- so drop the row.
        if kind not in RUN_EVENT_KINDS:
            log.warning(
                "run_events.emit: kind %r is not one of %s -- row DROPPED "
                "(run=%s stage=%r)",
                kind, RUN_EVENT_KINDS, run_id, stage,
            )
            return None

        # (3) Coerce. Callers pass model-influenced values; none of them may
        #     raise here.
        stage_text = (_coerce_str(stage) or "unknown")[:_MAX_STAGE_CHARS]
        raw_text = _coerce_str(text) or ""

        # (4) SCRUB FIRST, CLAMP SECOND. THE ORDER IS LOAD-BEARING (D-07).
        #     Clamping first can cut an email in half and leave a fragment the
        #     scrubber no longer matches -- `someone@example.com` truncated to
        #     `someone@ex` has no TLD, so _EMAIL_RE misses it and a recognisable
        #     identifier is persisted. Do not reorder these two lines.
        scrubbed, _removed = scrub_pii(raw_text)
        event_text = _clamp(scrubbed)

        # (5) Whitelist + scrub meta.
        event_meta = _normalise_meta(meta, run_id=run_id, stage=stage_text, kind=kind)

        # (6) Sequence. Monotonic per run; assigned in process.
        buffer.seq += 1
        seq = buffer.seq

        # (7) Enqueue, bounded.
        maxlen = buffer.queue.maxlen or int(_MAX_QUEUE)
        if len(buffer.queue) >= maxlen:
            # Refuse the NEW row rather than let the deque evict the OLDEST: the
            # early events are the ones that explain how the run got here, and a
            # feed that silently rotates its own history is the failure mode this
            # table exists to end. Counted and stated (T-15.3-03).
            buffer.dropped += 1
            if (
                buffer.dropped == 1
                or buffer.dropped - buffer.dropped_logged_at >= _DROP_LOG_EVERY
            ):
                buffer.dropped_logged_at = buffer.dropped
                log.warning(
                    "run_events: queue ceiling %d reached (run=%s stage=%s) -- "
                    "%d event(s) dropped so far. The drain is behind; the feed "
                    "for this run is INCOMPLETE.",
                    maxlen, run_id, stage_text, buffer.dropped,
                )
            return None

        buffer.queue.append(
            {
                "id": uuid.uuid4(),
                "run_id": buffer.run_id,
                "seq": seq,
                "ts": datetime.now(timezone.utc),
                "stage": stage_text,
                "kind": kind,
                "text": event_text,
                "meta": event_meta,
            }
        )
    except Exception as exc:  # noqa: BLE001 -- an event write may never fail a run
        log.warning(
            "run_events.emit failed (run=%s stage=%r kind=%r): %r -- event "
            "dropped, run unaffected",
            run_id, stage, kind, exc,
        )
    return None


def emit_safe(
    run_id: Any,
    *,
    stage: str,
    kind: str,
    build: "Callable[[], tuple[str, Optional[dict]]]",
) -> None:
    """Queue one event whose text and meta are built INSIDE this function's try.

    THIS IS THE ONLY EMIT ENTRY POINT A PIPELINE MODULE MAY USE, and the reason
    it exists is a control-flow fact that is easy to talk past:

        A CALLER'S ARGUMENTS ARE EVALUATED BEFORE THE CALLEE IS ENTERED.

    So wrapping `emit`'s BODY in try/except protects nothing against the
    expression that produced its arguments. Written the obvious way,

        emit(rid, stage="deep_research", kind="agent_done",
             text=f"Angle {i+1} done -- {result['facts']} facts")

    a degrading provider that returns a short dict makes `result['facts']` raise
    `KeyError` AT THE CALL SITE, inside the paid angle-dispatch loop, and no
    amount of defensive code inside `emit` can catch it. The text of an event is
    built from exactly the provider-shaped dicts most likely to arrive
    malformed, so this is not a hypothetical.

    Passing a ZERO-ARGUMENT CALLABLE moves that construction inside the try
    below, which is what makes D-06 true AT THE SITES rather than only inside
    the emitter::

        run_events.emit_safe(run_id, stage="deep_research", kind="agent_done",
                             build=lambda: (f"Angle {i+1} done -- "
                                            f"{result['facts']} facts",
                                            {"cost": result.get("cost_usd")}))

    ONE `try/except` wraps BOTH the `build()` call and the `emit(...)` that
    follows it. DO NOT "tidy" this by assigning `build()` to a local above the
    try -- that hoists the evaluation back out of the protected region and
    reintroduces the entire defect while looking correct.

    That the rule is structural rather than a discipline is deliberate: about
    thirty emit sites land across five modules, and requiring thirty
    hand-written try/excepts is the "thirty edits, each of which is a chance to
    miss one" anti-pattern this codebase already names in `pipeline.py`'s
    `set_stage` shim. One helper is checkable with one grep; thirty wrappers are
    checkable only by a reviewer who does not get tired.
    """
    try:
        built = build()
        if not isinstance(built, tuple) or len(built) != 2:
            # Dropped rather than unpacked blindly: unpacking a non-pair would
            # raise here, which is the very thing this function exists to stop.
            log.warning(
                "run_events.emit_safe: build() returned %s, not a 2-tuple of "
                "(text, meta) -- event DROPPED (run=%s stage=%r kind=%r)",
                type(built).__name__, run_id, stage, kind,
            )
            return None
        built_text, built_meta = built
        emit(run_id, stage=stage, kind=kind, text=built_text, meta=built_meta)
    except Exception as exc:  # noqa: BLE001 -- D-06 at the CALL SITE
        log.warning(
            "run_events.emit_safe: building or queueing an event raised %s "
            "(run=%s stage=%r kind=%r) -- event DROPPED, run unaffected",
            type(exc).__name__, run_id, stage, kind,
        )
    return None


async def close_run(run_id: uuid.UUID) -> None:
    """Stop the drain, write what is left, and forget the run. Idempotent.

    The registry entry is POPPED FIRST, so the pipeline's `finally` and its
    `done` write can both call this and only the first one does any work.
    """
    key = str(run_id)
    try:
        buffer = _RUNS.pop(key, None)
        if buffer is None:
            return

        task, buffer.task = buffer.task, None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "run_events: drain task for run %s ended badly: %r",
                    run_id, exc,
                )

        # Final drain, BOUNDED. An unbounded loop here would let a writer that
        # keeps failing hold the pipeline's shutdown path open.
        max_batches = (int(buffer.queue.maxlen or _MAX_QUEUE) // max(1, _BATCH)) + 2
        for _ in range(max_batches):
            if not await _flush_once(buffer):
                break

        if buffer.queue:
            log.warning(
                "run_events.close_run: run %s still had %d buffered event(s) "
                "after its final drain -- they are DISCARDED",
                run_id, len(buffer.queue),
            )
        if buffer.dropped:
            log.warning(
                "run_events.close_run: run %s dropped %d event(s) at the queue "
                "ceiling over its lifetime -- its feed is INCOMPLETE",
                run_id, buffer.dropped,
            )
    except Exception as exc:  # noqa: BLE001 -- a close must never fail a run
        log.warning("run_events.close_run failed (run=%s): %r", run_id, exc)


# ===========================================================================
# Internals.
# ===========================================================================


async def _drain_loop(key: str) -> None:
    """Flush this run's queue every `_FLUSH_S` until the run is closed."""
    while True:
        try:
            await asyncio.sleep(_FLUSH_S)
            buffer = _RUNS.get(key)
            if buffer is None:
                return
            await _flush_once(buffer)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("run_events: drain loop failed (run=%s): %r", key, exc)


async def _flush_once(buffer: _RunBuffer) -> bool:
    """Write up to `_BATCH` queued rows. Returns True if any were taken.

    A FAILING BATCH IS DISCARDED, NOT RETRIED. Retrying a failing write forever
    is how an observability path starts consuming the run it observes -- and the
    rows it would retry are already superseded by newer ones in the queue.
    """
    rows: list[dict[str, Any]] = []
    async with buffer.lock:
        while buffer.queue and len(rows) < _BATCH:
            rows.append(buffer.queue.popleft())
    if not rows:
        return False
    try:
        await _writer(buffer.tenant_id, rows)
    except Exception as exc:  # noqa: BLE001 -- best-effort, never retried
        log.warning(
            "run_events: batch of %d event(s) DISCARDED for run=%s (seq %s-%s): "
            "%r -- not retried",
            len(rows), buffer.run_id, rows[0]["seq"], rows[-1]["seq"], exc,
        )
    return True


def _clamp(text: str) -> str:
    """Bound `text` to MAX_TEXT_CHARS, marking a cut with a single ellipsis.

    The result is MAX_TEXT_CHARS + 1 characters when it was cut, so a truncated
    line is VISIBLY cut rather than silently shortened -- the same convention
    `stage_feed.truncate_task_prompt` uses.
    """
    cap = int(MAX_TEXT_CHARS)
    if cap <= 0 or len(text) <= cap:
        return text
    return text[:cap] + "…"


def _normalise_meta(
    meta: Any, *, run_id: Any, stage: str, kind: str
) -> Optional[dict[str, Any]]:
    """Whitelist `meta`'s keys and scrub its string values. Never raises."""
    if meta is None:
        return None
    if not isinstance(meta, dict):
        log.warning(
            "run_events: meta %s is not a dict -- dropped (run=%s stage=%s "
            "kind=%s)",
            type(meta).__name__, run_id, stage, kind,
        )
        return None

    out: dict[str, Any] = {}
    for key, value in meta.items():
        if key not in _META_FIELDS:
            log.warning(
                "run_events: unknown meta key %r dropped (run=%s stage=%s "
                "kind=%s)",
                key, run_id, stage, kind,
            )
            continue
        if value is None:
            # Omitted rather than written as a JSON null -- keeps the column small.
            continue
        if isinstance(value, bool) or isinstance(value, (int, float)):
            out[key] = value
            continue
        text = _coerce_str(value)
        if text is None:
            continue
        # Meta carries provider names, model ids and free-form sub-lines, so it
        # gets the SAME scrub and the SAME bound as `text` (T-15.3-01).
        scrubbed, _removed = scrub_pii(text)
        out[key] = _clamp(scrubbed)
    return out or None


def _coerce_str(value: Any) -> Optional[str]:
    """Defensive stringify. Returns None rather than raising."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    try:
        return str(value)
    except Exception:  # noqa: BLE001 -- a hostile __str__ costs the text, not the run
        return None
