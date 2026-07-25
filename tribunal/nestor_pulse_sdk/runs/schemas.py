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

# The FULL run-status vocabulary -- MUST stay in sync with the DB CHECK
# (ck_run_status, db/models/run.py). 'needs_input' is the clarification pause
# (0005); 'needs_report_spec' is the interactive report-shaping pause (the
# report planner parks the run there until POST /{id}/report-spec). Response
# schemas validate FROM the DB row, so every DB-legal status must be listed --
# a missing literal turns reads of a paused run into HTTP 500s (CR-03).
RunStatus = Literal[
    "queued", "running", "completed", "failed", "cancelled",
    "needs_input", "needs_report_spec",
]


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
    # RunStatus mirrors the DB CHECK (ck_run_status, db/models/run.py): the
    # interactive report-shaping pause parks a run at 'needs_report_spec'
    # (submit_report_spec resumes it). Omitting it here made every read of a
    # paused run -- and GET /api/runs for the whole tenant -- 500 on pydantic
    # validation (CR-03). Keep this Literal in sync with the DB CHECK.
    status: RunStatus
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


class StageRetry(BaseModel):
    """Retry sub-state for one enriched stage_detail item (D15 feed).

    Present only when a call was retried; ALL fields optional so the recorded
    4cbb5311 run (which has no retries) still validates.
    """
    attempt: int | None = None
    max: int | None = None
    wait_s: float | None = None


class StageDetailItem(BaseModel):
    """One enriched stage_detail feed item (D15 Feed Data Model, Phase 15 SC2).

    The BASE feed contract is `{name, status}`. Plan 15-01's fixture and the
    15.2 engine enrich each item with per-row cost / task_prompt / facts / retry
    / audit_id. EVERY enriched field is Optional (default None) so today's
    recorded stage_detail -- and any legacy run's flat rows -- still validate
    (additive, D-07 contract). `status` widens the base to the D15 lifecycle.
    """
    name: str
    status: Literal["running", "done", "retry", "failed", "pending"] | None = None
    task_prompt: str | None = None
    cost_usd: str | None = None          # Decimal serialised as string in JSONB
    facts: int | None = None
    retry: StageRetry | None = None
    audit_id: str | None = None          # drill-down target for GET /audit/{audit_id}

    model_config = {"extra": "allow"}


class StageSummary(BaseModel):
    """Optional per-stage rollup carried alongside a stage's items."""
    duration_s: float | None = None
    actions: int | None = None
    items_read: int | None = None
    cost_usd: str | None = None          # Decimal serialised as string in JSONB


class StageDetail(BaseModel):
    """One stage bucket in the enriched stage_detail map: items + optional summary."""
    items: list[StageDetailItem] = []
    summary: StageSummary | None = None

    model_config = {"extra": "allow"}


class RunMetrics(BaseModel):
    """GET /api/runs/{id}/metrics -- per-run A/B comparison metrics.

    citation_recall is the Phase 1 PHASE1-05 gate metric: the fraction of
    persisted claims that carry >=1 source (claim_source row). Computed live
    from the claim / claim_source tables, tenant-scoped via RLS.
    """
    run_id: uuid.UUID
    engine: Engine
    # Full DB-legal vocabulary incl. needs_report_spec (CR-03 -- see RunStatus).
    status: RunStatus
    cost_usd_total: Decimal | None = None
    elapsed_seconds: int | None = None
    claim_count: int = 0
    grounded_claim_count: int = 0
    citation_recall: float | None = None   # grounded / claim_count; None if 0 claims
    source_count: int = 0                   # distinct sources cited across claims
    # Live stage progress (0006). `stages` is the engine's full ordered schema
    # [{"key","label"}] so the UI can render every stage up front; `current_stage`
    # is the key the engine is on now ('done' when finished, None if not started).
    #
    # `stage_detail` is the enriched sub-progress map (Phase 15 SC2). Each stage
    # bucket is a `StageDetail` (items + optional summary) whose items carry the
    # enriched per-row cost_usd / task_prompt / facts / retry / audit_id fields
    # (see StageDetailItem). We keep the wire type as an open `dict` so
    # get_run_metrics returns `run.stage_detail` JSONB VERBATIM -- the enriched
    # fields ride through for free (D-07 contract; NO field stripping, and legacy
    # flat {name,status} rows still validate). StageDetail/StageDetailItem are the
    # documented schema the D15 feed renderer (Plan 15-05) reads.
    stages: list[dict] = []
    current_stage: str | None = None
    stage_detail: dict[str, StageDetail] | dict | None = None


class VerificationVerdictItem(BaseModel):
    """One verdict row in the verification report (never leaks tenant_id/hashes).

    NOTE (15.1): this model has NO `model_config`, so pydantic v2's default
    `extra="ignore"` applies -- any key the shaper emits that is not declared
    HERE is silently dropped on the way out of the API. Declare, don't assume.
    """
    claim_id: str | None = None
    verdict: str
    confidence: str | None = None
    evidence_refs: list | None = None
    reconciliation: dict | None = None
    # G-07 (plan 15.1-03): the caveat the skeptic must supply with a `superseded`
    # verdict (what changed, and when). Declared so it survives the round trip
    # rather than being dropped by extra="ignore".
    superseded_note: str | None = None


class VerificationVerdictGroups(BaseModel):
    """Verdicts split by verdict class (support / refute / insufficient / superseded).

    NOTE (15.1): no `model_config` here either -- pydantic v2 defaults to
    `extra="ignore"`, so a new verdict class needs an EXPLICIT field or the API
    response silently loses it even though the shaper produced it.

    `superseded` here is the G-06 VERDICT CLASS. It is NOT the top-level
    `VerificationReport.superseded` list, which carries reconciliation-derived
    scoped/temporal findings. Same word, different question.
    """
    support: list[VerificationVerdictItem] = []
    refute: list[VerificationVerdictItem] = []
    insufficient: list[VerificationVerdictItem] = []
    superseded: list[VerificationVerdictItem] = []


class VerificationUnverified(BaseModel):
    """Honest UNVERIFIED accounting: claims with NO verdict row."""
    count: int = 0
    claims_with_verdict: int = 0
    total_claims: int = 0


class VerificationTrueCost(BaseModel):
    """True cost of the run: total + a pending flag (Plan 15-02 reconciliation)."""
    cost_usd_total: str | None = None    # Decimal serialised as string
    cost_pending: bool = False


class VerificationCitation(BaseModel):
    """One numbered [n] citation entry (SC4 / D13).

    Mirrors the entries produced by `citations.numbering.number_citations`:
    numbers are GENERATED from claim/claim_source DB ordering (never the model),
    so every [n] the operator surface renders resolves to a real source. The
    frontend opens the CitationPanel via `source_id` (proxied GET /api/sources/
    {source_id}); `first_claim_id` lets the report body attach markers to the
    verdict rows of the claim that introduced the source.
    """
    n: int
    source_id: str
    title: str | None = None
    url: str | None = None
    provider: str | None = None
    publication_date: str | None = None   # source.fetched_at ISO (date proxy, A3)
    quality_tier: int = 3                 # 1 official / 2 press / 3 blog-or-other
    single_source: bool = False
    first_claim_id: str | None = None
    first_claim_position: int | None = None

    model_config = {"extra": "allow"}


class VerificationReport(BaseModel):
    """GET /api/runs/{id}/verification -- the operator's post-run truth surface.

    Shaped by verification.report.build_verification_report from PERSISTED rows
    (verification_verdict + run.verification_summary + run cost) -- never from a
    GCS blob. Carries all six STAKEHOLDER-NOTES §2026-07-24 content areas:
    funnel, per-class verdicts, refuted-with-evidence, superseded/scoped,
    reconciled contradictions, an honest unverified list, and true cost.

    `extra="allow"` so the shaper's `counts` rollup rides through without a
    field-by-field mirror.
    """
    funnel: dict | None = None
    # G-08 (15.1): the three honest buckets -- checked / not_checkable (with the
    # specific reason) / should_have_been_checked. None for a pre-15.1 run that
    # carries no gate data, which is NOT the same as a clean bucket 3.
    accounting: dict | None = None
    # G-10 (15.1): a run whose fact-checking was gutted keeps status `completed`
    # (four endpoints gate on that literal; 15.2's R6 promotes the marker into a
    # real terminal state) but says so here, in words, at the top of the report.
    verification_degraded: bool = False
    verification_degraded_text: str | None = None
    verdicts: VerificationVerdictGroups = VerificationVerdictGroups()
    refuted: list[VerificationVerdictItem] = []
    superseded: list[VerificationVerdictItem] = []
    reconciled: list[VerificationVerdictItem] = []
    unverified: VerificationUnverified = VerificationUnverified()
    true_cost: VerificationTrueCost = VerificationTrueCost()
    # SC4 / D13: the numbered [n] citations list (DB-generated, all-resolving).
    citations: list[VerificationCitation] = []

    model_config = {"extra": "allow"}


class AuditBody(BaseModel):
    """GET /api/runs/{id}/audit/{audit_id} -- the feed's audit_id drill-down body.

    Returns the ALREADY-REDACTED request/response of one LLM call, read back from
    GCS (download_audit_body). The bodies were redacted at upload, so no provider
    key is re-exposed. hash / prev_hash are NEVER included (mirrors
    audit.api._audit_row_dto's omission -- chain integrity is only checkable via
    /api/audit/verify/{run_id}, never by exposing raw hashes).
    """
    audit_id: str
    provider: str | None = None
    model: str | None = None
    request: dict | None = None
    response: dict | None = None
