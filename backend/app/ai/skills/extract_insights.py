"""``extract-insights`` ported to a space-scoped background task (AI-03).

Ports ``docs/supabase-functions/extract-insights.ts`` onto the AI-06 release contract:
read the intake's transcript chunks + answers into a plain DTO, call Claude
(``claude-sonnet-4-6``, ``max_tokens=4096``) holding NO DB connection, then in a FRESH
tenant session (GUC re-issued — T-7-02) write the parsed insights into
``extracted_insights`` — each row carrying the caller's ``space_id`` (T-7-03).

Insight kinds: the legacy prompt advertises the 13 canonical kinds
(``INSIGHT_KINDS`` — pain_point, goal, stakeholder, … aha_moment) but the edge function did
NOT drop rows whose ``kind`` fell outside that list — it inserted whatever Claude returned.
This port keeps that behaviour: the ``kind`` is stored verbatim (the list drives the PROMPT,
not a write-time filter), so a kind the model phrases differently is never silently lost.

Status lifecycle (D-09): the row is created ``running`` by the endpoint and finalized here
to EXACTLY ``"succeeded"`` on a parseable Claude JSON array, or EXACTLY ``"failed"`` (with
``error_message``) when :func:`app.ai.parsing.extract_json_array` cannot find an array.

Grep-guard: constructs NO database engine/session — the injected ``session`` (from
``run_with_session_release``) plus the repository wall (D-01) do every tenant-scoped write;
the Claude client is obtained through ``app.ai.clients`` at CALL TIME (the test monkeypatch
seam on ``app.ai.clients.anthropic_client``). The insight ``space_id`` is injected by the
repository from the verified Identity (user path) / the intake's own space (superadmin
path) — never read from the LLM array (T-7-03).

Source: docs/supabase-functions/extract-insights.ts (claude-sonnet-4-6, max_tokens 4096
:104, 13 kinds :22-26, extracted_insights write :160-170; RESEARCH §5 :448-453).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from app.ai import clients
from app.ai.parsing import estimate_cost_usd, extract_json_array
from app.ai.prompts import EXTRACT_INSIGHTS_SYSTEM_PROMPT
from app.auth.identity import Identity
from app.core.config import get_settings
from app.db.ai_session import run_with_session_release
from app.db.repository import (
    ExtractedInsightRepository,
    IntakeAnswerRepository,
    IntakeRepository,
    SkillRunRepository,
    TranscriptRepository,
)

# max_tokens for the extract-insights call — legacy parity (extract-insights.ts:104).
_EXTRACT_MAX_TOKENS = 4096


def _now() -> datetime:
    """A timezone-aware UTC ``now`` for the ``completed_at`` stamp."""
    return datetime.now(timezone.utc)


def _coerce_uuid(value: Any) -> uuid.UUID | None:
    """Best-effort coerce an LLM-provided id to a ``UUID`` (untrusted input → None).

    The model's ``source_chunk_id`` / ``source_answer_id`` are free text from an untrusted
    array (T-7-04); a value that is not a valid UUID is dropped to ``None`` rather than
    crashing the whole write.
    """
    if value in (None, ""):
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def _value_text(raw: Any) -> str:
    """Render an answer value as prompt text (mirrors ``valueText`` :63-67)."""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        return ", ".join(str(item) for item in raw)
    if raw is None:
        return ""
    return json.dumps(raw, ensure_ascii=False)


def run_extract_insights(identity: Identity, intake_id: Any, run_id: Any) -> dict[str, Any]:
    """Distil ``extracted_insights`` rows from an intake (AI-03, 13 kinds, scoped).

    READ: load the intake's answers + transcript chunks into a plain DTO (incl. the intake's
    own ``space_id`` for the superadmin write path). CALL: invoke Claude
    (``claude-sonnet-4-6``, ``max_tokens=4096``, verbatim system prompt) holding NO DB
    connection. WRITE: parse the JSON array and insert one ``extracted_insights`` row per
    insight via :class:`ExtractedInsightRepository` (``space_id`` injected from Identity) —
    ``succeeded`` on a parseable array, ``failed`` + ``error_message`` on a parse error (D-09).
    """
    model = get_settings().model_extract_insights

    def read_fn(session: Any) -> dict[str, Any]:
        intake = IntakeRepository(session, identity).get(intake_id)
        if intake is None:
            # Deleted-intake race after dispatch: don't burn the paid Claude call on a
            # near-empty prompt — carry the missing sentinel through call_fn/write_fn
            # to a failed finalize (mirrors apply.py).
            return {"missing": True}
        space_id = str(intake.space_id)
        client_name = intake.client_name

        answers = [
            {"id": str(row.id), "field_key": row.field_key, "value": row.value}
            for row in IntakeAnswerRepository(session, identity).list_for_intake(intake_id)
        ]
        chunks = [
            {"id": str(row.id), "speaker": row.speaker, "text": row.text}
            for row in TranscriptRepository(session, identity).list_for_intake(intake_id)
        ]

        lines: list[str] = ["# Klantcontext"]
        if client_name:
            lines.append(f"Klant: {client_name}")
        lines.append("")
        lines.append("# Antwoorden uit de intake")
        for answer in answers:
            lines.append(f"[answer:{answer['id']}] {answer['field_key']}: "
                         f"{_value_text(answer['value'])}")
        if chunks:
            lines.append("")
            lines.append("# Transcript chunks")
            for chunk in chunks:
                speaker = f" ({chunk['speaker']})" if chunk["speaker"] else ""
                lines.append(f"[chunk:{chunk['id']}{speaker}] {chunk['text'] or ''}")

        return {"user_message": "\n".join(lines), "space_id": space_id}

    def call_fn(dto: dict[str, Any]) -> dict[str, Any]:
        if dto.get("missing"):
            # No Claude call for a vanished intake — surface the failure to write_fn.
            return {"error": "Intake not found"}
        # Obtained through app.ai.clients at CALL TIME (test monkeypatch seam, D-07).
        message = clients.anthropic_client().messages.create(
            model=model,
            max_tokens=_EXTRACT_MAX_TOKENS,
            system=EXTRACT_INSIGHTS_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": dto["user_message"]}],
        )
        return {
            "raw": message.content[0].text,
            "input_tokens": message.usage.input_tokens,
            "output_tokens": message.usage.output_tokens,
        }

    def write_fn(session: Any, dto: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        if result.get("error"):
            # Missing-intake sentinel: finalize failed with a clear diagnostic (D-09) —
            # never an FK-violation dump in the operator-facing error_message.
            SkillRunRepository(session, identity).patch(
                run_id,
                status="failed",
                error_message=result["error"],
                completed_at=_now(),
            )
            return {"status": "failed", "error_message": result["error"]}

        raw = result["raw"]
        cost = estimate_cost_usd(result["input_tokens"], result["output_tokens"])
        run_repo = SkillRunRepository(session, identity)
        common = dict(
            output=raw,
            llm_model=model,
            prompt_system=EXTRACT_INSIGHTS_SYSTEM_PROMPT,
            prompt_user=dto["user_message"],
            input_tokens=result["input_tokens"],
            output_tokens=result["output_tokens"],
            cost_estimate_usd=cost,
            completed_at=_now(),
        )

        try:
            parsed = extract_json_array(raw)
        except ValueError as exc:
            # D-09 failure path: no JSON array in the Claude output → failed + message.
            run_repo.patch(run_id, status="failed", error_message=str(exc), **common)
            return {"status": "failed", "error_message": str(exc)}

        insight_repo = ExtractedInsightRepository(session, identity)
        is_super = identity.role == "superadmin"
        space_uuid = uuid.UUID(dto["space_id"]) if dto["space_id"] else None
        if is_super and space_uuid is None:
            # Belt: the read-phase missing sentinel already short-circuits a vanished
            # intake before the Claude call; this guards a NULL-space DTO ever reaching
            # the superadmin write path (never a NULL-space create() crash).
            msg = "Intake not found — no target space for the superadmin write"
            run_repo.patch(run_id, status="failed", error_message=msg, **common)
            return {"status": "failed", "error_message": msg}
        inserted = 0
        for entry in parsed if isinstance(parsed, list) else []:
            if not isinstance(entry, dict):
                continue
            values = dict(
                intake_id=intake_id,
                kind=entry.get("kind"),
                label=entry.get("label"),
                summary=entry.get("summary"),
                confidence=entry.get("confidence"),
                supporting_text=entry.get("supporting_text"),
                source_chunk_id=_coerce_uuid(entry.get("source_chunk_id")),
                source_answer_id=_coerce_uuid(entry.get("source_answer_id")),
                llm_model=model,
            )
            # space_id is injected by the repo from the verified Identity (user) or set to
            # the intake's own space (superadmin) — NEVER read from the LLM array (T-7-03).
            if is_super:
                insight_repo.create_in_space(space_uuid, **values)
            else:
                insight_repo.create(**values)
            inserted += 1

        run_repo.patch(run_id, status="succeeded", **common)
        return {"status": "succeeded", "inserted": inserted}

    def on_error(session: Any, dto: Any, exc: Exception) -> dict[str, Any]:
        # D-09 terminal-status guard: any call/write failure (API timeout, 429, empty
        # content array, write crash) finalizes the row failed — never stuck running.
        SkillRunRepository(session, identity).patch(
            run_id, status="failed", error_message=str(exc), completed_at=_now()
        )
        return {"status": "failed", "error_message": str(exc)}

    return run_with_session_release(identity, read_fn, call_fn, write_fn, on_error=on_error)
