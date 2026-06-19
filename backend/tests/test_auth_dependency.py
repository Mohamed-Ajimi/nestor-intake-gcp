"""AUTH-01/02/03 auth-dependency suite — the 401 (no/invalid token) vs 403
(missing role claim) split that plan 02's ``get_current_identity`` must satisfy.

This is a **Wave 0 RED scaffold** (D-09): the ``app.auth.*`` modules land in
plan 02, so these cases are RED until then. The harness must still *collect*
cleanly on this dev box (no firebase-admin installed, no live IdP), so:

- ``firebase_admin`` is pulled via ``pytest.importorskip`` (skips, never errors,
  when the Admin SDK is not yet installed — mirrors conftest's skip philosophy), and
- ``app.auth.dependencies`` / ``app.auth.identity`` are imported lazily inside a
  module-level ``pytest.importorskip`` so collection does not hard-error before
  plan 02 creates them.

Every IdP interaction is **mocked**: ``app.auth.dependencies.auth.verify_id_token``
is patched in each case. No test ever calls the live ``verify_id_token`` — a live
call would consume/leak real project state (threat T-03-02), so the contract is
verified entirely against mocks.

Authoritative references:
- .planning/phases/03-identity-platform-auth/03-RESEARCH.md
    § Code Examples (the four dependency cases: authorized / missing / invalid /
      missing-role) + § Validation Architecture (test map, AUTH-01/02/03 rows)
- .planning/phases/03-identity-platform-auth/03-PATTERNS.md
    § test_auth_dependency.py -- TestClient + patched verify_id_token, 401/403 split
- threat_model T-03-02 (all IdP calls patched) / T-03-03 (pin the 401 vs 403 contract)
- D-09 (author-by-construction; mocks only, live IdP deferred to GCP)
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

# firebase-admin supplies the InvalidIdTokenError type the dependency raises 401 on.
# Skip (do NOT error) when the Admin SDK is not yet installed on this box (Wave 0).
firebase_admin = pytest.importorskip("firebase_admin")
from firebase_admin import auth as fb_auth  # noqa: E402  (after importorskip)

# app.auth.* lands in plan 02 — skip cleanly until then so this scaffold collects.
dependencies = pytest.importorskip("app.auth.dependencies")
identity_mod = pytest.importorskip("app.auth.identity")

get_current_identity = dependencies.get_current_identity
Identity = identity_mod.Identity


def _build_app() -> FastAPI:
    """A tiny app with ONE route guarded by the real dependency under test.

    The route echoes the resolved role so an authorized case can assert the
    claim actually flowed through ``get_current_identity`` -> ``Identity``.
    """
    app = FastAPI()

    @app.get("/whoami")
    def whoami(identity: Identity = Depends(get_current_identity)):
        return {"role": identity.role, "uid": identity.uid}

    return app


def test_authorized_token():
    """Valid bearer token with a full claim set -> 200 and the role echoed."""
    decoded = {
        "uid": "user-123",
        "email": "user@example.com",
        "role": "superadmin",
        "space_id": "00000000-0000-0000-0000-0000000000d0",
    }
    with patch.object(dependencies.auth, "verify_id_token", return_value=decoded):
        client = TestClient(_build_app())
        resp = client.get("/whoami", headers={"Authorization": "Bearer good-token"})

    assert resp.status_code == 200
    assert resp.json()["role"] == "superadmin"


def test_missing_token_401_or_403():
    """No Authorization header -> HTTPBearer rejects before the body runs.

    Accept either 401 or 403: Starlette's ``HTTPBearer`` defaults to 403 on a
    missing credential, while an explicit ``auto_error``/handler may map it to
    401. The contract is "unauthenticated requests never reach the handler",
    not the exact code, so we pin the pair.
    """
    # No need to patch verify_id_token: the request never gets that far.
    client = TestClient(_build_app())
    resp = client.get("/whoami")

    assert resp.status_code in (401, 403)


def test_invalid_token_401():
    """A token that fails verification -> 401 (authentication failed)."""
    with patch.object(
        dependencies.auth,
        "verify_id_token",
        side_effect=fb_auth.InvalidIdTokenError("bad token"),
    ):
        client = TestClient(_build_app())
        resp = client.get("/whoami", headers={"Authorization": "Bearer bad-token"})

    assert resp.status_code == 401


def test_missing_role_claim_403():
    """A verified token with NO ``role`` claim -> 403 (authenticated but not
    authorized — the claim sync has not run / the user has no membership)."""
    decoded = {"uid": "user-456", "email": "norole@example.com"}  # no "role"
    with patch.object(dependencies.auth, "verify_id_token", return_value=decoded):
        client = TestClient(_build_app())
        resp = client.get("/whoami", headers={"Authorization": "Bearer no-role-token"})

    assert resp.status_code == 403
