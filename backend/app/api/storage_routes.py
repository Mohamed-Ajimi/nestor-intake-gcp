"""The storage feature router — backend-mediated GCS upload / signed-url / delete (DOC-01/02).

Three endpoints under ``protected_router`` (so each inherits ``Depends(get_current_identity)``
— AUTH-01), each a SYNC ``def`` (pg8000 is a blocking driver; FastAPI runs sync handlers in a
threadpool — an ``async def`` calling the sync engine would stall the event loop). Every byte
moves THROUGH the backend; the object key is ALWAYS server-authored (D-05); authorization is
the existence-hidden 404 + key-prefix assert (D-08); an audio upload auto-registers a
space-scoped ``intake_sources`` row (D-07); a delete cleans the matching source ref in the
SAME tx as the object delete (D-09).

Locked decisions / invariants realized here:

* D-03 grep-guard — this module imports NO raw DB symbol (``get_engine`` /
  ``get_superadmin_engine`` / ``sessionmaker`` / ``create_engine`` / ``Session``); it reaches
  the database ONLY through the injected ``get_intake_and_source_repos`` dependency. GCS is
  reached ONLY through the ``app.storage.gcs`` seam (the test monkeypatch target) — this module
  constructs NO SDK clients inline.
* TENANT-02 / D-08 — ``space_id`` is NEVER read from the request. The tenant scope comes solely
  from the fetched intake row (the verified tenant): the upload key is built from
  ``str(intake.space_id)``, and the signed-url / delete handlers assert
  ``key.startswith(f"{intake.space_id}/{intake_id}/")`` so a client-supplied ``path`` aimed at
  another tenant's tree can never be signed or deleted.
* D-07 — 404 is the data-route denial code: ``intake_repo.get`` -> ``None`` (a cross-tenant /
  missing intake) maps to 404, never 403, never 200-with-data (existence hidden; no BOLA/IDOR).
  The single 403 on this path is the null-space default-deny inside the dependency (D-04).
* D-02 (25 MB) / D-04 (type allowlist) — the upload gate rejects an over-cap body with 413 via
  an AUTHORITATIVE ``read(_MAX_BYTES + 1)`` (never trusting the declared ``file.size``), and a
  type outside the D-04 allowlist with 415, BEFORE the byte stream ever reaches the seam.
* Scope ceiling — this module names no deep-research stage and moves no intake status.

Authoritative references:
- .planning/phases/09-gcs-storage/09-02-PLAN.md (this contract)
- .planning/phases/09-gcs-storage/09-RESEARCH.md § Pattern 2 / Pattern 3
- D-02/D-03/D-04/D-05/D-07/D-08/D-09/D-10; T-09-05..09
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from pydantic import BaseModel

from app.auth.dependencies import get_current_identity
from app.auth.identity import Identity
from app.db.session import get_intake_and_source_repos
from app.storage import gcs
from app.storage.keys import ALLOWED_EXT, CATEGORIES, build_object_key

# The storage feature router. NO auth dependency of its own — mounted UNDER protected_router
# in app/main.py (inherits Depends(get_current_identity)). prefix mirrors intake_router so the
# storage verbs hang off the same /intakes/{intake_id} resource.
storage_router = APIRouter(prefix="/intakes", tags=["storage"])

# D-02: the 25 MB per-file ceiling (Whisper per-file limit; < Cloud Run's 32 MB request cap).
_MAX_BYTES = 25 * 1024 * 1024


class UploadedFileMeta(BaseModel):
    """The 201 response for a successful upload — echoes the server-authored key (D-05)."""

    path: str
    filename: str
    size: int
    uploaded_at: str
    mime_type: str | None = None


class SignedUrlView(BaseModel):
    """The signed-url response — ``expires_in`` is the EFFECTIVE (clamped) lifetime (D-10)."""

    url: str
    expires_in: int


class DeleteObjectsBody(BaseModel):
    """The delete request body — a list of object keys to remove (server-validated)."""

    paths: list[str]


class DeleteResult(BaseModel):
    """The delete response — the count of objects removed."""

    removed: int


def _now_iso() -> str:
    """A timezone-aware UTC ISO-8601 timestamp for the ``uploaded_at`` stamp."""
    return datetime.now(timezone.utc).isoformat()


def _filename_from_key(key: str) -> str:
    """Recover a human download filename from a server-authored object key.

    ``build_object_key`` produces ``.../{uuid4}-{sanitized_name}``; strip the trailing
    path segment and drop the ``{uuid4}-`` prefix so the browser's Content-Disposition
    carries the original-ish name (T-09-04 — attachment disposition uses this). Falls
    back to the last path segment (or ``"download"``) when the shape is unexpected.
    """
    tail = key.rsplit("/", 1)[-1] or "download"
    # The uuid4 prefix is 36 chars + a single '-'; split once past it if present.
    if len(tail) > 37 and tail[36] == "-":
        candidate = tail[37:]
        if candidate:
            return candidate
    return tail


@storage_router.post(
    "/{intake_id}/storage/uploads", status_code=status.HTTP_201_CREATED
)
def upload_file(
    intake_id: str,
    file: UploadFile = File(...),
    category: str = Form(...),
    identity: Identity = Depends(get_current_identity),
    repos: tuple = Depends(get_intake_and_source_repos),
) -> UploadedFileMeta:
    """Stream one file through the backend to GCS under a server-authored key (DOC-02).

    Gate order (fail before the seam): (1) SIZE — authoritative ``read(_MAX_BYTES + 1)``,
    over-cap -> 413 (D-02/D-03); (2) TYPE — declared-MIME extension outside the D-04
    allowlist -> 415, an unknown ``category`` -> 422; (3) OWNERSHIP — a cross-tenant /
    missing intake -> 404 (existence hidden, D-08). Only then is the key built from the
    verified tenant's ``space_id`` (D-05) and uploaded. An ``audio`` upload additionally
    creates a space-scoped ``intake_sources`` row (``storage_path == key``) in the SAME
    tx (D-07) so the Phase-7 transcribe flow can find the object with no client bookkeeping.
    """
    intake_repo, source_repo = repos

    # (2a) TYPE — reject a category the server does not know (D-05 / build_object_key).
    if category not in CATEGORIES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Unknown storage category {category!r}",
        )

    # (2b) TYPE — reject an extension outside the D-04 allowlist (before reading bytes).
    filename = file.filename or ""
    _, ext = os.path.splitext(filename)
    if ext.lower() not in ALLOWED_EXT:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "Unsupported file type",
        )

    # (1) SIZE — authoritative read (never trust the declared file.size). Read one byte
    # PAST the cap: if we got more than _MAX_BYTES the body is over the limit -> 413.
    data = file.file.read(_MAX_BYTES + 1)
    if len(data) > _MAX_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "File exceeds the 25 MB limit",
        )

    # (3) OWNERSHIP — a cross-tenant / missing intake is 404 (existence hidden, D-08).
    intake = intake_repo.get(intake_id)
    if intake is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")

    # (4) KEY — server-authored from the VERIFIED tenant's space (D-05). str(intake.space_id)
    # works for both a user (own space) and a superadmin (the intake's own space).
    space_id = str(intake.space_id)
    key = build_object_key(space_id, intake_id, category, filename or "file")

    # (5) Upload the bytes through the seam (never construct an SDK client inline).
    gcs.upload_object(key, data, content_type=file.content_type)

    # (6) AUDIO — auto-register a space-scoped intake_sources row in the SAME tx (D-07).
    # space_id is injected from the verified Identity inside the repo (TENANT-02) — never
    # passed here; a superadmin path would use create_in_space, but uploads run as the
    # tenant user in practice, and the repo raises loudly on a NULL-space create (WR-01).
    if category == "audio":
        source_repo.create(
            intake_id=intake_id,
            kind="audio",
            storage_path=key,
            file_name=filename or None,
            language=None,
        )

    return UploadedFileMeta(
        path=key,
        filename=filename or _filename_from_key(key),
        size=len(data),
        uploaded_at=_now_iso(),
        mime_type=file.content_type,
    )


@storage_router.get("/{intake_id}/storage/signed-url")
def create_signed_url(
    intake_id: str,
    path: str,
    expires_in: int = 300,
    identity: Identity = Depends(get_current_identity),
    repos: tuple = Depends(get_intake_and_source_repos),
) -> SignedUrlView:
    """Return a keyless V4 signed GET URL for one object key (DOC-01, D-10).

    Ownership 404 (cross-tenant / missing intake -> 404, D-08); then the key-PREFIX
    assert (``key.startswith(f"{intake.space_id}/{intake_id}/")``) denies a forged path
    aimed at another tenant's tree with 404 (existence hidden). The seam clamps the TTL
    to <= 900s (D-10); the advertised ``expires_in`` is the same EFFECTIVE lifetime the
    client may rely on. Disposition is ``attachment`` (forced download, T-09-04) —
    emitted inside the seam.
    """
    intake_repo, _source_repo = repos

    intake = intake_repo.get(intake_id)
    if intake is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")

    prefix = f"{intake.space_id}/{intake_id}/"
    if not path.startswith(prefix):
        # A forged / cross-tenant key on an owned intake — existence hidden (D-08).
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Object not found")

    url = gcs.signed_download_url(
        path,
        ttl_seconds=expires_in,
        filename=_filename_from_key(path),
        content_type=None,
    )
    # The seam clamps internally; advertise the SAME effective ceiling so the client
    # never relies on a lifetime longer than what was actually signed (D-10).
    effective_ttl = gcs._clamp_ttl(expires_in)
    return SignedUrlView(url=url, expires_in=effective_ttl)


@storage_router.delete("/{intake_id}/storage/objects")
def delete_objects(
    intake_id: str,
    body: DeleteObjectsBody,
    identity: Identity = Depends(get_current_identity),
    repos: tuple = Depends(get_intake_and_source_repos),
) -> DeleteResult:
    """Delete object(s) AND clean the matching ``intake_sources`` ref(s) in ONE tx (D-09).

    Ownership 404; then a per-key PREFIX assert (any mismatch -> 404, D-08) BEFORE any
    seam call — so a forged key never reaches GCS or the DB. For each validated key:
    ``gcs.delete_object`` (idempotent on an already-gone object) then the scoped
    ``intake_sources`` ref cleanup on the SAME session (T-09-09 — no dangling ref, no
    orphaned object). Returns the count of objects removed.
    """
    intake_repo, source_repo = repos

    intake = intake_repo.get(intake_id)
    if intake is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")

    prefix = f"{intake.space_id}/{intake_id}/"
    # Validate EVERY key BEFORE deleting anything — an all-or-nothing prefix gate so a
    # forged key in the batch can never reach the seam (D-08).
    for key in body.paths:
        if not key.startswith(prefix):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Object not found")

    removed = 0
    for key in body.paths:
        gcs.delete_object(key)  # idempotent (Pitfall 6)
        # Clean the matching source ref in the SAME tx (D-09). Scoped delete: a user can
        # only remove a row in their own space (repo _scope wall, D-01).
        source_repo.delete_by_storage_path(intake_id, key)
        removed += 1

    return DeleteResult(removed=removed)
