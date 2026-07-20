"""
Engine adapter -- routes runs to ADK or SDK pipeline (D-02 engine toggle).

References:
- 01-CONTEXT.md D-02: engine field per brief, user-selected
- 01-CONTEXT.md D-01: ADK pipeline PRESERVED read-only; nestor_pulse/ unchanged
- 01-RESEARCH.md Pitfall 8: do NOT modify nestor_pulse/ files; import read-only
- 01-PATTERNS.md lines 469-502: adapter.py reference implementation

dispatch_runner(engine) -> Runner
  'adk'  -> ADKRunnerShim  (wraps nestor_pulse.agent.root_agent, D-01 preserved)
  'sdk'  -> SDKPipelineStub (Plan 09 replaces with real Claude Agent SDK pipeline)
  other  -> ValueError

Both runners implement the Runner protocol:
    async def run(*, brief: str, run_id: uuid.UUID, tenant_id: uuid.UUID) -> dict

ADK PRESERVATION INVARIANT (D-01, T-06-06):
  - ADKRunnerShim imports nestor_pulse READ-ONLY (never modifies)
  - Zero files under nestor_pulse/ are touched by this module
  - CI grep gate enforces: `grep -rE "from nestor_pulse[. ]" nestor_pulse_sdk/ | grep -v adapter.py` == 0

SDK STUB NOTE (Plan 09 replaces):
  SDKPipelineStub sleeps briefly and returns a canned output -- just enough
  to make test_async_worker.py pass for the engine='sdk' path. Plan 09 fills
  the real Claude Agent SDK pipeline implementation.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from typing import Protocol, runtime_checkable

import structlog

log = structlog.get_logger(__name__)

#: Marker the answer endpoint (runs/api.py) uses to fold clarification answers
#: into the brief. The ADK shim splits on it to replay rounds as conversation.
_CLAR_MARKER = "[CLARIFICATION ANSWERS]"


def _split_brief_rounds(brief: str) -> list[str]:
    """Split a folded brief into conversation turns: [base_brief, answer1, ...].

    The answer endpoint accumulates rounds as appended
    "[CLARIFICATION ANSWERS]\\n<answer>" blocks. For a conversational engine the
    answers must be REPLAYED as separate user turns (not pasted into one mega-
    brief), or its checkpoints re-ask the same question every round. Empty
    blocks are dropped; a brief without markers returns a single turn.
    """
    parts = (brief or "").split(_CLAR_MARKER)
    turns = [p.strip() for p in parts]
    return [t for t in turns if t] or [""]


@runtime_checkable
class Runner(Protocol):
    """Protocol shared by ADKRunnerShim and SDKPipelineStub."""
    async def run(self, *, brief: str, run_id: uuid.UUID, tenant_id: uuid.UUID) -> dict:
        """Execute the pipeline and return output dict."""
        ...


class ADKRunnerShim:
    """
    Thin shim that wraps the preserved nestor_pulse.agent ADK pipeline (D-01).

    Imports nestor_pulse READ-ONLY -- never modifies any file under nestor_pulse/.
    This is the D-02 engine toggle implementation for engine='adk'.

    The ADK pipeline uses its own SQLite session.db (D-08 archive-not-migrate).
    We drive it programmatically by creating an ADK Runner with an ephemeral
    session_id derived from the run_id (the run_id is the durable identity).

    Phase 1 minimum:
      - Import agent.root_agent lazily (Pitfall 8: lazy import keeps SDK runnable
        even if google-adk is broken for some other reason).
      - Invoke the pipeline with the brief as the user message.
      - Collect the final output text from the last event.
    """

    async def run(self, *, brief: str, run_id: uuid.UUID, tenant_id: uuid.UUID) -> dict:
        log.info("adk_runner_invoked", run_id=str(run_id))
        # Lazy import so SDK pipeline is runnable even if google-adk env is broken.
        # Per D-01: read-only import of nestor_pulse; NEVER modify nestor_pulse/.
        from nestor_pulse import agent  # noqa: F401 (read-only ADK import, D-01)
        from google.adk.runners import Runner as ADKRunner
        from google.adk.sessions import DatabaseSessionService
        from google.genai import types

        # Use a local SQLite session.db adjacent to the nestor_pulse package
        # (the ADK pipeline's canonical session store, D-08).
        db_path = Path(__file__).parent.parent.parent / "nestor_pulse" / ".adk" / "session.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        app_name = f"nestor-run-{run_id}"

        runner = ADKRunner(
            agent=agent.root_agent,
            app_name=app_name,
            session_service=DatabaseSessionService(
                db_url=f"sqlite+aiosqlite:///{db_path}"
            ),
        )

        # Live stage progress (0006). ADK is a multi-turn agent pipeline; we map
        # each agent's events to a stage key and write it only on CHANGE (a DB
        # write per event would be wasteful). The synthesis sub-steps run inside
        # parallel_research_orchestrator and CANNOT be sub-instrumented (D-01:
        # nestor_pulse/ is read-only), so 'synthesize' is observed from state.
        import time as _time

        from nestor_pulse_sdk.runs.stages import set_stage, is_cancelled, RunCancelled

        _AUTHOR_STAGE = {
            "intake_agent": "intake",
            "decomposer_agent": "decompose",
            "intent_classifier": "classify",
            "parallel_research_orchestrator": "research",
        }
        _last_stage = {"key": None}

        async def _emit(stage_key: str) -> None:
            if stage_key and stage_key != _last_stage["key"]:
                _last_stage["key"] = stage_key
                await set_stage(run_id, tenant_id, stage_key)

        # Cooperative cancellation. ADK streams events throughout (incl. the long
        # research stage), so we poll run.status as events arrive — throttled to one
        # DB read every ~10s — and raise RunCancelled to break out cleanly. ADK
        # cannot be force-killed mid-tool-call (D-01: nestor_pulse is read-only), so
        # cancel latency is bounded by the gap between streamed events + this window.
        _CANCEL_CHECK_INTERVAL = 10.0
        _last_cancel_check = {"t": 0.0}

        async def _check_cancel() -> None:
            now = _time.monotonic()
            if now - _last_cancel_check["t"] >= _CANCEL_CHECK_INTERVAL:
                _last_cancel_check["t"] = now
                if await is_cancelled(run_id, tenant_id):
                    raise RunCancelled()

        await _emit("intake")

        session_id = str(run_id)
        try:
            await runner.session_service.create_session(
                app_name=app_name,
                user_id=str(tenant_id),
                session_id=session_id,
            )
        except Exception:
            # Re-run / retry of the same run_id: the ADK SQLite session.db already
            # has this session. ADK only needs it to exist, so proceed with it.
            pass

        # Drive the pipeline as a REPLAYED CONVERSATION (fix 2026-06-10).
        #
        # The answer endpoint folds each clarification round into the brief as a
        # [CLARIFICATION ANSWERS] block and queues a NEW run (append-only audit
        # chain) — which means a FRESH ADK session every round. Sending the whole
        # folded brief as one message made ADK's conversational checkpoints
        # (competitor confirmation etc.) re-ask the same question reworded every
        # round: the answer was buried in briefing prose, not given as a reply.
        #
        # Instead: send the BASE brief as turn 1, then feed each stored answer as
        # its own conversational turn whenever the pipeline pauses. The dialogue
        # is reconstructed inside this run's session, so "akkoord" lands as a
        # direct reply to the question that asked it. Bounded: max turns =
        # 1 + number of stored answer rounds; then either the report exists or
        # the run parks as needs_input on the first genuinely NEW question.
        #
        # ADK's run_async expects new_message as a Content object (it reads
        # .role/.parts) -- a bare string raises "'str' object has no attribute
        # 'role'" and fails the whole ADK arm.
        turns = _split_brief_rounds(brief)
        final_text = ""
        for turn_idx, turn_text in enumerate(turns):
            await _check_cancel()
            new_message = types.Content(role="user", parts=[types.Part(text=turn_text)])
            async for event in runner.run_async(
                user_id=str(tenant_id),
                session_id=session_id,
                new_message=new_message,
            ):
                await _check_cancel()  # throttled; stops a runaway ADK run
                # Map the emitting agent to a stage key (emit only on change).
                author = getattr(event, "author", None)
                if author in _AUTHOR_STAGE:
                    await _emit(_AUTHOR_STAGE[author])
                if event.content and event.content.parts:
                    for part in event.content.parts:
                        if hasattr(part, "text") and part.text:
                            final_text = part.text
            # Stop replaying once the pipeline has produced its report — any
            # leftover answers would just poke the post-synthesis Q&A agent.
            try:
                _s = await runner.session_service.get_session(
                    app_name=app_name, user_id=str(tenant_id), session_id=session_id,
                )
                if _s and _s.state.get("synthesis_output"):
                    await _emit("synthesize")
                    log.info(
                        "adk_replay_complete_early", run_id=str(run_id),
                        turns_sent=turn_idx + 1, turns_total=len(turns),
                    )
                    break
                # Research brief produced but no synthesis yet → still researching.
                if _s and _s.state.get("research_brief"):
                    await _emit("research")
            except Exception:  # noqa: BLE001 -- state probe is best-effort
                pass

        # The ADK pipeline writes its actual synthesized report to the session
        # state key 'synthesis_output' (nestor_pulse/agent.py display_synthesis_output).
        # The LAST run_async event, by contrast, is the post-synthesis interactive
        # Q&A agent's "ask me follow-ups" sign-off -- useless as a report. Prefer
        # synthesis_output; fall back to the last event text only if it's absent.
        report_text = ""
        briefing_validated = False
        try:
            session = await runner.session_service.get_session(
                app_name=app_name, user_id=str(tenant_id), session_id=session_id,
            )
            state = session.state if session else {}
            briefing_validated = bool(state.get("briefing_validated"))
            synth = state.get("synthesis_output")
            if synth:
                if isinstance(synth, str):
                    report_text = synth
                elif isinstance(synth, dict):
                    import json as _json
                    report_text = (
                        synth.get("report")
                        or synth.get("markdown")
                        or synth.get("body")
                        or synth.get("summary")
                        or _json.dumps(synth, indent=2, ensure_ascii=False, default=str)
                    )
        except Exception:  # noqa: BLE001 -- best-effort
            log.warning("adk_synthesis_output_unavailable", run_id=str(run_id))

        # CLARIFICATION (0005): no synthesized report means ADK PAUSED to ask the
        # user something. ADK is a multi-turn conversational pipeline with SEVERAL
        # human checkpoints -- intake, competitor confirmation inside intent
        # classification, and possibly more -- and in the one-shot worker it stops
        # at whichever one it reaches (its last event text is that question). We
        # cannot force ADK past a checkpoint (D-01: nestor_pulse/ is read-only), so
        # we surface the question as needs_input regardless of how far it got. This
        # also fixes the false "completed" where a mid-pipeline question (with
        # briefing_validated already True) was saved as a 291-char "report".
        if not report_text:
            ask = (final_text or "").strip()
            # NO clarification cap for ADK (decision 2026-06-10): the cap only makes
            # sense for Tribunal, which can FORCE-proceed past it (its own intake has
            # an override path). ADK cannot be forced (D-01 read-only) AND its design
            # asks ONE question per turn plus a mandatory competitor-confirmation
            # checkpoint — so any small cap fails virtually every competitive brief.
            # Every pause waits for a human answer (needs_input), so an uncapped ADK
            # cannot loop unattended; rounds are bounded by the user, not the engine.
            clar_rounds = (brief or "").count("[CLARIFICATION ANSWERS]")
            # Split a multi-question paragraph into separate question items.
            lines = [ln.strip(" -•\t").strip() for ln in ask.splitlines() if ln.strip()]
            questions = [ln for ln in lines if ln] or (
                [ask] if ask else
                ["ADK needs more detail before it can research. What specifically should it investigate?"]
            )
            log.info(
                "adk_runner_needs_input", run_id=str(run_id),
                briefing_validated=briefing_validated, clar_rounds=clar_rounds,
                n_questions=len(questions),
            )
            return {"needs_clarification": True, "clarifying_questions": questions}

        await _emit("done")
        log.info("adk_runner_completed", run_id=str(run_id), output_len=len(report_text))
        return {"output_text": report_text}


# Plan 09 replaced the stub with the real SDKPipeline. Re-export the class
# under both `SDKPipeline` and the legacy `SDKPipelineStub` name so any
# callers that imported `SDKPipelineStub` keep working until Plan 12 cleans
# up the historical name (no behavior change -- both point to the same class).
from nestor_pulse_sdk.pipeline.orchestrator import SDKPipeline  # noqa: E402

SDKPipelineStub = SDKPipeline  # legacy name (Plan 06 -> Plan 09 transition)


def dispatch_runner(engine: str) -> Runner:
    """
    Route engine name to the correct runner implementation.

    Args:
        engine: 'adk', 'sdk', or 'tribunal' (matches Run.engine CHECK constraint).

    Returns:
        ADKRunnerShim for 'adk'.
        TribunalPipeline for 'tribunal' (explicit, env-independent A/B arm).
        TribunalPipeline when engine='sdk' AND NESTOR_SDK_ORCHESTRATOR == 'tribunal'
            (legacy toggle, preserved for back-compat).
        SDKPipeline (control arm) when engine='sdk' and NESTOR_SDK_ORCHESTRATOR is anything else.

    Raises:
        ValueError: for any engine value outside {'adk', 'sdk', 'tribunal'}.

    A/B ARMS (Plan 01-12):
        The comparison fan-out selects arms by explicit engine value -- 'adk',
        'sdk' (thin control), and 'tribunal' (challenger) -- so all three are
        distinguishable in one process regardless of NESTOR_SDK_ORCHESTRATOR.
        The legacy env toggle still works for engine='sdk' but is NOT needed
        when 'tribunal' is selected explicitly.

    T-15-03 mitigation (fail-safe engine selection):
        For engine='sdk', any value of NESTOR_SDK_ORCHESTRATOR other than exactly
        'tribunal' returns the thin SDKPipeline control. The flag is not a Boolean;
        only the exact string 'tribunal' activates the Tribunal engine. This
        prevents a misconfigured env from silently running an unvalidated variant.
    """
    if engine == "adk":
        return ADKRunnerShim()
    if engine == "tribunal":
        from nestor_pulse_sdk.pipeline.tribunal.pipeline import TribunalPipeline
        log.info("dispatch_runner: engine=tribunal -> TribunalPipeline (explicit A/B arm)")
        return TribunalPipeline()
    if engine == "sdk":
        orchestrator = os.environ.get("NESTOR_SDK_ORCHESTRATOR", "")
        if orchestrator == "tribunal":
            from nestor_pulse_sdk.pipeline.tribunal.pipeline import TribunalPipeline
            log.info("dispatch_runner: NESTOR_SDK_ORCHESTRATOR=tribunal -> TribunalPipeline")
            return TribunalPipeline()
        # Any other value (including empty string) falls through to the control arm
        log.info("dispatch_runner: sdk -> SDKPipeline (control; NESTOR_SDK_ORCHESTRATOR=%r)", orchestrator)
        return SDKPipeline()
    raise ValueError(f"Unknown engine: {engine!r}. Expected 'adk', 'sdk', or 'tribunal'.")
