"""R3 checkpoints — the store, the guards and the park sequence (plan 15.2-16).

WHY this file exists
--------------------
Before 15.2-16 an Anthropic monthly cap turned a ~$45 Tribunal run into a
`failed` row and nothing else: every paid deep-research report, every gate
decision and every skeptic session was discarded. R3 records each paid stage as
it completes so a PARKED run can be resumed without re-charging anything. The
whole value of that depends on three properties that are easy to get subtly
wrong, so each one is pinned here by name:

  1. a restored payload belongs to THIS run's questions (`angles_digest`),
  2. a payload written by older code is DISCARDED, not replayed
     (`CHECKPOINT_VERSION`),
  3. a provider job id can never carry a path into a URL (`safe_job_id`).

EVERY TEST IN THIS FILE IS PURE: no database, no network, no LLM, no API key, no
mocking library. The store takes its `read`/`write` as injected awaitables, so a
plain dict is the whole backing store. That is not a testing convenience — it is
why `checkpoints.py` contains no database code at all.

Coverage (Layer A — pure, runs in the keyless DB-less engine gate):
  * round-trip: a fresh store over the same backing dict restores the payload
  * version guard: an envelope written under another version is discarded, loudly
  * `angles_digest` stability, sensitivity and tolerance of a malformed entry
  * `safe_job_id` accepts a realistic id and refuses four hostile shapes
  * the size bound refuses a payload and writes NOTHING
  * park sequencing: same signature keeps `seq`, a new signature increments it
  * `resumed()` is False when the only stored key is `ckpt_park`
  * `CHECKPOINT_KEYS` hygiene, and the unknown-key `KeyError`
  * DEC-6: `terminal_state(**_park_result(...)["terminal_inputs"]) == "parked"`
    for BOTH the F6 case and the hard-wall case
  * a park reason built from an exception carrying a secret does not leak it
  * `resume_run` is a 404-not-403 handler BY CONSTRUCTION (source gate)
  * the worker's park branch keeps the cancel guard and stamps no completed_at

Coverage (Layer B — REAL Postgres, as a NON-SUPERUSER; read the block above
those tests before trusting any green run):
  * `test_resume_cross_tenant_run_is_404` — tenant B cannot resume tenant A's run
  * `test_resume_wrong_state_is_409_and_mutates_nothing` — the allow-list is closed
  * `test_resume_parked_run_requeues_the_same_run` — the SAME run id, re-queued

Cloud Build gate:
    gcloud builds submit tribunal --config=tribunal/cloudbuild.test-engine.yaml \
        --project="$GOOGLE_PROJECT"

This file is ALREADY pre-listed in `cloudbuild.test-engine.yaml` by plan 15.2-02,
so no config edit is ever needed to run it.
"""
from __future__ import annotations

import json
import logging
import os
import uuid

import pytest

from nestor_pulse_sdk.pipeline.tribunal import checkpoints as ckpt_mod
from nestor_pulse_sdk.pipeline.tribunal.checkpoints import (
    CHECKPOINT_KEYS,
    CHECKPOINT_VERSION,
    CheckpointStore,
    angles_digest,
    ckpt_format,
    next_park_seq,
    park_signature,
    safe_job_id,
)


# ---------------------------------------------------------------------------
# The backing store: a plain dict behind two tiny async closures. No Postgres,
# no session, no fixture — the injection seam IS the test harness.
# ---------------------------------------------------------------------------


def _store(backing: dict, *, enabled: bool = True) -> CheckpointStore:
    async def _read(fmt: str):
        return backing.get(fmt)

    async def _write(fmt: str, payload) -> None:
        backing[fmt] = payload

    return CheckpointStore(read=_read, write=_write, enabled=enabled)


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


async def test_a_checkpoint_round_trips_through_a_fresh_store():
    """What one store wrote, a NEW store over the same rows reads back.

    This is the resume contract in miniature: the run that wrote the checkpoint
    is gone (the worker died, or the run parked), and a different process reads
    it.
    """
    backing: dict = {}
    data = {"funnel": {"distilled": 12}, "claims": [{"text": "a"}]}

    wrote = await _store(backing).put("gates", data)
    assert wrote is True, "put() must report that it wrote the checkpoint"
    assert ckpt_format("gates") in backing, (
        "the payload must land under the ckpt_-prefixed Output format"
    )

    fresh = _store(backing)
    await fresh.load()
    assert fresh.get("gates") == data, (
        "a fresh store over the same rows must return the payload verbatim — "
        "otherwise a resumed run silently re-charges the gate stage"
    )
    assert fresh.restored_keys == ["gates"]
    assert fresh.resumed() is True, "a restored gate result IS resumable work"


# ---------------------------------------------------------------------------
# The version guard (T-15.2-128)
# ---------------------------------------------------------------------------


async def test_a_payload_from_another_checkpoint_version_is_discarded(caplog):
    """A run may park before a redeploy and resume after it (T-15.2-128).

    Replaying a payload the current code cannot read is worse than re-running
    the stage, so the envelope carries `v` and a mismatch is dropped IN WORDS.
    """
    backing = {
        ckpt_format("verify"): {
            "v": 99,
            "digest": None,
            "written_at": "2026-07-26T00:00:00+00:00",
            "data": {"per_claim_verdicts": {"stale": []}},
        }
    }
    store = _store(backing)
    with caplog.at_level(logging.WARNING):
        await store.load()

    assert store.get("verify") is None, (
        "a payload from another checkpoint version must not be readable"
    )
    assert store.restored_keys == []
    assert store.resumed() is False
    assert any(
        "DISCARDED" in record.getMessage() and "ckpt_verify" in record.getMessage()
        for record in caplog.records
    ), "the discard must be logged at WARNING naming the key — never silently"


async def test_a_non_envelope_payload_is_discarded_rather_than_trusted():
    """A row that is not a dict is not an envelope. Fail closed, run the stage."""
    backing = {ckpt_format("merge"): ["not", "an", "envelope"]}
    store = _store(backing)
    await store.load()
    assert store.get("merge") is None
    assert store.restored_keys == []


# ---------------------------------------------------------------------------
# angles_digest — the guard that makes index-keyed restore safe
# ---------------------------------------------------------------------------


def test_angles_digest_is_stable_for_the_same_questions():
    angles = [{"query": "Aral's German fuel market share"}, {"query": "LUKOIL sale"}]
    assert angles_digest(angles) == angles_digest(list(angles)), (
        "the same angle list must always digest identically, or every resume "
        "would discard a valid checkpoint"
    )
    assert len(angles_digest(angles)) == 16


def test_angles_digest_changes_when_one_question_changes():
    """A different question list MUST produce a different digest (T-15.2-123).

    `ckpt_research` is keyed by angle INDEX, so replaying it against a changed
    list would attach one stream's answer to another question — a wrong report
    that looks healthy.
    """
    a = [{"query": "Aral's German fuel market share"}, {"query": "LUKOIL sale"}]
    b = [{"query": "Aral's German fuel market share"}, {"query": "LUKOIL buyer"}]
    assert angles_digest(a) != angles_digest(b), (
        "a changed sub-question must invalidate the research checkpoint"
    )


def test_angles_digest_tolerates_a_malformed_entry():
    """A non-dict entry contributes the empty string; it never raises."""
    assert isinstance(angles_digest([{"query": "x"}, None, "junk", 7]), str)
    assert angles_digest(None) == angles_digest([])


# ---------------------------------------------------------------------------
# safe_job_id — the path-injection control (T-15.2-125)
# ---------------------------------------------------------------------------


def test_safe_job_id_accepts_a_realistic_provider_id():
    assert safe_job_id("resp_68a1f0c2b3d94e1a9f00b7c1d2e3f405") == (
        "resp_68a1f0c2b3d94e1a9f00b7c1d2e3f405"
    )
    assert safe_job_id("  interactions-abc.123:v2  ") == "interactions-abc.123:v2"


@pytest.mark.parametrize(
    "hostile",
    [
        "../../secrets",              # parent-directory traversal
        "abc/def",                    # a bare slash — a second path segment
        "",                           # empty
        "x" * 300,                    # unbounded length
    ],
)
def test_safe_job_id_refuses_a_hostile_id_and_never_raises(hostile):
    """Each hostile shape returns None. NOTE: no pytest.raises anywhere here —
    a guard that raises would turn a poisoned `output` row into a crashed run
    instead of a named, degraded stream."""
    assert safe_job_id(hostile) is None, (
        f"safe_job_id must refuse {hostile[:40]!r} rather than let it reach a URL"
    )


# ---------------------------------------------------------------------------
# The size bound (T-15.2-131)
# ---------------------------------------------------------------------------


async def test_an_oversized_payload_is_refused_and_nothing_is_written(
    caplog, monkeypatch
):
    """A refused checkpoint costs a stage re-run — never a failed transaction."""
    monkeypatch.setattr(ckpt_mod, "CKPT_MAX_BYTES", 64)
    backing: dict = {}
    big = {"claims": [{"text": "x" * 200} for _ in range(20)]}
    assert len(json.dumps(big).encode("utf-8")) > 64

    with caplog.at_level(logging.WARNING):
        wrote = await _store(backing).put("research", big)

    assert wrote is False, "put() must report the refusal"
    assert len(backing) == 0, (
        "a refused put() must write NOTHING — a partial checkpoint is worse "
        "than none"
    )
    assert any("REFUSED" in record.getMessage() for record in caplog.records), (
        "the refusal must name the byte count at WARNING"
    )


# ---------------------------------------------------------------------------
# DEC-5 — park sequencing
# ---------------------------------------------------------------------------


def test_park_sequence_holds_for_one_event_and_increments_for_a_new_one():
    sig = park_signature("deep_research", "no research provider produced a result")
    assert len(sig) == 12

    assert next_park_seq(None, sig) == 1, "no prior park is sequence 1"
    assert next_park_seq({}, sig) == 1
    assert next_park_seq({"seq": 1, "signature": sig}, sig) == 1, (
        "re-parking for the SAME reason is the same event — the sequence holds, "
        "so 15.2-19 sends one mail"
    )
    assert next_park_seq({"seq": 1, "signature": "other0000000"}, sig) == 2, (
        "a different park reason is a new event and must get its own sequence"
    )


def test_park_signature_separates_stage_from_reason():
    assert park_signature("gate", "wall") != park_signature("verify", "wall")
    assert park_signature("gate", "wall") != park_signature("gate", "other")


# ---------------------------------------------------------------------------
# `park` alone is not resumable work
# ---------------------------------------------------------------------------


async def test_a_park_marker_alone_does_not_count_as_a_resume():
    """A run that parked before its first paid stage has nothing to re-use."""
    backing: dict = {}
    store = _store(backing)
    assert await store.put("park", {"seq": 1, "stage": "intake"}) is True

    fresh = _store(backing)
    await fresh.load()
    assert fresh.restored_keys == ["park"]
    assert fresh.resumed() is False, (
        "a park marker records WHY a run stopped; it is not a stage result"
    )
    assert fresh.get("park") == {"seq": 1, "stage": "intake"}


# ---------------------------------------------------------------------------
# Key hygiene
# ---------------------------------------------------------------------------


def test_checkpoint_keys_are_unique_and_prefixed():
    assert len(set(CHECKPOINT_KEYS)) == len(CHECKPOINT_KEYS), (
        "a duplicate key would make one stage overwrite another's checkpoint"
    )
    for key in CHECKPOINT_KEYS:
        assert ckpt_format(key) == f"ckpt_{key}"


def test_the_two_pre_existing_checkpoints_are_not_r3_keys():
    """`synthesis_cache` and `report_spec` have their OWN resume branch at the
    top of `run()`. If this store claimed them it would shadow that branch."""
    assert "synthesis_cache" not in CHECKPOINT_KEYS
    assert "report_spec" not in CHECKPOINT_KEYS


def test_an_unknown_checkpoint_key_raises_rather_than_reading_as_absent():
    """A typo must not silently mean "no checkpoint" and re-charge a stage."""
    store = _store({})
    with pytest.raises(KeyError):
        store.get("nope")
    assert CHECKPOINT_VERSION == 1


# ===========================================================================
# LAYER A (continued) — the park contract and the resume verb, proven PURELY.
# ===========================================================================


def _park_inputs(**overrides):
    base = {
        "streams_lost": 4,
        "streams_total": 4,
        "verify_ran": False,
        "synthesis_ran": False,
        "hard_wall": False,
        "degradation_reasons": [],
    }
    base.update(overrides)
    return base


def test_park_result_resolves_to_parked_through_terminal_state():
    """DEC-6, THE CONTRACT OF THIS WHOLE PLAN.

    The pipeline never returns the string "parked". It returns FACTS built so
    that `terminal_state()` — the single decision function — provably yields
    "parked". If this test ever fails, the engine has grown a second park rule.
    """
    from nestor_pulse_sdk.pipeline.tribunal.pipeline import _park_result
    from nestor_pulse_sdk.pipeline.tribunal.reliability import terminal_state

    # --- F6: every research stream lost -----------------------------------
    f6 = _park_result(
        stage="deep_research",
        reason="No research provider produced a usable result for this run.",
        prior_park=None,
        terminal_inputs=_park_inputs(),
    )
    assert f6["parked"] is True
    assert f6["park"]["seq"] == 1
    assert len(f6["park"]["signature"]) == 12
    assert len(f6["park"]["reason"]) <= 400
    assert terminal_state(**f6["terminal_inputs"]) == "parked", (
        "losing every research stream must resolve to parked — streams_lost == "
        "streams_total is what makes that true"
    )

    # --- The hard wall: the monthly cap / exhausted credits / 402 ----------
    wall = _park_result(
        stage="verify",
        reason="The provider refused the request at the account level.",
        prior_park=None,
        terminal_inputs=_park_inputs(
            streams_lost=0, streams_total=4, hard_wall=True,
        ),
    )
    assert terminal_state(**wall["terminal_inputs"]) == "parked", (
        "a hard provider wall must resolve to parked, not failed"
    )


def test_losing_two_of_four_streams_is_degraded_not_parked():
    """The other half of D-17, and the one most easily got wrong.

    A park is "no honest deliverable is possible". Losing one or two streams of
    four still produces a report, so it is `completed_degraded` — parking it
    would put a Resume button in front of an operator who already has an answer.
    """
    from nestor_pulse_sdk.pipeline.tribunal.reliability import terminal_state

    assert terminal_state(
        streams_lost=2, streams_total=4, verify_ran=True, synthesis_ran=True,
        hard_wall=False, degradation_reasons=["two streams were lost"],
    ) == "completed_degraded"
    assert terminal_state(
        streams_lost=4, streams_total=4, verify_ran=True, synthesis_ran=True,
        hard_wall=False, degradation_reasons=["every stream was lost"],
    ) == "parked"


def test_park_reason_is_redacted():
    """A park reason is rendered into an EMAIL and the operator UI (15.2-19).

    It is built from `error_signature()` — redacted, digit-stripped, truncated —
    plus a plain lead sentence, never `repr(exc)`. A SerpApi failure carries its
    key in the query string, so this is a real leak path (T-15.2-126).
    """
    from nestor_pulse_sdk.pipeline.tribunal.pipeline import _park_result
    from nestor_pulse_sdk.pipeline.tribunal.reliability import error_signature

    secret = "zzsupersecretvaluezz"
    exc = RuntimeError(f"request failed: api_key={secret} monthly cap reached")

    result = _park_result(
        stage="deep_research",
        reason=f"The provider refused this run. Provider signal: {error_signature(exc)}",
        prior_park=None,
        terminal_inputs=_park_inputs(),
    )
    assert secret not in result["park"]["reason"].lower(), (
        "a credential from provider error text must never reach the park reason "
        "— it is persisted, emailed and rendered in the operator panel"
    )
    assert "<redacted>" in result["park"]["reason"]


def test_resume_handler_is_404_not_403_by_construction():
    """A cross-tenant run_id must be INVISIBLE, not FORBIDDEN.

    A 403 would confirm that the run exists and belongs to somebody else. This
    reads the handler's own source, so the property cannot be lost by an edit
    that happens to keep the DB-backed test skipping.
    """
    import inspect

    from nestor_pulse_sdk.runs.api import resume_run

    src = inspect.getsource(resume_run)
    assert "scalar_one_or_none" in src, (
        "the row must be resolved through RLS, so a foreign run reads as absent"
    )
    assert "HTTPException(404" in src
    assert "409" in src, "a non-parked run must be refused with a conflict"
    assert "403" not in src, (
        "a cross-tenant run_id is invisible, not forbidden — a 403 here would "
        "confirm the run exists"
    )

    signature = inspect.signature(resume_run)
    assert "session" in signature.parameters, (
        "the tenant arrives through get_db_session's RLS context, not a param"
    )
    assert "parked" in (resume_run.__doc__ or ""), (
        "the status allow-list must be documented where the handler is read"
    )


def test_worker_park_branch_keeps_the_cancel_guard():
    """A user cancel must win over every terminal write, park included.

    Read as TEXT (path resolved through the package's `__file__`, never a
    repo-root relative path — the build context ships only the tribunal subtree).
    """
    import re
    from pathlib import Path

    from nestor_pulse_sdk.runs import worker as worker_module

    src = Path(worker_module.__file__).read_text(encoding="utf-8")

    assert "park_state_inconsistent" in src, (
        "a park branch whose facts do not resolve to 'parked' must be logged by "
        "name — never silently overridden (DEC-6)"
    )
    assert "terminal_state(" in src, "the worker must compute, not hardcode, the status"

    # The LEADING QUOTE is load-bearing: it matches the SQL string literals and
    # not the module docstring's prose mention of the failure UPDATE, which would
    # otherwise inflate the count by one and make this assertion unsatisfiable.
    terminal_updates = len(re.findall(r'"UPDATE run SET status=', src))
    guards = len(re.findall(r"AND status='running'", src))
    assert terminal_updates >= 5, (
        "expected the four pre-existing terminal UPDATEs plus the new park one; "
        f"found {terminal_updates}"
    )
    assert guards >= terminal_updates, (
        f"every terminal UPDATE needs its cancel guard: {terminal_updates} "
        f"UPDATEs but only {guards} `AND status='running'` clauses"
    )

    park_region = src.split('result.get("parked")', 1)[1].split(
        "The runner returns the synthesized report text", 1
    )[0]
    # COMMENTS ARE STRIPPED FIRST. The park branch documents, in prose, that it
    # deliberately does not stamp a completion time — and that sentence contains
    # the very token this assertion looks for. Asserting on code only is what
    # makes this test about behaviour rather than about wording.
    park_code = "\n".join(
        line for line in park_region.splitlines()
        if not line.lstrip().startswith("#")
    )
    assert "completed_at" not in park_code, (
        "a parked run has NOT completed; stamping completed_at would make the "
        "intake card render a duration for a run that has not finished"
    )




# ===========================================================================
# LAYER B — REAL POSTGRES, AS A NON-SUPERUSER.
#
# READ THIS BEFORE TRUSTING A GREEN RUN.
#
# These tests do NOT use the testcontainers `async_engine` fixture, and that is
# a deliberate correction rather than a shortcut. Two measured facts, both
# recorded in `tribunal/cloudbuild.test.yaml`'s own header (commit b479499):
#
#   1. The testcontainers fixture DOES NOT START in the full suite —
#      `"host" network_mode is incompatible with port_bindings`. Every test
#      depending on it skips, and the build still exits 0. A green full suite
#      proves nothing about any DB-backed path.
#   2. Even if it started, testcontainers' Postgres runs as SUPERUSER, and RLS
#      is bypassed UNCONDITIONALLY for a superuser. A cross-tenant denial test
#      written against it would PASS WITH A COMPLETELY BROKEN POLICY — which is
#      precisely the bug plan 15.2-01 found, where four denial tests had never
#      once executed under a role RLS binds to.
#
# So these use the `DATABASE_URL` + non-superuser idiom of
# `test_rls_isolation.py`: they SKIP CLEANLY when no DSN is configured, they
# SKIP LOUDLY when the DSN is a superuser (never a false green), and they
# EXECUTE FAITHFULLY against the migrated, non-superuser `app_user` DSN that
# `cloudbuild.test-rls.yaml` provides — the only harness in this repo where
# FORCE ROW LEVEL SECURITY genuinely binds the connecting role.
#
# A SKIP HERE IS NOT A PASS. See the SUMMARY: no COMMITTED gate config runs
# this file against a DSN today (both candidate configs are owned by other
# plans), so these were proven by an explicit non-superuser Cloud Build run and
# the standing-gate gap is recorded in `deferred-items.md` for 15.2-17.
# ===========================================================================


def _require_database_url() -> str:
    """The DSN, or a clean skip. Same contract as test_rls_isolation.py."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip(
            "DATABASE_URL not set — these are real-Postgres tests. They run "
            "faithfully only under a NON-SUPERUSER DSN (the app_user harness of "
            "tribunal/cloudbuild.test-rls.yaml). A skip here is NOT a pass."
        )
    return url


@pytest.fixture
async def live_engine():
    """Async engine bound to a real, migrated Postgres."""
    url = _require_database_url()
    sa = pytest.importorskip("sqlalchemy.ext.asyncio")
    engine = sa.create_async_engine(url, echo=False, future=True)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def require_non_superuser(live_engine):
    """Skip LOUDLY unless the connected role is a NON-superuser.

    RLS is bypassed unconditionally for a Postgres superuser, so the
    cross-tenant assertion below would pass even with a completely broken
    policy. This guard makes the file self-excluding on a superuser DSN — a
    loud skip, never a false green (threat T-15.2-07 / T-15.2-122).
    """
    from sqlalchemy import text as sql

    async with live_engine.connect() as conn:
        is_super = (
            await conn.execute(sql("SELECT current_setting('is_superuser')"))
        ).scalar_one()
    if str(is_super).lower() in ("on", "true", "yes", "1"):
        pytest.skip(
            "connected as a Postgres SUPERUSER — RLS is bypassed, so this "
            "cross-tenant denial test would be a false green. Runs faithfully "
            "only under a non-superuser DSN (tribunal/cloudbuild.test-rls.yaml)."
        )


@pytest.fixture
async def two_orgs(live_engine):
    """Two ephemeral orgs, CASCADE-cleaned at teardown so the suite reruns."""
    from sqlalchemy import text as sql

    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    async with live_engine.begin() as conn:
        await conn.execute(
            sql(
                "INSERT INTO org (id, name, slug, retention_days) "
                "VALUES (:id, :name, :slug, 180)"
            ),
            [
                {"id": tenant_a, "name": "Tenant A (resume test)",
                 "slug": f"resume-a-{tenant_a.hex[:8]}"},
                {"id": tenant_b, "name": "Tenant B (resume test)",
                 "slug": f"resume-b-{tenant_b.hex[:8]}"},
            ],
        )
    yield tenant_a, tenant_b
    async with live_engine.begin() as conn:
        await conn.execute(
            sql("DELETE FROM org WHERE id IN (:a, :b)"),
            {"a": tenant_a, "b": tenant_b},
        )


def _sessionmaker(live_engine):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    return async_sessionmaker(live_engine, class_=AsyncSession, expire_on_commit=False)


async def _seed_run(live_engine, tenant_id, *, status):
    """A project + a run in `status`, both written under the tenant's RLS context."""
    from nestor_pulse_sdk.db.models import Project, Run
    from nestor_pulse_sdk.db.rls import set_tenant_context

    project_id = uuid.uuid4()
    run_id = uuid.uuid4()
    async with _sessionmaker(live_engine)() as session:
        async with session.begin():
            await set_tenant_context(session, tenant_id)
            session.add(Project(
                id=project_id, tenant_id=tenant_id, name="Resume test project",
            ))
            session.add(Run(
                id=run_id, tenant_id=tenant_id, project_id=project_id,
                engine="tribunal", brief="brief", status=status,
                idempotency_key=uuid.uuid4(), worker_id="worker-1",
                error_message="[park#1] parked earlier",
            ))
    return run_id


async def _read_run(live_engine, tenant_id, run_id):
    """(status, worker_id, error_message) read back under the tenant's context."""
    from sqlalchemy import text as sql

    from nestor_pulse_sdk.db.rls import set_tenant_context

    async with _sessionmaker(live_engine)() as session:
        async with session.begin():
            await set_tenant_context(session, tenant_id)
            return (await session.execute(
                sql("SELECT status, worker_id, error_message FROM run WHERE id = :r"),
                {"r": str(run_id)},
            )).first()


async def test_resume_cross_tenant_run_is_404(
    live_engine, require_non_superuser, two_orgs
):
    """THE HIGH-SEVERITY PROOF (T-15.2-122).

    Tenant B drives the handler against tenant A's parked run. RLS hides the
    row, `scalar_one_or_none()` returns None, and the handler answers EXACTLY
    404 — never "forbidden", which would confirm the run exists.
    """
    from fastapi import HTTPException

    from nestor_pulse_sdk.db.rls import set_tenant_context
    from nestor_pulse_sdk.runs.api import resume_run

    tenant_a, tenant_b = two_orgs
    run_id = await _seed_run(live_engine, tenant_a, status="parked")

    async with _sessionmaker(live_engine)() as session:
        async with session.begin():
            await set_tenant_context(session, tenant_b)
            with pytest.raises(HTTPException) as ei:
                await resume_run(run_id, session=session)
    assert ei.value.status_code == 404, (
        "a cross-tenant run must be INVISIBLE (404), never forbidden — a "
        "distinguishable refusal would confirm the run exists"
    )

    # THE ASSERTION ON THE ROW, not just on the exception: the denied call must
    # have mutated nothing.
    row = await _read_run(live_engine, tenant_a, run_id)
    assert row is not None, "tenant A must still see its own run"
    assert row[0] == "parked", "tenant A's run must still be parked after the denial"
    assert row[1] == "worker-1", "the denied call must not have cleared worker_id"


@pytest.mark.parametrize("wrong_status", [
    "queued", "running", "completed", "completed_degraded", "failed", "cancelled",
])
async def test_resume_wrong_state_is_409_and_mutates_nothing(
    live_engine, require_non_superuser, two_orgs, wrong_status
):
    """The status allow-list is EXACTLY `parked` — proven closed, not sampled.

    Parametrised over every other DB-legal terminal and in-flight status, so the
    verb cannot re-queue finished, running or cancelled work.
    """
    from fastapi import HTTPException

    from nestor_pulse_sdk.db.rls import set_tenant_context
    from nestor_pulse_sdk.runs.api import resume_run

    tenant_a, _ = two_orgs
    run_id = await _seed_run(live_engine, tenant_a, status=wrong_status)

    async with _sessionmaker(live_engine)() as session:
        async with session.begin():
            await set_tenant_context(session, tenant_a)
            with pytest.raises(HTTPException) as ei:
                await resume_run(run_id, session=session)
    assert ei.value.status_code == 409, (
        f"resuming a {wrong_status!r} run must be EXACTLY 409 — a 404 would be a "
        "lie about a run the caller can see, and a 200 would re-queue work that "
        "is already finished or already moving"
    )

    row = await _read_run(live_engine, tenant_a, run_id)
    assert row[0] == wrong_status, "a refused resume must mutate nothing"


async def test_resume_parked_run_requeues_the_same_run(
    live_engine, require_non_superuser, two_orgs
):
    """The SAME run is re-queued — a new run would re-charge the whole brief."""
    from nestor_pulse_sdk.db.rls import set_tenant_context
    from nestor_pulse_sdk.runs.api import resume_run

    tenant_a, _ = two_orgs
    run_id = await _seed_run(live_engine, tenant_a, status="parked")

    async with _sessionmaker(live_engine)() as session:
        async with session.begin():
            await set_tenant_context(session, tenant_a)
            response = await resume_run(run_id, session=session)

    assert response.status == "queued"
    assert response.id == run_id, (
        "the SAME run must be re-queued — a new run id would mean every "
        "deep-research angle is dispatched and billed again"
    )

    row = await _read_run(live_engine, tenant_a, run_id)
    assert row[0] == "queued"
    assert row[1] is None, "worker_id must be cleared so the worker can re-claim it"
    assert row[2] is None, "the stale park reason must not survive the resume"
