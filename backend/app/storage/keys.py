"""Object-key builder + filename sanitizer for GCS storage (D-04, D-05, T-09-02).

The server ALWAYS authors the object key — a client-supplied path/bucket is
never trusted (D-05). ``build_object_key`` produces::

    {space_id}/{intake_id}/{category}/{uuid4}-{sanitized_filename}

so every object is space-scoped by construction and the route layer can assert
ownership with a plain ``key.startswith(f"{space_id}/{intake_id}/")`` check
(D-08). The ``{uuid4}-`` prefix guarantees uniqueness and neutralizes any
sanitizer edge case; ``sanitize_filename`` strips ``/`` and every character
outside ``[A-Za-z0-9._-]``, so path traversal via a hostile filename is
structurally impossible (T-09-02).

``sanitize_filename`` is a 1:1 Python port of the frontend's
``sanitizeFilenameForStorage`` (frontend/src/components/intake/
FinalReportBlock.tsx:24-34) so both ends of the system agree on what a stored
name looks like: NFD-normalize, drop combining marks, map em/en dashes to
``-``, whitespace to ``_``, drop anything outside ``[A-Za-z0-9._-]``, collapse
repeated ``_`` / ``-``, and strip leading/trailing ``._-``. The Python port
additionally caps the length (``max_len``) and falls back to ``"file"`` when
nothing survives.

Pure module: no I/O, no GCS, no DB — safe to import anywhere.
"""

from __future__ import annotations

import re
import unicodedata
import uuid

# The four server-known object categories (D-05). A category outside this set
# is a caller bug -> ValueError (the route layer maps it to 400/422).
CATEGORIES = frozenset({"attachments", "audio", "artifacts", "reports"})

# The 16 allowed upload extensions (D-04 allowlist). Anything else -> 415 at
# the route layer. Documents, images, and the Whisper-supported audio formats.
ALLOWED_EXT = frozenset(
    {
        ".pdf",
        ".docx",
        ".xlsx",
        ".pptx",
        ".txt",
        ".md",
        ".csv",
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".m4a",
        ".mp3",
        ".wav",
        ".webm",
        ".ogg",
    }
)


def sanitize_filename(name: str, *, max_len: int = 200) -> str:
    """Sanitize a client filename for use inside a server-authored object key.

    Port of the frontend ``sanitizeFilenameForStorage`` (FinalReportBlock.tsx):

    1. NFD-normalize, then drop combining marks (``é`` -> ``e``).
    2. Map em/en dashes (``—``/``–``) to ``-``.
    3. Collapse any whitespace run to a single ``_``.
    4. Drop every character outside ``[A-Za-z0-9._-]`` (this removes ``/`` —
       the path-traversal kill switch, T-09-02).
    5. Collapse repeated ``_`` and repeated ``-``.
    6. Strip leading/trailing ``.``, ``_``, ``-``.
    7. Cap at ``max_len`` characters (then re-strip a dangling ``._-`` tail).
    8. Fall back to ``"file"`` when nothing survives.
    """
    decomposed = unicodedata.normalize("NFD", name or "")
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    cleaned = re.sub(r"[—–]", "-", stripped)  # em dash / en dash -> '-'
    cleaned = re.sub(r"\s+", "_", cleaned)
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned)
    cleaned = re.sub(r"-+", "-", cleaned)
    cleaned = re.sub(r"^[_.-]+|[_.-]+$", "", cleaned)
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len]
        cleaned = re.sub(r"[_.-]+$", "", cleaned)
    return cleaned or "file"


def build_object_key(space_id: str, intake_id: str, category: str, filename: str) -> str:
    """Return the server-authored object key for one uploaded file (D-05).

    Shape: ``{space_id}/{intake_id}/{category}/{uuid4}-{sanitized_filename}``.

    ``space_id`` MUST come from the fetched intake row (the verified tenant),
    never from client input; ``category`` must be one of :data:`CATEGORIES`
    (``ValueError`` otherwise — the route maps it to a 4xx). The ``uuid4-``
    segment makes every key unique regardless of the client filename.
    """
    if category not in CATEGORIES:
        raise ValueError(
            f"unknown storage category {category!r} — must be one of {sorted(CATEGORIES)}"
        )
    return f"{space_id}/{intake_id}/{category}/{uuid.uuid4()}-{sanitize_filename(filename)}"
