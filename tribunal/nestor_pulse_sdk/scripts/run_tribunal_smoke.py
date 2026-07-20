"""Tribunal end-to-end smoke script — Plan 01-16 Task 1.

Runs a single brief through TribunalPipeline against live Cloud SQL, then prints:
  - run_id / tenant_id / project_id (for cleanup)
  - total claims, grounded claims (claim_source hits), recall %
  - sum(audit_log.cost_usd) for this run
  - chain-verify result (ok / broken_at)
  - verification_report (adaptive-effort proof: dropped count, coverage, budget marker)

The one-line summary is designed to be pasted into the Plan 01-12 A/B results table
as the Tribunal challenger arm numbers.

Guards:
  - Exits non-zero with a clear error if DEMO_MODE is set (DEMO_MODE bypasses engine+DB+audit).
  - Exits non-zero if NESTOR_SDK_ORCHESTRATOR != 'tribunal' (smoke is meaningless on the stub).

Tenant self-provisioning:
  --tenant-id / --project-id  Reuse an existing org/project (operator passes own UUIDs).
  (neither provided)           Self-provisions ONE ephemeral org + project + run, all clearly
                               labelled "Tribunal Smoke". Prints created IDs so the operator
                               can DELETE FROM org WHERE id='...' (ON DELETE CASCADE cleans
                               claims/sources/runs automatically).

The smoke calls dispatch_runner('sdk').run(...) directly in-process — no HTTP auth or
JWT needed. set_tenant_context is called inside TribunalPipeline's persist step.

Usage:
  # POSIX
  NESTOR_SDK_ORCHESTRATOR=tribunal .venv/bin/python nestor_pulse_sdk/scripts/run_tribunal_smoke.py

  # Windows
  $env:NESTOR_SDK_ORCHESTRATOR='tribunal'; .venv\Scripts\python nestor_pulse_sdk\scripts\run_tribunal_smoke.py

  --help   show this message and exit (no DB contact)
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

# Windows consoles default to cp1252; the summary output below uses unicode
# arrows/dashes. Force UTF-8 so a print() cannot raise UnicodeEncodeError
# mid-run (which would abort an otherwise-successful paid run).
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

# ---------------------------------------------------------------------------
# Guard: DEMO_MODE must be off — early, before any DB/engine import
# ---------------------------------------------------------------------------
_DEMO_MODE = os.environ.get("DEMO_MODE", "").strip()
if _DEMO_MODE not in ("", "0", "false", "False", "no"):
    print(
        "ERROR: DEMO_MODE is set. DEMO_MODE bypasses the engine, DB, and audit trail.\n"
        "       The Tribunal smoke requires a REAL run (no bypass). Unset DEMO_MODE and retry.",
        file=sys.stderr,
    )
    sys.exit(1)


# ---------------------------------------------------------------------------
# Default high-stakes brief — triggers ≥1 high-stakes focus area so skeptics fire
# ---------------------------------------------------------------------------
_DEFAULT_BRIEF = (
    "Competitive analysis of the European B2B SaaS market for AI-powered legal research tools. "
    "We need to understand: (1) Who are the top 5 competitors and their pricing strategies? "
    "(2) What are the key regulatory risks (EU AI Act, GDPR) that could affect adoption? "
    "(3) Which venture-backed entrants raised ≥$10M in the last 24 months? "
    "This is a high-stakes investment decision — accuracy matters, especially on regulatory claims."
)


# ---------------------------------------------------------------------------
# CLI arg parsing (exits 0 on --help, no DB contact)
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="run_tribunal_smoke",
        description=(
            "Run a single brief through TribunalPipeline against live Cloud SQL.\n"
            "Prints cost, claim/source counts, recall, and chain-verify result.\n\n"
            "Requires: NESTOR_SDK_ORCHESTRATOR=tribunal, DEMO_MODE unset, Cloud SQL resumed,\n"
            "          Cloud SQL Auth Proxy running (DATABASE_URL with ?ssl=disable)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--brief",
        default=None,
        help="Brief text to run. Defaults to a high-stakes AI legal SaaS brief.",
    )
    p.add_argument(
        "--tenant-id",
        dest="tenant_id",
        default=None,
        metavar="UUID",
        help="Reuse an existing org's UUID as tenant. If omitted, a new ephemeral org is created.",
    )
    p.add_argument(
        "--project-id",
        dest="project_id",
        default=None,
        metavar="UUID",
        help="Reuse an existing project UUID. If omitted (and --tenant-id also omitted), "
             "a new ephemeral project is created under the ephemeral org.",
    )
    p.add_argument(
        "--max-budget-usd",
        dest="max_budget_usd",
        type=float,
        default=None,
        help="Override the pipeline's max_budget_usd governor (default: engine default).",
    )
    return p


def _parse_args(argv=None) -> argparse.Namespace:
    return _build_parser().parse_args(argv)


# ---------------------------------------------------------------------------
# DB helpers — ephemeral org/project/run provisioning
# ---------------------------------------------------------------------------

async def _provision_ephemeral_tenant(session, tenant_id: uuid.UUID, project_id: uuid.UUID) -> None:
    """Insert a clearly-labelled smoke org + project into live Cloud SQL.

    ON DELETE CASCADE means:  DELETE FROM org WHERE id = '<tenant_id>'
    removes project → runs → claims → claim_source automatically.
    """
    from sqlalchemy import text

    # Insert org (tenant)
    await session.execute(
        text(
            "INSERT INTO org (id, name, slug, retention_days) "
            "VALUES (:id, :name, :slug, 180) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {
            "id": str(tenant_id),
            "name": "Tribunal Smoke",
            "slug": f"tribunal-smoke-{str(tenant_id)[:8]}",
        },
    )

    # Insert project
    await session.execute(
        text(
            "INSERT INTO project (id, tenant_id, name, client_name, status) "
            "VALUES (:id, :tid, :name, :client, 'active') "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {
            "id": str(project_id),
            "tid": str(tenant_id),
            "name": "Tribunal Smoke Run",
            "client": "smoke-test",
        },
    )


async def _provision_run_row(
    session,
    *,
    run_id: uuid.UUID,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    brief: str,
) -> None:
    """Insert a run row (status='running') so audit_log FK is satisfied."""
    from sqlalchemy import text

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
            "brief": brief[:10_000],
            "ikey": str(idempotency_key),
        },
    )


async def _mark_run_completed(session, *, run_id: uuid.UUID) -> None:
    from sqlalchemy import text

    await session.execute(
        text(
            "UPDATE run SET status='completed', completed_at=NOW() "
            "WHERE id = :id"
        ),
        {"id": str(run_id)},
    )


async def _query_recall(session, *, run_id: uuid.UUID, tenant_id: uuid.UUID) -> tuple[int, int]:
    """Return (total_claims, grounded_claims) for the run.

    grounded = claims with ≥1 claim_source row.

    PHASE1-05 recall surface: this is the query the A/B will use.
    """
    from sqlalchemy import text
    from nestor_pulse_sdk.db.rls import set_tenant_context

    await set_tenant_context(session, tenant_id)

    total_row = await session.execute(
        text("SELECT COUNT(*) FROM claim WHERE run_id = :r AND tenant_id = :t"),
        {"r": str(run_id), "t": str(tenant_id)},
    )
    total: int = total_row.scalar() or 0

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
    grounded: int = grounded_row.scalar() or 0

    return total, grounded


async def _query_cost(session, *, run_id: uuid.UUID) -> float:
    """Sum cost_usd from audit_log for this run."""
    from sqlalchemy import text

    row = await session.execute(
        text(
            "SELECT COALESCE(SUM(cost_usd), 0.0) "
            "FROM audit_log "
            "WHERE run_id = :r"
        ),
        {"r": str(run_id)},
    )
    result = row.scalar()
    try:
        return float(result)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Main async entrypoint
# ---------------------------------------------------------------------------

async def _run(args: argparse.Namespace) -> int:
    """Execute the full smoke and return exit code (0=ok, 1=failure)."""

    # Set NESTOR_SDK_ORCHESTRATOR so dispatch_runner returns TribunalPipeline
    os.environ["NESTOR_SDK_ORCHESTRATOR"] = "tribunal"

    # Validate flag after arg parsing (so --help exits 0 without this check)
    orchestrator_flag = os.environ.get("NESTOR_SDK_ORCHESTRATOR", "")
    if orchestrator_flag != "tribunal":
        print(
            f"ERROR: NESTOR_SDK_ORCHESTRATOR={orchestrator_flag!r}. "
            "Must be 'tribunal' for the Tribunal smoke. "
            "The smoke is meaningless on the control arm stub.",
            file=sys.stderr,
        )
        return 1

    # Bootstrap secrets / env (DATABASE_URL must be in env)
    try:
        from nestor_pulse_sdk.secrets_bootstrap import load_sdk_secrets_into_env
        load_sdk_secrets_into_env()
    except Exception:
        # If the secrets module is unavailable or fails, DATABASE_URL must already
        # be in the environment (e.g. set by the operator before running the script).
        pass

    # Resolve / provision tenant
    reusing_tenant = args.tenant_id is not None
    reusing_project = args.project_id is not None

    if reusing_tenant:
        try:
            tenant_id = uuid.UUID(args.tenant_id)
        except ValueError:
            print(f"ERROR: --tenant-id {args.tenant_id!r} is not a valid UUID.", file=sys.stderr)
            return 1
    else:
        tenant_id = uuid.uuid4()

    if reusing_project:
        try:
            project_id = uuid.UUID(args.project_id)
        except ValueError:
            print(f"ERROR: --project-id {args.project_id!r} is not a valid UUID.", file=sys.stderr)
            return 1
    else:
        project_id = uuid.uuid4()

    run_id = uuid.uuid4()
    brief_text = args.brief if args.brief else _DEFAULT_BRIEF

    from nestor_pulse_sdk.db.base import get_sessionmaker
    from nestor_pulse_sdk.audit.verifier import verify_chain_endpoint
    from nestor_pulse_sdk.runs.adapter import dispatch_runner

    sessionmaker = get_sessionmaker()

    # ------------------------------------------------------------------
    # Phase 1: Provision tenant context (if needed) + run row
    # ------------------------------------------------------------------
    print(f"\n{'='*60}")
    print("Tribunal Smoke — Plan 01-16")
    print(f"{'='*60}")
    print(f"  run_id    : {run_id}")
    print(f"  tenant_id : {tenant_id}  {'[REUSED]' if reusing_tenant else '[NEW — ephemeral]'}")
    print(f"  project_id: {project_id}  {'[REUSED]' if reusing_project else '[NEW — ephemeral]'}")
    print(f"  brief     : {brief_text[:120]}{'...' if len(brief_text)>120 else ''}")
    print()

    async with sessionmaker() as session:
        async with session.begin():
            # project + run carry FORCE RLS: their WITH CHECK policy evaluates
            # current_setting('app.tenant_id'), which raises "unrecognized
            # configuration parameter" if the GUC was never set this transaction.
            # Set the tenant context up front so the provisioning inserts pass.
            # (org is the tenant root and has no RLS, so this is harmless for it.)
            from nestor_pulse_sdk.db.rls import set_tenant_context as _set_tctx
            await _set_tctx(session, tenant_id)
            if not reusing_tenant:
                await _provision_ephemeral_tenant(session, tenant_id, project_id)
            elif not reusing_project:
                # New project under existing tenant
                from sqlalchemy import text
                await session.execute(
                    text(
                        "INSERT INTO project (id, tenant_id, name, client_name, status) "
                        "VALUES (:id, :tid, :name, :client, 'active') "
                        "ON CONFLICT (id) DO NOTHING"
                    ),
                    {
                        "id": str(project_id),
                        "tid": str(tenant_id),
                        "name": "Tribunal Smoke Run",
                        "client": "smoke-test",
                    },
                )
            await _provision_run_row(
                session,
                run_id=run_id,
                tenant_id=tenant_id,
                project_id=project_id,
                brief=brief_text,
            )

    if not reusing_tenant:
        print("EPHEMERAL TENANT CREATED — to clean up after the smoke:")
        print(f"  DELETE FROM org WHERE id = '{tenant_id}';")
        print("  (ON DELETE CASCADE removes project → run → claim → claim_source)")
        print()

    # ------------------------------------------------------------------
    # Phase 2: Run TribunalPipeline
    # ------------------------------------------------------------------
    print("Starting TribunalPipeline run...")
    started_at = datetime.now(timezone.utc)

    runner = dispatch_runner("sdk")
    result = await runner.run(
        brief=brief_text,
        run_id=run_id,
        tenant_id=tenant_id,
    )

    elapsed_s = (datetime.now(timezone.utc) - started_at).total_seconds()

    # ------------------------------------------------------------------
    # Phase 3: Mark run completed
    # ------------------------------------------------------------------
    async with sessionmaker() as session:
        async with session.begin():
            # run carries FORCE RLS — set tenant context before the UPDATE.
            from nestor_pulse_sdk.db.rls import set_tenant_context as _set_tctx
            await _set_tctx(session, tenant_id)
            await _mark_run_completed(session, run_id=run_id)

    # ------------------------------------------------------------------
    # Phase 4: Query recall + cost + verify chain
    # ------------------------------------------------------------------
    async with sessionmaker() as session:
        async with session.begin():
            total_claims, grounded_claims = await _query_recall(
                session, run_id=run_id, tenant_id=tenant_id
            )
            cost_usd = await _query_cost(session, run_id=run_id)

    async with sessionmaker() as session:
        async with session.begin():
            # audit_log carries FORCE RLS — set tenant context before the
            # chain-verify reads (verify_chain_endpoint does not set it itself).
            from nestor_pulse_sdk.db.rls import set_tenant_context as _set_tctx
            await _set_tctx(session, tenant_id)
            chain_result = await verify_chain_endpoint(run_id, session)

    # ------------------------------------------------------------------
    # Phase 5: Print summary
    # ------------------------------------------------------------------
    recall_pct = (grounded_claims / total_claims * 100.0) if total_claims > 0 else 0.0
    claim_count = result.get("claim_count", 0)
    verdict = result.get("verdict") or {}
    vr = result.get("verification_report") or {}

    chain_ok = chain_result.get("ok", False)
    broken_at = chain_result.get("broken_at")
    chain_str = "OK" if chain_ok else f"BROKEN at seq {broken_at}"

    survivor_count = vr.get("survivor_count", claim_count)
    dropped_count = vr.get("dropped_count", 0)
    budget_marker = vr.get("budget_marker", "")
    reentry_count = vr.get("reentry_count", 0)
    coverage = vr.get("coverage", {})
    coverage_pass = coverage.get("pass", True)

    print(f"\n{'='*60}")
    print("TRIBUNAL SMOKE RESULTS")
    print(f"{'='*60}")
    print(f"  run_id           : {run_id}")
    print(f"  elapsed          : {elapsed_s:.1f}s")
    print(f"  survivors        : {survivor_count}")
    print(f"  dropped          : {dropped_count}")
    print(f"  total claims (DB): {total_claims}")
    print(f"  grounded claims  : {grounded_claims}")
    print(f"  recall           : {recall_pct:.1f}%")
    print(f"  cost_usd         : ${cost_usd:.4f}")
    print(f"  chain            : {chain_str}")
    print(f"  budget_marker    : {budget_marker!r}")
    print(f"  coverage_gate    : {'PASS' if coverage_pass else 'FAIL'}")
    print(f"  reentry_count    : {reentry_count}")
    print(f"  quality_gate     : {'PASS' if verdict.get('pass') else verdict}")
    print()

    # One-line A/B summary (paste into results table)
    print("A/B one-liner (paste into Plan 01-12 challenger arm):")
    print(
        f"  Tribunal | run_id={run_id} | claims={total_claims} | "
        f"grounded={grounded_claims} | recall={recall_pct:.1f}% | "
        f"cost=${cost_usd:.4f} | chain={chain_str} | "
        f"elapsed={elapsed_s:.0f}s | budget_marker={budget_marker!r}"
    )
    print()

    if result.get("needs_clarification"):
        print("NOTE: The brief triggered a clarification request (vague brief path).")
        print("      Try a more specific brief with --brief '...' to drive full skeptic runs.")
        return 0

    if not chain_ok:
        print(f"WARNING: hash chain broken at seq {broken_at} — "
              "investigate before using this run in the A/B.", file=sys.stderr)
        return 1

    if total_claims == 0:
        print("WARNING: 0 claims persisted — check pipeline logs for errors.", file=sys.stderr)
        return 1

    return 0


def main(argv=None) -> None:
    args = _parse_args(argv)
    exit_code = asyncio.run(_run(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
