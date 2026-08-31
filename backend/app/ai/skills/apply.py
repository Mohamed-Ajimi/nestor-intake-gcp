"""``apply-intake-skill`` ported to a space-scoped background task (AI-01).

The legacy Supabase edge function (``docs/supabase-functions/apply-intake-skill.ts``)
ran the long Claude call inline while holding the DB connection. Here it is the
WRITE half of the AI-06 release contract: :func:`run_apply_intake_skill` runs through
:func:`app.db.ai_session.run_with_session_release` so the connection is RELEASED across
the ~120s Claude call and the per-space GUC is RE-ISSUED on the write session
structurally (T-7-02 / T-7-06).

Status lifecycle (D-09, the marquee cross-component contract): the row is created
``running`` by the endpoint (``create_running_skill_run``) and finalized by this task to
EXACTLY ``"succeeded"`` on a parseable Claude JSON object, or EXACTLY ``"failed"`` (with
``error_message``) when :func:`app.ai.parsing.extract_json` cannot find a JSON object —
never a synonym (the frontend ``SkillRunProgress`` polls these literals verbatim).

``output_parsed`` keeps the legacy JSON shape (``decision_or_goal`` / ``research_questions_refined``
/ ``additional_questions`` / ``dropped_questions`` / ``bias_radar`` / ``blind_spots`` /
``gaps_flagged``) so the existing ``AIReviewPanel`` accept/edit/reject UX renders unchanged —
this task stores whatever Claude returned VERBATIM (it does NOT auto-apply it to
``research_questions``; a human reviews it). ``applied_at`` is deliberately left null —
that marks the human accept step, not the AI run.

Grep-guard: this module constructs NO database engines or sessions. Every tenant-scoped
read/write goes through the injected ``session`` (opened by ``run_with_session_release``)
and the existing repository wall (D-01); the Claude client is obtained through
``app.ai.clients`` at CALL TIME (so the test monkeypatch on
``app.ai.clients.anthropic_client`` takes effect).

Source: docs/supabase-functions/apply-intake-skill.ts (status lifecycle :171-273,
max_tokens 8192, output_parsed + prompt/token/cost writes) + 07-RESEARCH Pattern 2 / §1.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.ai import clients
from app.ai.parsing import estimate_cost_usd, extract_json
from app.ai.prompts import NESTOR_INTAKE_SKILL_PROMPT
from app.auth.identity import Identity
from app.core.config import get_settings
from app.db.ai_session import run_with_session_release
from app.db.repository import (
    IntakeAnswerRepository,
    IntakeRepository,
    SkillRunRepository,
)

# max_tokens for the apply call. Raised from the legacy 8192
# (apply-intake-skill.ts:229) by quick task 260831-lm4: the system prompt now
# requires every GENERATED string in nl+fr+en, so the JSON object the model has to
# fit is roughly 3x its old size on the authored fields.
#
# ⚠ DO NOT RAISE THIS FURTHER WITHOUT SWITCHING TO STREAMING. The call below is
# NON-STREAMING (``messages.create``), and the Anthropic SDK REFUSES a
# non-streaming request whose max_tokens exceeds ~21333 output tokens. 24576 (a
# naive 3x) would therefore not be a bigger budget — it would break the call
# outright. 20000 sits under that ceiling with ~2.4x headroom on a payload that
# grows by LESS than 3x, because the client's own echoed words (``current`` /
# ``original``) deliberately stay scalar and untranslated (D-2).
_APPLY_MAX_TOKENS = 20000

# The SDK's non-streaming output ceiling, named so the number above is checkable
# rather than folklore. Anything at or above this must stream instead.
_ANTHROPIC_NON_STREAMING_MAX_TOKENS = 21333

# The instruction prefix prepended to the rendered intake markdown. The legacy
# (apply-intake-skill.ts:234) wrote it in Dutch; it is ENGLISH here because it is an
# instruction to the MODEL, not client-facing copy, and a Dutch instruction wrapper
# reinforced exactly the Dutch-only output this skill was fixed to stop producing
# (quick task 260831-lm4). The meaning is unchanged.
_APPLY_USER_PREFIX = (
    "Apply the nestor-intake skill to this intake. Output: STRICT JSON per the "
    "schema in the system prompt. No markdown, no explanation, only the JSON "
    "object.\n\n---\n\n"
)


def _now() -> datetime:
    """A timezone-aware UTC ``now`` for the ``completed_at`` stamp."""
    return datetime.now(timezone.utc)


def _format_intake_markdown(client_name: str | None, answers: list[dict[str, Any]]) -> str:
    """Render the intake answers as the markdown the legacy fed Claude (parity-ish).

    The GCP backend has no per-section template render here (the canonical template is
    shared product config), so this renders ``field_key: value`` pairs in answer order —
    enough for the decomposer, and the system prompt carries the strict-JSON contract.
    """
    lines = [
        f"# Intake — {client_name or '(onbekende klant)'}",
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


def run_apply_intake_skill(identity: Identity, intake_id: Any, run_id: Any) -> dict[str, Any]:
    """Run apply-intake-skill as the WRITE half of the AI-06 release contract (AI-01).

    READ: load the intake + its answers + the display client name into a PLAIN dict DTO
    (no live ORM rows cross the session boundary). CALL: build the user message and invoke
    Claude (``claude-sonnet-4-5``, ``max_tokens=_APPLY_MAX_TOKENS``, verbatim system prompt)
    holding NO DB connection. WRITE: parse the JSON object and finalize the ``skill_runs``
    row — ``succeeded`` + ``output_parsed`` on success, ``failed`` + ``error_message`` on a
    parse error or on a ``max_tokens`` truncation (D-09). The model id + prompts + token/cost
    are persisted for parity/observability.
    """
    model = get_settings().model_apply_intake

    def read_fn(session: Any) -> dict[str, Any]:
        intake = IntakeRepository(session, identity).get(intake_id)
        if intake is None:
            # Deleted-intake race after dispatch (WR-04): don't run the model on
            # empty/near-empty input and mark it succeeded — carry the missing
            # sentinel through call_fn/write_fn to a failed finalize instead.
            return {"missing": True}
        answer_rows = IntakeAnswerRepository(session, identity).list_for_intake(intake_id)
        answers = [
            {"field_key": row.field_key, "value": row.value, "value_json": row.value_json}
            for row in answer_rows
        ]
        client_name = intake.client_name
        user_message = _APPLY_USER_PREFIX + _format_intake_markdown(client_name, answers)
        return {"client_name": client_name, "answers": answers, "user_message": user_message}

    def call_fn(dto: dict[str, Any]) -> dict[str, Any]:
        if dto.get("missing"):
            # No Claude call for a vanished intake — surface the failure to write_fn.
            return {"error": "Intake not found"}
        # Obtained through app.ai.clients at CALL TIME (test monkeypatch seam, D-07).
        message = clients.anthropic_client().messages.create(
            model=model,
            max_tokens=_APPLY_MAX_TOKENS,
            system=NESTOR_INTAKE_SKILL_PROMPT,
            messages=[{"role": "user", "content": dto["user_message"]}],
        )
        # D-4 (quick 260831-lm4): a response cut off at the budget is a BUDGET
        # failure, not a model failure. Tripling the required output made this
        # realistic for the first time. Without this branch the truncated JSON is
        # merely unparseable, and `extract_json` reports a generic parse error that
        # reads to the operator like the model produced garbage — sending them to
        # re-run the skill instead of to the token budget. `getattr` because the
        # test doubles are not required to grow a new attribute for this check.
        if getattr(message, "stop_reason", None) == "max_tokens":
            return {
                "error": (
                    f"Claude response truncated: hit the max_tokens budget of "
                    f"{_APPLY_MAX_TOKENS}, so the JSON object is incomplete. Raising "
                    f"the budget requires switching to a streaming call — the "
                    f"non-streaming SDK ceiling is ~"
                    f"{_ANTHROPIC_NON_STREAMING_MAX_TOKENS} output tokens."
                )
            }
        return {
            "raw": message.content[0].text,
            "input_tokens": message.usage.input_tokens,
            "output_tokens": message.usage.output_tokens,
        }

    def write_fn(session: Any, dto: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        if result.get("error"):
            # Missing-intake sentinel (WR-04): finalize failed, never a silent success.
            SkillRunRepository(session, identity).patch(
                run_id,
                status="failed",
                error_message=result["error"],
                completed_at=_now(),
            )
            return {"status": "failed", "error_message": result["error"]}

        raw = result["raw"]
        input_tokens = result["input_tokens"]
        output_tokens = result["output_tokens"]
        cost = estimate_cost_usd(input_tokens, output_tokens)
        repo = SkillRunRepository(session, identity)

        common = dict(
            output=raw,
            llm_model=model,
            prompt_system=NESTOR_INTAKE_SKILL_PROMPT,
            prompt_user=dto["user_message"],
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_estimate_usd=cost,
            completed_at=_now(),
        )
        try:
            parsed = extract_json(raw)
        except ValueError as exc:
            # D-09 failure path: malformed Claude JSON -> failed + error_message, no
            # partial output_parsed written (the row keeps a null parsed object).
            repo.patch(run_id, status="failed", error_message=str(exc), **common)
            return {"status": "failed", "error_message": str(exc)}

        repo.patch(run_id, status="succeeded", output_parsed=parsed, **common)
        return {"status": "succeeded"}

    def on_error(session: Any, dto: Any, exc: Exception) -> dict[str, Any]:
        # D-09 terminal-status guard: any call/write failure (API timeout, 429, empty
        # content array, write crash) finalizes the row failed — never stuck running.
        SkillRunRepository(session, identity).patch(
            run_id, status="failed", error_message=str(exc), completed_at=_now()
        )
        return {"status": "failed", "error_message": str(exc)}

    return run_with_session_release(identity, read_fn, call_fn, write_fn, on_error=on_error)
