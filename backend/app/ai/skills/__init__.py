"""Phase 7 skill handlers — the background-task bodies the AI routes dispatch.

Each ``run_*`` function is the WRITE half of the AI-06 release contract: it runs through
``app.db.ai_session.run_with_session_release`` (READ plain DTO -> CALL the external API
holding NO connection -> WRITE in a fresh tenant session with the GUC re-issued). The route
layer (``app/api/ai_routes.py``) creates the ``skill_runs`` row synchronously, then
schedules one of these via ``BackgroundTasks``.

This plan (07-05) lands ``apply`` + ``context_pack`` fully; the other four
(``embeddings`` / ``structure_answers`` / ``extract_insights`` / ``transcribe``) are
signature stubs so the route surface is complete and importable now — 07-06 / 07-07 fill
their bodies (their contract tests stay RED until then).

``download_audio_bytes`` is re-exported at the package level so the transcribe contract
test can monkeypatch ``app.ai.skills.download_audio_bytes`` (the audio-fetch seam, faked in
Phase 7 — the real GCS download is Phase 9 / D-08).

Grep-guard: this package constructs NO database engines/sessions — all DB access flows
through the ``app/db`` seam (``run_with_session_release`` + the repository wall).
"""

from __future__ import annotations

from app.ai.skills.apply import run_apply_intake_skill
from app.ai.skills.context_pack import run_context_pack
from app.ai.skills.embeddings import run_embeddings
from app.ai.skills.extract_insights import run_extract_insights
from app.ai.skills.structure_answers import run_structure_answers
from app.ai.skills.transcribe import download_audio_bytes, run_transcribe

__all__ = [
    "run_apply_intake_skill",
    "run_context_pack",
    "run_embeddings",
    "run_structure_answers",
    "run_extract_insights",
    "run_transcribe",
    "download_audio_bytes",
]
