"""
Pydantic v2 schemas for the runs API (D-02 engine toggle + D-09 async job).

CreateRunRequest: what the UI sends when starting a new brief run.
RunResponse: what GET /api/runs/{id} returns for polling.

References:
- 01-CONTEXT.md D-02: engine = "adk" | "sdk" -- required, no default
- 01-CONTEXT.md D-09: status enum queued/running/completed/failed/cancelled
- 01-RESEARCH.md line 513: idempotency_key client-generated UUID
- 01-PATTERNS.md lines 853-862: [UPLOADED DOCUMENTS] marker convention
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class UploadedDoc(BaseModel):
    """One extracted document attached to the brief."""
    filename: str
    text: str  # text-extracted content; Plan 10 cloud-function gen 2 produces this


# D-02 (+ Plan 01-12 A/B arm): the three selectable engines.
Engine = Literal["adk", "sdk", "tribunal"]


class CreateRunRequest(BaseModel):
    """POST /api/runs request body."""
    project_id: uuid.UUID
    brief: str = Field(min_length=1)
    engine: Engine                  # D-02: required, no default
    uploaded_documents: list[UploadedDoc] = []
    idempotency_key: uuid.UUID      # client-generated per RESEARCH line 513


class CreateCompareRequest(BaseModel):
    """POST /api/runs/compare request body -- one A/B fan-out (Plan 01-12).

    Fans the same brief out to >=2 engines as sibling child runs sharing a
    server-assigned comparison_id. Each child's idempotency_key is derived
    deterministically from (comparison_id, engine) so a retried POST returns the
    same children instead of double-charging.
    """
    project_id: uuid.UUID
    brief: str = Field(min_length=1)
    engines: list[Engine] = Field(min_length=2)
    uploaded_documents: list[UploadedDoc] = []
    comparison_id: uuid.UUID        # client-generated; groups the children


class RunResponse(BaseModel):
    """Polling-friendly response for GET /api/runs/{id} and POST /api/runs."""
    id: uuid.UUID
    project_id: uuid.UUID
    engine: Engine
    status: Literal[
        "queued", "running", "completed", "failed", "cancelled", "needs_input"
    ]
    brief: str
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    cost_usd_total: Decimal | None = None
    comparison_id: uuid.UUID | None = None
    # Clarification loop (0005): questions the engine asked when status='needs_input'.
    clarifying_questions: list[str] | None = None

    model_config = {"from_attributes": True}


class AnswerRequest(BaseModel):
    """POST /api/runs/{id}/answer -- the user's reply to clarifying questions.

    Answers are folded into the brief and a NEW run (or new comparison) is queued;
    a fresh run keeps the audit chain clean (Art.12) rather than mutating in place.

    Two shapes:
      - `answers`: a single answer string. Used for a single-engine run, or as a
        fallback shared answer for every arm of a comparison.
      - `answers_by_engine`: per-engine answers, e.g. {"adk": "...", "tribunal": "..."}.
        Each engine's answer is folded into THAT engine's own brief, so the A/B
        arms intentionally diverge. Takes precedence over `answers` per engine.

    At least one of the two must be provided.
    """
    answers: str | None = None
    answers_by_engine: dict[str, str] | None = None

    @model_validator(mode="after")
    def _require_some_answer(self) -> "AnswerRequest":
        has_single = bool(self.answers and self.answers.strip())
        has_map = bool(
            self.answers_by_engine
            and any(v and v.strip() for v in self.answers_by_engine.values())
        )
        if not (has_single or has_map):
            raise ValueError("Provide 'answers' or a non-empty 'answers_by_engine'.")
        return self


class ReportSpecRequest(BaseModel):
    """POST /api/runs/{id}/report-spec and /rewrite -- how to shape the report.

    Drives synthesize_report after the interactive report planner. All fields
    optional; the engine normalises (defaults to all focus areas, standard
    length, key tables) so an empty body still produces a valid report.
    """
    included_focus_areas: list[str] | None = None   # subset of the brief's focus areas
    length: str | None = None                        # brief | standard | comprehensive
    tables: str | None = None                        # none | key | heavy
    instructions: str | None = None                  # free-text shaping notes


class CompareResponse(BaseModel):
    """POST /api/runs/compare + GET /api/runs/compare/{id} response."""
    comparison_id: uuid.UUID
    runs: list[RunResponse]


class RunMetrics(BaseModel):
    """GET /api/runs/{id}/metrics -- per-run A/B comparison metrics.

    citation_recall is the Phase 1 PHASE1-05 gate metric: the fraction of
    persisted claims that carry >=1 source (claim_source row). Computed live
    from the claim / claim_source tables, tenant-scoped via RLS.
    """
    run_id: uuid.UUID
    engine: Engine
    status: Literal[
        "queued", "running", "completed", "failed", "cancelled", "needs_input"
    ]
    cost_usd_total: Decimal | None = None
    elapsed_seconds: int | None = None
    claim_count: int = 0
    grounded_claim_count: int = 0
    citation_recall: float | None = None   # grounded / claim_count; None if 0 claims
    source_count: int = 0                   # distinct sources cited across claims
    # Live stage progress (0006). `stages` is the engine's full ordered schema
    # [{"key","label"}] so the UI can render every stage up front; `current_stage`
    # is the key the engine is on now ('done' when finished, None if not started);
    # `stage_detail` is optional sub-progress {"items":[{"name","status"}]}.
    stages: list[dict] = []
    current_stage: str | None = None
    stage_detail: dict | None = None
