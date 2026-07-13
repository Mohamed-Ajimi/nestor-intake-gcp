"""``transcribe-audio`` ported to a space-scoped background task (AI-05).

Ports ``docs/supabase-functions/transcribe-audio.ts`` onto the AI-06 release contract:
read the ``intake_sources`` audio row into a plain DTO, fetch the audio bytes via the
:func:`download_audio_bytes` seam + call OpenAI Whisper (``whisper-1``,
``response_format='verbose_json'`` so ``.segments`` come back) holding NO DB connection,
then in a FRESH tenant session (GUC re-issued — T-7-02) chunk the segments into ~500-word
``transcripts`` rows — each carrying the caller's ``space_id`` (T-7-03).

Audio fetch is FAKED in Phase 7 (D-08): the real download couples to Cloud Storage, which
lands in Phase 9. :func:`download_audio_bytes` is the single seam that Phase 9 replaces; it
is re-exported at the package level (``app.ai.skills.download_audio_bytes``) so the contract
test monkeypatches it. This module constructs NO object-store client — the byte fetch stays
behind the seam.

No ``intake_status`` bump (07-RESEARCH Pitfall 1 / Open Q2): the audio path is out-of-flow —
the flow ceiling stays at ``decomposed`` and the audio source's ``intakes.status`` is never
advanced. Progress is recorded ONLY on the ``transcripts`` rows.

Status lifecycle (D-09): the ``skill_runs`` row is created ``running`` by the endpoint and
finalized here to EXACTLY ``"succeeded"`` on a Whisper response, or ``"failed"`` (with
``error_message``) when the Whisper call / audio fetch raises.

Grep-guard: constructs NO database engine/session — the injected ``session`` (from
``run_with_session_release``) plus the repository wall (D-01) do every tenant-scoped write;
the OpenAI client is obtained through ``app.ai.clients`` at CALL TIME (the test monkeypatch
seam on ``app.ai.clients.openai_client``).

Source: docs/supabase-functions/transcribe-audio.ts (whisper-1 + verbose_json :84-98,
~500-word chunking :31-53, transcripts write :104-117; the out-of-flow status bump :120-122
is DELIBERATELY NOT ported — Pitfall 1).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from app.ai import clients
from app.auth.identity import Identity
from app.storage import gcs
from app.core.config import get_settings
from app.db.ai_session import run_with_session_release
from app.db.repository import (
    IntakeSourceRepository,
    SkillRunRepository,
    TranscriptRepository,
)

# ~500-word chunk ceiling for embedding-friendly transcript rows (transcribe-audio.ts:31).
_MAX_WORDS_PER_CHUNK = 500


def _now() -> datetime:
    """A timezone-aware UTC ``now`` for the ``completed_at`` stamp."""
    return datetime.now(timezone.utc)


def download_audio_bytes(source: dict[str, Any] | None = None, **kwargs: Any) -> bytes:
    """Fetch an audio source's bytes from GCS keyed off its ``storage_path`` (Phase 9 / D-08).

    Delegates to the :func:`app.storage.gcs.download_bytes` seam — the single place the
    backend reads an object — using the ``storage_path`` the ``intake_sources`` row carries
    (projected into the DTO by ``run_transcribe``'s ``read_fn``). Runs inside the AI-06
    no-DB-connection window: it holds NO DB session, only the object key.

    Constructs NO object-store client here — the GCS coupling lives behind
    ``app.storage.gcs`` (the test monkeypatch target). The transcribe contract test still
    monkeypatches THIS function (``app.ai.skills.download_audio_bytes``) to avoid the wire;
    the new delegation test patches ``app.storage.gcs.download_bytes`` to prove the wiring.
    """
    if not source or not source.get("storage_path"):
        raise ValueError("download_audio_bytes requires a source with a storage_path")
    return gcs.download_bytes(source["storage_path"])


def _chunk_segments(segments: list[Any], max_words: int = _MAX_WORDS_PER_CHUNK) -> list[dict[str, Any]]:
    """Group Whisper segments into ~``max_words``-word blocks (ports ``chunkSegments``).

    Mirrors transcribe-audio.ts:31-53: accumulate segment text until the running word count
    reaches ``max_words``, then flush a chunk carrying its ``start_ms`` / ``end_ms`` window.
    """
    out: list[dict[str, Any]] = []
    buf: list[str] = []
    word_count = 0
    start_ms = 0
    end_ms = 0

    for seg in segments:
        text = (getattr(seg, "text", "") or "").strip()
        words = len(text.split()) if text else 0
        if not buf:
            start_ms = round(float(getattr(seg, "start", 0.0)) * 1000)
        buf.append(text)
        end_ms = round(float(getattr(seg, "end", 0.0)) * 1000)
        word_count += words
        if word_count >= max_words:
            out.append({"text": " ".join(buf), "start_ms": start_ms, "end_ms": end_ms})
            buf = []
            word_count = 0
    if buf:
        out.append({"text": " ".join(buf), "start_ms": start_ms, "end_ms": end_ms})
    return out


class _FallbackSegment:
    """A single synthetic segment when Whisper returns no ``.segments`` (legacy :101)."""

    def __init__(self, text: str) -> None:
        self.start = 0.0
        self.end = 0.0
        self.text = text


def run_transcribe(
    identity: Identity, intake_id: Any, source_id: Any, run_id: Any
) -> dict[str, Any]:
    """Transcribe an intake audio source into chunked ``transcripts`` rows (AI-05, scoped).

    READ: load the ``intake_sources`` audio row (file name + language + the source's own
    ``space_id``) into a plain DTO. CALL: fetch the audio bytes via the
    :func:`download_audio_bytes` seam (faked in Phase 7) and call Whisper (``whisper-1``,
    ``response_format='verbose_json'``, the source language) holding NO DB connection. WRITE:
    chunk the verbose_json segments into ~500-word ``transcripts`` rows via
    :class:`TranscriptRepository` (``space_id`` injected from Identity), REPLACING the
    source's prior chunk set in the same tx (idempotent re-run — WR-02), and finalize the
    ``skill_runs`` row ``succeeded`` — no ``intakes.status`` change (Pitfall 1).
    """
    model = get_settings().model_transcription
    intake_uuid = uuid.UUID(str(intake_id))
    source_uuid = uuid.UUID(str(source_id))

    def read_fn(session: Any) -> dict[str, Any]:
        source = IntakeSourceRepository(session, identity).get(source_id)
        if source is None or source.intake_id != intake_uuid:
            # Missing, OR the source belongs to a DIFFERENT intake than the path names
            # (WR-03): writing rows stamped with the path intake_id but sourced from
            # another intake would mislabel the transcript — treat both as missing
            # (the sentinel flows through call_fn/write_fn to a failed finalize).
            return {"missing": True}
        return {
            "missing": False,
            "kind": source.kind,
            "file_name": source.file_name,
            "language": source.language,
            "space_id": str(source.space_id),
            # The GCS object key the audio-fetch seam downloads (Phase 9 / D-08). Projected
            # here so download_audio_bytes carries the key into the no-DB CALL window.
            "storage_path": source.storage_path,
        }

    def call_fn(dto: dict[str, Any]) -> dict[str, Any]:
        if dto.get("missing"):
            return {"error": "Source not found"}
        try:
            # The audio-fetch seam — faked in Phase 7, real fetch in Phase 9 (D-08). Called
            # through the package so the contract test's monkeypatch on
            # app.ai.skills.download_audio_bytes takes effect.
            from app.ai import skills as _skills_pkg

            audio_bytes = _skills_pkg.download_audio_bytes(dto)
            language = dto.get("language") or "nl"
            transcription = clients.openai_client().audio.transcriptions.create(
                model=model,
                file=(dto.get("file_name") or "audio.m4a", audio_bytes),
                response_format="verbose_json",
                language=language,
            )
            return {
                "text": getattr(transcription, "text", "") or "",
                "language": getattr(transcription, "language", None) or language,
                "segments": list(getattr(transcription, "segments", []) or []),
            }
        except Exception as exc:  # noqa: BLE001 — surface any fetch/Whisper failure as failed
            return {"error": str(exc)}

    def write_fn(session: Any, dto: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        run_repo = SkillRunRepository(session, identity)
        if result.get("error"):
            run_repo.patch(
                run_id,
                status="failed",
                error_message=result["error"],
                completed_at=_now(),
            )
            return {"status": "failed", "error_message": result["error"]}

        segments = result["segments"]
        if not segments:
            # Whisper returned no segment windows — fall back to one synthetic segment from
            # the full text (legacy transcribe-audio.ts:101).
            segments = [_FallbackSegment(result["text"])]
        chunks = _chunk_segments(segments)
        language = result["language"] or dto.get("language") or "nl"

        repo = TranscriptRepository(session, identity)
        is_super = identity.role == "superadmin"
        space_uuid = uuid.UUID(dto["space_id"]) if dto.get("space_id") else None
        if is_super and space_uuid is None:
            # Deleted-source race after dispatch: a superadmin has no own space, so with
            # the source gone there is no target space — finalize the run failed (D-09)
            # instead of falling through to a NULL-space create() crash (WR-01).
            msg = "Source not found — no target space for the superadmin write"
            run_repo.patch(
                run_id, status="failed", error_message=msg, completed_at=_now()
            )
            return {"status": "failed", "error_message": msg}
        # Idempotent re-run (WR-02): a second dispatch for the same source (double-click,
        # retry after a success, concurrent 202s) must not interleave a duplicate chunk
        # set — replace this source's prior chunks in the SAME tx, so the last run stays
        # authoritative and a crash mid-replace rolls back to the prior consistent set.
        for row in repo.list_for_source(source_id):
            session.delete(row)
        for index, chunk in enumerate(chunks):
            values = dict(
                intake_id=intake_uuid,
                source_id=source_uuid,
                chunk_index=index,
                text=chunk["text"],
                start_ms=chunk["start_ms"],
                end_ms=chunk["end_ms"],
                language=language,
                token_count=len(chunk["text"].split()),
            )
            # space_id injected from the verified Identity (user) / the source's own space
            # (superadmin) — never a method/LLM-provided value (T-7-03).
            if is_super:
                repo.create_in_space(space_uuid, **values)
            else:
                repo.create(**values)

        run_repo.patch(
            run_id, status="succeeded", llm_model=model, completed_at=_now()
        )
        return {"status": "succeeded", "chunks": len(chunks)}

    def on_error(session: Any, dto: Any, exc: Exception) -> dict[str, Any]:
        # D-09 terminal-status guard: call_fn already catches its own fetch/Whisper
        # failures, so this covers the WRITE phase (and any read crash) — a write
        # exception finalizes the row failed instead of leaving it stuck running.
        SkillRunRepository(session, identity).patch(
            run_id, status="failed", error_message=str(exc), completed_at=_now()
        )
        return {"status": "failed", "error_message": str(exc)}

    return run_with_session_release(identity, read_fn, call_fn, write_fn, on_error=on_error)
