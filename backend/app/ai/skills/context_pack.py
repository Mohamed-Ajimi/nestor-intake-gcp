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
   ``context_pack_artifact_id`` at the new artifact — ONLY from an allow-listed source
   status, as a compare-and-swap (D-23.1-05). This bump used to be unconditional, so a
   run launched against a ``delivered`` or ``in_research`` intake dragged it backwards to
   ``decomposed``, re-opening a closed intake and re-arming the paid research trigger;
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
from app.intake_canonical import admin_only_field_keys

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

# The allow-listed source -> target statuses for the `decomposed` bump (D-23.1-05).
# Mirrors the shape of `_REVIEW_TRANSITIONS` in `api/intake_routes.py:1242`; that
# module's maps are NOT touched from here.
#
# There is exactly ONE entry, and it is derived from the caller, not guessed. The
# Generate-context-pack button renders in exactly one phase, `awaiting_context_pack`
# (`frontend/src/components/intake/NextStepBanner.tsx:270`), and that phase is derived
# from `status === "validated_by_client" && !intake.context_pack_artifact_id`
# (`frontend/src/lib/intake-phase.ts:55-58`). So `validated_by_client` is the only
# status from which a human can legitimately launch this skill.
#
# `decomposed` is DELIBERATELY absent: re-running the skill on an already-decomposed
# intake is a no-op the UI never offers (that status maps to `awaiting_research_start`),
# and silently re-linking a fresh artifact would swap the pack a research run was
# briefed on. Do not widen this map without a caller to point at.
_CONTEXT_PACK_TRANSITIONS: dict[str, str] = {"validated_by_client": "decomposed"}


def _now() -> datetime:
    """A timezone-aware UTC ``now`` for ``applied_at`` / ``completed_at``."""
    return datetime.now(timezone.utc)


def _refusal_message(observed_status: str | None, artifact_id: Any) -> str:
    """The sentence an operator reads in ``SkillRunProgress`` when the bump is refused.

    Plain language, not a code: it names what was attempted, the status the intake is
    ACTUALLY in, and the fact that the (already paid for) context pack was kept. This is
    a refusal, not a crash — there is deliberately no traceback in it.
    """
    allowed = ", ".join(sorted(_CONTEXT_PACK_TRANSITIONS))
    observed = observed_status if observed_status else "unknown (the intake is gone)"
    return (
        f"The context pack was generated but not applied: this intake is in status "
        f"'{observed}', and a context pack may only be applied from '{allowed}'. "
        f"The generated pack was kept as research artifact {artifact_id}."
    )


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
    bump the intake to ``decomposed`` with ``context_pack_artifact_id`` **only from an
    allow-listed source status** (D-23.1-05 — ``_CONTEXT_PACK_TRANSITIONS``, enforced as a
    compare-and-swap so the database does the comparison), and finalize the ``skill_runs``
    row (``succeeded`` + ``applied_at`` + token/cost). No object-store API is touched
    (Phase 9 deferral — Pitfall 7).

    A refused transition is NOT an exception: the artifact is kept unlinked and the run
    finalizes ``failed`` with a readable ``error_message``. It is never left ``running``.

    **WITHHELD FROM THE READ (D-23.2-01).** Every answer whose ``field_key`` is in
    ``admin_only_field_keys()`` is dropped before ``user_message`` is built — today the
    four ``strategic_perspective`` fields, whose own schema description reads *"Visible
    only to admin, not to the client and not in the handoff PDF"*. The set is DERIVED from
    the canonical schema (D-23.2-02), so a fifth admin-only field added to
    ``pulse_intake_v1.json`` closes automatically; do not hand-write a key here.

    The filter is **UNCONDITIONAL** and is deliberately NOT keyed on ``identity.role``.
    This skill runs on the superadmin-gated ``ai_router`` (D-23.1-02), so the generator is
    ALWAYS a superadmin and a role-conditional filter would never fire — an inert fix
    behind a green test. The role that matters is the ARTIFACT READER's: the pack lands as
    ``research_artifacts.text_content``, which ``GET /intakes/{id}/context-pack``
    (``api/intake_routes.py:629``) serves to ``role=user`` by design.

    **Output-side scrubbing was considered and REJECTED by D-23.2-01 — do not add one.**
    Not a regex over ``raw``, not a redact pass on the artifact, and not an instruction in
    the system prompt telling the model to omit the strategic analysis. A prompt
    instruction is not a control: the content would still be in the prompt, and the
    model's compliance is not a boundary. Once admin-only prose has been through the
    model it comes back paraphrased, translated and re-framed, and no filter removes that
    reliably. The INPUT is the only place this can be enforced.
    """
    model = get_settings().model_context_pack
    intake_uuid = uuid.UUID(str(intake_id))

    def read_fn(session: Any) -> dict[str, Any]:
        intake = IntakeRepository(session, identity).get(intake_id)
        if intake is None:
            # Deleted-intake race after dispatch: don't burn the paid Claude call on a
            # near-empty prompt and then crash on a NULL space — carry the missing
            # sentinel through call_fn/write_fn to a failed finalize (mirrors apply.py).
            return {"missing": True}
        answer_rows = IntakeAnswerRepository(session, identity).list_for_intake(intake_id)
        # D-23.2-01 — drop admin-only answers BEFORE the prompt is built. UNCONDITIONAL, and
        # deliberately NOT keyed on identity.role: this skill runs on the superadmin-gated
        # ai_router (D-23.1-02), so a role check would never fire. The role that matters is
        # the ARTIFACT READER's — the pack's text_content is served to role=user by
        # GET /intakes/{id}/context-pack (intake_routes.py:629). Filtering the INPUT is the
        # only reliable control: once admin-only prose is laundered through the model, no
        # output filter can remove the paraphrase (23.2-CONTEXT § 2, hop 3).
        hidden = admin_only_field_keys()
        answers = [
            {"field_key": row.field_key, "value": row.value, "value_json": row.value_json}
            for row in answer_rows
            if row.field_key not in hidden
        ]
        client_name = intake.client_name
        # The artifact's space comes from the intake's OWN space (the superadmin path has
        # no identity.space_id, so the row must carry the intake's space explicitly).
        space_id = str(intake.space_id)
        user_message = _CONTEXT_PACK_USER_PREFIX + _format_intake_markdown(client_name, answers)
        return {
            "client_name": client_name,
            "space_id": space_id,
            "answers": answers,
            "user_message": user_message,
        }

    def call_fn(dto: dict[str, Any]) -> dict[str, Any]:
        if dto.get("missing"):
            # No Claude call for a vanished intake — surface the failure to write_fn.
            return {"error": "Intake not found"}
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
        if result.get("error"):
            # Missing-intake sentinel: finalize failed with a clear diagnostic (D-09) —
            # never a cryptic TypeError from a NULL-space artifact insert.
            SkillRunRepository(session, identity).patch(
                run_id,
                status="failed",
                error_message=result["error"],
                completed_at=_now(),
            )
            return {"status": "failed", "error_message": result["error"]}

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

        # 2. Bump the intake to the in-scope ceiling + link the artifact — but ONLY from
        #    an allow-listed source status, as ONE conditional UPDATE per candidate
        #    (D-23.1-05). The comparison belongs to the DATABASE: a get()-then-patch(),
        #    even in this transaction, is still read-then-write under READ COMMITTED.
        #    The loop stops at the first hit, so widening the map later is a one-line
        #    dict change and not a code change.
        intake_repo = IntakeRepository(session, identity)
        applied = False
        for source_status, target_status in _CONTEXT_PACK_TRANSITIONS.items():
            if intake_repo.patch_if(
                intake_id,
                expected={"status": source_status},
                status=target_status,
                context_pack_artifact_id=artifact.id,
            ):
                applied = True
                break

        if not applied:
            # REFUSED. Do NOT raise: `run_context_pack` executes in a BackgroundTasks job
            # AFTER the 202 has been sent, so nobody is listening, and routing this
            # through `on_error` would roll back the artifact insert above.
            #
            # The artifact STAYS. By the time we get here the Claude call has been made
            # and paid for; `research_artifacts` is append-only history that
            # `GET /intakes/{id}/context-pack` already serves as {latest, history}, so an
            # unlinked row is a shape the API already handles. Discarding a paid
            # generation to punish a status mismatch costs money and teaches nobody
            # anything — do not "clean this up".
            #
            # This re-read exists ONLY to name the observed status in the message. It is
            # NOT the precondition — the precondition was the WHERE clause above.
            observed = intake_repo.get(intake_id)
            observed_status = None if observed is None else str(observed.status)
            message = _refusal_message(observed_status, artifact.id)
            # Finalize in THIS control flow, in THIS transaction. A bare early return
            # would leave the run `running` forever (T-23.1-14): the orphan sweep would
            # only clear it 30 minutes later, and once 23.1-12's partial unique index on
            # (intake_id, skill) WHERE status='running' lands, that orphan would block
            # every future context-pack run for this intake. `applied_at` is deliberately
            # NOT set — nothing was applied (D-09).
            SkillRunRepository(session, identity).patch(
                run_id,
                status="failed",
                error_message=message,
                output=f"Context pack kept as research artifact {artifact.id}.\n\n{raw}",
                llm_model=model,
                prompt_system=CONTEXT_PACK_SKILL_PROMPT,
                prompt_user=dto["user_message"],
                input_tokens=result["input_tokens"],
                output_tokens=result["output_tokens"],
                cost_estimate_usd=cost,
                completed_at=_now(),
            )
            return {
                "status": "failed",
                "error_message": message,
                "artifact_id": str(artifact.id),
            }

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

    def on_error(session: Any, dto: Any, exc: Exception) -> dict[str, Any]:
        # D-09 terminal-status guard: any call/write failure (API timeout, 429, empty
        # content array, deleted-intake race in the write) finalizes the row failed.
        SkillRunRepository(session, identity).patch(
            run_id, status="failed", error_message=str(exc), completed_at=_now()
        )
        return {"status": "failed", "error_message": str(exc)}

    return run_with_session_release(identity, read_fn, call_fn, write_fn, on_error=on_error)
