"""Intake -> Tribunal integration seam client (SEAM-02, intake side, D-06).

Gives the intake backend the minimal HTTP machinery to drive the internal Tribunal
API: mint a **keyless** Google-signed OIDC ID token for the Tribunal service URL
audience, forward the acting superadmin's identity via headers, and call the
idempotent ``ensure_org`` / ``ensure_project`` provisioning endpoints.

Secret discipline (D-07): there is NO secret in this seam. The OIDC token is minted
keyless via ADC (``fetch_id_token``) from the attached service account — no SA JSON
key exists (org policy). The Tribunal service URL is NON-secret typed config
(``Settings.tribunal_service_url``), never read as a call-time ``os.environ`` secret
and never logged. The minted token is never logged either.

OIDC audience (Pitfall 4): ``fetch_id_token`` is called with the service URL WITHOUT
a path suffix as the audience. Cloud Run's OIDC receiver checks ``aud`` against the
service URL, so appending ``/api/...`` would fail verification. The request PATH is
added only when composing the POST URL, never to the token audience.

Wire contract (MUST match Plan 01's InternalCallerProvider header constants verbatim):
    Authorization: Bearer <id_token>
    X-Nestor-Tenant-Id: <space_id>       (space_id IS org.id — identity mapping)
    X-Acting-User-Id: <superadmin uid>   (the human, D-05 attribution)
    X-Acting-User-Email: <superadmin email>

Transport shape mirrors ``app/mail/resend.py``: a blocking ``httpx.post`` (not async)
with a module-const timeout + ``raise_for_status()``. The FastAPI handlers are sync-def
running on the pg8000 threadpool, so this stays synchronous too.

SCOPE (D-06): ``ensure_org`` / ``ensure_project`` ONLY. Run-trigger / status-poll /
report-fetch methods are Phase 16 (they must land against Phase 15's final report
shape). This module persists NOTHING — no ``project_id`` storage, no DB column
(``research_runs`` is Phase 16's).

Authoritative references:
- .planning/phases/14-auth-retirement-integration-seam/14-RESEARCH.md § Code Examples + Pitfall 4
- .planning/phases/14-auth-retirement-integration-seam/14-PATTERNS.md § tribunal_client.py
- app/mail/resend.py (the httpx.post + timeout + raise_for_status shape)
"""

from __future__ import annotations

import httpx
from google.auth.transport import requests as ga_requests
from google.oauth2 import id_token as ga_id_token

#: Reusable transport for keyless OIDC minting (ADC-backed). One per process is fine.
_TRANSPORT = ga_requests.Request()

#: Transport timeout (seconds) for the seam POSTs. 30s per RESEARCH (the /ensure
#: endpoints are quick provisioning calls; more generous than the 15s mail path).
_TIMEOUT_S = 30.0

#: Header-name constants — MUST match Plan 01's InternalCallerProvider verbatim.
_HDR_TENANT_ID = "X-Nestor-Tenant-Id"
_HDR_ACTING_USER_ID = "X-Acting-User-Id"
_HDR_ACTING_USER_EMAIL = "X-Acting-User-Email"


def _mint_id_token(service_url: str) -> str:
    """Mint a keyless Google-signed OIDC ID token for ``service_url`` as audience.

    Uses ADC (the attached service account) via ``fetch_id_token`` — no SA JSON key.
    The audience is the service URL WITHOUT a path suffix (Pitfall 4); the caller must
    NOT pass a URL that includes ``/api/...``.
    """
    return ga_id_token.fetch_id_token(_TRANSPORT, service_url)


def _headers(
    service_url: str,
    space_id: str,
    acting_user_id: str,
    acting_email: str,
) -> dict[str, str]:
    """Build the Bearer + D-05 acting-user + tenant headers for a seam call.

    The token is minted fresh per call (mints are cheap and keep the token short-lived).
    ``space_id`` is sent verbatim as the tenant id (space_id IS org.id — identity mapping).
    """
    return {
        "Authorization": f"Bearer {_mint_id_token(service_url)}",
        _HDR_TENANT_ID: space_id,
        _HDR_ACTING_USER_ID: acting_user_id,
        _HDR_ACTING_USER_EMAIL: acting_email,
    }


def ensure_org(
    *,
    service_url: str,
    space_id: str,
    acting_user_id: str,
    acting_email: str,
) -> None:
    """Idempotently provision the Tribunal org for ``space_id`` (raises on non-2xx).

    POSTs to ``{service_url}/api/orgs/ensure`` with the minted OIDC token + the D-05
    acting-user headers + the ``X-Nestor-Tenant-Id`` tenant header. The endpoint is
    idempotent (ensure semantics), so repeated calls are safe. Raises
    ``httpx.HTTPStatusError`` on any non-2xx status.
    """
    resp = httpx.post(
        f"{service_url}/api/orgs/ensure",
        headers=_headers(service_url, space_id, acting_user_id, acting_email),
        json={},
        timeout=_TIMEOUT_S,
    )
    resp.raise_for_status()


def ensure_project(
    *,
    service_url: str,
    space_id: str,
    acting_user_id: str,
    acting_email: str,
) -> str:
    """Idempotently provision the Tribunal project for ``space_id``; return project_id.

    POSTs to ``{service_url}/api/projects/ensure`` with the same headers as
    :func:`ensure_org`. Raises ``httpx.HTTPStatusError`` on non-2xx; on success returns
    the ``project_id`` from the JSON response body. Does NOT persist the id (Phase 16
    owns ``research_runs``).
    """
    resp = httpx.post(
        f"{service_url}/api/projects/ensure",
        headers=_headers(service_url, space_id, acting_user_id, acting_email),
        json={},
        timeout=_TIMEOUT_S,
    )
    resp.raise_for_status()
    return resp.json()["project_id"]
