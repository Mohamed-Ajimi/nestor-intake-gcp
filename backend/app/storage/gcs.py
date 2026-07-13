"""GCS external-client seam — the test monkeypatch target (Phase 9 twin of app/ai/clients.py).

These four functions — ``upload_object`` / ``signed_download_url`` /
``delete_object`` / ``download_bytes`` — are the ONLY place the backend touches
Google Cloud Storage. The storage test suites monkeypatch them (the ``fake_gcs``
fixture in tests/conftest.py) so no test ever reaches a real bucket, and the
route handlers (09-02) MUST call through this module (``gcs.upload_object(...)``)
rather than constructing SDK clients inline — same discipline as the
``anthropic_client`` / ``openai_client`` factories.

Credentials are Application Default Credentials ONLY (``google.auth.default()``):
the Cloud Run attached service account signs V4 URLs via the IAM signBlob API,
so NO SA JSON key file is ever loaded, referenced, or constructed here
(T-09-01 — enforced by scripts/ci_no_sa_json_key.sh). The bucket NAME is the
only configuration and it is non-secret (``Settings.storage_bucket``, env
``STORAGE_BUCKET``); it is read via ``get_settings()`` INSIDE the function
bodies — never at module import — so tests can vary the environment per case.

Grep-guard: this module constructs NO database engines or sessions of any kind.
It is HTTP/transport only — every tenant-scoped read/write stays in app/db/.

Authoritative references:
- .planning/phases/09-gcs-storage/09-01-PLAN.md <interfaces> (this contract)
- D-10 (signed-URL TTL ceiling 900s), D-05 (server-authored keys),
  T-09-03 (TTL clamp), T-09-04 (attachment disposition — no inline render)
"""

from __future__ import annotations

from datetime import timedelta

import google.auth
import google.auth.transport.requests
from google.api_core import exceptions as api_exceptions
from google.cloud import storage

from app.core.config import get_settings
from app.storage.keys import sanitize_filename

# D-10: hard server-side ceiling for signed-URL lifetimes. A client may ask for
# any expires_in; the effective TTL is clamped to <= 900 seconds (15 min).
_MAX_TTL_S = 900
# Default TTL when the caller does not ask for a specific lifetime.
_DEFAULT_TTL_S = 300


def _clamp_ttl(ttl_seconds: int) -> int:
    """Clamp a requested TTL into ``[1, _MAX_TTL_S]`` (D-10 / T-09-03).

    Pure arithmetic (unit-testable without any GCS/auth machinery): a huge or
    negative request can never widen the exposure window past 900 seconds.
    """
    return max(1, min(int(ttl_seconds), _MAX_TTL_S))


def _bucket() -> "storage.Bucket":
    """Return the configured bucket handle (bucket name read HERE, call time).

    ``get_settings().storage_bucket`` (env ``STORAGE_BUCKET``) is resolved
    inside the function body — never at module top-level — mirroring the
    call-time discipline of app/ai/clients.py. A missing bucket name raises
    loudly rather than degrading to a default bucket.
    """
    bucket_name = get_settings().storage_bucket
    if not bucket_name:
        raise RuntimeError(
            "STORAGE_BUCKET is not configured — set the env var on Cloud Run "
            "(non-secret; see Settings.storage_bucket)."
        )
    return storage.Client().bucket(bucket_name)


def upload_object(key: str, data: bytes, content_type: str | None = None) -> None:
    """Upload ``data`` under the server-authored ``key`` (DOC-02 backend-mediated).

    ``key`` MUST come from :func:`app.storage.keys.build_object_key` — this
    seam never authors or validates keys itself (the route layer owns the
    ownership/prefix checks, D-08).
    """
    _bucket().blob(key).upload_from_string(data, content_type=content_type)


def signed_download_url(
    key: str,
    *,
    ttl_seconds: int,
    filename: str,
    content_type: str | None = None,
) -> str:
    """Return a keyless V4 signed GET URL for ``key`` (DOC-01, D-10).

    - TTL is clamped server-side to ``_MAX_TTL_S`` (900s) via :func:`_clamp_ttl`
      — a client-requested lifetime can never exceed it (T-09-03).
    - ``response_disposition`` is ALWAYS ``attachment`` so the browser downloads
      the object and never renders it inline (stored-XSS neutralized, T-09-04).
    - Signing is keyless: ADC credentials are refreshed and the V4 signature is
      produced via the IAM signBlob API using the attached service account —
      no key material exists in the process (T-09-01).

    NOTE (Assumption A1): the exact keyless kwargs (``service_account_email`` +
    ``access_token``) must be confirmed against the installed
    ``Blob.generate_signed_url`` signature in the Cloud Build run — the
    google-cloud-storage 3.x docs document this signBlob path, but the pinned
    wheel is the source of truth.
    """
    ttl = _clamp_ttl(ttl_seconds)
    # WR-01: sanitize the download filename inside the seam (single choke point) so a
    # client-influenced tail can never inject into the Content-Disposition header (strips
    # quotes/semicolons/control chars via the shared keys.py sanitizer, T-09-02/T-09-04).
    safe_filename = sanitize_filename(filename)
    credentials, _project = google.auth.default()
    credentials.refresh(google.auth.transport.requests.Request())
    blob = _bucket().blob(key)
    return blob.generate_signed_url(
        version="v4",
        expiration=timedelta(seconds=ttl),
        method="GET",
        service_account_email=credentials.service_account_email,
        access_token=credentials.token,
        response_disposition=f'attachment; filename="{safe_filename}"',
        response_type=content_type or None,
    )


def delete_object(key: str) -> None:
    """Delete the object at ``key`` — idempotent (Pitfall 6).

    A ``NotFound`` from GCS is treated as success: the desired end state
    ("object gone") already holds, so a retry or a ref-cleanup race never
    surfaces as an error to the caller (D-09).
    """
    try:
        _bucket().blob(key).delete()
    except api_exceptions.NotFound:
        pass  # already gone -> success (idempotent delete)


def download_bytes(key: str) -> bytes:
    """Download the full object at ``key`` as bytes (the transcribe audio fetch).

    Consumed by ``app.ai.skills.transcribe.download_audio_bytes`` (09-02) inside
    the AI-06 no-DB-connection window — this call holds no DB session.
    """
    return _bucket().blob(key).download_as_bytes()
