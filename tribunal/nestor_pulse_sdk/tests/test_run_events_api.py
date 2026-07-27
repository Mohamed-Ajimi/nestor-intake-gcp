"""
Run-event READ surface: isolation + paging proofs (Phase 15.3, plan 15.3-02).

Plan 15.3-01 made a run's activity persist. This file pins the endpoint that makes
it READABLE -- `GET /api/runs/{run_id}/events` -- plus the additive `event_seq`
cursor on `GET /api/runs/{run_id}/metrics`.

WHAT IS BEING DEFENDED, in the order it matters:

  1. TENANT ISOLATION. This is a NEW read surface over run data. A cross-tenant
     caller must get EXACTLY 404 -- never forbidden, never 200, never an EMPTY 200 --
     and a missing run must take the IDENTICAL path, so the response SHAPE leaks no
     more than its status does. Proven three ways: behaviourally through the real
     FastAPI stack (`_build_app`), structurally by reading the handler source (a
     forbidden arm cannot be added without turning this file red), and negatively by
     proving the run_event query is NEVER reached on a denial.

  2. BOUNDEDNESS. A 24-angle run emits thousands of rows. `limit` is CLAMPED into
     1..1000 (not rejected outside it) and `has_more` is decided by a `limit + 1`
     probe row rather than a COUNT over the run's whole history.

  3. ANTI-REWIND. An empty page returns the cursor the caller PASSED IN, never 0. A
     0 would send a live client back to the start of the run on its first quiet tick.

  4. ROLLING-DEPLOY TOLERANCE. `RunEventItem.kind` is a plain `str`, so a row written
     by a NEWER engine revision carrying a kind this build has never heard of still
     validates on read instead of 500-ing the feed for the length of a rollout.

SCOPE NOTE ON THE DENIAL DIMENSIONS. The tribunal engine's isolation dimension is the
JWT-trusted tenant + the FORCE-RLS GUC set by `get_db_session`. It has NO role and NO
space concept -- `Identity.role`, null-space callers and the superadmin gate are the
INTAKE side's (`backend/app/api/research_routes.py`), and the role/null-space denial
arms for this feed therefore belong to the intake PROXY in plan 15.3-07, which is the
layer that has an `Identity` to check. What IS provable here, and is proven below, is
that this handler accepts NO caller-supplied tenant of any kind: the only way a tenant
reaches the query is `Depends(get_db_session)`, so there is nothing for a caller to
spoof (the TENANT-02 property).

PURE AND KEYLESS BY DESIGN. No Postgres, no DATABASE_URL, no provider key, no network.
The session is a hand-written duck-typed fake that behaves like a tiny in-memory
`run_event` table (it HONOURS the `:after` / `:lim` binds the handler sends), which is
what makes the paging assertions real rather than decorative. House style: the
TestClient + fake-session shape of test_audit_body_endpoint.py, and the direct
handler-call shape of test_stage_logging.py::_FakeMetricsSession.

`fastapi` and `httpx` are PINNED in tribunal/requirements.txt (0.136.3 / 0.28.1), so
the importorskip guards below are a local-dev convenience and CANNOT make this file
skip silently in the engine gate -- read the `collecting:` block and the `-rs` summary,
not the exit status.

Cloud Build gate:
  pytest nestor_pulse_sdk/tests/test_run_events_api.py -x
"""

from __future__ import annotations

import inspect
import uuid

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")  # fastapi.testclient transport

from datetime import datetime, timedelta, timezone  # noqa: E402 -- after importorskip


# The forbidden status is CONSTRUCTED, never written as a literal, so this file
# cannot defeat its own source gate: the gates below scan handler source for this
# string, and a bare "403" typed here would be indistinguishable noise to a future
# reader trying to work out whether the gate is honest. Same trick as
# test_checkpoint_resume.py::test_resume_handler_is_404_not_403_by_construction.
_FORBIDDEN = str(403)


def _handler_code(fn) -> str:
    """A handler's source with its DOCSTRING removed -- prose is not behaviour.

    The structural gates below count CODE constructs (how many resolves, how many
    denial arms). A docstring that names `scalar_one_or_none` while explaining why it
    is there would inflate those counts and turn a good comment into a red build --
    which is how a gate teaches people to stop writing comments. The forbidden-status
    gate deliberately does NOT use this: it scans the FULL source, docstring included,
    because a docstring quoting that number would defeat its own gate.
    """
    src = inspect.getsource(fn)
    doc = fn.__doc__
    return src.replace(doc, "") if doc else src


# ---------------------------------------------------------------------------
# Fakes: a tiny in-memory run_event table + the run SELECT that guards it
# ---------------------------------------------------------------------------

class _FakeRow:
    """A SQLAlchemy Row stand-in exposing `._mapping`, the idiom runs/api.py uses."""

    def __init__(self, mapping: dict):
        self._mapping = mapping


def _event(seq: int, *, kind: str = "thinking", meta=None, stage: str = "deep_research"):
    """One run_event row as the raw SELECT would hand it back."""
    return _FakeRow(
        {
            "seq": seq,
            "ts": datetime(2026, 7, 27, 8, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=seq),
            "stage": stage,
            "kind": kind,
            "text": f"line {seq}",
            "meta": meta,
        }
    )


class _RunResult:
    def __init__(self, run):
        self._run = run

    def scalar_one_or_none(self):
        return self._run


class _RowsResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeRun:
    """The subset of `Run` this endpoint reads (it reads only `.id`, via the 404 guard)."""

    def __init__(self, run_id: uuid.UUID, status: str = "running"):
        self.id = run_id
        self.status = status


class _Session:
    """Fake AsyncSession: the run SELECT first, then the run_event page SELECT.

    `run=None` models an RLS MISS -- Postgres hides another tenant's run, so the
    handler's `scalar_one_or_none` is None and it must 404 before touching run_event.

    The second call behaves like a real `run_event` table: it FILTERS on the `:after`
    bind and TRUNCATES to the `:lim` bind the handler sent. That is deliberate -- a
    fake that ignored those binds would let a handler that forgot to clamp, or forgot
    to ask for the probe row, still pass every paging assertion below.
    """

    def __init__(self, run, rows=()):
        self._run = run
        self._rows = list(rows)
        self.calls = 0
        self.statements: list[tuple[str, dict | None]] = []

    async def execute(self, statement, params=None):  # noqa: ANN001 -- duck type
        self.calls += 1
        self.statements.append((str(statement), params))
        # ODD call = the run resolve, EVEN call = the page read. The handler issues
        # exactly that pair per invocation, and several tests below invoke it TWICE
        # against the same session to walk a cursor forward -- so the sequencing has
        # to reset per invocation rather than count cumulatively from the first.
        if self.calls % 2 == 1:
            return _RunResult(self._run)
        after = int((params or {}).get("after", 0))
        lim = int((params or {}).get("lim", len(self._rows)))
        visible = [r for r in self._rows if r._mapping["seq"] > after]
        return _RowsResult(visible[:lim])


def _build_app(session: _Session):
    from fastapi import FastAPI

    from nestor_pulse_sdk.auth.deps import get_db_session
    from nestor_pulse_sdk.runs.api import router as runs_router

    app = FastAPI()
    app.include_router(runs_router)

    async def _fake_db_session():
        yield session

    app.dependency_overrides[get_db_session] = _fake_db_session
    return app


# ===========================================================================
# (a)(b)(c) SOURCE GATES -- properties that must survive any future edit
# ===========================================================================

def test_events_handler_is_404_not_forbidden_by_construction():
    """A cross-tenant run_id must be INVISIBLE, not FORBIDDEN (T-15.3-10).

    A forbidden answer would CONFIRM the run exists and belongs to somebody else --
    the exact fact the tenant wall is there to hide. This reads the handler's own
    source, so the property cannot be lost by an edit that happens to leave the
    behavioural tests passing against a fake.
    """
    from nestor_pulse_sdk.runs.api import get_run_events

    src = inspect.getsource(get_run_events)

    assert "scalar_one_or_none" in src, (
        "the run must be resolved through RLS, so a foreign run reads as absent"
    )
    assert "HTTPException(404" in src, (
        "an unknown or cross-tenant run_id must be a 404"
    )
    assert _FORBIDDEN not in src, (
        f"get_run_events gained a {_FORBIDDEN}. A cross-tenant run_id is invisible, "
        "not forbidden -- that status would confirm the run exists."
    )


def test_missing_and_foreign_runs_cannot_take_different_paths():
    """T-15.3-11: exactly ONE denial arm exists, so both cases reach the same 404.

    Non-distinguishability is not something you can prove by comparing two identical
    fakes -- that is a tautology. What CAN be proved is that the handler offers only
    one way out other than success: a single `HTTPException`, raised from the single
    `scalar_one_or_none() is None` branch. If a second denial arm is ever added (a
    different status, a different detail string, or an empty-page early return), this
    goes red and the reviewer has to justify it.
    """
    from nestor_pulse_sdk.runs.api import get_run_events

    src = _handler_code(get_run_events)

    assert src.count("HTTPException(") == 1, (
        "get_run_events must have EXACTLY ONE denial arm, so a missing run and a "
        "foreign run cannot be told apart by status OR by detail text"
    )
    assert src.count("scalar_one_or_none") == 1, (
        "one resolve, one branch -- a second lookup is a second way to diverge"
    )
    # No empty-200 arm: the only RunEventPage construction is the success return,
    # and it is not reachable before the 404 raise.
    raise_at = src.index("HTTPException(404")
    assert "RunEventPage(" not in src[:raise_at], (
        "a page constructed BEFORE the 404 guard would answer a foreign run with an "
        "empty 200 -- leaking through the response shape what the status hides"
    )


def test_events_endpoint_has_no_status_gate():
    """A failed, cancelled or parked run is exactly the run whose feed is needed.

    Today's failed/cancelled cards DROP the feed; that is the defect this endpoint
    exists to end. Follow `get_run_verification` (deliberately gate-free), NOT
    `get_run_report` (gated). Pins the ABSENCE, in the shape of
    test_status_gates.py::test_verification_endpoint_has_no_status_gate.
    """
    from nestor_pulse_sdk.runs.api import get_run_events

    src = inspect.getsource(get_run_events)

    for forbidden in ("report_readable", "bundle_readable", "409"):
        assert forbidden not in src, (
            f"{forbidden!r} appeared in get_run_events. A parked or failed run must "
            "still be able to show what it did; a status gate here is the regression."
        )
    assert "parked" in (get_run_events.__doc__ or ""), (
        "the docstring must record that this endpoint is deliberately gate-free, so "
        "nobody 'fixes' it later"
    )


def test_events_route_is_declared_before_the_catch_all():
    """FastAPI resolves in DECLARATION order -- a later sub-path is shadowed.

    Declared after `GET /{run_id}`, this endpoint would never be reached: the
    catch-all would match `/{run_id}/events` first and fail to parse `events` as a
    UUID. The failure mode is a 422 on a route that looks correct in the source.
    """
    from nestor_pulse_sdk.runs.api import router

    paths = [r.path for r in router.routes]
    assert "/api/runs/{run_id}/events" in paths, "the events route must be registered"
    assert paths.index("/api/runs/{run_id}/events") < paths.index("/api/runs/{run_id}"), (
        "GET /{run_id}/events is shadowed by the /{run_id} catch-all declared above it"
    )


def test_no_caller_supplied_tenant_reaches_the_query():
    """TENANT-02 at this layer: the tenant is not an input, so there is nothing to spoof.

    The tribunal engine has no role and no space concept -- those live on the intake
    side and the role / null-space denial arms for this feed belong to the 15.3-07
    proxy. What this layer owns is that the tenant arrives ONLY through
    `Depends(get_db_session)` (which SET LOCALs the GUC the FORCE-RLS policies read),
    never as a path, query or body parameter.
    """
    from nestor_pulse_sdk.runs.api import get_run_events

    params = inspect.signature(get_run_events).parameters
    assert "session" in params, (
        "the tenant arrives through get_db_session's RLS context, not a parameter"
    )
    for spoofable in ("tenant_id", "space_id", "org_id"):
        assert spoofable not in params, (
            f"{spoofable} is a caller-supplied tenant input -- the tenant must come "
            "only from the verified session context"
        )


def test_the_page_query_is_bound_ordered_and_countless():
    """T-15.3-12/T-15.3-14 read off the statement the handler actually sends.

    Docstring-stripped: these are claims about the SQL, and prose describing the SQL
    must not be able to satisfy them.
    """
    from nestor_pulse_sdk.runs.api import get_run_events

    src = _handler_code(get_run_events)

    assert "ORDER BY seq ASC" in src, "ordering is by seq ascending, with no DESC mode"
    assert "seq > :after" in src and "LIMIT :lim" in src, (
        "cursor paging on bound parameters -- never OFFSET, never interpolation"
    )
    assert "limit + 1" in src, (
        "has_more must be decided by a probe row, so the extra row must be requested"
    )
    lowered = src.lower()
    assert "count(*)" not in lowered and "count(seq)" not in lowered, (
        "a COUNT over the run's whole history on every page turn is exactly the "
        "denial of service the limit + 1 probe exists to avoid"
    )
    # `:after` / `:lim` / `:rid` are binds; nothing is f-stringed into the SQL.
    assert 'f"SELECT' not in src and "f'SELECT" not in src, (
        "the SQL must never be built by interpolation (T-15.3-14)"
    )


# ===========================================================================
# ISOLATION, behaviourally, through the real FastAPI stack
# ===========================================================================

def test_cross_tenant_run_id_returns_exactly_404_and_never_reads_run_event():
    """An RLS-invisible run is EXACTLY 404, and the feed is never even queried.

    The run SELECT returns None (Postgres hides another tenant's row), so the handler
    404s BEFORE the run_event page query. Asserting `session.calls == 1` is what makes
    this more than a status check: it proves the denial fires at the tenant wall, not
    after a read that already touched another tenant's rows.
    """
    from fastapi.testclient import TestClient

    foreign_run_id = uuid.uuid4()
    session = _Session(run=None, rows=[_event(1), _event(2)])
    app = _build_app(session)
    try:
        resp = TestClient(app).get(f"/api/runs/{foreign_run_id}/events")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 404, (
        f"a cross-tenant run_id must be EXACTLY 404 (RLS miss == absent, T-15.3-10), "
        f"got {resp.status_code} (body={resp.text!r})."
    )
    assert session.calls == 1, (
        "run_event was queried on a denied request -- the 404 must fire at the run "
        f"resolve, before any feed read (execute called {session.calls} times)"
    )
    assert str(foreign_run_id) not in resp.text, (
        "the 404 body echoed the foreign run_id back at the caller"
    )
    assert "events" not in resp.json(), (
        "a denial must not answer with a page-shaped body -- an empty events list "
        "would leak, through the response SHAPE, what the status is hiding"
    )


def test_unknown_run_id_is_the_same_404_with_the_same_body():
    """A run that never existed is answered identically to one owned by somebody else.

    Both cases arrive at the handler as `scalar_one_or_none() -> None`; this pins that
    the caller-visible result of that single branch is one fixed status AND one fixed
    body, so the two cases cannot be told apart by reading the response (T-15.3-11).
    """
    from fastapi.testclient import TestClient

    unknown = _Session(run=None)
    foreign = _Session(run=None)

    app_a = _build_app(unknown)
    try:
        resp_unknown = TestClient(app_a).get(f"/api/runs/{uuid.uuid4()}/events")
    finally:
        app_a.dependency_overrides.clear()

    app_b = _build_app(foreign)
    try:
        resp_foreign = TestClient(app_b).get(f"/api/runs/{uuid.uuid4()}/events?after_seq=42")
    finally:
        app_b.dependency_overrides.clear()

    assert resp_unknown.status_code == 404 and resp_foreign.status_code == 404
    assert resp_unknown.json() == resp_foreign.json(), (
        "the two denial bodies differ -- a caller could distinguish a run that does "
        "not exist from one that exists and is not theirs"
    )


def test_a_same_tenant_caller_gets_the_page_through_the_real_route():
    """The happy path, end to end -- which is also the honest shadowing check.

    `test_events_route_is_declared_before_the_catch_all` reads declaration order; this
    proves the consequence. Were the route shadowed by `GET /{run_id}`, this request
    would come back 422 (the catch-all failing to parse `events` as a UUID) rather
    than 200, on source that looks perfectly correct.
    """
    from fastapi.testclient import TestClient

    run_id = uuid.uuid4()
    session = _Session(
        run=_FakeRun(run_id),
        rows=[_event(1), _event(2, kind="search", meta={"angle": "pricing"})],
    )
    app = _build_app(session)
    try:
        resp = TestClient(app).get(f"/api/runs/{run_id}/events?after_seq=0&limit=50")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200, (
        f"same-tenant read should be 200, got {resp.status_code} (body={resp.text!r})."
    )
    payload = resp.json()
    assert payload["run_id"] == str(run_id)
    assert [e["seq"] for e in payload["events"]] == [1, 2]
    assert payload["events"][1]["kind"] == "search"
    assert payload["events"][1]["meta"] == {"angle": "pricing"}
    assert payload["next_after_seq"] == 2
    assert payload["has_more"] is False
    # The tenant key is never a wire value.
    assert "tenant_id" not in resp.text


def test_a_non_integer_cursor_is_rejected_before_the_handler_runs():
    """T-15.3-14: `after_seq` / `limit` are typed query params, not free text."""
    from fastapi.testclient import TestClient

    run_id = uuid.uuid4()
    session = _Session(run=_FakeRun(run_id), rows=[_event(1)])
    app = _build_app(session)
    try:
        client = TestClient(app)
        bad_cursor = client.get(f"/api/runs/{run_id}/events?after_seq=abc")
        bad_limit = client.get(f"/api/runs/{run_id}/events?limit=all")
    finally:
        app.dependency_overrides.clear()

    assert bad_cursor.status_code == 422, (
        f"a non-integer after_seq must be refused by validation, got {bad_cursor.status_code}"
    )
    assert bad_limit.status_code == 422, (
        f"a non-integer limit must be refused by validation, got {bad_limit.status_code}"
    )


# ===========================================================================
# (d)-(h) PAGING BEHAVIOUR, driven through the handler with a fake table
# ===========================================================================

async def _events(session: _Session, run_id: uuid.UUID, **kwargs):
    from nestor_pulse_sdk.runs.api import get_run_events

    return await get_run_events(run_id, session=session, **kwargs)


async def test_an_oversized_limit_is_clamped_to_the_ceiling_not_rejected():
    """(d) T-15.3-12: `limit=99999` yields 1000 rows, not an unbounded read and not a 422.

    Clamping rather than rejecting is the deliberate choice: a client that asks for
    too much gets a bounded page and can keep paging, instead of an error it has to
    learn to avoid. The ceiling is what makes an unbounded read of a 24-angle run
    impossible.
    """
    session = _Session(run=_FakeRun(uuid.uuid4()), rows=[_event(i) for i in range(1, 1201)])
    run_id = session._run.id

    page = await _events(session, run_id, after_seq=0, limit=99999)

    assert len(page.events) == 1000, (
        f"limit must clamp to the 1000 ceiling; got {len(page.events)} events"
    )
    assert page.has_more is True
    # The handler asked for the ceiling PLUS the probe row -- proof the probe is real.
    _, params = session.statements[-1]
    assert params["lim"] == 1001, (
        f"expected a limit + 1 probe fetch of 1001, got {params['lim']}"
    )


async def test_a_zero_or_negative_limit_is_clamped_to_one():
    """(d) The floor: `limit=0` must not turn paging into an infinite empty loop."""
    session = _Session(run=_FakeRun(uuid.uuid4()), rows=[_event(i) for i in range(1, 6)])
    run_id = session._run.id

    zero = await _events(session, run_id, after_seq=0, limit=0)
    assert len(zero.events) == 1, f"limit=0 must clamp to 1, got {len(zero.events)}"
    assert zero.has_more is True
    assert zero.next_after_seq == 1

    negative = await _events(session, run_id, after_seq=0, limit=-5)
    assert len(negative.events) == 1, "a negative limit must clamp to 1 too"


async def test_a_negative_cursor_is_floored_at_zero():
    """T-15.3-14: a hostile `after_seq` cannot reach the query as-is."""
    session = _Session(run=_FakeRun(uuid.uuid4()), rows=[_event(i) for i in range(1, 4)])
    run_id = session._run.id

    page = await _events(session, run_id, after_seq=-999, limit=10)

    _, params = session.statements[-1]
    assert params["after"] == 0, f"after_seq must floor at 0, the query got {params['after']}"
    assert [e.seq for e in page.events] == [1, 2, 3]


async def test_a_full_page_reports_has_more_and_the_last_seq_as_the_cursor():
    """(e) The probe row decides `has_more` and is TRIMMED before the client sees it."""
    session = _Session(run=_FakeRun(uuid.uuid4()), rows=[_event(i) for i in range(1, 11)])
    run_id = session._run.id

    page = await _events(session, run_id, after_seq=0, limit=4)

    assert [e.seq for e in page.events] == [1, 2, 3, 4], (
        "the limit + 1 probe row must be dropped before the response is built"
    )
    assert page.has_more is True
    assert page.next_after_seq == 4, "the cursor is the LAST seq in this page"

    # And the next page continues from that cursor rather than repeating anything.
    nxt = await _events(session, run_id, after_seq=page.next_after_seq, limit=4)
    assert [e.seq for e in nxt.events] == [5, 6, 7, 8]


async def test_the_final_page_reports_no_more():
    """The probe row does NOT come back when the history is exhausted."""
    session = _Session(run=_FakeRun(uuid.uuid4()), rows=[_event(i) for i in range(1, 6)])
    run_id = session._run.id

    page = await _events(session, run_id, after_seq=0, limit=10)

    assert [e.seq for e in page.events] == [1, 2, 3, 4, 5]
    assert page.has_more is False, "no probe row came back, so there is nothing more"
    assert page.next_after_seq == 5


async def test_an_empty_page_holds_the_callers_cursor_instead_of_rewinding():
    """(f) THE ANTI-REWIND PROPERTY. An empty page must never return 0.

    A live client polls with the highest seq it holds. If a quiet tick answered
    `next_after_seq: 0` the client would go back to the start of the run and
    re-download every line it already has -- on every quiet tick, for the rest of the
    run. This is the single most expensive way to get pagination subtly wrong.
    """
    session = _Session(run=_FakeRun(uuid.uuid4()), rows=[_event(i) for i in range(1, 6)])
    run_id = session._run.id

    page = await _events(session, run_id, after_seq=5, limit=100)

    assert page.events == []
    assert page.has_more is False
    assert page.next_after_seq == 5, (
        f"an empty page must hold the caller's cursor, got {page.next_after_seq} "
        "-- a 0 here rewinds a live client to the beginning of the run"
    )


async def test_rows_are_returned_in_ascending_seq_order():
    """(g) Ordering is the feed's whole meaning -- a mis-ordered feed is a wrong feed."""
    session = _Session(run=_FakeRun(uuid.uuid4()), rows=[_event(i) for i in (1, 2, 3, 4, 5)])
    run_id = session._run.id

    page = await _events(session, run_id, after_seq=0, limit=100)
    seqs = [e.seq for e in page.events]

    assert seqs == sorted(seqs), f"events came back out of order: {seqs}"
    assert seqs == [1, 2, 3, 4, 5]
    # The order is the DATABASE's job, not a post-sort in Python -- pin the clause.
    statement, _ = session.statements[-1]
    assert "ORDER BY seq ASC" in statement


async def test_an_unknown_kind_from_a_newer_engine_still_validates():
    """(h) THE ROLLING-DEPLOY PROPERTY.

    Cloud Run replaces revisions gradually. A newer engine revision writing a
    thirteenth kind while an older API revision still serves reads is the NORMAL state
    of a deploy. A `Literal` over RUN_EVENT_KINDS here would turn every read of that
    run -- the live one an operator is watching -- into a 500 for the length of the
    rollout. Widening the writer's vocabulary must stay a no-op on the reader.
    """
    from nestor_pulse_sdk.runs.run_events import RUN_EVENT_KINDS

    assert "teleport" not in RUN_EVENT_KINDS, "pick a kind this build genuinely lacks"

    session = _Session(
        run=_FakeRun(uuid.uuid4()),
        rows=[_event(1, kind="thinking"), _event(2, kind="teleport")],
    )
    run_id = session._run.id

    page = await _events(session, run_id, after_seq=0, limit=10)

    assert [e.kind for e in page.events] == ["thinking", "teleport"], (
        "an out-of-vocabulary kind must ride through the read unchanged"
    )


async def test_meta_survives_as_a_dict_and_a_malformed_meta_does_not_500():
    """`meta` is JSONB written by the worker -- shaped input, read defensively.

    The normal path (already-decoded dict) must ride through untouched. A driver or
    dialect change that hands back a JSON STRING must degrade to a dropped `meta` on
    one line, never to a 500 on the feed an operator is reading.
    """
    session = _Session(
        run=_FakeRun(uuid.uuid4()),
        rows=[
            _event(1, meta={"angle": "pricing"}),
            _event(2, meta='{"angle": "supply"}'),   # string form
            _event(3, meta="not json at all"),        # unparseable
            _event(4, meta=None),
        ],
    )
    run_id = session._run.id

    page = await _events(session, run_id, after_seq=0, limit=10)

    assert page.events[0].meta == {"angle": "pricing"}
    assert page.events[1].meta == {"angle": "supply"}
    assert page.events[2].meta is None, "an unparseable meta drops the field, not the run"
    assert page.events[3].meta is None


# ===========================================================================
# SCHEMA CONTRACT -- the additive cursor and the deliberately-loose `kind`
# ===========================================================================

def test_run_metrics_carries_an_additive_event_seq():
    """The cursor is ADDITIVE: nothing the poll driver already reads may be disturbed."""
    from nestor_pulse_sdk.runs.schemas import RunMetrics

    fields = RunMetrics.model_fields
    assert "event_seq" in fields, "RunMetrics must publish the feed cursor"
    for kept in (
        "started_at",
        "completed_at",
        "stages",
        "current_stage",
        "stage_detail",
        "park",
        "elapsed_seconds",
        "citation_recall",
    ):
        assert kept in fields, (
            f"{kept} disappeared from RunMetrics -- event_seq is ADDITIVE and must "
            "not be paid for by removing a field an existing consumer reads"
        )


def test_run_metrics_still_validates_without_the_cursor():
    """An engine revision predating 15.3-02 simply omits it; the intake must not care."""
    from nestor_pulse_sdk.runs.schemas import RunMetrics

    metrics = RunMetrics(run_id=uuid.uuid4(), engine="tribunal", status="running")

    assert metrics.event_seq is None
    assert "event_seq" in metrics.model_dump(mode="json")


def test_event_kind_is_a_plain_str_not_a_literal():
    """The rolling-deploy property, pinned at the type level rather than by behaviour."""
    from nestor_pulse_sdk.runs.schemas import RunEventItem

    assert RunEventItem.model_fields["kind"].annotation is str, (
        "RunEventItem.kind must be a plain str. A Literal over RUN_EVENT_KINDS turns "
        "a rolling deploy into 500s on exactly the live run being watched."
    )


def test_run_event_page_defaults_are_safe_for_an_empty_run():
    """A run with no events yet is a valid, empty, non-rewinding page."""
    from nestor_pulse_sdk.runs.schemas import RunEventPage

    page = RunEventPage(run_id=uuid.uuid4())

    assert page.events == []
    assert page.next_after_seq == 0
    assert page.has_more is False
