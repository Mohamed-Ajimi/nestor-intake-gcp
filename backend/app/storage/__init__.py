"""``app.storage`` — the GCS object-storage seam package (Phase 9, INFRA-03).

Re-exports the four ``app.storage.gcs`` seam functions at the package level —
mirroring how ``app/ai/skills/__init__.py`` re-exports ``download_audio_bytes``
— so consumers can import the seam either way::

    from app.storage import gcs            # module handle (monkeypatch-friendly)
    from app.storage import download_bytes # package-level re-export

The transcribe seam (``app.ai.skills.transcribe.download_audio_bytes``, 09-02)
consumes :func:`download_bytes` through this package. Key authoring lives in
:mod:`app.storage.keys` (NOT re-exported here — import it explicitly so the
route layer's dependency on ``build_object_key`` stays visible).

Grep-guard: this package constructs NO database engines/sessions — it is the
GCS transport seam only (see app/storage/gcs.py).
"""

from __future__ import annotations

from app.storage.gcs import (
    delete_object,
    download_bytes,
    signed_download_url,
    upload_object,
)

__all__ = [
    "upload_object",
    "signed_download_url",
    "delete_object",
    "download_bytes",
]
