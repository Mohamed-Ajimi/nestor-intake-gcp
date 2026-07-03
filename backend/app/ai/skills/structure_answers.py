"""``structure-answers`` ported to a space-scoped background task (AI-03).

Ports ``docs/supabase-functions/structure-answers.ts`` onto the AI-06 release contract:
read the intake's transcript chunks (+ the template field keys, when a template is
attached) into a plain DTO, call Claude (``claude-sonnet-4-6``) holding NO DB connection,
then in a FRESH tenant session (GUC re-issued — T-7-02) UPSERT the parsed answers into
``intake_answers`` carrying ``extracted_by='llm'``.

Collision handling (Open Q3 / A6 — the marquee parity decision): the legacy edge function
did a plain ``INSERT`` into ``intake_answers``, which would raise ``23505`` against the
existing ``(intake_id, field_key)`` unique constraint when an answer already exists. Rather
than relax the constraint, this port routes every write through
:meth:`IntakeAnswerRepository.upsert_extracted`, which ``ON CONFLICT (intake_id, field_key)
DO UPDATE`` stamps ``extracted_by='llm'`` + ``confidence`` + ``source_chunk_id`` — so a
transcript-derived answer that collides with a manual answer UPDATES it (never duplicates,
never 23505) while the unique constraint stays intact (T-7-14).

Status lifecycle (D-09): the row is created ``running`` by the endpoint and finalized here
to EXACTLY ``"succeeded"`` on a parseable Claude JSON array, or EXACTLY ``"failed"`` (with
``error_message``) when :func:`app.ai.parsing.extract_json_array` cannot find an array.

Grep-guard: constructs NO database engine/session — the injected ``session`` (from
``run_with_session_release``) plus the repository wall (D-01) do every tenant-scoped write;
the Claude client is obtained through ``app.ai.clients`` at CALL TIME (the test monkeypatch
seam on ``app.ai.clients.anthropic_client``). This module contains NO constraint DDL — it
respects the ``(intake_id, field_key)`` unique constraint, it never drops or re-targets it.

Source: docs/supabase-functions/structure-answers.ts (claude-sonnet-4-6, max_tokens 8192,
transcript read :88-101, intake_answers write :131-148; Pitfall 3 / Open Q3 routes the
legacy INSERT through the upsert with extracted_by='llm').
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from app.ai import clients
from app.ai.parsing import estimate_cost_usd, extract_json_array
from app.ai.prompts import STRUCTURE_ANSWERS_SYSTEM_PROMPT
from app.auth.identity import Identity
from app.core.config import get_settings
from app.db.ai_session import run_with_session_release
from app.db.repository import (
    IntakeAnswerRepository,
    IntakeRepository,
    IntakeTemplateRepository,
    SkillRunRepository,
    TranscriptRepository,
)

# max_tokens for the structure-answers call — legacy parity (structure-answers.ts:47).
_STRUCTURE_MAX_TOKENS = 8192


def _now() -> datetime:
    """A timezone-aware UTC ``now`` for the ``completed_at`` stamp."""
    return datetime.now(timezone.utc)


def _coerce_uuid(value: Any) -> uuid.UUID | None:
    """Best-effort coerce an LLM-provided id to a ``UUID`` (untrusted input → None).

    The model's ``source_chunk_id`` is free text from an untrusted array (T-7-04); a value
    that is not a valid UUID is dropped to ``None`` rather than crashing the whole write.
    """
    if value in (None, ""):
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def _split_value(raw: Any) -> tuple[str | None, Any]:
    """Split an LLM answer value into the ``(value, value_json)`` column pair.

    Scalars (str / number / bool) land in the ``value`` Text column; complex values
    (list for multi-choice, dict) land in the ``value_json`` JSONB column — mirroring the
    save-as-you-go shape so the ``intake_answers`` row reads back uniformly.
    """
    if raw is None:
        return None, None
    if isinstance(raw, (dict, list)):
        return None, raw
    if isinstance(raw, str):
        return raw, None
    return str(raw), None


def _flatten_template_keys(schema: Any) -> list[str]:
    """Flatten ``schema.sections[].fields[].key`` into a list of valid field keys.

    Mirrors ``flattenFields`` (structure-answers.ts:33-35). Returns ``[]`` when the intake
    has no template / schema — in which case the write phase accepts the LLM's field_keys
    as-is (an interview intake without a strict template still structures its transcript).
    """
    keys: list[str] = []
    if not isinstance(schema, dict):
        return keys
    for section in schema.get("sections", []) or []:
        if not isinstance(section, dict):
            continue
        for field in section.get("fields", []) or []:
            if isinstance(field, dict) and field.get("key"):
                keys.append(field["key"])
    return keys


def run_structure_answers(identity: Identity, intake_id: Any, run_id: Any) -> dict[str, Any]:
    """Map a transcript into LLM-extracted ``intake_answers`` (AI-03, scoped upsert).

    READ: load the intake's transcript chunks + the template field keys (when a template is
    attached) into a plain DTO — no live ORM rows cross the session boundary. CALL: invoke
    Claude (``claude-sonnet-4-6``, ``max_tokens=8192``, verbatim system prompt) holding NO
    DB connection. WRITE: parse the JSON array and UPSERT each answer per ``field_key`` via
    :meth:`IntakeAnswerRepository.upsert_extracted` (``extracted_by='llm'``, respecting
    the ``(intake_id, field_key)`` unique constraint) — ``succeeded`` on a parseable array, ``failed`` +
    ``error_message`` on a parse error (D-09).
    """
    model = get_settings().model_structure_answers

    def read_fn(session: Any) -> dict[str, Any]:
        intake = IntakeRepository(session, identity).get(intake_id)
        if intake is None:
            # Deleted-intake race after dispatch: don't burn the paid Claude call on a
            # near-empty prompt — carry the missing sentinel through call_fn/write_fn
            # to a failed finalize (mirrors apply.py).
            return {"missing": True}
        # Capture the intake's OWN space for the superadmin write path (a superadmin
        # identity has no space_id of its own — CR-01).
        space_id = str(intake.space_id)
        template_keys: list[str] = []
        if intake.template_id is not None:
            tpl = IntakeTemplateRepository(session, identity).get(intake.template_id)
            if tpl is not None:
                template_keys = _flatten_template_keys(tpl.schema)

        chunks = [
            {"id": str(row.id), "speaker": row.speaker, "text": row.text}
            for row in TranscriptRepository(session, identity).list_for_intake(intake_id)
        ]
        transcript_text = "\n".join(
            f"[chunk:{c['id']}{(' (' + c['speaker'] + ')') if c['speaker'] else ''}] "
            f"{c['text'] or ''}"
            for c in chunks
        )
        user_message = "\n".join(
            [
                "# Template velden",
                json.dumps(template_keys, ensure_ascii=False, indent=2),
                "",
                "# Transcript",
                transcript_text,
            ]
        )
        return {
            "user_message": user_message,
            "valid_keys": template_keys,
            "space_id": space_id,
        }

    def call_fn(dto: dict[str, Any]) -> dict[str, Any]:
        if dto.get("missing"):
            # No Claude call for a vanished intake — surface the failure to write_fn.
            return {"error": "Intake not found"}
        # Obtained through app.ai.clients at CALL TIME (test monkeypatch seam, D-07).
        message = clients.anthropic_client().messages.create(
            model=model,
            max_tokens=_STRUCTURE_MAX_TOKENS,
            system=STRUCTURE_ANSWERS_SYSTEM_PROMPT,
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
        repo = SkillRunRepository(session, identity)
        common = dict(
            output=raw,
            llm_model=model,
            prompt_system=STRUCTURE_ANSWERS_SYSTEM_PROMPT,
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
            repo.patch(run_id, status="failed", error_message=str(exc), **common)
            return {"status": "failed", "error_message": str(exc)}

        valid_keys = set(dto["valid_keys"])
        items: list[dict[str, Any]] = []
        for entry in parsed if isinstance(parsed, list) else []:
            if not isinstance(entry, dict):
                continue
            field_key = entry.get("field_key")
            if not field_key:
                continue
            # When a template is attached, drop keys outside it (legacy validKeys filter);
            # with no template (no keys) accept the LLM's field_keys as-is.
            if valid_keys and field_key not in valid_keys:
                continue
            value, value_json = _split_value(entry.get("value"))
            items.append(
                {
                    "field_key": field_key,
                    "value": value,
                    "value_json": value_json,
                    "confidence": entry.get("confidence"),
                    "source_chunk_id": _coerce_uuid(entry.get("source_chunk_id")),
                }
            )

        # Route the write through the upsert (extracted_by='llm') — respects the existing
        # (intake_id, field_key) unique constraint; never a plain INSERT (no 23505).
        answer_repo = IntakeAnswerRepository(session, identity)
        if identity.role == "superadmin":
            # A superadmin has no own space: write into the intake's OWN space (CR-01).
            # Belt: the read-phase missing sentinel already short-circuits a vanished
            # intake before the Claude call; this guards a NULL-space DTO ever reaching
            # the write (finalize failed, never a NULL space_id write — D-09).
            if not dto["space_id"]:
                msg = "Intake not found — no target space for the superadmin write"
                repo.patch(run_id, status="failed", error_message=msg, **common)
                return {"status": "failed", "error_message": msg}
            answer_repo.upsert_extracted_in_space(
                uuid.UUID(dto["space_id"]), intake_id, items
            )
        else:
            # User path: space_id injected from the verified Identity (TENANT-02).
            answer_repo.upsert_extracted(intake_id, items)
        repo.patch(run_id, status="succeeded", **common)
        return {"status": "succeeded", "inserted": len(items)}

    def on_error(session: Any, dto: Any, exc: Exception) -> dict[str, Any]:
        # D-09 terminal-status guard: any call/write failure (API timeout, 429, empty
        # content array, write crash) finalizes the row failed — never stuck running.
        SkillRunRepository(session, identity).patch(
            run_id, status="failed", error_message=str(exc), completed_at=_now()
        )
        return {"status": "failed", "error_message": str(exc)}

    return run_with_session_release(identity, read_fn, call_fn, write_fn, on_error=on_error)
