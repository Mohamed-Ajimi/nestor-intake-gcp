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

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from nestor_pulse_sdk.auth.deps import get_db_session, get_current_user
from nestor_pulse_sdk.auth.provider import AuthClaims
from nestor_pulse_sdk.db.models import Run, Project, Output
from nestor_pulse_sdk.runs.schemas import (
    AnswerRequest,
    CompareResponse,
    CreateCompareRequest,
    CreateRunRequest,
    ReportSpecRequest,
    RunMetrics,
    RunResponse,
    VerificationReport,
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
    """
    import json as _json

    run = (await session.execute(select(Run).where(Run.id == run_id))).scalar_one_or_none()
    if run is None:
        raise HTTPException(404, "run not found")

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
        if r.status != "completed":
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
        if r.status != "completed":
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
        claim_count=int(claim_count),
        grounded_claim_count=int(grounded_claim_count),
        citation_recall=recall,
        source_count=int(source_count),
        # Live stage progress (0006). Completed/terminal runs report 'done' so the
        # UI shows every stage green even if the last set_stage write raced the
        # status flip.
        stages=stages_for(run.engine),
        current_stage=(
            "done" if run.status == "completed" else run.current_stage
        ),
        stage_detail=run.stage_detail,
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
    """
    from nestor_pulse_sdk.verification.report import build_verification_report

    run = (await session.execute(select(Run).where(Run.id == run_id))).scalar_one_or_none()
    if run is None:
        raise HTTPException(404, "run not found")

    report = await build_verification_report(session, run)
    return VerificationReport.model_validate(report)


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
    panel. All tenant-scoped via RLS. 409 until the run is completed + persisted.
    """
    run = (await session.execute(select(Run).where(Run.id == run_id))).scalar_one_or_none()
    if run is None:
        raise HTTPException(404, "run not found")
    if run.status != "completed":
        raise HTTPException(409, "report not available yet")

    output = (await session.execute(
        select(Output)
        .where(Output.run_id == run_id)
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

    Gate discipline mirrors ``get_run_report``: 404 on an unknown run, 409 until the
    run is ``completed``, 409 when no ``synthesis_cache`` Output exists yet. All
    reads are RLS-scoped via ``Depends(get_db_session)`` (the seam's
    ``X-Nestor-Tenant-Id`` sets the tenant GUC, so a cross-tenant run is invisible).

    READ-only: writes NO Output row, touches NO audit chain, and does NOT alter the
    frozen ``canonical_json`` payload (14 D-05).
    """
    import json as _json

    run = (await session.execute(select(Run).where(Run.id == run_id))).scalar_one_or_none()
    if run is None:
        raise HTTPException(404, "run not found")
    if run.status != "completed":
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
