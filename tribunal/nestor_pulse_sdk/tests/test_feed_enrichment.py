"""The D15 live feed: no lost rows, bounded rows, and a drill-down that resolves.

WHY THIS FILE EXISTS
--------------------
Two defects, one file.

**F9 -- rows vanish under fan-out.** `set_stage` merges with `||`
(`stages.py:117-124`), and `||` REPLACES the whole stage key. So every caller hands
it the COMPLETE item list built from its own snapshot. That is safe today only
because there is exactly one writer per stage (`pipeline.py:453-465`). The 15.2
engine runs N concurrent agents inside a single stage, and with the current pattern
each agent's write replaces the others': last writer wins, and rows the operator
watched appear and then disappear. `StageFeed` makes one object the OWNER of a
stage's list; these tests pin that N concurrent mutators produce N rows.

**F4 -- the drill-down had no source.** `StageDetailItem.audit_id`
(`schemas.py:167`) targets `GET /{run_id}/audit/{audit_id}` (`runs/api.py:885`), and
the frontend already renders it -- but the atomic `audited.*` methods generated the
id internally and threw it away, so a workshop / skeptic / gate row had no way to
carry one. The additive `audit_out` out-param hands it back. The last test here
closes the loop: an LLM call's id reaches a feed row that validates as a
`StageDetailItem`.

Also pinned: `task_prompt` truncation (Pitfall 12 -- `stage_detail` is re-read on
every SSE poll and the angle queries are ~2.6 KB each), `Decimal` cost reaching
JSONB as exact TEXT, enum clamping on caller-supplied status (ASVS V5), overflow
stated in WORDS rather than silently dropped, inertness after `close()` so a late
row cannot drag `run.current_stage` backwards, and the exception-safety contract
`StageFeed` inherits from `set_stage`.

THIS FILE MAKES ZERO LLM CALLS, OPENS NO DATABASE, USES NO MOCKING LIBRARY AND
NEEDS NO API KEY. The `set_stage` writer is a hand-written duck-typed recorder; both
provider clients are hand-written duck-typed fakes in the
`test_gate_replay.py::_AnswerKeyGateAudited` style. Nothing here is marked `live`,
nothing can flake on the network, and nothing spends -- which matters twice over
while the Anthropic account sits at its monthly cap (resets 2026-08-01).

Cloud Build invocation:
    gcloud builds submit tribunal --config=tribunal/cloudbuild.test-engine.yaml \
        --project="$GOOGLE_PROJECT"
"""
from __future__ import annotations

import asyncio
import json
import uuid
from decimal import Decimal
from typing import Any

import pytest

from nestor_pulse_sdk.runs import stage_feed as stage_feed_mod
from nestor_pulse_sdk.runs.schemas import StageDetail, StageDetailItem
from nestor_pulse_sdk.runs.stage_feed import StageFeed, truncate_task_prompt

# Every test uses a near-zero debounce so the suite stays fast and cannot flake on
# wall-clock. The PRODUCTION default (0.75s) is asserted separately, in
# test_tunable_defaults_are_the_documented_ones, so shrinking it here cannot hide a
# change to the shipped value.
_FAST = 0.01


# ---------------------------------------------------------------------------
# The recorder. Duck-typed to `runs.stages.set_stage`'s signature -- it is a
# stand-in for the DB WRITE only. Everything between a StageFeed mutation and this
# object (ownership, locking, debouncing, normalisation, snapshotting) is
# production code doing its real job.
# ---------------------------------------------------------------------------
class _Recorder:
    def __init__(self, *, raises: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self.raises = raises
        #: Overlap detection: the lock in _write_locked is what keeps a slow write
        #: from being overtaken by a newer one, and overlap is its observable
        #: signature. See test_concurrent_writers_do_not_lose_rows.
        self.in_flight = 0
        self.max_in_flight = 0

    @property
    def call_count(self) -> int:
        return len(self.calls)

    @property
    def last(self) -> dict[str, Any]:
        assert self.calls, "the recorder was never called -- nothing was written"
        return self.calls[-1]

    @property
    def last_items(self) -> list[dict[str, Any]]:
        return self.last["detail"]["items"]

    async def __call__(self, run_id, tenant_id, stage_key, detail=None):
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            # Yield at least once so an overlapping write would actually interleave
            # here rather than being hidden by a synchronous fast path.
            await asyncio.sleep(0)
            if self.raises:
                raise RuntimeError("recorder refuses to write")
            self.calls.append(
                {
                    "run_id": run_id,
                    "tenant_id": tenant_id,
                    "stage_key": stage_key,
                    # Deep-copied through JSON: the feed hands its snapshot out and
                    # keeps mutating its own list, so a shallow reference would let
                    # later rows leak into an earlier recorded "snapshot" and make
                    # these assertions lie.
                    "detail": json.loads(json.dumps(detail)),
                }
            )
        finally:
            self.in_flight -= 1


def _feed(
    recorder: _Recorder,
    *,
    stage_key: str = "workshop",
    debounce_s: float = _FAST,
) -> StageFeed:
    # debounce_s is an EXPLICIT parameter, not swept up by **kwargs: a **kwargs
    # passthrough here collided with the default below and raised "got multiple
    # values for keyword argument 'debounce_s'".
    return StageFeed(
        run_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        stage_key=stage_key,
        writer=recorder,
        debounce_s=debounce_s,
    )


# ---------------------------------------------------------------------------
# 1. F9 -- THE REGRESSION THIS CLASS EXISTS FOR
# ---------------------------------------------------------------------------
async def test_concurrent_writers_do_not_lose_rows():
    """20 concurrent mutators on one stage produce 20 rows, not one.

    THE PROPERTY PINNED. `set_stage`'s `||` replaces the whole stage key, so the
    pre-15.2 pattern -- every agent building and writing its OWN complete item list
    -- means the last writer's snapshot wins and the other 19 rows are gone from
    `run.stage_detail`. Single OWNERSHIP is the fix: the list lives in one object,
    every agent mutates its own row through a handle, and the snapshot written is
    always the whole roster.

    The `asyncio.Lock`'s own observable contribution is write SERIALISATION -- it is
    held across the awaited write in `_write_locked`, so a slow write cannot be
    overtaken by a newer one and re-lose rows. `recorder.max_in_flight == 1` is that
    property; it is asserted here and it is what fails if the lock is removed.
    """
    rec = _Recorder()
    async with _feed(rec) as feed:
        handles = await feed.declare([f"agent-{i}" for i in range(20)])
        assert handles == list(range(20))

        await asyncio.gather(
            *(feed.update(h, status="done", facts=h) for h in handles)
        )
        await feed.flush()

    items = rec.last_items
    assert len(items) == 20, (
        f"expected 20 rows, got {len(items)} -- rows were lost to last-writer-wins, "
        "which is exactly the F9 defect StageFeed exists to prevent"
    )
    assert [it["facts"] for it in items] == list(range(20))
    assert all(it["status"] == "done" for it in items)
    assert rec.max_in_flight == 1, (
        "two writes overlapped -- the lock is not held across the awaited write, so "
        "a slow snapshot can be overtaken by a newer one"
    )


# ---------------------------------------------------------------------------
# 2. Row order is the roster's order, not the event loop's
# ---------------------------------------------------------------------------
async def test_declare_order_is_input_order():
    """declare() fixes order up front so what the operator sees is deterministic."""
    rec = _Recorder()
    names = ["alpha", "beta", "gamma", "delta"]
    async with _feed(rec) as feed:
        handles = await feed.declare(names)
        assert handles == [0, 1, 2, 3]
        # Update in a DELIBERATELY scrambled order: row position must not follow it.
        await asyncio.gather(
            feed.update(2, status="done"),
            feed.update(0, status="running"),
            feed.update(3, status="failed"),
            feed.update(1, status="done"),
        )
        await feed.flush()

    assert [it["name"] for it in rec.last_items] == names
    assert [it["status"] for it in rec.last_items] == [
        "running", "done", "done", "failed",
    ]


# ---------------------------------------------------------------------------
# 3. Debounce -- many mutations, few writes
# ---------------------------------------------------------------------------
async def test_writes_are_debounced():
    """30 rapid mutations do NOT become 30 UPDATEs, and nothing is lost.

    Asserted as an INEQUALITY on purpose: an exact write count would be a
    wall-clock assertion and would flake on a loaded build machine.
    """
    rec = _Recorder()
    async with _feed(rec, debounce_s=0.05) as feed:
        handles = await feed.declare([f"agent-{i}" for i in range(30)])
        for h in handles:
            await feed.update(h, status="done", facts=h)
            await asyncio.sleep(0)  # let the loop interleave, as it would in prod
        await feed.flush()

    assert rec.call_count < 30, (
        f"{rec.call_count} writes for 30 mutations -- the debounce is not coalescing"
    )
    items = rec.last_items
    assert len(items) == 30
    assert [it["facts"] for it in items] == list(range(30))
    assert all(it["status"] == "done" for it in items)


# ---------------------------------------------------------------------------
# 4. Pitfall 12 -- task_prompt is bounded
# ---------------------------------------------------------------------------
async def test_task_prompt_is_truncated():
    """A 2.6 KB prompt reaches stage_detail as 401 characters, visibly cut.

    `stage_detail` is read in full on every SSE poll of a running brief. The full
    prompt is not lost -- it is reachable through the tenant-scoped
    GET /{run_id}/audit/{audit_id} the row's audit_id points at.
    """
    long_prompt = "N" * 2600
    rec = _Recorder()
    async with _feed(rec) as feed:
        h = await feed.add("angle-1", task_prompt=long_prompt)
        await feed.update(h, status="running")
        await feed.flush()

    stored = rec.last_items[0]["task_prompt"]
    assert len(stored) == 401, f"expected 400 chars + ellipsis, got {len(stored)}"
    assert stored.endswith("…")
    # default=str because the recorded call carries the run/tenant UUIDs alongside
    # the (already JSON-round-tripped) detail; the assertion is about the payload
    # text, not about the ids being serialisable.
    assert long_prompt not in json.dumps(rec.last, default=str), (
        "the untruncated prompt reached the snapshot -- stage_detail will inflate on "
        "every poll (Pitfall 12)"
    )

    # The shared helper other plans reuse rather than re-truncating.
    assert truncate_task_prompt(None) is None
    assert truncate_task_prompt("") is None
    assert truncate_task_prompt("   ") is None
    assert truncate_task_prompt("short") == "short"
    assert truncate_task_prompt("abcdef", 3) == "abc…"


# ---------------------------------------------------------------------------
# 5. The feed POPULATES the existing contract -- it does not invent one
# ---------------------------------------------------------------------------
async def test_emitted_rows_validate_against_the_declared_schema():
    """Every emitted row round-trips through runs/schemas.py, unmodified.

    This is the proof that plan 15.2-03 populates the D15 model that plan 15-01
    already shipped (`StageDetail` / `StageDetailItem` / `StageRetry` /
    `StageSummary`) instead of building a second, subtly-different feed model.
    `runs/schemas.py` is NOT in this plan's files_modified.
    """
    rec = _Recorder()
    async with _feed(rec) as feed:
        h = await feed.add("skeptic-3", task_prompt="check this claim")
        await feed.update(
            h,
            status="done",
            cost_usd=Decimal("0.0123"),
            facts=7,
            audit_id=str(uuid.uuid4()),
            retry={"attempt": 2, "max": 3, "wait_s": 1.5},
        )
        await feed.set_summary(duration_s=12.5, actions=4, items_read=91,
                               cost_usd=Decimal("1.25"))
        await feed.flush()

    detail = StageDetail.model_validate(rec.last["detail"])
    item = detail.items[0]
    assert item.name == "skeptic-3"
    assert item.status == "done"
    assert item.task_prompt == "check this claim"
    assert item.cost_usd == "0.0123"
    assert item.facts == 7
    assert uuid.UUID(item.audit_id)
    assert item.retry is not None and item.retry.attempt == 2
    assert detail.summary is not None
    assert detail.summary.duration_s == 12.5
    assert detail.summary.actions == 4
    assert detail.summary.items_read == 91
    assert detail.summary.cost_usd == "1.25"


# ---------------------------------------------------------------------------
# 6. R5 -- a retried call reads as retrying, not as stalled
# ---------------------------------------------------------------------------
async def test_retry_row_uses_the_existing_retry_literal():
    """mark_retry uses the `"retry"` status literal schemas.py:162 already declares.

    Zero frontend work: `toStageRows` already flattens the retry sub-state. Without
    this the operator sees a row sitting at `running` with no explanation while a
    backoff sleeps, which is indistinguishable from a hang.
    """
    rec = _Recorder()
    async with _feed(rec) as feed:
        h = await feed.add("provider-call")
        await feed.mark_retry(h, attempt=2, max=3, wait_s=1.5)
        await feed.flush()

    item = rec.last_items[0]
    assert item["status"] == "retry"
    assert item["retry"] == {"attempt": 2, "max": 3, "wait_s": 1.5}
    parsed = StageDetailItem.model_validate(item)
    assert parsed.status == "retry"
    assert parsed.retry is not None and parsed.retry.wait_s == 1.5


# ---------------------------------------------------------------------------
# 7. No null keys -- the JSONB stays small and legacy rows stay byte-identical
# ---------------------------------------------------------------------------
async def test_none_fields_are_omitted_from_the_snapshot():
    rec = _Recorder()
    async with _feed(rec) as feed:
        await feed.add("bare-row")
        await feed.flush()

    item = rec.last_items[0]
    assert item == {"name": "bare-row", "status": "pending"}, (
        f"unset fields leaked into the row as nulls: {item}"
    )


# ---------------------------------------------------------------------------
# 8. ASVS V5 -- an out-of-vocabulary status is clamped, never passed through
# ---------------------------------------------------------------------------
async def test_unknown_status_is_clamped(caplog):
    """A bogus status becomes `pending` (+ a WARNING), never an invalid literal.

    Passing it through would fail response validation at the API edge, far away
    from the code that produced it -- and would take the whole run's metrics
    response down with it rather than one row.
    """
    rec = _Recorder()
    with caplog.at_level("WARNING"):
        async with _feed(rec) as feed:
            h = await feed.add("agent-x")
            await feed.update(h, status="exploding")
            await feed.flush()

    item = rec.last_items[0]
    assert item["status"] == "pending"
    assert StageDetailItem.model_validate(item).status == "pending"
    # Clamped LOUDLY, not silently (cross-cutting rule 6).
    assert any("exploding" in r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------------------
# 9. Money is TEXT in JSONB -- exact cents, never a float
# ---------------------------------------------------------------------------
async def test_cost_is_serialised_as_a_string():
    """StageDetailItem.cost_usd is `str | None`; float() would lose exact cents."""
    rec = _Recorder()
    async with _feed(rec) as feed:
        h = await feed.add("agent-cost")
        await feed.update(h, cost_usd=Decimal("0.0123"))
        await feed.flush()

    stored = rec.last_items[0]["cost_usd"]
    assert isinstance(stored, str)
    assert stored == "0.0123", f"exact Decimal text lost: {stored!r}"


# ---------------------------------------------------------------------------
# 10. Overflow is STATED, not silently dropped
# ---------------------------------------------------------------------------
async def test_overflow_is_stated_in_words_not_silently_dropped(monkeypatch, caplog):
    """Past the row cap the feed says so IN the feed (cross-cutting rule 6).

    Silently truncating the list would show the operator a complete-looking feed
    that is missing agents -- the "silent green" this phase exists to eliminate.
    """
    monkeypatch.setattr(stage_feed_mod, "_FEED_MAX_ITEMS", 3)
    rec = _Recorder()
    with caplog.at_level("WARNING"):
        async with _feed(rec) as feed:
            await feed.declare([f"agent-{i}" for i in range(9)])
            await feed.flush()

    items = rec.last_items
    assert len(items) == 4, f"3 rows + 1 overflow row expected, got {len(items)}"
    overflow = items[-1]
    assert "more agent" in overflow["name"]
    assert "6" in overflow["name"], f"dropped count not stated: {overflow['name']!r}"
    assert StageDetailItem.model_validate(overflow)
    assert any("row cap" in r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------------------
# 11. A closed feed is INERT -- current_stage never moves backwards
# ---------------------------------------------------------------------------
async def test_writes_after_close_are_ignored(caplog):
    """`set_stage` re-pins run.current_stage on EVERY write (stages.py:119).

    So a row arriving after the pipeline advanced would drag the operator's view
    back onto a finished stage. After close() the feed is inert -- and says so.
    """
    rec = _Recorder()
    feed = _feed(rec)
    h = await feed.add("agent-1")
    await feed.close()
    frozen = rec.call_count
    assert frozen >= 1, "close() must flush the pending snapshot before going inert"

    with caplog.at_level("WARNING"):
        await feed.update(h, status="done")     # must not raise
        await feed.add("late-agent")
        await feed.mark_retry(h, attempt=1, max=2, wait_s=0.1)
        await feed.set_summary(actions=1)
        await feed.flush()

    assert rec.call_count == frozen, "a post-close mutation reached the writer"
    assert any("after close" in r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------------------
# 12. A feed failure never breaks the pipeline reporting through it
# ---------------------------------------------------------------------------
async def test_writer_exception_never_propagates(caplog):
    """Inherits set_stage's contract (stages.py:125-126), and logs rather than dies."""
    rec = _Recorder(raises=True)
    with caplog.at_level("WARNING"):
        async with _feed(rec) as feed:
            handles = await feed.declare(["a", "b"])
            await feed.update(handles[0], status="done")
            await feed.flush()
            # Still usable after a failed write -- not wedged.
            await feed.update(handles[1], status="failed")
            await feed.flush()

    assert rec.call_count == 0, "the raising recorder should have recorded nothing"
    assert any(
        "StageFeed write failed" in r.getMessage() for r in caplog.records
    ), "a swallowed write failure must still be logged in words"


# ---------------------------------------------------------------------------
# 12b. The shipped tunable defaults (the August retune reads these)
# ---------------------------------------------------------------------------
def test_tunable_defaults_are_the_documented_ones():
    """Pinned separately because every test above overrides the debounce.

    Shrinking `_FAST` must not be able to hide a change to what production runs
    with. All three are NESTOR_TRIBUNAL_* env-overridable, so August retunes
    without a code change.
    """
    assert stage_feed_mod._FEED_DEBOUNCE_S == 0.75
    assert stage_feed_mod._FEED_PROMPT_MAX == 400
    assert stage_feed_mod._FEED_MAX_ITEMS == 200


# ---------------------------------------------------------------------------
# 12c. StageFeed delegates -- it is not a second writer
# ---------------------------------------------------------------------------
def test_stage_feed_delegates_to_set_stage_and_owns_no_session():
    """The tenant boundary lives in ONE place: runs.stages.set_stage.

    T-15.2-32. StageFeed must not open a session, must not call
    set_tenant_context itself and must not issue SQL -- a second writer is a second
    chance to get RLS scoping wrong, which is the defect class this project's
    security constraint names explicitly.
    """
    import inspect

    src = inspect.getsource(stage_feed_mod)
    assert "from nestor_pulse_sdk.runs.stages import set_stage" in src
    for forbidden in ("sessionmaker", "set_tenant_context", "UPDATE run", "text("):
        assert forbidden not in src, (
            f"stage_feed.py contains {forbidden!r} -- it must delegate every write "
            "to set_stage rather than talking to the database itself"
        )

    # The default writer IS set_stage (not a copy, not a wrapper).
    from nestor_pulse_sdk.runs.stages import set_stage as canonical

    feed = StageFeed(
        run_id=uuid.uuid4(), tenant_id=uuid.uuid4(), stage_key="merge"
    )
    assert feed._writer is canonical


# ===========================================================================
# THE AUDIT HALF (Task 3) -- F4: audit_out hands back the id of the call made
#
# Hand-written duck-typed fakes in the test_gate_replay.py::_AnswerKeyGateAudited
# style. No mocking library, no network, no DB, no API key, no spend.
# ===========================================================================


class _FakeAnthropicUsage:
    def __init__(self) -> None:
        self.input_tokens = 1200
        self.output_tokens = 340
        self.cache_read_input_tokens = 100
        self.cache_creation_input_tokens = 50


class _FakeAnthropicResponse:
    def __init__(self) -> None:
        self.usage = _FakeAnthropicUsage()
        self.content: list[Any] = []


class _RecordingAnthropicMessages:
    def __init__(self, parent: "_RecordingAnthropic") -> None:
        self._parent = parent

    async def create(self, **kwargs: Any):
        self._parent.last_kwargs = dict(kwargs)
        self._parent.calls += 1
        return _FakeAnthropicResponse()


class _RecordingAnthropic:
    """Records the EXACT kwargs dict forwarded to the provider SDK.

    That dict is the HTTP-400 trap: `anthropic_messages` splats `**kwargs` straight
    into `messages.create(**kwargs)`, so an unknown key there is a request the API
    rejects. `audit_out` must never appear in it.
    """

    def __init__(self) -> None:
        self.messages = _RecordingAnthropicMessages(self)
        self.last_kwargs: dict[str, Any] = {}
        self.calls = 0


class _FakeGeminiUsage:
    def __init__(self) -> None:
        self.prompt_token_count = 800
        self.candidates_token_count = 210


class _FakeGeminiResponse:
    def __init__(self) -> None:
        self.usage_metadata = _FakeGeminiUsage()
        self.text = ""


class _RecordingGeminiModels:
    def __init__(self, parent: "_RecordingGemini") -> None:
        self._parent = parent

    def generate_content(self, *, model: str, contents: Any, **kwargs: Any):
        self._parent.last_kwargs = dict(kwargs)
        self._parent.last_model = model
        self._parent.calls += 1
        return _FakeGeminiResponse()


class _RecordingGemini:
    def __init__(self) -> None:
        self.models = _RecordingGeminiModels(self)
        self.last_kwargs: dict[str, Any] = {}
        self.last_model: str | None = None
        self.calls = 0


class _RecordingAuditWriter:
    """Records every write_full_row call. No DB."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    async def get_prev_hash_and_seq(self, run_id, tenant_id):
        return ("0" * 64, len(self.rows))

    async def write_full_row(self, **kwargs: Any) -> None:
        self.rows.append(dict(kwargs))

    async def insert_placeholder(self, *a, **kw) -> None:
        return None

    async def finalize_row(self, *a, **kw) -> None:
        return None


class _NoopGcs:
    async def upload_audit_body(self, **kwargs: Any) -> str:
        return "gs://fake-bucket/audit/body.json"


class _StubHashChain:
    @staticmethod
    def link_hash(prev_hash: str, payload: Any) -> str:
        # Deterministic and payload-sensitive, so test 16's "identical modulo
        # per-call ids" comparison is meaningful rather than trivially true.
        import hashlib

        return hashlib.sha256(f"{prev_hash}|{payload!r}".encode()).hexdigest()


class _StubCostTable:
    @staticmethod
    def compute(**kwargs: Any) -> Decimal:
        return Decimal("0.0123")


def _audited(anthropic_client=None, gemini_client=None):
    """Build a real AuditedLLMClient over fakes -- the production method bodies run."""
    from nestor_pulse_sdk.audit.audited_llm_client import AuditedLLMClient

    writer = _RecordingAuditWriter()
    client = AuditedLLMClient(
        anthropic_client if anthropic_client is not None else _RecordingAnthropic(),
        gemini_client if gemini_client is not None else _RecordingGemini(),
        writer,
        _StubHashChain,
        _StubCostTable,
        _NoopGcs(),
    )
    return client, writer


_IDS = ("run_id", "tenant_id", "model")


# ---------------------------------------------------------------------------
# 13/14. audit_out receives the id of the call that was just made
# ---------------------------------------------------------------------------
async def test_audit_out_receives_the_audit_id_anthropic():
    provider = _RecordingAnthropic()
    audited, writer = _audited(anthropic_client=provider)
    out: dict[str, Any] = {}

    resp = await audited.anthropic_messages(
        run_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        model="claude-sonnet-4-5",
        max_tokens=64,
        messages=[{"role": "user", "content": "hi"}],
        audit_out=out,
    )

    assert resp is not None
    assert uuid.UUID(out["audit_id"])          # a real, parseable UUID string
    assert isinstance(out["audit_id"], str) and len(out["audit_id"]) == 36
    assert out["cost_usd"] == "0.0123" and isinstance(out["cost_usd"], str)
    assert out["provider"] == "anthropic"
    assert out["model"] == "claude-sonnet-4-5"
    assert isinstance(out["duration_ms"], int)
    assert len(writer.rows) == 1


async def test_audit_out_receives_the_audit_id_gemini():
    provider = _RecordingGemini()
    audited, writer = _audited(gemini_client=provider)
    out: dict[str, Any] = {}

    await audited.gemini_generate(
        run_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        model="gemini-2.5-flash",
        contents="hello",
        audit_out=out,
    )

    assert uuid.UUID(out["audit_id"])
    assert out["cost_usd"] == "0.0123" and isinstance(out["cost_usd"], str)
    assert out["provider"] == "google"
    assert out["model"] == "gemini-2.5-flash"
    assert isinstance(out["duration_ms"], int)
    assert len(writer.rows) == 1


# ---------------------------------------------------------------------------
# 15. THE HTTP-400 TRAP -- audit_out never reaches the provider SDK
# ---------------------------------------------------------------------------
async def test_audit_out_never_reaches_the_provider_sdk():
    """kwargs is forwarded VERBATIM to the provider; an unknown key is a 400.

    This is why `audit_out` is an explicit keyword-only parameter declared BEFORE
    `**kwargs` instead of being fished out of kwargs.
    """
    anth = _RecordingAnthropic()
    audited_a, _ = _audited(anthropic_client=anth)
    await audited_a.anthropic_messages(
        run_id=uuid.uuid4(), tenant_id=uuid.uuid4(), model="claude-sonnet-4-5",
        max_tokens=64, messages=[{"role": "user", "content": "hi"}],
        audit_out={},
    )
    assert anth.calls == 1
    assert "audit_out" not in anth.last_kwargs, (
        f"audit_out was forwarded to the Anthropic SDK: {sorted(anth.last_kwargs)}"
    )
    assert "max_tokens" in anth.last_kwargs   # positive control: kwargs DO flow

    gem = _RecordingGemini()
    audited_g, _ = _audited(gemini_client=gem)
    await audited_g.gemini_generate(
        run_id=uuid.uuid4(), tenant_id=uuid.uuid4(), model="gemini-2.5-flash",
        contents="hello", config={"temperature": 0}, audit_out={},
    )
    assert gem.calls == 1
    assert "audit_out" not in gem.last_kwargs, (
        f"audit_out was forwarded to the Gemini SDK: {sorted(gem.last_kwargs)}"
    )
    assert "config" in gem.last_kwargs        # positive control


# ---------------------------------------------------------------------------
# 16. THE ADDITIVE PROOF -- the audit row is unchanged, with or without audit_out
# ---------------------------------------------------------------------------
async def test_audit_out_is_optional_and_omitting_it_changes_nothing():
    """The persisted audit row is byte-identical modulo the per-call ids.

    `verify_chain` green is a legal gate (EU AI Act Art. 12, deadline 2026-08-02).
    `audit_out` is populated AFTER write_full_row and is never read back, so it
    writes no new audit field and alters no existing one. `audit_id`, `gcs_uri` and
    `hash` legitimately differ per call (fresh UUID each time), so they are removed
    before comparing; `started_at` is wall-clock and `duration_ms` is a measurement,
    so they are removed too.
    """
    varying = {"audit_id", "gcs_uri", "hash", "started_at", "duration_ms"}
    run_id, tenant_id = uuid.uuid4(), uuid.uuid4()
    call = dict(
        run_id=run_id, tenant_id=tenant_id, model="claude-sonnet-4-5",
        max_tokens=64, messages=[{"role": "user", "content": "hi"}],
    )

    audited, writer = _audited()
    await audited.anthropic_messages(**call)                 # WITHOUT audit_out
    await audited.anthropic_messages(**call, audit_out={})   # WITH audit_out

    assert len(writer.rows) == 2
    without = {k: v for k, v in writer.rows[0].items() if k not in varying}
    with_out = {k: v for k, v in writer.rows[1].items() if k not in varying}
    # seq advances per row by design; normalise it out of the comparison.
    without.pop("seq", None)
    with_out.pop("seq", None)

    assert without == with_out, (
        "the audit row changed when audit_out was supplied -- audit_out must be "
        f"purely additive.\nwithout={without}\nwith={with_out}"
    )
    assert "audit_out" not in writer.rows[1], (
        "audit_out leaked into the persisted audit row"
    )


# ---------------------------------------------------------------------------
# 17. The drill-down resolves to the row that was actually written
# ---------------------------------------------------------------------------
async def test_audit_out_id_matches_the_persisted_row():
    audited, writer = _audited()
    out: dict[str, Any] = {}
    await audited.anthropic_messages(
        run_id=uuid.uuid4(), tenant_id=uuid.uuid4(), model="claude-sonnet-4-5",
        max_tokens=64, messages=[{"role": "user", "content": "hi"}],
        audit_out=out,
    )
    assert out["audit_id"] == str(writer.rows[0]["audit_id"]), (
        "the id handed to the feed is not the id of the persisted row -- the "
        "drill-down would 404"
    )


# ---------------------------------------------------------------------------
# 18. A malformed audit_out cannot break an LLM call
# ---------------------------------------------------------------------------
async def test_non_dict_audit_out_does_not_break_the_call():
    """Telemetry must never be able to abort the work it describes."""
    for bad in ([], "x", 0, object()):
        audited, writer = _audited()
        resp = await audited.anthropic_messages(
            run_id=uuid.uuid4(), tenant_id=uuid.uuid4(), model="claude-sonnet-4-5",
            max_tokens=64, messages=[{"role": "user", "content": "hi"}],
            audit_out=bad,
        )
        assert resp is not None
        assert len(writer.rows) == 1, "the audit row must still be written"


# ---------------------------------------------------------------------------
# 19. END TO END -- clicking a feed row opens the call behind it (F4)
# ---------------------------------------------------------------------------
async def test_feed_row_carries_the_audit_id_end_to_end():
    """One audited call -> audit_out -> a feed row -> a valid StageDetailItem.

    This is the truth "a feed row's drill-down can open the exact LLM call behind
    it", proved with zero LLM spend. `GET /{run_id}/audit/{audit_id}`
    (`runs/api.py:885`) already exists and is tenant-scoped; what was missing was
    any way for a workshop / skeptic / gate row to LEARN the id.
    """
    audited, writer = _audited()
    out: dict[str, Any] = {}
    rec = _Recorder()

    async with _feed(rec, stage_key="workshop") as feed:
        h = await feed.add("workshop agent 1", status="running",
                           task_prompt="draft three sub-questions")
        await audited.anthropic_messages(
            run_id=uuid.uuid4(), tenant_id=uuid.uuid4(), model="claude-sonnet-4-5",
            max_tokens=64, messages=[{"role": "user", "content": "hi"}],
            audit_out=out,
        )
        await feed.update(
            h, status="done", audit_id=out["audit_id"], cost_usd=out["cost_usd"],
            facts=3,
        )
        await feed.flush()

    item = StageDetailItem.model_validate(rec.last_items[0])
    assert item.status == "done"
    assert uuid.UUID(item.audit_id)
    assert item.audit_id == str(writer.rows[0]["audit_id"])
    assert item.cost_usd == "0.0123"
    assert item.facts == 3
    assert rec.last["stage_key"] == "workshop"
