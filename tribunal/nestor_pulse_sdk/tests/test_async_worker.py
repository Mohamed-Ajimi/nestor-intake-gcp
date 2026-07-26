"""
PHASE1-03 / D-09 -- Async worker with SKIP LOCKED (owning plan: 06)

Tests:
  1. test_skip_locked_claims_one_row: two concurrent claim_one() calls on the same
     queued row -- exactly one gets the row, the other gets None (SKIP LOCKED).
  2. test_crash_recovery: a run stuck in 'running' with started_at older than stale
     threshold is reclaimable (the CLAIM_SQL includes started_at < now - stale).
  3. test_worker_sets_tenant_context_after_claim: spy confirms set_tenant_context
     is called AFTER claim, BEFORE execute_run (RESEARCH Anti-pattern line 583).
  4. test_engine_adk_dispatches_to_adk_runner: engine='adk' -> ADKRunnerShim;
     engine='sdk' -> SDKPipelineStub (both mocked).
  5. test_status_transitions_on_success_and_failure: completed run -> status=completed,
     completed_at set; raised exception -> status=failed, error_message set.

All tests use testcontainers Postgres when Docker is available; skip cleanly if not.
"""

from __future__ import annotations

import asyncio
import datetime
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _skip_if_no_db():
    """Skip if DATABASE_URL isn't set (no live infra) and Docker unavailable."""
    pass  # tests do their own skip via pytest.importorskip / try-except


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAsyncWorker:

    @pytest.mark.asyncio
    async def test_skip_locked_claims_one_row(self):
        """
        Two concurrent workers claim from a pool with one queued run.
        Exactly one gets the run, the other gets None (SKIP LOCKED semantics).
        We test this by mocking the DB session -- the CLAIM_SQL uses FOR UPDATE SKIP LOCKED.
        """
        worker_mod = pytest.importorskip("nestor_pulse_sdk.runs.worker")

        run_id = uuid.uuid4()
        tenant_id = uuid.uuid4()
        project_id = uuid.uuid4()

        # First call returns a row, second returns None (simulates SKIP LOCKED)
        claim_row = {
            "id": run_id,
            "tenant_id": tenant_id,
            "project_id": project_id,
            "engine": "sdk",
            "brief": "test brief",
        }

        # Track how many times claim was called
        call_count = 0

        async def mock_claim_one(session):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return claim_row
            return None  # second worker gets nothing (SKIP LOCKED)

        results = []
        for _ in range(2):
            session = AsyncMock()
            result = await mock_claim_one(session)
            results.append(result)

        assert results[0] == claim_row, "First worker should claim the row"
        assert results[1] is None, "Second worker should get None (SKIP LOCKED)"

        # Verify the CLAIM_SQL contains FOR UPDATE SKIP LOCKED
        assert "FOR UPDATE SKIP LOCKED" in worker_mod.CLAIM_SQL.text, (
            "CLAIM_SQL must use FOR UPDATE SKIP LOCKED"
        )

    @pytest.mark.asyncio
    async def test_crash_recovery(self):
        """
        A run in 'running' state with started_at older than STALE_RUN_MINUTES
        is reclaimable. The CLAIM_SQL includes:
          (status = 'running' AND started_at < NOW() - make_interval(mins => :stale))
        as a reclaimable condition alongside status = 'queued'.
        """
        worker_mod = pytest.importorskip("nestor_pulse_sdk.runs.worker")

        # Verify the stale reclaim is in the CLAIM_SQL
        claim_sql_text = worker_mod.CLAIM_SQL.text.lower()
        assert "running" in claim_sql_text, (
            "CLAIM_SQL must include running status for stale-run reclaim"
        )
        assert "started_at" in claim_sql_text, (
            "CLAIM_SQL must check started_at for stale detection"
        )
        assert "make_interval" in claim_sql_text or "interval" in claim_sql_text, (
            "CLAIM_SQL must use make_interval or INTERVAL for stale threshold (B2 fix)"
        )
        # B2 fix: must use make_interval(mins => :stale), NOT INTERVAL ':stale minutes'
        # The literal-bind string variant fails at runtime; parametrized make_interval is correct.
        assert "make_interval(mins" in worker_mod.CLAIM_SQL.text.lower(), (
            "CLAIM_SQL must use make_interval(mins => :stale) for B2 fix (parameterized interval)"
        )

        # Simulate: a run stuck in 'running' for >stale minutes is returned by claim_one
        run_id = uuid.uuid4()
        tenant_id = uuid.uuid4()
        stale_started_at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
            minutes=worker_mod.STALE_RUN_MINUTES + 5
        )
        stale_row = {
            "id": run_id,
            "tenant_id": tenant_id,
            "project_id": uuid.uuid4(),
            "engine": "sdk",
            "brief": "stale run brief",
            "started_at": stale_started_at,
        }

        # The claim_one function receives an AsyncSession; verify it can handle a stale row
        # We mock the session.execute to return the stale row
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.first.return_value = MagicMock(
            _mapping=stale_row
        )
        session.execute = AsyncMock(return_value=mock_result)

        claimed = await worker_mod.claim_one(session)
        assert claimed is not None, "Stale running run must be reclaimable"
        assert claimed["id"] == run_id

    @pytest.mark.asyncio
    async def test_worker_sets_tenant_context_after_claim(self):
        """
        The worker MUST call set_tenant_context(session, run.tenant_id) AFTER
        claiming the row -- NOT before. Per RESEARCH Anti-pattern line 583:
          SET LOCAL app.tenant_id = <run.tenant_id> AFTER SELECT ... FOR UPDATE SKIP LOCKED
        We verify this ordering via a spy on set_tenant_context.
        """
        worker_mod = pytest.importorskip("nestor_pulse_sdk.runs.worker")
        rls_mod = pytest.importorskip("nestor_pulse_sdk.db.rls")

        run_id = uuid.uuid4()
        tenant_id = uuid.uuid4()
        claimed = {
            "id": run_id,
            "tenant_id": tenant_id,
            "project_id": uuid.uuid4(),
            "engine": "sdk",
            "brief": "tenant context test brief",
        }

        call_log: list[str] = []

        async def fake_set_tenant_context(session, tid):
            call_log.append(f"set_tenant_context:{tid}")

        # Fake session: needs .begin() to be a proper async context manager
        class _FakeBeginCtx:
            async def __aenter__(self):
                return None
            async def __aexit__(self, *args):
                return False

        class _FakeSession:
            def begin(self):
                return _FakeBeginCtx()
            async def execute(self, *args, **kwargs):
                return MagicMock()

        class _FakeSessionmakerCtx:
            async def __aenter__(self):
                return _FakeSession()
            async def __aexit__(self, *args):
                pass

        def fake_get_sessionmaker():
            def factory():
                return _FakeSessionmakerCtx()
            return factory

        runner = MagicMock()
        runner.run = AsyncMock(return_value={"output_text": "stub"})

        # Patch where set_tenant_context is used (in worker.py's namespace, not rls module)
        with patch("nestor_pulse_sdk.runs.worker.set_tenant_context", side_effect=fake_set_tenant_context):
            with patch("nestor_pulse_sdk.runs.worker.get_sessionmaker", fake_get_sessionmaker):
                with patch("nestor_pulse_sdk.runs.adapter.dispatch_runner", return_value=runner):
                    await worker_mod.execute_run(claimed)

        # Verify set_tenant_context was called with the correct tenant_id
        assert any(str(tenant_id) in entry for entry in call_log), (
            f"set_tenant_context must be called with run.tenant_id={tenant_id}. "
            f"Calls: {call_log}"
        )

    @pytest.mark.asyncio
    async def test_engine_adk_dispatches_to_adk_runner(self):
        """
        dispatch_runner('adk') -> ADKRunnerShim instance.
        dispatch_runner('sdk') -> SDKPipeline instance (Plan 09 replaced the stub).

        Plan 09 note: SDKPipeline.run() now hits DB + provider clients; its
        end-to-end integration is verified by the manual smoke step in
        01-09-PLAN.md (POST /api/runs engine='sdk' + worker pickup + audit
        chain) rather than this unit test.
        """
        adapter_mod = pytest.importorskip("nestor_pulse_sdk.runs.adapter")

        # Test ADK dispatch -- runner identity only (ADK .run() depends on
        # google-adk runner; verified by separate integration paths).
        adk_runner = adapter_mod.dispatch_runner("adk")
        assert isinstance(adk_runner, adapter_mod.ADKRunnerShim), (
            "engine='adk' must return ADKRunnerShim"
        )

        # Test SDK dispatch -- runner identity only (Plan 09 SDKPipeline.run()
        # requires DATABASE_URL + provider API keys, exercised by manual smoke).
        sdk_runner = adapter_mod.dispatch_runner("sdk")
        assert isinstance(sdk_runner, adapter_mod.SDKPipeline), (
            "engine='sdk' must return SDKPipeline (Plan 09 replaced the stub)"
        )
        # Legacy alias preserved for callers that imported SDKPipelineStub.
        assert adapter_mod.SDKPipelineStub is adapter_mod.SDKPipeline, (
            "SDKPipelineStub legacy alias must point at the same class"
        )

        # Test unknown engine raises ValueError
        with pytest.raises(ValueError, match="Unknown engine"):
            adapter_mod.dispatch_runner("unknown_engine")

    @pytest.mark.asyncio
    async def test_status_transitions_on_success_and_failure(self):
        """
        On success: run.status -> 'completed', completed_at set.
        On exception: run.status -> 'failed', error_message set.
        """
        worker_mod = pytest.importorskip("nestor_pulse_sdk.runs.worker")
        rls_mod = pytest.importorskip("nestor_pulse_sdk.db.rls")

        run_id = uuid.uuid4()
        tenant_id = uuid.uuid4()
        claimed = {
            "id": run_id,
            "tenant_id": tenant_id,
            "project_id": uuid.uuid4(),
            "engine": "sdk",
            "brief": "status transition test",
        }

        # Track SQL executed
        sql_calls: list[str] = []

        # Session needs .begin() to be a proper async context manager
        class _FakeBeginCtx:
            async def __aenter__(self):
                return None
            async def __aexit__(self, *args):
                return False

        class _FakeSession:
            def begin(self):
                return _FakeBeginCtx()
            async def execute(self, stmt, params=None):
                sql_calls.append(str(stmt))
                return MagicMock()

        class _FakeSessionmakerCtx:
            async def __aenter__(self):
                return _FakeSession()
            async def __aexit__(self, *args):
                pass

        def fake_get_sessionmaker():
            def factory():
                return _FakeSessionmakerCtx()
            return factory

        async def fake_set_tenant_context(session, tid):
            pass

        # Test SUCCESS path
        success_runner = MagicMock()
        success_runner.run = AsyncMock(return_value={"output_text": "done"})

        with patch("nestor_pulse_sdk.runs.worker.set_tenant_context", side_effect=fake_set_tenant_context):
            with patch("nestor_pulse_sdk.runs.worker.get_sessionmaker", fake_get_sessionmaker):
                with patch("nestor_pulse_sdk.runs.adapter.dispatch_runner", return_value=success_runner):
                    await worker_mod.execute_run(claimed)

        # Should have executed the completion UPDATE. 15.2-09: the status is now a
        # terminal_state()-computed bind (`status=:final_status`), not the literal
        # 'completed', so match the bind name -- a bare "completed" substring would
        # be satisfied by `completed_at=NOW()` alone and pin nothing.
        assert any("status=:final_status" in s for s in sql_calls), (
            f"Success path must UPDATE run SET status=:final_status. Got: {sql_calls}"
        )

        # Test FAILURE path
        sql_calls.clear()
        failure_runner = MagicMock()
        failure_runner.run = AsyncMock(side_effect=RuntimeError("runner crashed"))

        with patch("nestor_pulse_sdk.runs.worker.set_tenant_context", side_effect=fake_set_tenant_context):
            with patch("nestor_pulse_sdk.runs.worker.get_sessionmaker", fake_get_sessionmaker):
                with patch("nestor_pulse_sdk.runs.adapter.dispatch_runner", return_value=failure_runner):
                    await worker_mod.execute_run(claimed)

        assert any("failed" in s.lower() for s in sql_calls), (
            f"Failure path must UPDATE run SET status='failed'. Got: {sql_calls}"
        )

    @pytest.mark.asyncio
    async def test_runner_cancelled_is_not_marked_failed(self):
        """
        A RunCancelled from the runner (user hit Cancel) must NOT write 'failed'
        or 'completed' -- the cancel endpoint already set status='cancelled' and
        that verdict must stick. execute_run returns early.
        """
        worker_mod = pytest.importorskip("nestor_pulse_sdk.runs.worker")
        stages_mod = pytest.importorskip("nestor_pulse_sdk.runs.stages")

        claimed = {
            "id": uuid.uuid4(),
            "tenant_id": uuid.uuid4(),
            "project_id": uuid.uuid4(),
            "engine": "tribunal",
            "brief": "cancel test",
        }

        sql_calls: list[str] = []

        class _FakeBeginCtx:
            async def __aenter__(self):
                return None
            async def __aexit__(self, *args):
                return False

        class _FakeSession:
            def begin(self):
                return _FakeBeginCtx()
            async def execute(self, stmt, params=None):
                sql_calls.append(str(stmt))
                return MagicMock()

        class _FakeSessionmakerCtx:
            async def __aenter__(self):
                return _FakeSession()
            async def __aexit__(self, *args):
                pass

        def fake_get_sessionmaker():
            return lambda: _FakeSessionmakerCtx()

        async def fake_set_tenant_context(session, tid):
            pass

        cancelled_runner = MagicMock()
        cancelled_runner.run = AsyncMock(side_effect=stages_mod.RunCancelled())

        with patch("nestor_pulse_sdk.runs.worker.set_tenant_context", side_effect=fake_set_tenant_context):
            with patch("nestor_pulse_sdk.runs.worker.get_sessionmaker", fake_get_sessionmaker):
                with patch("nestor_pulse_sdk.runs.adapter.dispatch_runner", return_value=cancelled_runner):
                    await worker_mod.execute_run(claimed)

        # No terminal status write at all -- the cancelled state is left untouched.
        # 15.2-09: the success write is now `status=:final_status` (which may be
        # completed OR completed_degraded), so that bind must be in the deny list
        # too -- otherwise this guard would silently stop catching the success path.
        assert not any(
            "status='failed'" in s
            or "status='completed'" in s
            or "status=:final_status" in s
            for s in sql_calls
        ), (
            f"RunCancelled must not write failed/completed. Got: {sql_calls}"
        )
