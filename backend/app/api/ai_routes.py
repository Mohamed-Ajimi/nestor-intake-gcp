"""The AI route surface — the ported edge functions as Cloud Run endpoints (AI-01/02..05).

Seven endpoints under ``protected_router`` (so each inherits ``Depends(get_current_identity)``
— AUTH-01), each a SYNC ``def`` depending on ``Identity`` ONLY — never ``get_tenant_repo``.
The long external (Claude / OpenAI / Whisper) call is NOT held in the request: the handler
creates the ``skill_runs`` row synchronously in a short tx (``create_running_skill_run`` —
ownership-checked, GUC set, connection released) and schedules the work via FastAPI
``BackgroundTasks``, returning ``202`` with the run id immediately. The background task runs
the AI-06 release contract (``run_with_session_release``) so the connection is free across
the ~120s call and the per-space GUC is re-issued on the write session (T-7-02 / T-7-06).

Locked invariants realized here:

* SEC-01 / COST-01 / D-23.1-02 — the whole router is OPERATOR-ONLY. ``ai_router`` carries
  ONE router-level ``Depends(superadmin_gate)`` (plan 23.1-11), so a role=``user`` caller
  gets the existence-hidden ``404`` before any handler body runs and can never fire paid
  Claude/OpenAI/Whisper work. See the comment on the router construction below for why the
  gate is on the ROUTER and not on the seven handlers. ``tests/test_ai_router_gate.py`` is
  the denial proof; ``tests/test_client_surface_open.py`` is the counterweight.
* TENANT-02 / T-7-03 — the tenant key is NEVER read from the path/body/query/LLM. The tenant
  scope comes solely from the verified ``Identity``; ``create_running_skill_run`` scopes the
  row to that tenant. There is NO request model carrying a tenant field (the grep gate).
* T-7-12 / D-07 — a cross-tenant or missing ``intake_id`` raises ``IntakeNotInScopeError``
  inside ``create_running_skill_run`` -> ``404`` (existence hidden; never 200-with-data,
  never 403). The single 403 is the null-space default-deny (``PermissionError`` from
  ``tenant_session``).
* D-09 — terminal ``skill_runs.status`` is written by the background task as EXACTLY
  ``succeeded`` / ``failed`` (the contract the frontend polls); the endpoint only sets the
  initial ``running``.
* Scope ceiling (INTAKE-05 / T-7-07) — NO route path names the deep-research stage; the
  flow stops at ``decomposed``.
* D-03 grep-guard — this module imports ONLY ``Identity`` + the ``ai_session`` helper +
  the skill/search handlers; it constructs NO engine/session (raw DB lives in ``app/db/``).

Sync (blocking) handlers, never coroutine handlers: pg8000 is a blocking driver and the
synchronous ``create_running_skill_run`` runs in FastAPI's threadpool; a coroutine handler
touching the engine would stall the event loop (mirrors ``intake_routes.py:33`` / ``main.py``).
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from app.ai.search import semantic_search
from app.ai.skills import (
    run_apply_intake_skill,
    run_context_pack,
    run_embeddings,
    run_extract_insights,
    run_structure_answers,
    run_transcribe,
)
from app.auth.dependencies import get_current_identity
from app.auth.gates import superadmin_gate
from app.auth.identity import Identity
from app.core.config import get_settings
from app.db.ai_session import IntakeNotInScopeError, create_running_skill_run

# The AI feature router. It inherits Depends(get_current_identity) from protected_router
# (mounted UNDER it in app/main.py) and carries ONE router-level Depends(superadmin_gate) of
# its own — D-23.1-02, "one dependency, not seven". prefix mirrors intake_router so the AI
# verbs hang off the same /intakes/{intake_id} resource; the two are separate APIRouter
# objects, so this gate reaches only the seven routes below and never intake_router's client
# surface (tests/test_client_surface_open.py pins that half).
#
# ROUTER LEVEL AND NOT SEVEN PER-ROUTE COPIES, for two reasons that are not style:
#
#  1. A route ADDED to this router later is gated BY CONSTRUCTION. Seven per-route copies
#     would leave route number eight open — which is exactly how the six extra ungated
#     operator verbs in 23.1-CONTEXT.md § 1's table came to exist in the first place.
#  2. FastAPI PREPENDS router-level dependencies to each route's own list, so the gate
#     resolves before every handler dependency and before the handler body. That satisfies
#     app/auth/gates.py's ordering contract STRUCTURALLY rather than by remembering to put a
#     parameter in the right position — and it is what makes a null-space user receive the
#     existence-hidden 404 instead of _dispatch_skill_run's 403 existence oracle.
ai_router = APIRouter(
    prefix="/intakes",
    tags=["ai"],
    dependencies=[Depends(superadmin_gate)],
)


def _dispatch_skill_run(identity: Identity, intake_id: str, skill: str, llm_model: str) -> str:
    """Create the ``running`` ``skill_runs`` row (own short tx) and return its id.

    The single synchronous step every long-running AI endpoint performs BEFORE scheduling
    its background task: ``create_running_skill_run`` verifies the intake is in the caller's
    scope (cross-tenant/missing -> ``IntakeNotInScopeError`` -> 404, D-07), inserts the
    ``running`` row (D-09), and releases the connection. A null-space user surfaces as 403
    (the default-deny ``PermissionError`` from ``tenant_session``).
    """
    try:
        run_id = create_running_skill_run(
            identity, intake_id, skill=skill, llm_model=llm_model
        )
    except IntakeNotInScopeError:
        # Existence hidden: a cross-tenant / missing intake is a 404, never a 403 / 200.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")
    except PermissionError:
        # Null-space user default-deny (D-04) — the only 403 on this path.
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No space — not authorized")
    return str(run_id)


@ai_router.post("/{intake_id}/skills/apply", status_code=status.HTTP_202_ACCEPTED)
def apply_intake_skill(
    intake_id: str,
    bg: BackgroundTasks,
    identity: Identity = Depends(get_current_identity),
) -> dict:
    """Run apply-intake-skill as a space-scoped background task (AI-01).

    Creates the ``running`` run, schedules the Claude call, and returns ``202`` + the run
    id immediately. The task finalizes the row ``succeeded`` (with ``output_parsed`` for
    AIReviewPanel) or ``failed`` (D-09).
    """
    run_id = _dispatch_skill_run(
        identity, intake_id, "apply-intake-skill", get_settings().model_apply_intake
    )
    bg.add_task(run_apply_intake_skill, identity, intake_id, run_id)
    return {"skill_run_id": run_id, "status": "running"}


@ai_router.post("/{intake_id}/skills/context-pack", status_code=status.HTTP_202_ACCEPTED)
def generate_context_pack(
    intake_id: str,
    bg: BackgroundTasks,
    identity: Identity = Depends(get_current_identity),
) -> dict:
    """Generate the context pack as a background task (AI-02).

    The task writes the ``research_artifacts`` row (``text_content`` + ``embed_status=pending``),
    bumps the intake to ``decomposed`` + ``context_pack_artifact_id``, and finalizes the run
    (``succeeded`` + ``applied_at``). No GCS call (Phase 9 deferral).
    """
    run_id = _dispatch_skill_run(
        identity, intake_id, "context-pack", get_settings().model_context_pack
    )
    bg.add_task(run_context_pack, identity, intake_id, run_id)
    return {"skill_run_id": run_id, "status": "running"}


@ai_router.post("/{intake_id}/skills/structure-answers", status_code=status.HTTP_202_ACCEPTED)
def structure_answers(
    intake_id: str,
    bg: BackgroundTasks,
    identity: Identity = Depends(get_current_identity),
) -> dict:
    """Map a transcript into LLM-extracted ``intake_answers`` as a background task (AI-03).

    Stub handler in 07-05 (signature fixed); 07-07 fills ``run_structure_answers``.
    """
    run_id = _dispatch_skill_run(
        identity, intake_id, "structure-answers", get_settings().model_structure_answers
    )
    bg.add_task(run_structure_answers, identity, intake_id, run_id)
    return {"skill_run_id": run_id, "status": "running"}


@ai_router.post("/{intake_id}/skills/extract-insights", status_code=status.HTTP_202_ACCEPTED)
def extract_insights(
    intake_id: str,
    bg: BackgroundTasks,
    identity: Identity = Depends(get_current_identity),
) -> dict:
    """Distil ``extracted_insights`` from an intake as a background task (AI-03).

    Stub handler in 07-05 (signature fixed); 07-07 fills ``run_extract_insights``.
    """
    run_id = _dispatch_skill_run(
        identity, intake_id, "extract-insights", get_settings().model_extract_insights
    )
    bg.add_task(run_extract_insights, identity, intake_id, run_id)
    return {"skill_run_id": run_id, "status": "running"}


@ai_router.post("/{intake_id}/embeddings", status_code=status.HTTP_202_ACCEPTED)
def generate_embeddings(
    intake_id: str,
    bg: BackgroundTasks,
    identity: Identity = Depends(get_current_identity),
) -> dict:
    """Embed the intake's pending artifacts as a background task (AI-04 write half).

    Stub handler in 07-05 (signature fixed); 07-06 fills ``run_embeddings``.
    """
    run_id = _dispatch_skill_run(
        identity, intake_id, "generate-embeddings", get_settings().model_embeddings
    )
    bg.add_task(run_embeddings, identity, intake_id, run_id)
    return {"skill_run_id": run_id, "status": "running"}


@ai_router.post(
    "/{intake_id}/sources/{source_id}/transcribe", status_code=status.HTTP_202_ACCEPTED
)
def transcribe_source(
    intake_id: str,
    source_id: str,
    bg: BackgroundTasks,
    identity: Identity = Depends(get_current_identity),
) -> dict:
    """Transcribe an intake audio source as a background task (AI-05).

    Stub handler in 07-05 (signature fixed); 07-07 fills ``run_transcribe`` (which fetches
    audio via the ``download_audio_bytes`` seam — faked in tests, real GCS in Phase 9).
    """
    run_id = _dispatch_skill_run(
        identity, intake_id, "transcribe-audio", get_settings().model_transcription
    )
    bg.add_task(run_transcribe, identity, intake_id, source_id, run_id)
    return {"skill_run_id": run_id, "status": "running"}


@ai_router.get("/{intake_id}/search")
def search_intake_artifacts(
    intake_id: str,
    q: str,
    identity: Identity = Depends(get_current_identity),
) -> dict:
    """Semantic search over the caller's space-scoped artifact embeddings (AI-04 read half).

    SYNC + returns results directly (no background task — the search is fast). Dispatches to
    ``app.ai.search.semantic_search`` (stubbed in 07-05; 07-06 wires the query-embed +
    space-prefiltered cosine scan). Tenant comes from the verified ``Identity`` only — a
    cross-tenant row can never be returned (RLS + the explicit space prefilter, T-7-01).
    """
    results = semantic_search(identity, intake_id, q)
    return {"results": results}
