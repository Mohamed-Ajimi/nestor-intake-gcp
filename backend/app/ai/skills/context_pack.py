"""``generate-context-pack`` ported to a space-scoped background task (AI-02).

Ports ``docs/supabase-functions/generate-context-pack.ts`` onto the AI-06 release
contract: read the intake inputs into a plain DTO, call Claude (``claude-sonnet-4-5``)
holding NO connection, then in a FRESH tenant session (GUC re-issued — T-7-02) write the
result.

The WRITE does three things the legacy did, MINUS the object-store write (Pitfall 7 — the
Cloud Storage object is Phase 9 / D-08):

1. insert a ``research_artifacts`` row carrying ``text_content`` (the briefing markdown)
   and ``embed_status='pending'`` (so the 07-06 embed step can pick it up), leaving
   ``storage_bucket`` / ``storage_path`` NULL — the pack is fully usable from
   ``text_content`` without any stored object;
2. advance the intake to ``status='decomposed'`` (the in-scope flow ceiling) and point
   ``context_pack_artifact_id`` at the new artifact;
3. finalize the ``skill_runs`` row: ``status='succeeded'`` + ``applied_at`` (D-09 — marks
   the finalized output) + the model id / prompts / token+cost columns.

Grep-guard: constructs NO engine/session — the injected ``session`` (from
``run_with_session_release``) plus the repository wall do every tenant-scoped write; the
artifact ``space_id`` is taken from the READ-phase DTO (the intake's own space) so the
superadmin path (no own space) still lands the row in the right tenant under the 0003
bypass, and the user path matches its GUC.

Source: generate-context-pack.ts (research_artifacts write :198-216, decomposed bump +
context_pack_artifact_id :219-227, applied_at :230-234; the object-store write :191-195
is DEFERRED to Phase 9).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from app.ai import clients
from app.ai.parsing import estimate_cost_usd
from app.ai.prompts import CONTEXT_PACK_SKILL_PROMPT
from app.auth.identity import Identity
from app.core.config import get_settings
from app.db.ai_session import run_with_session_release
from app.db.models.research import ResearchArtifact
from app.db.repository import (
    IntakeAnswerRepository,
    IntakeRepository,
    SkillRunRepository,
)

# max_tokens for the context-pack call — legacy parity (generate-context-pack.ts:363).
_CONTEXT_PACK_MAX_TOKENS = 8192

# The instruction prefix the legacy prepended to the rendered intake markdown
# (generate-context-pack.ts:367) — carried verbatim.
_CONTEXT_PACK_USER_PREFIX = (
    "Genereer het Context Pack op basis van deze gevalideerde intake. Output: "
    "STRIKT markdown volgens de template. Geen JSON, geen ingeleidende tekst. "
    "Sectie 12 (Onderzoeksvragen verbatim) niet zelf schrijven — die wordt apart "
    "toegevoegd.\n\n---\n\n"
)


def _now() -> datetime:
    """A timezone-aware UTC ``now`` for ``applied_at`` / ``completed_at``."""
    return datetime.now(timezone.utc)


def _format_intake_markdown(client_name: str | None, answers: list[dict[str, Any]]) -> str:
    """Render the intake answers as the markdown the context-pack generator consumes."""
    lines = [
        f"# Intake — {client_name or ''}",
        "",
        f"**Klantnaam**: {client_name or ''}",
        "",
        "---",
        "",
    ]
    for answer in answers:
        value = answer.get("value")
        if (value is None or value == "") and answer.get("value_json") is not None:
            value = json.dumps(answer["value_json"], ensure_ascii=False)
        if value in (None, ""):
            continue
        lines.append(f"**{answer['field_key']}**: {value}")
    return "\n".join(lines)


def run_context_pack(identity: Identity, intake_id: Any, run_id: Any) -> dict[str, Any]:
    """Generate the context pack and finalize the artifact + intake + run (AI-02).

    READ: load the intake (its space + client name) and answers into a plain DTO. CALL:
    Claude builds the briefing markdown holding NO connection. WRITE: insert the
    ``research_artifacts`` row (``text_content`` + ``embed_status='pending'``, no object),
    bump the intake to ``decomposed`` with ``context_pack_artifact_id``, and finalize the
    ``skill_runs`` row (``succeeded`` + ``applied_at`` + token/cost). No object-store API is
    touched (Phase 9 deferral — Pitfall 7).
    """
    model = get_settings().model_context_pack
    intake_uuid = uuid.UUID(str(intake_id))

    def read_fn(session: Any) -> dict[str, Any]:
        intake = IntakeRepository(session, identity).get(intake_id)
        answer_rows = IntakeAnswerRepository(session, identity).list_for_intake(intake_id)
        answers = [
            {"field_key": row.field_key, "value": row.value, "value_json": row.value_json}
            for row in answer_rows
        ]
        client_name = intake.client_name if intake is not None else None
        # The artifact's space comes from the intake's OWN space (the superadmin path has
        # no identity.space_id, so the row must carry the intake's space explicitly).
        space_id = str(intake.space_id) if intake is not None else None
        user_message = _CONTEXT_PACK_USER_PREFIX + _format_intake_markdown(client_name, answers)
        return {
            "client_name": client_name,
            "space_id": space_id,
            "answers": answers,
            "user_message": user_message,
        }

    def call_fn(dto: dict[str, Any]) -> dict[str, Any]:
        message = clients.anthropic_client().messages.create(
            model=model,
            max_tokens=_CONTEXT_PACK_MAX_TOKENS,
            system=CONTEXT_PACK_SKILL_PROMPT,
            messages=[{"role": "user", "content": dto["user_message"]}],
        )
        return {
            "raw": message.content[0].text,
            "input_tokens": message.usage.input_tokens,
            "output_tokens": message.usage.output_tokens,
        }

    def write_fn(session: Any, dto: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        raw = result["raw"]
        cost = estimate_cost_usd(result["input_tokens"], result["output_tokens"])

        # 1. Insert the artifact (text_content now; storage refs deferred to Phase 9).
        artifact = ResearchArtifact(
            space_id=uuid.UUID(dto["space_id"]),
            intake_id=intake_uuid,
            source="context-pack-generator",
            artifact_type="note",
            text_content=raw,
            embed_status="pending",
            notes="Context Pack — auto-generated briefing voor Nestor onderzoeker",
        )
        session.add(artifact)
        session.flush()  # populate artifact.id before linking it onto the intake

        # 2. Bump the intake to the in-scope ceiling + link the artifact.
        IntakeRepository(session, identity).patch(
            intake_id, status="decomposed", context_pack_artifact_id=artifact.id
        )

        # 3. Finalize the skill_runs row (D-09: succeeded + applied_at marks finalized).
        SkillRunRepository(session, identity).patch(
            run_id,
            status="succeeded",
            output=raw,
            llm_model=model,
            prompt_system=CONTEXT_PACK_SKILL_PROMPT,
            prompt_user=dto["user_message"],
            input_tokens=result["input_tokens"],
            output_tokens=result["output_tokens"],
            cost_estimate_usd=cost,
            applied_at=_now(),
            completed_at=_now(),
        )
        return {"status": "succeeded", "artifact_id": str(artifact.id)}

    return run_with_session_release(identity, read_fn, call_fn, write_fn)
