"""Probe which briefs trigger clarification on Tribunal + ADK intake (isolated, cheap).

Runs ONLY the intake step of each engine — no research, no skeptics. Tribunal via
its real adaptive_intake() with a stub (non-audited) Gemini client; ADK by running
just its intake_agent alone in an in-memory session. One cheap LLM call per engine
per brief. Use this to find a brief that reliably makes BOTH engines ask questions
before testing the full UI loop.
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / "nestor_pulse" / ".env")

CANDIDATES = [
    "Lukoil",
    "Lukoil risks",
    "What should we focus on?",
    "We need some research help",
    "Give us strategic insights for our business",
    "Help us with our marketing strategy",
]


# --- Tribunal: real adaptive_intake with a non-audited stub client ----------
class _StubAudited:
    """Minimal stand-in for AuditedLLMClient: calls Gemini directly, no DB/audit."""

    def __init__(self) -> None:
        from google import genai
        self._g = genai.Client()

    async def gemini_generate(self, *, run_id, tenant_id, model, contents, **kwargs):
        return await asyncio.to_thread(
            lambda: self._g.models.generate_content(model=model, contents=contents, **kwargs)
        )


async def probe_tribunal(brief: str) -> dict:
    from nestor_pulse_sdk.pipeline.tribunal.intake import adaptive_intake
    res = await adaptive_intake(
        brief=brief,
        audited=_StubAudited(),
        run_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
    )
    return {
        "needs_clarification": bool(res.get("needs_clarification")),
        "questions": res.get("clarifying_questions", []),
    }


# --- ADK: run intake_agent alone, see if it accepts or asks -----------------
async def probe_adk(brief: str) -> dict:
    from nestor_pulse.intake_agent import intake_agent
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    runner = Runner(
        agent=intake_agent,
        app_name="probe-intake",
        session_service=InMemorySessionService(),
    )
    sid = str(uuid.uuid4())
    await runner.session_service.create_session(
        app_name="probe-intake", user_id="probe", session_id=sid
    )
    accepted = False
    texts: list[str] = []
    async for ev in runner.run_async(
        user_id="probe",
        session_id=sid,
        new_message=types.Content(role="user", parts=[types.Part(text=brief)]),
    ):
        if ev.content and ev.content.parts:
            for p in ev.content.parts:
                fc = getattr(p, "function_call", None)
                if fc and getattr(fc, "name", "") == "validate_briefing":
                    accepted = True
                if getattr(p, "text", None):
                    texts.append(p.text)
    # ACCEPTED => ADK would proceed to (expensive) research, no questions.
    # NOT accepted => ADK rejected and asked the user (the text is the questions).
    return {
        "needs_clarification": not accepted,
        "questions_text": (texts[-1].strip() if texts else ""),
    }


async def main() -> None:
    for brief in CANDIDATES:
        print("=" * 72)
        print(f"BRIEF: {brief!r}")
        try:
            t = await probe_tribunal(brief)
            mark = "ASKS ✅" if t["needs_clarification"] else "proceeds (no questions) ❌"
            print(f"  TRIBUNAL: {mark}")
            for q in t["questions"]:
                print(f"     - {q}")
        except Exception as exc:  # noqa: BLE001
            print(f"  TRIBUNAL: ERROR {type(exc).__name__}: {exc}")
        try:
            a = await probe_adk(brief)
            mark = "ASKS ✅" if a["needs_clarification"] else "proceeds (no questions) ❌"
            print(f"  ADK:      {mark}")
            if a["needs_clarification"] and a["questions_text"]:
                print(f"     {a['questions_text'][:300]}")
        except Exception as exc:  # noqa: BLE001
            print(f"  ADK:      ERROR {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    asyncio.run(main())
