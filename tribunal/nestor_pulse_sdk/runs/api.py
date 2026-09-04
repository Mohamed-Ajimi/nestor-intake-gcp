"""
Runs API -- POST/GET/LIST endpoints for async job management (D-09).

References:
- 01-CONTEXT.md D-09: queued/running/completed/failed/cancelled lifecycle
- 01-CONTEXT.md D-02: engine toggle per brief
- 01-RESEARCH.md line 513: idempotency_key UNIQUE(tenant_id, idempotency_key)
- 01-PATTERNS.md lines 853-862: [UPLOADED DOCUMENTS] marker convention
- 01-PATTERNS.md lines 433-465: analog to server.py:200-287 endpoints
- CLAUDE.md Critical rules: ADK pipeline must remain runnable through Phase 1
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from nestor_pulse_sdk.auth.deps import get_db_session, get_current_user
from nestor_pulse_sdk.auth.provider import AuthClaims
from nestor_pulse_sdk.db.models import Run, Project, Output
# D-23.1-07: the proposal GET takes the SAME per-run advisory lock the executor
# uses, so the key expression can never diverge (T-23.1-25). This import is
# safe at module level and must STAY at module level: `runs/execute.py` imports
# `runs/worker.py` LAZILY (inside execute_run_locked) precisely to keep the
# import graph acyclic, and nothing in execute.py's module-level chain reaches
# `runs/api.py`. Do not "fix" this into a function-local import.
from nestor_pulse_sdk.runs.execute import ADVISORY_LOCK_SQL
from nestor_pulse_sdk.runs.schemas import (
    AnswerRequest,
    AuditBody,
    CompareResponse,
    CreateCompareRequest,
    CreateRunRequest,
    ReportSpecRequest,
    RunEventItem,
    RunEventPage,
    RunMetrics,
    RunResponse,
    VerificationReport,
    bundle_readable,
    report_readable,
)
from nestor_pulse_sdk.runs.stages import stages_for

router = APIRouter(prefix="/api/runs", tags=["runs"])


def _prepend_uploaded_docs(brief: str, uploaded_documents) -> str:
    """Prepend the [UPLOADED DOCUMENTS] marker block (PATTERNS lines 853-862)."""
    if not uploaded_documents:
        return brief
    doc_parts = [f"--- {d.filename} ---\n{d.text}" for d in uploaded_documents if d.text]
    if not doc_parts:
        return brief
    prefix = "[UPLOADED DOCUMENTS]\n\n" + "\n\n".join(doc_parts) + "\n\n[END OF UPLOADED DOCUMENTS]\n\n"
    return prefix + brief


_UPLOAD_END = "[END OF UPLOADED DOCUMENTS]"


def _report_title(brief: str) -> str:
    """First real line of the brief (past any uploaded-docs block) as a title."""
    if not brief:
        return "Research report"
    end = brief.find(_UPLOAD_END)
    q = brief[end + len(_UPLOAD_END):] if end >= 0 else brief
    for line in q.splitlines():
        line = line.strip().lstrip("#").strip()
        if line:
            return line[:120]
    return "Research report"


def _markdown_to_sections(body: str) -> list[dict]:
    """Parse a synthesized markdown report into the {heading, paragraphs, list}
    sections the Report viewer renders. Headings start a section; '- '/'* ' lines
    become list items; blank lines separate paragraphs."""
    sections: list[dict] = []
    cur = {"heading": "Overview", "paragraphs": [], "list": []}
    buf: list[str] = []

    def flush_para():
        if buf:
            cur["paragraphs"].append(" ".join(buf).strip())
            buf.clear()

    started = False
    for raw in (body or "").splitlines():
        stripped = raw.strip()
        if stripped.startswith("#"):
            flush_para()
            if started or cur["paragraphs"] or cur["list"]:
                sections.append(cur)
            heading = stripped.lstrip("#").strip() or "Section"
            cur = {"heading": heading, "paragraphs": [], "list": []}
            started = True
        elif stripped.startswith(("- ", "* ")):
            flush_para()
            cur["list"].append(stripped[2:].strip())
        elif not stripped:
            flush_para()
        else:
            buf.append(stripped)
    flush_para()
    if cur["paragraphs"] or cur["list"] or cur["heading"] != "Overview":
        sections.append(cur)

    # Drop empty list arrays so the viewer doesn't render an empty <ul>.
    cleaned = []
    for s in sections:
        if not s["list"]:
            s.pop("list", None)
        cleaned.append(s)
    if not cleaned:
        cleaned = [{"heading": "Report", "paragraphs": [(body or "").strip()[:4000]]}]
    return cleaned


@router.post("", status_code=status.HTTP_201_CREATED, response_model=RunResponse)
async def create_run(
    payload: CreateRunRequest,
    user: AuthClaims = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> RunResponse:
    """
    Create a new async run (brief execution).

    Idempotency (D-09, T-06-01): same (tenant_id, idempotency_key) returns the
    existing run with 201 -- no duplicate rows, no double-charges on retry.

    Engine (D-02): the caller picks 'adk' or 'sdk'; no default -- the UI toggle
    is explicit.

    Uploaded documents (PATTERNS lines 853-862): [UPLOADED DOCUMENTS] block is
    prepended to brief so all agents see the document text.
    """
    # 1. Verify project belongs to tenant (RLS already filters; this is additive D-05 defense)
    proj = (await session.execute(
        select(Project).where(Project.id == payload.project_id)
    )).scalar_one_or_none()
    if proj is None:
        raise HTTPException(404, "project not found")

    # 2. Idempotency: try to find an existing run with the same key first.
    # Defense-in-depth (W9 plan-check): explicit tenant_id filter alongside RLS.
    # CONTEXT.md D-05 forbids relying ONLY on app-level WHERE for isolation -- RLS is still
    # active; this filter is additive defense, not a replacement.
    tenant_uuid = uuid.UUID(user.tenant_id)
    existing = (await session.execute(
        select(Run).where(
            Run.idempotency_key == payload.idempotency_key,
            Run.tenant_id == tenant_uuid,
        )
    )).scalar_one_or_none()
    if existing:
        return RunResponse.model_validate(existing, from_attributes=True)

    # 3. Insert new run -- handle the race where two requests insert concurrently.
    # Use a SAVEPOINT (begin_nested): on a UNIQUE collision only THIS insert rolls
    # back, leaving the outer request transaction AND the SET LOCAL app.tenant_id
    # GUC intact (a bare session.rollback() would clear the tenant context and make
    # the re-SELECT fail the RLS policy -- review blocker fix).
    new_run = Run(
        tenant_id=tenant_uuid,
        project_id=payload.project_id,
        engine=payload.engine,
        brief=payload.brief,  # uploaded_documents text gets prepended below (PATTERNS line 853-862)
        status="queued",
        idempotency_key=payload.idempotency_key,
    )
    try:
        async with session.begin_nested():
            session.add(new_run)
            await session.flush()
    except IntegrityError:
        # concurrent retry hit our UNIQUE(tenant_id, idempotency_key); fetch existing
        existing = (await session.execute(
            select(Run).where(
                Run.idempotency_key == payload.idempotency_key,
                Run.tenant_id == tenant_uuid,
            )
        )).scalar_one()
        return RunResponse.model_validate(existing, from_attributes=True)

    # 4. Persist uploaded documents into run.brief with [UPLOADED DOCUMENTS] marker
    # (PATTERNS lines 853-862 -- preserve the [UPLOADED DOCUMENTS] convention from server.py)
    if payload.uploaded_documents:
        doc_parts = [f"--- {d.filename} ---\n{d.text}" for d in payload.uploaded_documents if d.text]
        if doc_parts:
            prefix = "[UPLOADED DOCUMENTS]\n\n" + "\n\n".join(doc_parts) + "\n\n[END OF UPLOADED DOCUMENTS]\n\n"
            new_run.brief = prefix + new_run.brief

    return RunResponse.model_validate(new_run, from_attributes=True)


@router.post("/compare", status_code=status.HTTP_201_CREATED, response_model=CompareResponse)
async def create_comparison(
    payload: CreateCompareRequest,
    user: AuthClaims = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> CompareResponse:
    """
    Fan one brief out to >=2 engines as sibling child runs (A/B, Plan 01-12).

    Each child shares the caller-supplied comparison_id and gets a deterministic
    idempotency_key = uuid5(comparison_id, engine) so a retried POST returns the
    same children instead of double-charging (D-09 idempotency, extended to the
    fan-out). Engines are de-duplicated, order preserved.
    """
    # 1. Verify project belongs to tenant (RLS filters; additive D-05 defense).
    proj = (await session.execute(
        select(Project).where(Project.id == payload.project_id)
    )).scalar_one_or_none()
    if proj is None:
        raise HTTPException(404, "project not found")

    tenant_uuid = uuid.UUID(user.tenant_id)
    brief = _prepend_uploaded_docs(payload.brief, payload.uploaded_documents)

    # De-dupe engines, preserve order (dict preserves insertion order in 3.7+).
    engines = list(dict.fromkeys(payload.engines))

    runs: list[Run] = []
    for engine in engines:
        child_key = uuid.uuid5(payload.comparison_id, engine)
        existing = (await session.execute(
            select(Run).where(
                Run.idempotency_key == child_key,
                Run.tenant_id == tenant_uuid,
            )
        )).scalar_one_or_none()
        if existing:
            runs.append(existing)
            continue
        child = Run(
            tenant_id=tenant_uuid,
            project_id=payload.project_id,
            engine=engine,
            brief=brief,
            status="queued",
            idempotency_key=child_key,
            comparison_id=payload.comparison_id,
        )
        try:
            # SAVEPOINT per child: a UNIQUE collision on one engine rolls back ONLY
            # that child, preserving the siblings already created in this request
            # and the tenant GUC. A bare session.rollback() here would discard the
            # whole fan-out (review blocker fix).
            async with session.begin_nested():
                session.add(child)
                await session.flush()
        except IntegrityError:
            # concurrent retry hit our UNIQUE(tenant_id, idempotency_key)
            existing = (await session.execute(
                select(Run).where(
                    Run.idempotency_key == child_key,
                    Run.tenant_id == tenant_uuid,
                )
            )).scalar_one()
            runs.append(existing)
            continue
        runs.append(child)

    return CompareResponse(
        comparison_id=payload.comparison_id,
        runs=[RunResponse.model_validate(r, from_attributes=True) for r in runs],
    )


@router.post("/{run_id}/answer", status_code=status.HTTP_201_CREATED)
async def answer_run(
    run_id: uuid.UUID,
    payload: AnswerRequest,
    user: AuthClaims = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """
    Resume a 'needs_input' run by answering its clarifying questions (0005).

    Folds the user's answers into the original brief and queues a NEW run so the
    audit chain stays clean (Art.12) rather than mutating the paused run. If the
    paused run was part of an A/B comparison, re-runs the SAME set of engines as
    a fresh comparison; otherwise a single run on the same engine.
    """
    run = (await session.execute(
        select(Run).where(Run.id == run_id)
    )).scalar_one_or_none()
    if run is None:
        raise HTTPException(404, "run not found")
    if run.status != "needs_input":
        raise HTTPException(409, "run is not awaiting clarification")

    tenant_uuid = uuid.UUID(user.tenant_id)
    by_engine = payload.answers_by_engine or {}
    shared = (payload.answers or "").strip()
    _MARKER = "[CLARIFICATION ANSWERS]"

    def _answer_for(engine: str) -> str:
        return (by_engine.get(engine) or shared or "").strip()

    def _fold(base_brief: str, engine: str) -> str:
        """Append this engine's answers as a new round. We ACCUMULATE rounds (rather
        than strip) so the engine sees every round's answers AND the round count is
        visible as the number of [CLARIFICATION ANSWERS] blocks. Bounding is
        per-engine: Tribunal force-proceeds after 2 rounds (its intake override);
        ADK is uncapped — every round waits for a human answer, so the round count
        is bounded by the user, not the engine."""
        ans = _answer_for(engine)
        if not ans:
            return base_brief
        return base_brief.rstrip() + "\n\n" + _MARKER + "\n" + ans

    # A/B: re-run ONLY the engines the user answered. Each replacement run stays
    # in the SAME comparison (so the other arms are untouched and keep running /
    # their completed result); the paused run it replaces is cancelled. This is
    # per-engine and independent -- answering one arm never restarts the others.
    if run.comparison_id is not None:
        paused = (await session.execute(
            select(Run).where(
                Run.comparison_id == run.comparison_id,
                Run.status == "needs_input",
            )
        )).scalars().all()
        children: list[Run] = []
        for s in paused:
            if not _answer_for(s.engine):
                continue  # user didn't answer this engine -> leave it paused
            child = Run(
                tenant_id=tenant_uuid,
                project_id=s.project_id,
                engine=s.engine,
                brief=_fold(s.brief, s.engine),
                status="queued",
                idempotency_key=uuid.uuid4(),
                comparison_id=run.comparison_id,  # SAME comparison
            )
            session.add(child)
            # Retire the paused run it supersedes.
            s.status = "cancelled"
            s.completed_at = datetime.now(timezone.utc)
            children.append(child)
        await session.flush()
        return {
            "mode": "comparison",
            "comparison_id": str(run.comparison_id),
            "runs": [
                RunResponse.model_validate(c, from_attributes=True).model_dump(mode="json")
                for c in children
            ],
        }

    # Single run: queue a fresh one on the same engine; retire the paused one.
    new_run = Run(
        tenant_id=tenant_uuid,
        project_id=run.project_id,
        engine=run.engine,
        brief=_fold(run.brief, run.engine),
        status="queued",
        idempotency_key=uuid.uuid4(),
    )
    session.add(new_run)
    run.status = "cancelled"
    run.completed_at = datetime.now(timezone.utc)
    await session.flush()
    return {
        "mode": "run",
        "run_id": str(new_run.id),
        "run": RunResponse.model_validate(new_run, from_attributes=True).model_dump(mode="json"),
    }


@router.get("/{run_id}/report-proposal")
async def get_report_proposal(
    run_id: uuid.UUID,
    user: AuthClaims = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """The report-planner's proposal (focus areas / length / tables) for a run.

    Used by the interactive shaping panel AND the 'Rewrite report' flow. If the
    run was zero-touch (no cached proposal) but has a cached research bundle, a
    proposal is generated on demand from that bundle and cached — so any
    completed Tribunal run can be reshaped without re-running research.

    D-23.1-07 — WHY THIS BILLABLE GET IS SAFE UNDER CONCURRENCY:
      The URL, the method and the on-demand generation are UNCHANGED; the
      shaping panel depends on all three, and moving the verb to a POST was the
      explicitly REJECTED alternative (a breaking change for a live UI that buys
      nothing the lock does not). What changed is that generation now runs under
      the SAME per-run `ADVISORY_LOCK_SQL` that `runs/execute.py` uses, and the
      proposal cache is RE-READ UNDER THAT LOCK. That re-read is the entire
      mechanism: a second concurrent caller blocks at the lock, and when it
      proceeds the first caller's committed INSERT is visible (Postgres' default
      READ COMMITTED gives each statement a fresh snapshot), so it returns the
      cache instead of paying a second time.

      The lock does NOT introduce a long-held transaction. `auth/deps.py::
      get_db_session` yields INSIDE `session.begin()`, so this handler was
      ALREADY holding one transaction across the `build_report_proposal` await
      before this change. The lock serialises a long transaction that already
      existed; it is per-run, never global (T-23.1-24). Do not "optimise" it
      away.
    """
    import json as _json

    run = (await session.execute(select(Run).where(Run.id == run_id))).scalar_one_or_none()
    if run is None:
        raise HTTPException(404, "run not found")

    # Serialise every caller for THIS run before the first read that can lead to
    # a paid generation. Transaction-scoped: released when the response commits.
    await session.execute(ADVISORY_LOCK_SQL, {"run_id": str(run_id)})

    async def _latest(fmt: str):
        body = (await session.execute(
            select(Output.body).where(Output.run_id == run_id, Output.format == fmt)
            .order_by(Output.created_at.desc()).limit(1)
        )).scalar_one_or_none()
        return _json.loads(body) if body else None

    proposal = await _latest("report_proposal")
    if proposal is not None:
        return {"run_id": str(run_id), "status": run.status, "proposal": proposal}

    bundle = await _latest("synthesis_cache")
    if bundle is None:
        raise HTTPException(409, "no cached research for this run — cannot propose a report shape")

    # Generate on demand from the cached scrubbed research, then cache it.
    from nestor_pulse_sdk.audit.audited_llm_client import build_audited_client
    from nestor_pulse_sdk.pipeline.tribunal.report_planner import build_report_proposal
    audited = build_audited_client()
    proposal = await build_report_proposal(
        mission_brief=bundle.get("mission_brief") or {},
        cleaned_reports=[tuple(r) for r in (bundle.get("cleaned_reports") or [])],
        audited=audited, run_id=run_id, tenant_id=uuid.UUID(user.tenant_id),
    )
    session.add(Output(
        tenant_id=uuid.UUID(user.tenant_id), run_id=run_id,
        format="report_proposal", body=_json.dumps(proposal, ensure_ascii=False),
    ))
    await session.flush()
    return {"run_id": str(run_id), "status": run.status, "proposal": proposal}


@router.post("/{run_id}/report-spec", status_code=status.HTTP_201_CREATED)
async def submit_report_spec(
    run_id: uuid.UUID,
    payload: ReportSpecRequest,
    user: AuthClaims = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Submit the report shape for a run paused at 'needs_report_spec' -> resume.

    Stores the spec as Output('report_spec') and flips the SAME run back to
    'queued'; the worker re-claims it and the pipeline resumes from the cached
    research bundle (no re-research).
    """
    import json as _json

    run = (await session.execute(select(Run).where(Run.id == run_id))).scalar_one_or_none()
    if run is None:
        raise HTTPException(404, "run not found")
    if run.status != "needs_report_spec":
        raise HTTPException(409, "run is not awaiting a report spec")

    session.add(Output(
        tenant_id=uuid.UUID(user.tenant_id), run_id=run_id,
        format="report_spec", body=_json.dumps(payload.model_dump(), ensure_ascii=False),
    ))
    # Re-queue the SAME run; the resume branch in the pipeline reads report_spec.
    run.status = "queued"
    run.worker_id = None
    await session.flush()
    return RunResponse.model_validate(run, from_attributes=True).model_dump(mode="json")


@router.post("/{run_id}/resume", response_model=RunResponse)
async def resume_run(
    run_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> RunResponse:
    """Re-queue a PARKED run so it continues from its checkpoints (R3/R4, 15.2-16).

    THE SAME RUN is re-queued -- never a new one. A new run would re-dispatch
    every deep-research angle and re-charge the whole brief; this one is
    re-claimed by the worker, and the pipeline's checkpoint branch restores the
    stages that were already paid for from their `ckpt_*` rows.

    A cross-tenant `run_id` is a 404 -- NEVER a "forbidden" response. The row is
    resolved only through `Depends(get_db_session)` -- which sets the tenant GUC
    that the FORCE-RLS policies read -- so another tenant's run is INVISIBLE here
    and is indistinguishable from one that does not exist. That
    non-distinguishability is the security property, not a rough edge
    (T-15.2-122); it mirrors get_run_metrics / get_run_verification, and it is
    pinned by tests/test_checkpoint_resume.py::test_resume_cross_tenant_run_is_404.

    ("Forbidden" is spelled out rather than given as its status code on purpose.
    The source gate in test_checkpoint_resume.py asserts that that code appears
    NOWHERE in this handler's source, and a docstring quoting the number would
    defeat its own gate.)

    The status allow-list is EXACTLY `parked`. Anything else is a 409, so this
    verb cannot re-queue a completed, running, queued or cancelled run, and two
    concurrent clicks cannot both succeed: the first commits `queued` and the
    second sees it and 409s.

    `completed_at` is left alone -- it is NULL on a parked run, because a parked
    run has not completed.

    NO ATTEMPT CAP IS CONSULTED HERE, deliberately (F-02). Resuming from
    checkpoints costs nothing already paid for, so it is free and unlimited at
    this layer; the intake-side cap and its own endpoint are 15.2-19's.
    """
    run = (await session.execute(
        select(Run).where(Run.id == run_id)
    )).scalar_one_or_none()
    if run is None:
        raise HTTPException(404, "run not found")
    if run.status != "parked":
        raise HTTPException(409, "run is not parked")

    run.status = "queued"
    run.worker_id = None
    run.error_message = None
    await session.flush()
    return RunResponse.model_validate(run, from_attributes=True)


@router.post("/{run_id}/rewrite", status_code=status.HTTP_201_CREATED)
async def rewrite_report(
    run_id: uuid.UUID,
    payload: ReportSpecRequest,
    user: AuthClaims = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Re-generate a completed Tribunal run's report with a new shape.

    Creates a NEW run that inherits the source run's cached research bundle and
    the supplied spec, then queues it. The worker runs ONLY synthesis from the
    cache — deep research is never repeated. Each rewrite is its own run/report.
    """
    import json as _json

    src = (await session.execute(select(Run).where(Run.id == run_id))).scalar_one_or_none()
    if src is None:
        raise HTTPException(404, "run not found")
    if src.engine != "tribunal":
        raise HTTPException(409, "rewrite is only available for Tribunal runs")

    bundle_body = (await session.execute(
        select(Output.body).where(Output.run_id == run_id, Output.format == "synthesis_cache")
        .order_by(Output.created_at.desc()).limit(1)
    )).scalar_one_or_none()
    if not bundle_body:
        raise HTTPException(409, "no cached research for this run — cannot rewrite")

    tenant_uuid = uuid.UUID(user.tenant_id)
    new_run = Run(
        tenant_id=tenant_uuid,
        project_id=src.project_id,
        engine="tribunal",
        brief=src.brief,
        status="queued",
        idempotency_key=uuid.uuid4(),
        comparison_id=src.comparison_id,
    )
    session.add(new_run)
    await session.flush()  # assign new_run.id

    # Copy the cached bundle + attach the new spec so the resume branch fires.
    session.add(Output(
        tenant_id=tenant_uuid, run_id=new_run.id,
        format="synthesis_cache", body=bundle_body,
    ))
    session.add(Output(
        tenant_id=tenant_uuid, run_id=new_run.id,
        format="report_spec", body=_json.dumps(payload.model_dump(), ensure_ascii=False),
    ))
    await session.flush()
    return {
        "mode": "rewrite",
        "source_run_id": str(run_id),
        "run": RunResponse.model_validate(new_run, from_attributes=True).model_dump(mode="json"),
    }


@router.post("/{run_id}/cancel", response_model=RunResponse)
async def cancel_run(
    run_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> RunResponse:
    """Cancel a single run (queued, running, or awaiting input).

    Sets status='cancelled' so:
      * a QUEUED run is never claimed by a worker;
      * a RUNNING run's engine aborts at its next cancellation checkpoint (it polls
        run.status at stage boundaries / between skeptic batches), and the worker's
        terminal write is guarded with `AND status='running'` so it can never flip
        a cancelled run back to completed/failed.

    Idempotent: cancelling an already-terminal run is a no-op that returns its
    current state. Tenant-scoped via RLS (get_db_session).
    """
    run = (await session.execute(
        select(Run).where(Run.id == run_id)
    )).scalar_one_or_none()
    if run is None:
        raise HTTPException(404, "run not found")

    if run.status in ("queued", "running", "needs_input"):
        run.status = "cancelled"
        run.completed_at = datetime.now(timezone.utc)
        await session.flush()
    # else: already completed/failed/cancelled -> return as-is (idempotent).

    return RunResponse.model_validate(run, from_attributes=True)


@router.get("/compare/{comparison_id}", response_model=CompareResponse)
async def get_comparison(
    comparison_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> CompareResponse:
    """
    Get all child runs of one A/B comparison (tenant-scoped via RLS).

    Polling-friendly: the Compare screen polls this until every child run reaches
    a terminal status (completed/failed/cancelled).
    """
    rows = (await session.execute(
        select(Run).where(Run.comparison_id == comparison_id).order_by(Run.created_at)
    )).scalars().all()
    if not rows:
        raise HTTPException(404, "comparison not found")
    return CompareResponse(
        comparison_id=comparison_id,
        runs=[RunResponse.model_validate(r, from_attributes=True) for r in rows],
    )


@router.post("/compare/{comparison_id}/critique", status_code=status.HTTP_201_CREATED)
async def create_comparison_critique(
    comparison_id: uuid.UUID,
    user: AuthClaims = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """
    Blind head-to-head critique of the comparison's two completed reports.

    User-triggered (Compare screen button). The judge sees only the brief and
    two anonymised reports — engine names masked, process metadata stripped,
    A/B assignment randomised, order-swapped double judging (see critique/judge.py).
    The result is persisted as an Output(format='critique') so the GET endpoint
    can serve it cached.
    """
    import json as _json

    rows = (await session.execute(
        select(Run).where(Run.comparison_id == comparison_id).order_by(Run.created_at)
    )).scalars().all()
    if not rows:
        raise HTTPException(404, "comparison not found")

    latest_completed: dict[str, Run] = {}
    for r in rows:
        # D-09: report_readable, not a bare status comparison -- a degraded arm
        # still has a report body and belongs in the critique.
        if not report_readable(r.status):
            continue
        cur = latest_completed.get(r.engine)
        if cur is None or r.created_at > cur.created_at:
            latest_completed[r.engine] = r

    if len(latest_completed) != 2:
        raise HTTPException(
            409,
            f"blind critique needs exactly 2 completed engines; "
            f"found {len(latest_completed)} ({', '.join(sorted(latest_completed)) or 'none'})",
        )

    reports_by_engine: dict[str, str] = {}
    for engine, r in latest_completed.items():
        body = (await session.execute(
            select(Output.body)
            .where(Output.run_id == r.id)
            .order_by(Output.created_at.desc())
            .limit(1)
        )).scalar_one_or_none()
        if not body:
            raise HTTPException(409, f"engine {engine!r} has no stored report output")
        reports_by_engine[engine] = body

    # Newest judged run anchors the audit rows + the persisted critique.
    anchor = max(latest_completed.values(), key=lambda r: r.created_at)

    from nestor_pulse_sdk.audit.audited_llm_client import build_audited_client
    from nestor_pulse_sdk.critique.judge import run_blind_critique

    audited = build_audited_client()
    try:
        result = await run_blind_critique(
            brief=anchor.brief,
            reports_by_engine=reports_by_engine,
            audited=audited,
            run_id=anchor.id,
            tenant_id=uuid.UUID(user.tenant_id),
        )
    except Exception as exc:
        raise HTTPException(502, f"critique judge failed: {exc}") from exc

    result["comparison_id"] = str(comparison_id)
    result["judged_runs"] = {e: str(r.id) for e, r in latest_completed.items()}
    result["created_at"] = datetime.now(timezone.utc).isoformat()

    session.add(Output(
        tenant_id=uuid.UUID(user.tenant_id),
        run_id=anchor.id,
        format="critique",
        body=_json.dumps(result, ensure_ascii=False),
    ))
    await session.flush()
    return result


@router.get("/compare/{comparison_id}/critique")
async def get_comparison_critique(
    comparison_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Latest cached critique for this comparison, or 404 if never run."""
    import json as _json

    body = (await session.execute(
        select(Output.body)
        .join(Run, Run.id == Output.run_id)
        .where(Run.comparison_id == comparison_id, Output.format == "critique")
        .order_by(Output.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    if not body:
        raise HTTPException(404, "no critique for this comparison yet")
    try:
        return _json.loads(body)
    except Exception as exc:
        raise HTTPException(500, f"stored critique is unreadable: {exc}") from exc


@router.post("/compare/{comparison_id}/content-compare", status_code=status.HTTP_201_CREATED)
async def create_comparison_content_compare(
    comparison_id: uuid.UUID,
    user: AuthClaims = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Deep, exhaustive content comparison of the comparison's two reports.

    Heavier companion to the blind score critique: buckets the reports' content
    into shared / only-A / only-B, characterises redundancy and the size delta,
    and (for an engine that fact-checks) cross-checks each REJECTED claim against
    the other report. User-triggered (separate Compare button). Persisted as
    Output(format='content_compare') so the GET endpoint serves it cached.
    """
    import json as _json

    rows = (await session.execute(
        select(Run).where(Run.comparison_id == comparison_id).order_by(Run.created_at)
    )).scalars().all()
    if not rows:
        raise HTTPException(404, "comparison not found")

    latest_completed: dict[str, Run] = {}
    for r in rows:
        # D-09: report_readable, not a bare status comparison -- a degraded arm
        # still has a report body and belongs in the comparison.
        if not report_readable(r.status):
            continue
        cur = latest_completed.get(r.engine)
        if cur is None or r.created_at > cur.created_at:
            latest_completed[r.engine] = r

    if len(latest_completed) != 2:
        raise HTTPException(
            409,
            f"content compare needs exactly 2 completed engines; "
            f"found {len(latest_completed)} ({', '.join(sorted(latest_completed)) or 'none'})",
        )

    reports_by_engine: dict[str, str] = {}
    rejected_by_engine: dict[str, list] = {}
    for engine, r in latest_completed.items():
        body = (await session.execute(
            select(Output.body)
            .where(Output.run_id == r.id, Output.format == "markdown")
            .order_by(Output.created_at.desc())
            .limit(1)
        )).scalar_one_or_none()
        if not body:
            raise HTTPException(409, f"engine {engine!r} has no stored report output")
        reports_by_engine[engine] = body

        # Rejected-claims ledger (present only for engines that verify, going
        # forward — older runs predate persistence and simply have none).
        rej = (await session.execute(
            select(Output.body)
            .where(Output.run_id == r.id, Output.format == "rejected_claims")
            .order_by(Output.created_at.desc())
            .limit(1)
        )).scalar_one_or_none()
        if rej:
            try:
                parsed = _json.loads(rej)
                if isinstance(parsed, list):
                    rejected_by_engine[engine] = parsed
            except Exception:
                pass

    anchor = max(latest_completed.values(), key=lambda r: r.created_at)

    from nestor_pulse_sdk.audit.audited_llm_client import build_audited_client
    from nestor_pulse_sdk.critique.content_compare import run_content_comparison

    audited = build_audited_client()
    try:
        result = await run_content_comparison(
            brief=anchor.brief,
            reports_by_engine=reports_by_engine,
            rejected_by_engine=rejected_by_engine,
            audited=audited,
            run_id=anchor.id,
            tenant_id=uuid.UUID(user.tenant_id),
        )
    except Exception as exc:
        raise HTTPException(502, f"content comparison failed: {exc}") from exc

    result["comparison_id"] = str(comparison_id)
    result["judged_runs"] = {e: str(r.id) for e, r in latest_completed.items()}
    result["created_at"] = datetime.now(timezone.utc).isoformat()

    session.add(Output(
        tenant_id=uuid.UUID(user.tenant_id),
        run_id=anchor.id,
        format="content_compare",
        body=_json.dumps(result, ensure_ascii=False),
    ))
    await session.flush()
    return result


@router.get("/compare/{comparison_id}/content-compare")
async def get_comparison_content_compare(
    comparison_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Latest cached content comparison for this comparison, or 404 if never run."""
    import json as _json

    body = (await session.execute(
        select(Output.body)
        .join(Run, Run.id == Output.run_id)
        .where(Run.comparison_id == comparison_id, Output.format == "content_compare")
        .order_by(Output.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    if not body:
        raise HTTPException(404, "no content comparison for this comparison yet")
    try:
        return _json.loads(body)
    except Exception as exc:
        raise HTTPException(500, f"stored content comparison is unreadable: {exc}") from exc


def _park_of(verification_summary) -> dict | None:
    """The park descriptor on a run's verification_summary, or None.

    Plan 15.2-16 / DEC-4. Additive read of an additive JSONB key: no migration,
    no audit-payload change, and a run that never parked simply has no `park`
    key. Never raises -- a malformed column must not break the metrics endpoint
    the poll driver depends on.
    """
    if not isinstance(verification_summary, dict):
        return None
    park = verification_summary.get("park")
    return park if isinstance(park, dict) and park else None


@router.get("/{run_id}/metrics", response_model=RunMetrics)
async def get_run_metrics(
    run_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> RunMetrics:
    """
    Per-run A/B comparison metrics (Plan 01-12 scoring inputs).

    citation_recall is the PHASE1-05 gate: persisted claims carrying >=1 source,
    over total persisted claims. All counts are tenant-scoped via RLS (the claim
    / claim_source tables enforce their own per-tenant policies).
    """
    run = (await session.execute(select(Run).where(Run.id == run_id))).scalar_one_or_none()
    if run is None:
        raise HTTPException(404, "run not found")

    # Claim counts (RLS-scoped). EXISTS avoids JOIN row-fan-out.
    claim_count = (await session.execute(
        text("SELECT count(*) FROM claim WHERE run_id = :rid"),
        {"rid": str(run_id)},
    )).scalar_one()
    grounded_claim_count = (await session.execute(
        text(
            "SELECT count(*) FROM claim c "
            "WHERE c.run_id = :rid "
            "AND EXISTS (SELECT 1 FROM claim_source cs WHERE cs.claim_id = c.id)"
        ),
        {"rid": str(run_id)},
    )).scalar_one()
    source_count = (await session.execute(
        text(
            "SELECT count(DISTINCT source_id) FROM claim_source "
            "WHERE claim_id IN (SELECT id FROM claim WHERE run_id = :rid)"
        ),
        {"rid": str(run_id)},
    )).scalar_one()

    recall = (grounded_claim_count / claim_count) if claim_count else None

    # THE FEED CURSOR (D-01/D-05, plan 15.3-02). An aggregate without GROUP BY always
    # returns EXACTLY ONE row, so scalar_one() is safe here and matches the three
    # counts above; on a run that has emitted nothing that single row is NULL, which
    # arrives as None and publishes as `event_seq: null` rather than a misleading 0.
    #
    # RLS injects `tenant_id = current_setting(...)`, so the planner sees equality on
    # the leading column of idx_run_event_tenant_run_seq (tenant_id, run_id, seq) and
    # resolves max(seq) as an index-only BACKWARD scan -- it touches the last entry of
    # one index range, not the run's history. That is what makes it affordable on an
    # endpoint the intake poll driver hits every ~3 seconds, alongside the three
    # counts above (T-15.3-13, accepted).
    #
    # This carries no feed CONTENT on purpose. It is the one integer that lets the run
    # page decide whether to spend a request on GET /{run_id}/events at all.
    event_seq = (await session.execute(
        text("SELECT max(seq) FROM run_event WHERE run_id = :rid"),
        {"rid": str(run_id)},
    )).scalar_one()

    # Elapsed: completed runs use the closed interval; running runs measure to now.
    elapsed_seconds: int | None = None
    if run.started_at is not None:
        end = run.completed_at or datetime.now(timezone.utc)
        elapsed_seconds = max(0, int((end - run.started_at).total_seconds()))

    return RunMetrics(
        run_id=run.id,
        engine=run.engine,
        status=run.status,
        cost_usd_total=run.cost_usd_total,
        elapsed_seconds=elapsed_seconds,
        # D-L (plan 15.2-24). The handler ALREADY read both columns, three lines
        # above, to compute `elapsed_seconds` — so this projection adds no query,
        # no branch and no cost to an endpoint the intake poll driver hits every
        # ~3 seconds. It is what lets the intake mirror row carry the run's own
        # clock, so the elapsed counter survives a page refresh and the summary
        # card renders a duration instead of an em-dash. Unconditional on
        # purpose: a parked run is paused, not un-started, and must still report
        # when it began.
        started_at=run.started_at,
        completed_at=run.completed_at,
        # ADDITIVE (see RunMetrics.event_seq). None on a run with no events yet.
        event_seq=(int(event_seq) if event_seq is not None else None),
        claim_count=int(claim_count),
        grounded_claim_count=int(grounded_claim_count),
        citation_recall=recall,
        source_count=int(source_count),
        # Live stage progress (0006). Report-readable runs report 'done' so the
        # UI shows every stage green even if the last set_stage write raced the
        # status flip. F2: this reads report_readable, so completed_degraded
        # reports 'done' TOO -- otherwise the feed shows a permanently spinning
        # stage on exactly the runs an operator most needs to read.
        stages=stages_for(run.engine),
        current_stage=(
            "done" if report_readable(run.status) else run.current_stage
        ),
        stage_detail=run.stage_detail,
        # D-17 park descriptor (plan 15.2-16), projected from the run's
        # verification_summary. This endpoint is the ONLY channel the intake poll
        # driver has for a park REASON, because RunMetrics carries no
        # error_message. Read defensively and pass None when it is not a dict:
        # verification_summary is JSONB written by the worker, so it is shaped
        # input, not a trusted object.
        park=_park_of(run.verification_summary),
    )


@router.get("/{run_id}/verification", response_model=VerificationReport)
async def get_run_verification(
    run_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> VerificationReport:
    """
    The operator's post-run verification report (Phase 15 ENGINE-09).

    Shapes the run's PERSISTED per-claim verdicts (verification_verdict) + the
    run-level funnel (run.verification_summary) + true cost (run.cost_usd_total /
    run.cost_pending) into the STAKEHOLDER-NOTES §2026-07-24 content:
      funnel, per-class verdicts, refuted-with-evidence, superseded/scoped
      findings, reconciled contradictions, an HONEST unverified list, true cost.

    Reads ONLY persisted rows -- NEVER a GCS blob (build_verification_report
    contains no storage import). All reads are tenant-scoped via RLS
    (get_db_session sets the tenant GUC), so a cross-tenant run_id reads as absent:
    the run scalar_one_or_none -> 404 (T-15-06), mirroring get_run_metrics /
    renderer.get_source. There is NO distinguishable 403 -- a foreign run and a
    non-existent run look identical to the caller by design.

    F1: this endpoint is DELIBERATELY status-gate-free -- it carries no
    readability predicate and no conflict response -- and that is already correct
    for a parked run, which must be able to show *why* it stopped. Do not add a
    status gate here;
    tests/test_status_gates.py::test_verification_endpoint_has_no_status_gate
    pins it.
    """
    from nestor_pulse_sdk.verification.report import build_verification_report

    run = (await session.execute(select(Run).where(Run.id == run_id))).scalar_one_or_none()
    if run is None:
        raise HTTPException(404, "run not found")

    report = await build_verification_report(session, run)
    return VerificationReport.model_validate(report)


@router.get("/{run_id}/audit/{audit_id}", response_model=AuditBody)
async def get_run_audit_body(
    run_id: uuid.UUID,
    audit_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> AuditBody:
    """
    The feed's audit_id drill-down: the redacted request/response of one LLM call.

    Loads the audit_log row filtered by BOTH id == audit_id AND run_id == run_id
    under the caller's tenant context; scalar_one_or_none -> 404 when None (an RLS
    miss -- a cross-tenant audit_id, or one whose run_id != the path run_id --
    reads as absent, T-15-08b). Then reads the ALREADY-REDACTED body back from GCS
    via download_audit_body; a None body (missing/error uri) is also a 404.

    Returns the body ONLY -- {audit_id, provider, model, request, response}. The
    request was redacted at upload (no key re-exposure, T-15-08c) and hash/prev_hash
    are NEVER included (mirrors audit.api._audit_row_dto).
    """
    from nestor_pulse_sdk.audit.gcs_blob import download_audit_body
    from nestor_pulse_sdk.db.models.audit_log import AuditLog

    row = (
        await session.execute(
            select(AuditLog).where(
                AuditLog.id == audit_id,
                AuditLog.run_id == run_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "audit not found")

    body = await download_audit_body(row.gcs_uri)
    if body is None:
        raise HTTPException(404, "audit not found")

    return AuditBody(
        audit_id=str(audit_id),
        provider=body.get("provider") or row.provider,
        model=body.get("model") or row.model,
        request=body.get("request"),
        response=body.get("response"),
    )


# Page bounds for the run-event feed (T-15.3-12). `limit` is CLAMPED into this
# range rather than rejected outside it: a client that asks for 99999 gets a
# bounded page, not a 422. The ceiling is what makes an unbounded read of a
# 24-angle run impossible; the floor is what stops `limit=0` from turning a page
# turn into an infinite loop of empty pages.
_EVENTS_MAX_LIMIT = 1000
_EVENTS_DEFAULT_LIMIT = 500


def _event_meta(value) -> dict | None:
    """The `meta` JSONB of one run_event row, as a dict, or None.

    SQLAlchemy's asyncpg dialect registers a jsonb codec, so this column normally
    arrives already decoded. Read it defensively anyway: `meta` is JSONB written by
    the worker, it reaches us through a raw `text()` SELECT rather than the ORM, and
    a driver or dialect change that hands back a string must degrade to a dropped
    `meta` on one line -- never to a 500 on the feed an operator is reading.
    """
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        import json

        try:
            decoded = json.loads(value)
        except (ValueError, TypeError):
            return None
        return decoded if isinstance(decoded, dict) else None
    return None


@router.get("/{run_id}/events", response_model=RunEventPage)
async def get_run_events(
    run_id: uuid.UUID,
    after_seq: int = Query(
        0, description="Return events with seq STRICTLY GREATER than this. 0 = from the start."
    ),
    limit: int = Query(
        _EVENTS_DEFAULT_LIMIT,
        description=f"Max events in this page; clamped to 1..{_EVENTS_MAX_LIMIT}.",
    ),
    session: AsyncSession = Depends(get_db_session),
) -> RunEventPage:
    """One bounded, seq-ordered page of a run's activity feed (D-01/D-04/D-05).

    THE BACKFILL READ. The live stream only carries what happens while somebody is
    watching; this is what makes closing the run page and reopening it show TRUE
    history instead of a snapshot. Ordering is `seq ASC` and there is NO descending
    mode and NO offset paging: `seq` is monotonic per run, so a cursor is both
    cheaper and stable under concurrent appends, which an OFFSET is not.

    ISOLATION. The run is resolved ONLY through `Depends(get_db_session)`, which sets
    the tenant GUC that the FORCE-RLS policies read. Another tenant's run is therefore
    INVISIBLE here, `scalar_one_or_none` is None, and the caller gets the SAME 404,
    with the SAME body, as a run_id that never existed. That non-distinguishability is
    the security property, not a rough edge (T-15.3-10/T-15.3-11): a "forbidden"
    answer would confirm the run exists and belongs to somebody else, and an empty
    200 would leak the same fact through the response SHAPE instead of its status.
    There is no forbidden arm in this handler and there must never be one.

    ("Forbidden" is spelled out rather than given as its status code on purpose --
    the source gate in tests/test_run_events_api.py asserts that number appears
    NOWHERE in this handler, and a docstring quoting it would defeat its own gate.
    Same convention as `resume_run` above.)

    BOUNDS. A 24-angle run emits thousands of rows, so `limit` is clamped into
    1..1000 and `after_seq` floored at 0 (T-15.3-12/T-15.3-14 -- both arrive as typed
    query params, so a non-integer is rejected before this body runs, and both are
    passed as BOUND parameters, never interpolated into SQL). `has_more` is decided by
    fetching `limit + 1` rows and noticing whether the extra one came back; issuing a
    COUNT over the run's whole history on every page turn is the denial of service
    this endpoint exists to avoid.

    `next_after_seq` on an EMPTY page is the cursor the caller PASSED IN, never 0 --
    returning 0 would rewind a live client to the beginning of the run on its first
    quiet tick and make it re-download everything it already holds.

    NO STATUS GATE, DELIBERATELY. A failed, cancelled or parked run is exactly the run
    whose events an operator most needs, and today's failed/cancelled cards DROP the
    feed -- the defect this endpoint exists to end. Follow `get_run_verification`,
    which is deliberately gate-free, NOT `get_run_report`, which is gated. Adding a
    readability predicate here is the regression; a source gate in
    tests/test_run_events_api.py pins its absence.
    """
    run = (await session.execute(
        select(Run).where(Run.id == run_id)
    )).scalar_one_or_none()
    if run is None:
        raise HTTPException(404, "run not found")

    # Clamp, do not reject: an over-large ask is answered with a bounded page.
    limit = max(1, min(int(limit), _EVENTS_MAX_LIMIT))
    after = max(0, int(after_seq))

    # RLS injects `tenant_id = current_setting(...)` into this statement, so the
    # planner sees equality on the LEADING column of idx_run_event_tenant_run_seq
    # (tenant_id, run_id, seq) and this is an ordered index range scan -- no sort,
    # no heap scan of the run's whole history. Fetch limit + 1: the extra row IS
    # the has_more signal, which is why no COUNT is issued here.
    rows = (await session.execute(
        text(
            'SELECT seq, ts, stage, kind, "text", meta FROM run_event '
            "WHERE run_id = :rid AND seq > :after "
            "ORDER BY seq ASC LIMIT :lim"
        ),
        {"rid": str(run_id), "after": after, "lim": limit + 1},
    )).all()

    has_more = len(rows) > limit
    rows = rows[:limit]          # drop the probe row before it reaches the client

    events = [
        RunEventItem(
            seq=int(r._mapping["seq"]),
            ts=r._mapping["ts"],
            stage=r._mapping["stage"],
            kind=r._mapping["kind"],
            text=r._mapping["text"],
            meta=_event_meta(r._mapping["meta"]),
        )
        for r in rows
    ]

    return RunEventPage(
        run_id=run_id,
        events=events,
        # Anti-rewind: hold the caller's cursor when the page is empty.
        next_after_seq=(events[-1].seq if events else after),
        has_more=has_more,
    )


@router.get("/{run_id}/report")
async def get_run_report(
    run_id: uuid.UUID,
    user: AuthClaims = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """
    Render a completed run as a structured report for the Report viewer.

    Reads the persisted Output (markdown) the worker wrote on completion, parses
    it into sections, and joins the run's claims -> sources for the citation
    panel. All tenant-scoped via RLS. 409 until report_readable(run.status) --
    i.e. completed OR completed_degraded (D-09/G-10: a degraded run's ~$45 of
    output is never withheld); parked has no report yet and still 409s.
    """
    run = (await session.execute(select(Run).where(Run.id == run_id))).scalar_one_or_none()
    if run is None:
        raise HTTPException(404, "run not found")
    if not report_readable(run.status):
        raise HTTPException(409, "report not available yet")

    # WR-02: filter to format='markdown' (mirrors create_comparison_content_compare).
    # Later flows append NON-markdown Outputs to the same run (critique /
    # content_compare / synthesis_cache / report_spec); an unfiltered
    # newest-Output pick returned those JSON blobs as the report, corrupting the
    # Report viewer and the downstream intake raw-output bundle.
    output = (await session.execute(
        select(Output)
        .where(Output.run_id == run_id, Output.format == "markdown")
        .order_by(Output.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    if output is None:
        raise HTTPException(409, "report not available yet")

    proj = (await session.execute(
        select(Project).where(Project.id == run.project_id)
    )).scalar_one_or_none()
    if proj is None:
        project_label = ""
    elif proj.client_name and proj.client_name.strip().lower() != proj.name.strip().lower():
        project_label = f"{proj.client_name} - {proj.name}"
    else:
        # No client, or client == project name ("Lukoil - Lukoil" reads broken).
        project_label = proj.name

    # Sources cited by this run's claims (RLS-scoped on all three tables).
    src_rows = (await session.execute(
        text(
            "SELECT DISTINCT s.id, s.title, s.url, s.provider, s.fetched_at, s.snapshot_text "
            "FROM source s "
            "JOIN claim_source cs ON cs.source_id = s.id "
            "JOIN claim c ON c.id = cs.claim_id "
            "WHERE c.run_id = :rid "
            "ORDER BY s.fetched_at"
        ),
        {"rid": str(run_id)},
    )).all()
    sources = [
        {
            "id": str(r._mapping["id"]),
            "title": r._mapping["title"],
            "url": r._mapping["url"],
            "provider": r._mapping["provider"],
            "fetched_at": r._mapping["fetched_at"].isoformat() if r._mapping["fetched_at"] else None,
            "snapshot_text": r._mapping["snapshot_text"],
        }
        for r in src_rows
    ]

    return {
        "run_id": str(run.id),
        "title": _report_title(run.brief),
        "project": project_label,
        "owner": {"name": user.email},
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "cost_usd_total": str(run.cost_usd_total) if run.cost_usd_total is not None else None,
        "sections": _markdown_to_sections(output.body),
        # The RAW synthesized markdown (Output.body). The intake side persists this as
        # research_runs.output_markdown and writes it as report.md in the raw-output
        # bundle (D-03) — without it both fall back to empty (A1 shape mismatch: this
        # endpoint historically returned only the parsed ``sections``).
        "markdown": output.body,
        "sources": sources,
    }


@router.get("/{run_id}/research-bundle")
async def get_run_research_bundle(
    run_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Serve a completed run's SCRUBBED per-provider research (Phase-17 D-01).

    The intake seam (``tribunal_client.get_research_bundle``) calls this at the
    Phase-16 poll driver's finalize step to materialize the raw-output bundle. It
    returns ONLY the engine's ``cleaned_reports`` — the subtractive-verification
    scrub where passages supporting dropped claims are already physically removed.

    D-01 CRITICAL: the ``synthesis_cache`` body ALSO contains ``rejected_claims``
    (the discredited-content ledger), ``contested_notes``, and ``verification``.
    Those are DELIBERATELY EXCLUDED — the raw-output download never exposes
    discredited content. This handler returns EXACTLY ``{"cleaned_reports": [...]}``.

    Gate discipline mirrors ``get_run_report``: 404 on an unknown run, 409 until
    ``bundle_readable(run.status)``, 409 when no ``synthesis_cache`` Output exists
    yet. ``bundle_readable`` is WIDER than ``report_readable``: ``parked`` is
    readable by design (D-09) — a parked run has research in hand and the
    superadmin must be able to inspect it before resuming, even though there is no
    report. A parked run with no cache still hits the second 409, which is what
    makes ``parked`` inspection-only rather than a crash. All reads are RLS-scoped
    via ``Depends(get_db_session)`` (the seam's ``X-Nestor-Tenant-Id`` sets the
    tenant GUC, so a cross-tenant run is invisible).

    READ-only: writes NO Output row, touches NO audit chain, and does NOT alter the
    frozen ``canonical_json`` payload (14 D-05).
    """
    import json as _json

    run = (await session.execute(select(Run).where(Run.id == run_id))).scalar_one_or_none()
    if run is None:
        raise HTTPException(404, "run not found")
    if not bundle_readable(run.status):
        raise HTTPException(409, "bundle not available yet")

    body = (await session.execute(
        select(Output.body)
        .where(Output.run_id == run_id, Output.format == "synthesis_cache")
        .order_by(Output.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    if body is None:
        raise HTTPException(409, "no cached research for this run")

    bundle = _json.loads(body)
    # ONLY cleaned_reports — rejected_claims / contested_notes / verification are
    # NEVER returned (D-01). Default to [] if the cache predates cleaned_reports.
    return {"cleaned_reports": bundle.get("cleaned_reports") or []}


@router.get("/{run_id}", response_model=RunResponse)
async def get_run(
    run_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> RunResponse:
    """
    Get run status by ID.

    Polling-friendly (D-09): the UI polls this endpoint after browser disconnect.
    No WebSocket required -- just poll until status is completed/failed.
    """
    run = (await session.execute(select(Run).where(Run.id == run_id))).scalar_one_or_none()
    if run is None:
        raise HTTPException(404, "run not found")
    return RunResponse.model_validate(run, from_attributes=True)


@router.get("", response_model=list[RunResponse])
async def list_runs(
    project_id: Optional[uuid.UUID] = None,
    session: AsyncSession = Depends(get_db_session),
) -> list[RunResponse]:
    """
    List runs for the current tenant (tenant-scoped via RLS).

    Optionally filter by project_id. Returns at most 50 most recent runs.
    """
    stmt = select(Run).order_by(Run.created_at.desc()).limit(50)
    if project_id:
        stmt = stmt.where(Run.project_id == project_id)
    rows = (await session.execute(stmt)).scalars().all()
    return [RunResponse.model_validate(r, from_attributes=True) for r in rows]
