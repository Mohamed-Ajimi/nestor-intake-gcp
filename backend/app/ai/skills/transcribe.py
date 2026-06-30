"""``transcribe-audio`` port — SIGNATURE STUBS (AI-05).

The route surface (07-05) fixes the function signatures so ``ai_routes.py`` imports
cleanly and dispatches the background task today; the real Whisper implementation lands in
plan 07-07 (``test_ai_transcribe.py`` is RED until then). Two seams are stubbed here:

- :func:`run_transcribe` — the background task (``identity, intake_id, source_id, run_id``).
- :func:`download_audio_bytes` — the audio-fetch seam the transcribe test monkeypatches
  (re-exported from the package as ``app.ai.skills.download_audio_bytes``). The real fetch
  couples to GCS (Phase 9 / D-08), so 07-07 keeps it behind this seam; the test fakes it.

Grep-guard: constructs NO engine/session — the real impl writes the chunked
``transcripts`` rows via ``run_with_session_release`` + ``TranscriptRepository``.
"""

from __future__ import annotations

from typing import Any

from app.auth.identity import Identity


def download_audio_bytes(*args: Any, **kwargs: Any) -> bytes:
    """Fetch an audio source's bytes — STUB (the GCS fetch is Phase 9 / D-08).

    The transcribe contract test monkeypatches this seam (``raising=False``) so no bytes
    ever go over the wire in Phase 7; 07-07 wires the real download.
    """
    raise NotImplementedError("download_audio_bytes is implemented in plan 07-07 / Phase 9")


def run_transcribe(
    identity: Identity, intake_id: Any, source_id: Any, run_id: Any
) -> Any:
    """Transcribe an ``intake_sources`` audio row into chunked ``transcripts`` (AI-05).

    Filled in 07-07: fetch the audio bytes via :func:`download_audio_bytes`, call Whisper
    (``whisper-1``, ``response_format='verbose_json'`` so ``.segments`` come back) with the
    source language, then in a fresh tenant session write space-scoped ``transcripts``
    chunk rows. No ``intake_status`` bump (the audio path is out-of-flow — 07-RESEARCH
    Pitfall 1).
    """
    raise NotImplementedError("run_transcribe is implemented in plan 07-07")
