"""
Demo router -- in-memory mock implementations of the public API surface.
Mounted by server.py when DEMO_MODE=1. Bypasses auth + DB.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from nestor_pulse_sdk.demo import fixtures as F

router = APIRouter(tags=["demo"])


# ---- health ----------------------------------------------------------------

@router.get("/healthz")
async def healthz():
    return {"status": "ok", "mode": "demo"}


@router.get("/readyz")
async def readyz():
    return {"status": "ready", "db": "demo (in-memory)"}


# ---- workspace -------------------------------------------------------------

@router.get("/api/me")
async def me():
    return {"workspace": F.WORKSPACE, "user": F.CURRENT_USER}


# ---- projects --------------------------------------------------------------

def _project_summary(p: dict) -> dict:
    """Return a summary suitable for list/grid display."""
    return {
        "id": p["id"],
        "name": p["name"],
        "client_name": p["client_name"],
        "status": p["status"],
        "owner": p["owner"],
        "team": p["team"],
        "briefing_count": p["briefing_count"],
        "active_count": p["active_count"],
        "updated_rel": p["updated_rel"],
    }


@router.get("/api/projects")
async def list_projects(
    q: Optional[str] = None,
    status_: Optional[str] = None,
    sort: Optional[str] = None,
):
    rows = [_project_summary(p) for p in F.PROJECTS]
    if q:
        ql = q.lower()
        rows = [r for r in rows if ql in r["name"].lower() or ql in (r["client_name"] or "").lower()]
    if status_ and status_ != "all":
        rows = [r for r in rows if r["status"] == status_]
    if sort == "alphabetical":
        rows.sort(key=lambda r: r["name"].lower())
    elif sort == "most-briefings":
        rows.sort(key=lambda r: -r["briefing_count"])
    # default sort = recently active (the fixture order)
    return rows


@router.get("/api/projects/{project_id}")
async def get_project(project_id: str):
    p = F.PROJECTS_BY_ID.get(project_id)
    if not p:
        raise HTTPException(404, "project not found")
    return {
        **_project_summary(p),
        "about": p["about"],
        "documents": p["documents"],
        "collaborators": p["team"],
    }


# ---- runs ------------------------------------------------------------------

def _run_summary(r: dict) -> dict:
    return {
        "id": r["id"],
        "project_id": r["project_id"],
        "project": r["project"],
        "title": r["title"],
        "brief": r.get("brief"),
        "engine": r["engine"],
        "status": r["status"],
        "owner": r["owner"],
        "when_rel": r["when_rel"],
        "created_at": r["created_at"],
        "started_at": r.get("started_at"),
        "completed_at": r.get("completed_at"),
        "elapsed_seconds": r.get("elapsed_seconds"),
        "estimated_remaining_seconds": r.get("estimated_remaining_seconds"),
        "cost_usd_total": r.get("cost_usd_total"),
        "tokens_total": r.get("tokens_total"),
        "error_message": r.get("error_message"),
        "comparison_id": r.get("comparison_id"),
    }


def _demo_progress(r: dict) -> None:
    """Auto-advance an in-process demo run so the polling UI can move.

    A run created this process (`_demo_created`) that is still "running" ticks its
    elapsed/cost and flips to "completed" after ~30s real wall-clock. Shared by
    get_run, get_comparison, and get_run_metrics so every poll surface advances.
    """
    if r["status"] != "running" or not r.get("created_at"):
        return
    from datetime import datetime, timezone
    try:
        created = datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        elapsed_real = (now - created).total_seconds()
        if 0 <= elapsed_real < 24 * 3600 and r.get("_demo_created", False):
            r["elapsed_seconds"] = int(elapsed_real)
            r["estimated_remaining_seconds"] = max(0, 30 - int(elapsed_real))
            r["cost_usd_total"] = f"{0.04 * elapsed_real / 30:.2f}"
            r["tokens_total"] = int(1200 * elapsed_real / 30)
            if elapsed_real >= 30:
                r["status"] = "completed"
                r["completed_at"] = now.isoformat()
                r["estimated_remaining_seconds"] = 0
    except Exception:
        pass


@router.get("/api/runs")
async def list_runs(
    project_id: Optional[str] = None,
    recent: Optional[int] = None,
    engine: Optional[str] = None,
):
    rows = list(F.RUNS)
    if project_id:
        rows = [r for r in rows if r["project_id"] == project_id]
    if engine:
        rows = [r for r in rows if r["engine"] == engine]
    rows.sort(key=lambda r: r["created_at"], reverse=True)
    if recent:
        rows = rows[:recent]
    return [_run_summary(r) for r in rows]


class CreateRunBody(BaseModel):
    project_id: str
    brief: str
    engine: str = "sdk"


class CreateCompareBody(BaseModel):
    project_id: str
    brief: str
    engines: list[str]
    comparison_id: str


# A/B comparison routes are declared BEFORE GET /api/runs/{run_id} so the literal
# "compare" segment isn't captured by the str-typed run_id path param.
@router.post("/api/runs/compare", status_code=201)
async def create_comparison(body: CreateCompareBody):
    if body.project_id not in F.PROJECTS_BY_ID:
        raise HTTPException(404, "project not found")
    seen, runs = set(), []
    for engine in body.engines:
        if engine in seen:
            continue
        seen.add(engine)
        runs.append(F.make_new_run(body.project_id, body.brief, engine, comparison_id=body.comparison_id))
    return {"comparison_id": body.comparison_id, "runs": [_run_summary(r) for r in runs]}


@router.get("/api/runs/compare/{comparison_id}")
async def get_comparison(comparison_id: str):
    rows = [r for r in F.RUNS if r.get("comparison_id") == comparison_id]
    if not rows:
        raise HTTPException(404, "comparison not found")
    for r in rows:
        _demo_progress(r)
    rows.sort(key=lambda r: r["created_at"])
    return {"comparison_id": comparison_id, "runs": [_run_summary(r) for r in rows]}


def _demo_metrics(r: dict) -> dict:
    """Synthesize plausible per-arm metrics for the Compare screen.

    ADK mirrors reality (writes to its own SQLite, not the audited claim tables),
    so it reports zero claims/sources -- the UI renders those as 'n/a · legacy'.
    """
    done = r["status"] == "completed"
    engine = r["engine"]
    # Deterministic-ish variety per run id so arms differ but are stable across polls.
    seed = int(r["id"].replace("-", "")[:6], 16)
    if not done or engine == "adk":
        claims = grounded = sources = 0
        recall = None
    else:
        claims = 40 + (seed % 18) + (8 if engine == "tribunal" else 0)
        recall = round(min(0.99, 0.90 + (seed % 9) / 100 + (0.04 if engine == "tribunal" else 0)), 3)
        grounded = int(round(claims * recall))
        sources = int(claims * (2.2 if engine == "tribunal" else 1.6))
    return {
        "run_id": r["id"],
        "engine": engine,
        "status": r["status"],
        "cost_usd_total": r.get("cost_usd_total") if done else None,
        "elapsed_seconds": r.get("elapsed_seconds"),
        "claim_count": claims,
        "grounded_claim_count": grounded,
        "citation_recall": recall,
        "source_count": sources,
    }


@router.get("/api/runs/{run_id}/metrics")
async def get_run_metrics(run_id: str):
    r = F.RUNS_BY_ID.get(run_id)
    if not r:
        raise HTTPException(404, "run not found")
    _demo_progress(r)
    return _demo_metrics(r)


@router.get("/api/runs/{run_id}")
async def get_run(run_id: str):
    r = F.RUNS_BY_ID.get(run_id)
    if not r:
        raise HTTPException(404, "run not found")
    _demo_progress(r)
    return _run_summary(r)


@router.post("/api/runs", status_code=201)
async def create_run(body: CreateRunBody):
    if body.project_id not in F.PROJECTS_BY_ID:
        raise HTTPException(404, "project not found")
    new = F.make_new_run(body.project_id, body.brief, body.engine)
    return _run_summary(new)


# ---- report viewer ---------------------------------------------------------

@router.get("/api/runs/{run_id}/report")
async def get_report(run_id: str):
    r = F.RUNS_BY_ID.get(run_id)
    if not r:
        raise HTTPException(404, "run not found")
    if r["status"] != "completed":
        raise HTTPException(409, "report not available yet")
    # Demo: return the canned report body for every completed run
    body = dict(F.REPORT_BODY)
    body["run_id"] = run_id
    body["title"] = r["title"]
    body["project"] = r["project"]
    body["owner"] = r["owner"]
    body["completed_at"] = r.get("completed_at")
    body["cost_usd_total"] = r.get("cost_usd_total")
    body["sources"] = F.SOURCES
    return body


# ---- sources (citation panel) ---------------------------------------------

@router.get("/api/sources/{source_id}")
async def get_source(source_id: str):
    s = F.SOURCES_BY_ID.get(source_id)
    if not s:
        raise HTTPException(404, "source not found")
    return s


# ---- audit -----------------------------------------------------------------

@router.get("/api/audit/runs/{run_id}/calls")
async def audit_calls(run_id: str):
    if run_id not in F.RUNS_BY_ID:
        raise HTTPException(404, "run not found")
    return {"run_id": run_id, "calls": F.AUDIT_CALLS}


@router.get("/api/audit/projects/{project_id}/sources")
async def audit_project_sources(project_id: str):
    if project_id not in F.PROJECTS_BY_ID:
        raise HTTPException(404, "project not found")
    return {"project_id": project_id, "sources": F.SOURCES}


@router.get("/api/audit/costs")
async def audit_costs(month: Optional[str] = None):
    month = month or "2026-05"
    payload = F.COSTS_BY_MONTH.get(month)
    if not payload:
        raise HTTPException(404, "no costs for that month")
    return {"month": month, **payload}


@router.get("/api/audit/verify/{run_id}")
async def audit_verify(run_id: str):
    if run_id not in F.RUNS_BY_ID:
        raise HTTPException(404, "run not found")
    return {"run_id": run_id, "ok": True, "broken_at": None, "verified_at": F.NOW.isoformat()}


@router.get("/api/audit/recent-verifications")
async def audit_recent_verifications():
    return {"verifications": F.VERIFY_RESULTS}
