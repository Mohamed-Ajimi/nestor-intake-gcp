"""Tribunal end-to-end integration test — Plan 01-16 Task 1.

This test runs TribunalPipeline against a LIVE Cloud SQL instance.

Skip condition:
  The test is skipped unless NESTOR_E2E=1 is set in the environment.
  This keeps CI green when Cloud SQL is not available (the normal state).

To run:
  NESTOR_E2E=1 NESTOR_SDK_ORCHESTRATOR=tribunal \\
    pytest nestor_pulse_sdk/tests/test_tribunal_e2e.py -x -m slow --tb=short

What this test asserts (PHASE1-05 mechanism proof):
  1. TribunalPipeline.run() completes with non-empty output_text.
  2. At least 1 claim row persisted for this run_id.
  3. At least 1 claim_source row linked to a claim from this run (skeptic citations landed).
  4. The audit hash chain verifies (no broken_at).
  5. Recall is computable: grounded/total is a float in [0, 1].
  6. Recall is non-trivial (> 0) — the mechanism works end-to-end.

Note: The strict >=95% recall assertion is Plan 01-12's canonical 5-brief
      certification gate. This test asserts the mechanism, not the threshold.

Cleanup:
  The test self-provisions an ephemeral org/project/run (labelled "Tribunal E2E").
  On teardown it calls DELETE FROM org WHERE id=<tenant_id>, which cascades.
  If teardown fails (e.g. DB unreachable during cleanup), the test prints
  the ephemeral UUIDs so the operator can clean up manually.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid

import pytest

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Skip guard — opt-in via NESTOR_E2E=1
# ---------------------------------------------------------------------------
_E2E_ENABLED = os.environ.get("NESTOR_E2E", "").strip() in ("1", "true", "True", "yes")

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        not _E2E_ENABLED,
        reason="Skipped: NESTOR_E2E not set. Set NESTOR_E2E=1 to run against live Cloud SQL.",
    ),
]


# ---------------------------------------------------------------------------
# Short test brief — enough to drive ≥1 skeptic but fast to complete
# ---------------------------------------------------------------------------
_TEST_BRIEF = (
    "What are the top 3 venture-backed AI coding assistant startups in Europe that raised "
    "funding in 2024? Focus on their funding amounts, key investors, and whether they face "
    "EU AI Act compliance risks. This is a high-stakes investment screening — verify claims."
)


# ---------------------------------------------------------------------------
# Fixture: ephemeral tenant + project for one test run
# ---------------------------------------------------------------------------

@pytest.fixture
async def ephemeral_e2e_context():
    """Provision an ephemeral org + project for this test run; teardown on exit.

    Yields:
        dict with keys: tenant_id, project_id, run_id, sessionmaker
    """
    # Guard: DEMO_MODE must be off
    demo = os.environ.get("DEMO_MODE", "").strip()
    if demo not in ("", "0", "false", "False", "no"):
        pytest.skip("DEMO_MODE is set — skipping e2e test (DEMO_MODE bypasses DB+engine).")

    # Ensure NESTOR_SDK_ORCHESTRATOR=tribunal
    os.environ["NESTOR_SDK_ORCHESTRATOR"] = "tribunal"

    # Bootstrap secrets / DATABASE_URL
    try:
        from nestor_pulse_sdk.secrets_bootstrap import load_sdk_secrets_into_env
        load_sdk_secrets_into_env()
    except Exception:
        pass  # Operator must have DATABASE_URL in env

    from nestor_pulse_sdk.db.base import get_sessionmaker
    from sqlalchemy import text

    sessionmaker = get_sessionmaker()

    tenant_id = uuid.uuid4()
    project_id = uuid.uuid4()
    run_id = uuid.uuid4()

    # Self-provision ephemeral rows
    async with sessionmaker() as session:
        async with session.begin():
            await session.execute(
                text(
                    "INSERT INTO org (id, name, slug, retention_days) "
                    "VALUES (:id, :name, :slug, 180)"
                ),
                {
                    "id": str(tenant_id),
                    "name": "Tribunal E2E",
                    "slug": f"tribunal-e2e-{str(tenant_id)[:8]}",
                },
            )
            await session.execute(
                text(
                    "INSERT INTO project (id, tenant_id, name, client_name, status) "
                    "VALUES (:id, :tid, :name, :client, 'active')"
                ),
                {
                    "id": str(project_id),
                    "tid": str(tenant_id),
                    "name": "Tribunal E2E Run",
                    "client": "e2e-test",
                },
            )
            idempotency_key = uuid.uuid4()
            await session.execute(
                text(
                    "INSERT INTO run "
                    "(id, tenant_id, project_id, engine, brief, status, idempotency_key) "
                    "VALUES (:id, :tid, :pid, 'sdk', :brief, 'running', :ikey)"
                ),
                {
                    "id": str(run_id),
                    "tid": str(tenant_id),
                    "pid": str(project_id),
                    "brief": _TEST_BRIEF,
                    "ikey": str(idempotency_key),
                },
            )

    log.info(
        "tribunal_e2e: provisioned ephemeral tenant=%s project=%s run=%s",
        tenant_id, project_id, run_id,
    )

    yield {
        "tenant_id": tenant_id,
        "project_id": project_id,
        "run_id": run_id,
        "sessionmaker": sessionmaker,
    }

    # Teardown — cascade DELETE removes project → run → claim → claim_source
    try:
        async with sessionmaker() as session:
            async with session.begin():
                await session.execute(
                    text("DELETE FROM org WHERE id = :id"),
                    {"id": str(tenant_id)},
                )
        log.info("tribunal_e2e: teardown complete — deleted ephemeral tenant %s", tenant_id)
    except Exception as exc:
        log.warning(
            "tribunal_e2e: teardown failed — clean up manually:\n"
            "  DELETE FROM org WHERE id = '%s';\n  Error: %s",
            tenant_id, exc,
        )
        # Print to stdout so it appears in test output even if log is suppressed
        print(
            f"\n[CLEANUP NEEDED] tribunal_e2e teardown failed.\n"
            f"  DELETE FROM org WHERE id = '{tenant_id}';\n"
            f"  (ON DELETE CASCADE removes project/run/claim/claim_source)\n"
            f"  Error: {exc}"
        )


# ---------------------------------------------------------------------------
# Core e2e test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tribunal_e2e_full_run(ephemeral_e2e_context):
    """TribunalPipeline runs end-to-end against live Cloud SQL:
    - Non-empty output_text
    - ≥1 claim persisted
    - ≥1 claim_source row (skeptic citations landed)
    - Audit hash chain verifies
    - Recall ∈ [0, 1] and > 0 (mechanism works)
    """
    ctx = ephemeral_e2e_context
    tenant_id: uuid.UUID = ctx["tenant_id"]
    project_id: uuid.UUID = ctx["project_id"]
    run_id: uuid.UUID = ctx["run_id"]
    sessionmaker = ctx["sessionmaker"]

    from sqlalchemy import text
    from nestor_pulse_sdk.runs.adapter import dispatch_runner
    from nestor_pulse_sdk.db.rls import set_tenant_context
    from nestor_pulse_sdk.audit.verifier import verify_chain_endpoint

    # ------------------------------------------------------------------
    # 1. Run the Tribunal pipeline
    # ------------------------------------------------------------------
    runner = dispatch_runner("sdk")

    # Confirm we got TribunalPipeline (not the stub)
    from nestor_pulse_sdk.pipeline.tribunal.pipeline import TribunalPipeline
    assert isinstance(runner, TribunalPipeline), (
        f"Expected TribunalPipeline (NESTOR_SDK_ORCHESTRATOR=tribunal), "
        f"got {type(runner).__name__}. Is NESTOR_SDK_ORCHESTRATOR set correctly?"
    )

    result = await runner.run(
        brief=_TEST_BRIEF,
        run_id=run_id,
        tenant_id=tenant_id,
    )

    # ------------------------------------------------------------------
    # 2. Assert: non-empty output_text
    # ------------------------------------------------------------------
    assert result.get("output_text"), (
        "TribunalPipeline must produce non-empty output_text. "
        f"Got: {result.get('output_text')!r}"
    )

    # Mark run completed so status is accurate
    async with sessionmaker() as session:
        async with session.begin():
            await session.execute(
                text("UPDATE run SET status='completed', completed_at=NOW() WHERE id = :id"),
                {"id": str(run_id)},
            )

    # ------------------------------------------------------------------
    # 3. Assert: ≥1 claim persisted
    # ------------------------------------------------------------------
    async with sessionmaker() as session:
        async with session.begin():
            await set_tenant_context(session, tenant_id)

            total_row = await session.execute(
                text(
                    "SELECT COUNT(*) FROM claim "
                    "WHERE run_id = :r AND tenant_id = :t"
                ),
                {"r": str(run_id), "t": str(tenant_id)},
            )
            total_claims: int = total_row.scalar() or 0

    assert total_claims >= 1, (
        f"Expected ≥1 claim persisted for run_id={run_id}, "
        f"got {total_claims}. Check TribunalPipeline persist_tribunal_claims call."
    )

    # ------------------------------------------------------------------
    # 4. Assert: ≥1 claim_source row (skeptic citations linked)
    # ------------------------------------------------------------------
    async with sessionmaker() as session:
        async with session.begin():
            await set_tenant_context(session, tenant_id)

            grounded_row = await session.execute(
                text(
                    "SELECT COUNT(DISTINCT claim_id) "
                    "FROM claim_source "
                    "WHERE claim_id IN ("
                    "  SELECT id FROM claim WHERE run_id = :r AND tenant_id = :t"
                    ")"
                ),
                {"r": str(run_id), "t": str(tenant_id)},
            )
            grounded_claims: int = grounded_row.scalar() or 0

    assert grounded_claims >= 1, (
        f"Expected ≥1 claim_source row for run_id={run_id}, "
        f"got {grounded_claims}. Skeptic citations must link to claim_source. "
        f"(total claims={total_claims})"
    )

    # ------------------------------------------------------------------
    # 5. Assert: audit hash chain verifies
    # ------------------------------------------------------------------
    async with sessionmaker() as session:
        async with session.begin():
            chain_result = await verify_chain_endpoint(run_id, session)

    assert chain_result.get("ok") is True, (
        f"Audit hash chain broken at seq={chain_result.get('broken_at')}. "
        "Chain integrity must hold after a real Tribunal run."
    )

    # ------------------------------------------------------------------
    # 6. Assert: recall ∈ [0, 1] and > 0
    # ------------------------------------------------------------------
    recall = grounded_claims / total_claims
    assert 0.0 <= recall <= 1.0, (
        f"Recall must be in [0, 1], got {recall:.4f} "
        f"(grounded={grounded_claims}, total={total_claims})"
    )
    assert recall > 0.0, (
        f"Recall must be > 0 (the citation mechanism must work end-to-end). "
        f"Got recall={recall:.4f} with grounded={grounded_claims}/{total_claims}. "
        "Check that skeptic web_fetch citations are being persisted via "
        "persist_tribunal_claims."
    )

    # ------------------------------------------------------------------
    # Logging — for the A/B summary
    # ------------------------------------------------------------------
    vr = result.get("verification_report") or {}
    claim_count = result.get("claim_count", 0)
    survivor_count = vr.get("survivor_count", claim_count)
    dropped_count = vr.get("dropped_count", 0)
    budget_marker = vr.get("budget_marker", "")
    coverage = vr.get("coverage", {})
    reentry_count = vr.get("reentry_count", 0)

    log.info(
        "tribunal_e2e PASS: run_id=%s survivors=%d dropped=%d "
        "db_claims=%d grounded=%d recall=%.1f%% "
        "coverage=%s reentry=%d budget_marker=%r",
        run_id, survivor_count, dropped_count,
        total_claims, grounded_claims, recall * 100,
        coverage.get("pass"), reentry_count, budget_marker,
    )

    print(
        f"\n[tribunal_e2e] PASS\n"
        f"  run_id     : {run_id}\n"
        f"  survivors  : {survivor_count}\n"
        f"  dropped    : {dropped_count}\n"
        f"  db_claims  : {total_claims}\n"
        f"  grounded   : {grounded_claims}\n"
        f"  recall     : {recall*100:.1f}%\n"
        f"  chain      : OK\n"
        f"  coverage   : {'PASS' if coverage.get('pass') else 'FAIL'}\n"
        f"  reentry    : {reentry_count}\n"
        f"  budget_mkr : {budget_marker!r}\n"
        f"\n  NOTE: strict >=95% recall gate is Plan 01-12's 5-brief certification.\n"
        f"        This test proves the mechanism works; recall={recall*100:.1f}% logged.\n"
    )
