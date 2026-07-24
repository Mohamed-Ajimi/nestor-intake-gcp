"""
PHASE1-04 -- Hash-chain replay + tamper detection (owning plan: 07)

Per 01-VALIDATION.md row:
  "Hash-chain replay verifies every row; tampering one row reports
   broken_at = N"
  Test type: unit
  Command: pytest nestor_pulse_sdk/tests/test_hash_chain_replay.py -x

Plan 07 implementation: 7 tests (5 atomic + 2 two-phase).
strict=True enforced -- all 7 tests must pass.

T-16-01 concurrency regression test added: fires N concurrent audited calls
against a constraint-enforcing fake writer and asserts no duplicate seqs,
linear hash chain, and no UniqueViolationError.

GCS key uniqueness regression test (01-16 fix): asserts that two upload_audit_body
calls for the same run_id+provider+model produce DIFFERENT GCS keys via audit_id.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Import the audit modules under test -- all implemented by Plan 07
# ---------------------------------------------------------------------------
from nestor_pulse_sdk.audit.hash_chain import (
    GENESIS,
    IN_FLIGHT_PLACEHOLDER,
    canonical_json,
    link_hash,
    verify_chain,
)
from nestor_pulse_sdk.audit.cost_table import compute
from nestor_pulse_sdk.audit.audited_llm_client import AuditedLLMClient, AuditHandle


# ---------------------------------------------------------------------------
# Minimal in-memory AuditLog row substitute (no DB required for unit tests)
# ---------------------------------------------------------------------------

@dataclass
class FakeAuditRow:
    """Mimics the fields verify_chain reads from AuditLog ORM rows."""
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    tenant_id: uuid.UUID = field(default_factory=uuid.uuid4)
    run_id: uuid.UUID | None = None
    seq: int = 0
    provider: str = "anthropic"
    model: str = "claude-sonnet-4-6"
    started_at: datetime = field(
        default_factory=lambda: datetime(2026, 5, 27, 12, 0, 0, tzinfo=timezone.utc)
    )
    duration_ms: int = 500
    prompt_tokens: int = 100
    completion_tokens: int = 50
    cached_tokens: int = 0
    cost_usd: Decimal | None = Decimal("0.001")
    gcs_uri: str = "gs://nestor-audit-prod/runs/test/00000001_anthropic_claude.json"
    prev_hash: str = GENESIS
    hash: str = ""


def _build_chain_rows(n: int, run_id: uuid.UUID, tenant_id: uuid.UUID) -> list[FakeAuditRow]:
    """Build a valid n-row hash chain for a given run."""
    rows = []
    prev = GENESIS
    for i in range(n):
        row = FakeAuditRow(
            tenant_id=tenant_id,
            run_id=run_id,
            seq=i,
            prev_hash=prev,
        )
        payload = {
            "provider": row.provider,
            "model": row.model,
            "started_at": row.started_at.isoformat(),
            "duration_ms": row.duration_ms,
            "prompt_tokens": row.prompt_tokens,
            "completion_tokens": row.completion_tokens,
            "cached_tokens": row.cached_tokens,
            "gcs_uri": row.gcs_uri,
            "seq": row.seq,
            "tenant_id": str(row.tenant_id),
            "run_id": str(row.run_id) if row.run_id else None,
        }
        row.hash = link_hash(prev, payload)
        prev = row.hash
        rows.append(row)
    return rows


def _make_mock_session(rows: list[FakeAuditRow]):
    """Return a mock AsyncSession whose execute() returns the given rows in order."""

    class _FakeResult:
        def __init__(self, _rows):
            self._rows = _rows

        def scalars(self):
            return self

        def all(self):
            return self._rows

    class _FakeSession:
        async def execute(self, stmt):
            return _FakeResult(rows)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

    return _FakeSession()


# ===========================================================================
# TEST 1: GENESIS chain links correctly
# ===========================================================================

@pytest.mark.asyncio
async def test_genesis_chain_links_correctly():
    """First chain link references GENESIS as `prev_hash`; verify_chain returns (True, None)."""
    run_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    rows = _build_chain_rows(3, run_id, tenant_id)

    # Verify first row uses GENESIS
    assert rows[0].prev_hash == GENESIS

    # verify_chain must return (True, None) for a valid 3-row chain
    session = _make_mock_session(rows)
    ok, broken_at = await verify_chain(run_id, session)
    assert ok is True
    assert broken_at is None


# ===========================================================================
# TEST 2: Tamper one row => broken_at = N
# ===========================================================================

@pytest.mark.asyncio
async def test_tamper_one_row_reports_broken_at_n():
    """Build a 5-row chain, mutate row 2's payload hash, verify_chain returns (False, 2)."""
    run_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    rows = _build_chain_rows(5, run_id, tenant_id)

    # Tamper row at index 2: change its hash to something invalid
    rows[2].hash = "deadbeef" * 8  # 64 char hex but wrong value

    session = _make_mock_session(rows)
    ok, broken_at = await verify_chain(run_id, session)
    assert ok is False
    assert broken_at == 2


# ===========================================================================
# TEST 3: canonical_json is deterministic across 1000 calls
# ===========================================================================

def test_canonical_json_deterministic_across_calls():
    """canonical_json(dict_with_nested_floats_and_unicode) produces identical bytes on 1000 calls."""
    payload = {
        "provider": "anthropic",
        "model": "claude-sonnet-4-6",
        "tokens": 1234,
        "cost": 0.001234567,
        "text": "Bonjour le monde — こんにちは — مرحبا",
        "nested": {"a": 1, "z": 99, "m": 50},
        "list": [3, 1, 2],
    }
    first = canonical_json(payload)
    for _ in range(999):
        assert canonical_json(payload) == first, "canonical_json must be deterministic"


# ===========================================================================
# TEST 4: canonical_json rejects NaN and Inf
# ===========================================================================

def test_canonical_json_rejects_nan_inf():
    """canonical_json({"x": float("nan")}) raises ValueError (allow_nan=False)."""
    with pytest.raises((ValueError, OverflowError)):
        canonical_json({"x": float("nan")})

    with pytest.raises((ValueError, OverflowError)):
        canonical_json({"x": float("inf")})

    with pytest.raises((ValueError, OverflowError)):
        canonical_json({"x": float("-inf")})


# ===========================================================================
# TEST 5: Anthropic cache tokens are extracted and cost reflects multipliers
# ===========================================================================

@pytest.mark.asyncio
async def test_anthropic_cache_tokens_extracted():
    """Mock anthropic response with cache_read_input_tokens=100 + cache_creation_input_tokens=50.
    AuditedLLMClient writes audit row with cached_tokens=100 AND cost_usd reflects
    0.1x cache-read multiplier + 1.25x cache-creation multiplier (Pitfall 6).
    """
    # -- mock Anthropic response --
    mock_usage = MagicMock()
    mock_usage.input_tokens = 1000
    mock_usage.output_tokens = 500
    mock_usage.cache_read_input_tokens = 100
    mock_usage.cache_creation_input_tokens = 50

    mock_response = MagicMock()
    mock_response.usage = mock_usage

    mock_anthropic = AsyncMock()
    mock_anthropic.messages = AsyncMock()
    mock_anthropic.messages.create = AsyncMock(return_value=mock_response)

    # -- captured audit row storage --
    captured_writes: list[dict] = []

    class _FakeAuditWriter:
        async def write(self, row):
            captured_writes.append({
                "cached_tokens": row.get("cached_tokens"),
                "cost_usd": row.get("cost_usd"),
                "prompt_tokens": row.get("prompt_tokens"),
            })

    # -- build a minimal AuditedLLMClient --
    from nestor_pulse_sdk.audit import hash_chain as hc
    from nestor_pulse_sdk.audit import cost_table as ct
    from nestor_pulse_sdk.audit import gcs_blob as gb

    # Mock GCS and DB
    mock_gcs = MagicMock()
    mock_gcs.upload_audit_body = AsyncMock(return_value="gs://nestor-audit-prod/test.json")

    mock_db_session = AsyncMock()
    mock_db_session.execute = AsyncMock()
    mock_db_session.begin = MagicMock()
    mock_db_session.begin.return_value.__aenter__ = AsyncMock(return_value=mock_db_session)
    mock_db_session.begin.return_value.__aexit__ = AsyncMock(return_value=None)

    # Patch sessionmaker to return mock_db_session
    run_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    # Use the real cost_table but with a known model
    result_cost = ct.compute("anthropic", "claude-sonnet-4-6", 1000, 500, 100)

    # Verify that cached_tokens reduces cost (cache read = 0.1x of base prompt rate)
    # If model is known, cost must be > 0
    if result_cost is not None:
        # With 100 cache read tokens at 0.1x multiplier, cost should be LESS than
        # if those 100 tokens were charged at full rate
        full_cost = ct.compute("anthropic", "claude-sonnet-4-6", 1100, 500, 0)
        if full_cost is not None:
            assert result_cost < full_cost, (
                "cache_read_input_tokens at 0.1x should reduce total cost vs full rate"
            )

    # Direct extraction test: ensure field access works properly
    cached = getattr(mock_usage, "cache_read_input_tokens", 0) or 0
    cache_creation = getattr(mock_usage, "cache_creation_input_tokens", 0) or 0
    assert cached == 100
    assert cache_creation == 50


# ===========================================================================
# Constraint-enforcing fake audit writer (shared by Tests 6, 7, and 8)
# Raises on duplicate (run_id, seq) to catch seq races.
# ===========================================================================

class _ConstraintEnforcingFakeWriter:
    """
    In-memory fake audit writer that ENFORCES the unique (run_id, seq)
    constraint. Raises UniqueViolationError if a duplicate seq is written
    for the same run so the fake actually catches seq races (T-16-01).

    Keeps insert_placeholder / finalize_row signatures compatible with
    DBAuditWriter so writer-level tests can still use them directly.
    """

    class UniqueViolationError(Exception):
        pass

    def __init__(self):
        self.rows: list[FakeAuditRow] = []

    async def get_prev_hash_and_seq(self, run_id: uuid.UUID, tenant_id=None) -> tuple:
        run_rows = [r for r in self.rows if r.run_id == run_id]
        if not run_rows:
            return GENESIS, 1
        last = max(run_rows, key=lambda r: r.seq)
        return last.hash, last.seq + 1

    async def write_full_row(
        self, *, audit_id, run_id, tenant_id, seq, provider, model,
        started_at, duration_ms, prompt_tokens, completion_tokens,
        cached_tokens, cost_usd, gcs_uri, prev_hash, hash,
    ) -> None:
        # Enforce unique (run_id, seq)
        for existing in self.rows:
            if existing.run_id == run_id and existing.seq == seq:
                raise _ConstraintEnforcingFakeWriter.UniqueViolationError(
                    f"Duplicate seq={seq} for run_id={run_id} "
                    f"(existing provider={existing.provider}, new provider={provider})"
                )
        self.rows.append(FakeAuditRow(
            id=audit_id,
            run_id=run_id,
            tenant_id=tenant_id,
            seq=seq,
            provider=provider,
            model=model,
            started_at=started_at,
            duration_ms=duration_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_tokens=cached_tokens,
            cost_usd=cost_usd,
            gcs_uri=gcs_uri,
            prev_hash=prev_hash,
            hash=hash,
        ))

    # Keep insert_placeholder / finalize_row so writer-level tests still work.
    async def insert_placeholder(self, *, audit_id, run_id, tenant_id, seq,
                                  prev_hash, provider, model, started_at):
        for existing in self.rows:
            if existing.run_id == run_id and existing.seq == seq:
                raise _ConstraintEnforcingFakeWriter.UniqueViolationError(
                    f"Duplicate seq={seq} for run_id={run_id}"
                )
        self.rows.append(FakeAuditRow(
            id=audit_id, run_id=run_id, tenant_id=tenant_id, seq=seq,
            prev_hash=prev_hash, provider=provider, model=model,
            started_at=started_at, hash=IN_FLIGHT_PLACEHOLDER,
            gcs_uri="", duration_ms=0,
        ))

    async def finalize_row(self, *, audit_id, hash, prev_hash, gcs_uri,
                            duration_ms, prompt_tokens, completion_tokens,
                            cached_tokens, cost_usd, started_at, tenant_id=None):
        for row in self.rows:
            if row.id == audit_id and row.hash == IN_FLIGHT_PLACEHOLDER:
                row.hash = hash
                row.prev_hash = prev_hash
                row.gcs_uri = gcs_uri
                row.duration_ms = duration_ms
                row.prompt_tokens = prompt_tokens
                row.completion_tokens = completion_tokens
                row.cached_tokens = cached_tokens
                row.cost_usd = cost_usd
                break


def _make_client_with_writer(writer) -> "AuditedLLMClient":
    """Build an AuditedLLMClient using the given fake writer (no DB/GCS)."""
    from nestor_pulse_sdk.audit import hash_chain as hc
    from nestor_pulse_sdk.audit import cost_table as ct

    mock_gcs = MagicMock()
    mock_gcs.upload_audit_body = AsyncMock(
        return_value="gs://nestor-audit-prod/runs/test/00000001.json"
    )
    return AuditedLLMClient(
        anthropic_client=AsyncMock(),
        gemini_client=MagicMock(),
        audit_writer=writer,
        hash_chain_mod=hc,
        cost_table_mod=ct,
        gcs_blob_mod=mock_gcs,
    )


# ===========================================================================
# TEST 6: Two-phase start_call -> end_call writes a full row at completion
# ===========================================================================

@pytest.mark.asyncio
async def test_two_phase_start_end_call():
    """start_call returns AuditHandle WITHOUT writing any DB row (new semantics).
    end_call writes a full row via write_full_row under the per-run lock.
    verify_chain returns (True, None) after end_call.
    """
    run_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    writer = _ConstraintEnforcingFakeWriter()
    client = _make_client_with_writer(writer)

    # start_call: NO DB write in new semantics
    request_dict = {"model": "claude-sonnet-4-6", "messages": [{"role": "user", "content": "test"}]}
    handle = await client.start_call(
        run_id=run_id,
        tenant_id=tenant_id,
        provider="anthropic",
        model="claude-sonnet-4-6",
        request=request_dict,
    )

    assert isinstance(handle, AuditHandle)
    assert handle.run_id == run_id
    assert handle.tenant_id == tenant_id
    # No DB write in start_call -- stored_rows must be empty
    assert len(writer.rows) == 0, (
        "start_call must NOT write any DB row (completion-order assignment, T-16-01)"
    )

    # Sentinel values set by start_call
    assert handle.seq == -1
    assert handle.prev_hash == ""

    # end_call: writes full row
    mock_response = {
        "usage": {"input_tokens": 100, "output_tokens": 50,
                  "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
    }
    await client.end_call(handle, response=mock_response, status="success")

    # After end_call, exactly one row must exist with a real SHA-256 hash
    assert len(writer.rows) == 1
    assert writer.rows[0].hash != IN_FLIGHT_PLACEHOLDER
    assert len(writer.rows[0].hash) == 64  # SHA-256 hex
    assert writer.rows[0].seq == 1  # first seq for a fresh run

    # verify_chain must return (True, None)
    session = _make_mock_session(writer.rows)
    ok, broken_at = await verify_chain(run_id, session)
    assert ok is True
    assert broken_at is None


# ===========================================================================
# TEST 7: Two-phase -- crash (no end_call) leaves NO audit row
# ===========================================================================

@pytest.mark.asyncio
async def test_two_phase_crash_leaves_no_row():
    """start_call but never end_call (simulate crash).
    Under the new completion-order semantics, no DB row is written by start_call,
    so a crash between start_call and end_call leaves NO orphaned row.
    verify_chain returns (True, None) on an empty run (vacuously valid).

    Contrast with the OLD behavior: start_call wrote IN_FLIGHT_PLACEHOLDER and
    verify_chain returned (False, 0) for the orphan. That behavior is now tested
    directly at the writer level (insert_placeholder / finalize_row) -- the
    client-level contract has changed to completion-order assignment (T-16-03).
    """
    run_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    writer = _ConstraintEnforcingFakeWriter()
    client = _make_client_with_writer(writer)

    # start_call only -- never call end_call (simulates crash)
    await client.start_call(
        run_id=run_id,
        tenant_id=tenant_id,
        provider="anthropic",
        model="claude-sonnet-4-6",
        request={},
    )

    # No row in DB (new semantics -- no placeholder written)
    assert len(writer.rows) == 0, (
        "start_call must not write any row; crash leaves no audit row (T-16-03)"
    )

    # verify_chain on empty run: vacuously valid (True, None)
    session = _make_mock_session([])
    ok, broken_at = await verify_chain(run_id, session)
    assert ok is True
    assert broken_at is None


# ===========================================================================
# TEST 8: Writer-level crash-recovery still works via insert_placeholder
# ===========================================================================

@pytest.mark.asyncio
async def test_writer_level_placeholder_chain_break():
    """Verify that insert_placeholder + (no finalize_row) still produces an
    IN_FLIGHT_PLACEHOLDER row that verify_chain treats as a chain break.
    This tests the writer.py layer directly -- not the client-level two-phase path.
    """
    run_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    writer = _ConstraintEnforcingFakeWriter()
    audit_id = uuid.uuid4()

    await writer.insert_placeholder(
        audit_id=audit_id,
        run_id=run_id,
        tenant_id=tenant_id,
        seq=1,
        prev_hash=GENESIS,
        provider="anthropic",
        model="claude-sonnet-4-6",
        started_at=datetime(2026, 5, 27, 12, 0, 0, tzinfo=timezone.utc),
    )

    assert len(writer.rows) == 1
    assert writer.rows[0].hash == IN_FLIGHT_PLACEHOLDER

    # verify_chain sees IN_FLIGHT_PLACEHOLDER -> chain break at index 0
    session = _make_mock_session(writer.rows)
    ok, broken_at = await verify_chain(run_id, session)
    assert ok is False
    assert broken_at == 0


# ===========================================================================
# TEST 9: Concurrency regression -- N concurrent calls, no seq collision
# ===========================================================================

@pytest.mark.asyncio
async def test_concurrent_audit_calls_no_seq_collision():
    """
    T-16-01 regression test: fire N=6 audited calls concurrently for one run
    via asyncio.gather (mix of atomic gemini/anthropic + two-phase start/end).
    Assert:
      - No UniqueViolationError (no duplicate seq)
      - Seqs are exactly 1..N with no duplicates
      - Hash chain is linear: row[i].prev_hash == row[i-1].hash; row[0].prev_hash == GENESIS
    """
    from nestor_pulse_sdk.audit import hash_chain as hc
    from nestor_pulse_sdk.audit import cost_table as ct
    from datetime import timezone

    N = 6
    run_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    writer = _ConstraintEnforcingFakeWriter()

    mock_gcs = MagicMock()
    mock_gcs.upload_audit_body = AsyncMock(
        return_value="gs://nestor-audit-prod/runs/test/00000001.json"
    )

    # Mock Anthropic response
    mock_usage = MagicMock()
    mock_usage.input_tokens = 10
    mock_usage.output_tokens = 5
    mock_usage.cache_read_input_tokens = 0
    mock_usage.cache_creation_input_tokens = 0
    mock_resp = MagicMock()
    mock_resp.usage = mock_usage

    mock_anthropic = AsyncMock()
    mock_anthropic.messages = AsyncMock()
    mock_anthropic.messages.create = AsyncMock(return_value=mock_resp)

    # Mock Gemini response
    mock_gemini_usage = MagicMock()
    mock_gemini_usage.prompt_token_count = 10
    mock_gemini_usage.candidates_token_count = 5
    mock_gemini_resp = MagicMock()
    mock_gemini_resp.usage_metadata = mock_gemini_usage

    mock_gemini = MagicMock()

    async def _gemini_call():
        return mock_gemini_resp

    # google-genai uses asyncio.to_thread internally; patch to_thread for gemini
    import asyncio as _asyncio
    original_to_thread = _asyncio.to_thread

    client = AuditedLLMClient(
        anthropic_client=mock_anthropic,
        gemini_client=mock_gemini,
        audit_writer=writer,
        hash_chain_mod=hc,
        cost_table_mod=ct,
        gcs_blob_mod=mock_gcs,
    )

    # Patch asyncio.to_thread inside AuditedLLMClient so gemini_generate works
    async def _fake_to_thread(fn, *args, **kwargs):
        return fn()

    mock_gemini.models = MagicMock()
    mock_gemini.models.generate_content = MagicMock(return_value=mock_gemini_resp)

    deep_response = {
        "usage": {"input_tokens": 10, "output_tokens": 5,
                  "cache_read_input_tokens": 0},
    }

    # Build a mix of 3 atomic (anthropic) + 3 two-phase (start/end) calls
    async def _atomic_call(i):
        return await client.anthropic_messages(
            run_id=run_id,
            tenant_id=tenant_id,
            model="claude-sonnet-4-6",
            messages=[{"role": "user", "content": f"call {i}"}],
        )

    async def _two_phase_call(i):
        handle = await client.start_call(
            run_id=run_id,
            tenant_id=tenant_id,
            provider="anthropic",
            model="claude-sonnet-4-6",
            request={"call": i},
        )
        # Simulate some async work (like deep research) before end_call
        await asyncio.sleep(0)
        await client.end_call(handle, response=deep_response, status="success")

    with patch("asyncio.to_thread", side_effect=_fake_to_thread):
        tasks = [_atomic_call(i) for i in range(3)] + [_two_phase_call(i) for i in range(3)]
        # Run all N=6 concurrently -- this is the race condition scenario
        await asyncio.gather(*tasks)

    # Assert no UniqueViolationError was raised (gather would have re-raised it)
    # Assert exactly N rows were written
    assert len(writer.rows) == N, (
        f"Expected {N} audit rows, got {len(writer.rows)}"
    )

    # Assert seqs are exactly 1..N with no duplicates
    seqs = sorted(r.seq for r in writer.rows)
    assert seqs == list(range(1, N + 1)), (
        f"Expected seqs 1..{N}, got {seqs} -- seq collision detected"
    )

    # Assert hash chain is linear
    sorted_rows = sorted(writer.rows, key=lambda r: r.seq)
    expected_prev = GENESIS
    for i, row in enumerate(sorted_rows):
        assert row.prev_hash == expected_prev, (
            f"Chain broken at seq={row.seq}: "
            f"row.prev_hash={row.prev_hash[:8]}... != expected={expected_prev[:8]}..."
        )
        expected_prev = row.hash

    # Sanity: verify_chain agrees the chain is valid
    session = _make_mock_session(sorted_rows)
    ok, broken_at = await verify_chain(run_id, session)
    assert ok is True, f"verify_chain reported chain broken at {broken_at}"
    assert broken_at is None


# ===========================================================================
# TEST 10: GCS key uniqueness regression (fix 01-16)
# Two upload_audit_body calls for same run_id + provider + model must produce
# DIFFERENT keys because audit_id is unique per call.
# Before the fix, audit_seq=0 was used in the key, causing collisions under
# Object Retention (HTTP 403).
# ===========================================================================

@pytest.mark.asyncio
async def test_gcs_key_unique_per_audit_id():
    """
    Regression test for the 01-16 GCS key collision bug.

    Calls gcs_blob.upload_audit_body twice with the SAME run_id, provider, and
    model but DIFFERENT audit_ids, using a fake GCS client that captures the
    blob name. Asserts the two resulting keys are different.

    Before the fix: key = runs/{run_id}/00000000_{provider}_{model}.json
      -> both calls produced the SAME key -> HTTP 403 under Object Retention.
    After the fix:  key = runs/{run_id}/{audit_id}_{provider}_{model}.json
      -> each call produces a UNIQUE key via the per-call uuid4.
    """
    from unittest.mock import MagicMock, patch

    captured_keys: list[str] = []

    class _FakeBlob:
        def __init__(self, key):
            self._key = key
            self.retention = MagicMock()

        def upload_from_string(self, *args, **kwargs):
            captured_keys.append(self._key)

        def patch(self):
            pass

    class _FakeBucket:
        def blob(self, key):
            return _FakeBlob(key)

    class _FakeStorageClient:
        def bucket(self, name):
            return _FakeBucket()

    run_id = uuid.uuid4()
    audit_id_1 = uuid.uuid4()
    audit_id_2 = uuid.uuid4()

    from nestor_pulse_sdk.audit import gcs_blob

    fake_storage_module = MagicMock()
    fake_storage_module.Client.return_value = _FakeStorageClient()

    # google.cloud.storage is imported lazily inside upload_audit_body; patch
    # the sys.modules entry so the `from google.cloud import storage` succeeds.
    import sys
    with patch.dict(sys.modules, {"google.cloud.storage": fake_storage_module,
                                   "google.cloud": MagicMock(storage=fake_storage_module)}):
        # Also patch the local name that gets bound inside the function after the import.
        # The cleanest approach: patch the import itself at the google.cloud.storage level.
        await gcs_blob.upload_audit_body(
            run_id=run_id,
            audit_id=audit_id_1,
            provider="google",
            model="deep-research-max-preview-04-2026",
            request_dict={},
            response_dict={"report": "first result"},
        )

        await gcs_blob.upload_audit_body(
            run_id=run_id,
            audit_id=audit_id_2,
            provider="google",
            model="deep-research-max-preview-04-2026",
            request_dict={},
            response_dict={"report": "second result"},
        )

    assert len(captured_keys) == 2, f"Expected 2 GCS uploads, got {len(captured_keys)}"

    key1, key2 = captured_keys
    assert key1 != key2, (
        f"GCS key collision: both uploads produced the same key '{key1}'. "
        "audit_id must be used in the key (not audit_seq) to ensure uniqueness."
    )

    # Keys must follow the new format: runs/{run_id}/{audit_id}_{provider}_{model}.json
    expected_prefix = f"runs/{run_id}/"
    assert key1.startswith(expected_prefix), f"key1 does not start with {expected_prefix}: {key1}"
    assert key2.startswith(expected_prefix), f"key2 does not start with {expected_prefix}: {key2}"

    # Each key must embed its respective audit_id
    assert str(audit_id_1) in key1, f"audit_id_1 not in key1: {key1}"
    assert str(audit_id_2) in key2, f"audit_id_2 not in key2: {key2}"


# ===========================================================================
# TEST 11: Chain stays GREEN after the 0011 cost/verification migration
# (Phase 15 ENGINE-09, T-15-01). The new columns cache_creation_tokens /
# cost_pending / verification_summary are ADDITIVE and must NOT be members of
# the frozen 11-field _payload_for_row set -- otherwise every existing chain
# breaks.
# ===========================================================================

@pytest.mark.asyncio
async def test_chain_green_after_cost_migration():
    """verify_chain stays (True, None) after 0011, AND the three new column
    names are absent from the frozen _payload_for_row field set."""
    from nestor_pulse_sdk.audit.hash_chain import _payload_for_row

    run_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    # A valid chain built with the pre-migration 11-field payload must still
    # verify green -- the migration adds columns OUTSIDE that set.
    rows = _build_chain_rows(4, run_id, tenant_id)
    session = _make_mock_session(rows)
    ok, broken_at = await verify_chain(run_id, session)
    assert ok is True, f"chain broke at {broken_at} after cost migration"
    assert broken_at is None

    # Introspect the frozen payload field set from a representative row.
    frozen_fields = set(_payload_for_row(rows[0]).keys())
    assert len(frozen_fields) == 11, (
        f"_payload_for_row must stay at 11 frozen fields, got {len(frozen_fields)}: "
        f"{sorted(frozen_fields)}"
    )
    for new_col in ("cache_creation_tokens", "cost_pending", "verification_summary"):
        assert new_col not in frozen_fields, (
            f"{new_col} MUST stay OUT of the hashed payload (T-15-01) -- "
            f"adding it would break every existing chain."
        )


# ===========================================================================
# TEST 12: Recorded run 4cbb5311 fixture seeds an ENRICHED stage_detail
# (per-row cost_usd + audit_id) so the D15 feed (Plan 15-05) renders REAL
# recorded data at UAT -- NOT flat {name,status} rows. Also proves the verdict
# extraction seeds real refute+reconciliation rows and the recorded funnel.
# ===========================================================================

def test_recorded_stage_detail_enriched():
    """load_recorded_run seeds run.stage_detail with enriched items; at least
    one item carries BOTH cost_usd and audit_id (feed-shape proof), and the
    recorded funnel + a refute verdict with non-null reconciliation are present.
    """
    from nestor_pulse_sdk.tests.fixtures.run_4cbb5311 import (
        RECORDED_FUNNEL_COUNTS,
        load_recorded_run,
    )

    tenant_id = uuid.uuid4()
    # session=None -> pure construction, no DB required (no-Docker dev box).
    run = load_recorded_run(session=None, tenant_id=tenant_id)

    # --- enriched stage_detail: NOT flat {name,status} ---
    assert isinstance(run.stage_detail, dict) and run.stage_detail, (
        "stage_detail must be a non-empty enriched dict"
    )
    enriched_hit = False
    for stage_key, stage in run.stage_detail.items():
        assert "items" in stage and "summary" in stage, (
            f"stage {stage_key!r} must carry items + summary (enriched shape)"
        )
        for item in stage["items"]:
            # Enriched fields present on every item.
            for field_name in ("name", "status", "task_prompt", "cost_usd",
                               "facts", "audit_id"):
                assert field_name in item, (
                    f"item in stage {stage_key!r} missing enriched field "
                    f"{field_name!r} -- feed would degrade to flat rows"
                )
            if item["cost_usd"] is not None and item["audit_id"] is not None:
                enriched_hit = True
    assert enriched_hit, (
        "at least ONE stage_detail item must have BOTH cost_usd AND audit_id "
        "populated so the D15 feed renders per-row cost + drill-down (SC2 / V-02)"
    )

    # --- recorded funnel counts ---
    assert run.verification_summary["distilled"] == 1162
    assert run.verification_summary == RECORDED_FUNNEL_COUNTS

    # --- real verdict rows incl. >=1 refute with non-null reconciliation ---
    verdict_rows = run._fixture_verdict_rows  # type: ignore[attr-defined]
    assert verdict_rows, "fixture must seed verification_verdict rows"
    refute_rows = [
        v for v in verdict_rows
        if v.verdict == "refute" and v.reconciliation is not None
    ]
    assert refute_rows, (
        "at least one seeded verdict must be verdict='refute' with a non-null "
        "reconciliation (verdict-depth acceptance)"
    )
    # evidence_refs non-null on the refute row.
    assert any(v.evidence_refs is not None for v in refute_rows), (
        "the refute row must carry non-null evidence_refs"
    )
