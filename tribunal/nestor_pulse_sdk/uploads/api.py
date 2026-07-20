"""
SDK upload endpoints: presign (GCS signed PUT URL) + extract (Cloud Function proxy).

References:
- 01-PLAN.md Plan 10 Task 2 -- SDK upload endpoints
- 01-CONTEXT.md D-02 -- engine toggle; D-10 -- auth abstraction
- 01-RESEARCH.md T-10-02 -- cross-tenant upload prevention (key prefix guard)
- 01-PATTERNS.md lines 113-132 -- server.py upload proxy shape to mirror
- CLAUDE.md § AWS Infrastructure -- presigned_upload Lambda (legacy)
- memory/project_gcp_sa_key_policy.md -- no SA keys; use iam.Signer with ADC

Threat mitigations from Plan 10 STRIDE register:
  T-10-01: function --no-allow-unauthenticated; extract endpoint fetches identity token via ADC
  T-10-02: extract endpoint validates key prefix == uploads/{tenant_id}/ (defense-in-depth vs T-10-02)
  T-10-07: no SA keys created (Signer uses roles/iam.serviceAccountTokenCreator)
"""
from __future__ import annotations

import os
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from nestor_pulse_sdk.auth.deps import get_current_user
from nestor_pulse_sdk.auth.provider import AuthClaims

router = APIRouter(prefix="/api/upload", tags=["upload"])

# ── Request schemas ──────────────────────────────────────────────────────────

class PresignRequest(BaseModel):
    """Request body for POST /api/upload/presign."""
    filename: str
    session_id: str | None = None  # Optional: legacy compat with server.py / AWS shape


class ExtractRequest(BaseModel):
    """Request body for POST /api/upload/extract."""
    key: str           # GCS object key, e.g. uploads/{tenant_id}/{fileId}_{filename}
    bucket: str | None = None  # Optional override; defaults to UPLOADS_GCS_BUCKET env var
    session_id: str | None = None  # Optional: legacy compat


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/presign")
async def presign_upload(
    payload: PresignRequest,
    user: AuthClaims = Depends(get_current_user),
) -> dict:
    """
    Return a signed PUT URL to gs://nestor-uploads-prod/uploads/{tenant_id}/{fileId}_{filename}.

    Key shape mirrors AWS/agents/presigned_upload/index.mjs:41-50 (PATTERNS line 24).
    Signing uses roles/iam.serviceAccountTokenCreator on the runtime SA -- NO SA key
    (org policy iam.disableServiceAccountKeyCreation; see project_gcp_sa_key_policy.md).
    """
    from google.auth import default
    from google.auth.transport.requests import Request as GoogleRequest
    from google.auth import iam as google_iam
    from google.cloud import storage

    bucket_name = os.environ.get("UPLOADS_GCS_BUCKET", "nestor-uploads-prod")
    runtime_sa = os.environ.get(
        "RUNTIME_SA_EMAIL",
        "nestor-pulse-runtime@project-cb01b861-cb4a-438d-b9a.iam.gserviceaccount.com",
    )

    file_id = str(uuid.uuid4())
    # Key shape: uploads/{tenant_id}/{fileId}_{filename}
    # tenant_id comes from the JWT (T-10-02: keys are tenant-scoped at creation time)
    key = f"uploads/{user.tenant_id}/{file_id}_{payload.filename}"

    try:
        # ADC-based signing -- no SA JSON key needed
        credentials, _ = default()
        auth_req = GoogleRequest()
        credentials.refresh(auth_req)

        signer = google_iam.Signer(auth_req, credentials, runtime_sa)
        client = storage.Client()
        blob = client.bucket(bucket_name).blob(key)
        upload_url = blob.generate_signed_url(
            version="v4",
            expiration=300,  # 5 min; T-10-05 (DoS via unbounded uploads)
            method="PUT",
            content_type="application/pdf",
            credentials=signer,
            service_account_email=runtime_sa,
        )
    except Exception as exc:
        raise HTTPException(502, f"could not generate signed URL: {exc}") from exc

    return {
        "upload_url": upload_url,
        "key": key,
        "file_id": file_id,
        "bucket": bucket_name,
        "filename": payload.filename,
        # Legacy compat fields (mirror presigned_upload Lambda response shape)
        "session_id": payload.session_id or user.tenant_id,
        "expiresIn": 300,
    }


@router.post("/extract")
async def extract_uploaded(
    payload: ExtractRequest,
    user: AuthClaims = Depends(get_current_user),
) -> dict:
    """
    Invoke the Cloud Function pdf-extractor for the given GCS key.

    Validates key prefix against user.tenant_id (T-10-02).
    Fetches an identity token via ADC to call the function (no SA key, T-10-01/T-10-07).
    """
    # T-10-02: verify key is scoped to this tenant (defense-in-depth on top of bucket IAM)
    if not payload.key.startswith(f"uploads/{user.tenant_id}/"):
        raise HTTPException(403, "key outside tenant scope")

    fn_url = os.environ.get("PDF_EXTRACTOR_URL", "")
    if not fn_url:
        raise HTTPException(503, "PDF_EXTRACTOR_URL not configured; run Plan 10 Task 1 deploy")

    # Obtain identity token for the Cloud Run function audience (no SA key required)
    try:
        from google.auth.transport.requests import Request as GoogleRequest
        from google.oauth2 import id_token as google_id_token

        auth_req = GoogleRequest()
        token = google_id_token.fetch_id_token(auth_req, fn_url)
    except Exception as exc:
        raise HTTPException(502, f"could not obtain identity token: {exc}") from exc

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            fn_url,
            json={"key": payload.key, "bucket": payload.bucket, "session_id": payload.session_id},
            headers={"Authorization": f"Bearer {token}"},
        )

    if resp.status_code != 200:
        raise HTTPException(502, f"extractor returned {resp.status_code}: {resp.text[:500]}")

    return resp.json()
