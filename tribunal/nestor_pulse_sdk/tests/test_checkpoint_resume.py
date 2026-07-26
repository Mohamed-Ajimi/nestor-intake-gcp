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

Cloud Build gate:
    gcloud builds submit tribunal --config=tribunal/cloudbuild.test-engine.yaml \
        --project="$GOOGLE_PROJECT"

This file is ALREADY pre-listed in `cloudbuild.test-engine.yaml` by plan 15.2-02,
so no config edit is ever needed to run it.
"""
from __future__ import annotations

import json
import logging

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
