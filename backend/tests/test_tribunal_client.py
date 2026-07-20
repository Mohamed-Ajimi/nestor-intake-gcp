"""Unit tests for the Tribunal integration seam client (Phase 14, SEAM-02).

These exercise ``app.research.tribunal_client`` with BOTH external dependencies
mocked — ``google.oauth2.id_token.fetch_id_token`` (no ADC / GCP credentials) and
``httpx.post`` (no network) — so the suite runs on a box with no GCP identity and
no outbound connectivity (mirrors ``fake_resend`` / ``fake_anthropic`` discipline).

Locked invariants (Task 2 <behavior>):
- ``ensure_org`` mints a token via ``fetch_id_token(transport, service_url)`` and
  POSTs to ``{service_url}/api/orgs/ensure`` with the D-05 acting-user headers +
  the ``X-Nestor-Tenant-Id`` == space_id tenant header; a 2xx returns without raising.
- A non-2xx response raises ``httpx.HTTPStatusError`` (via ``raise_for_status``).
- ``ensure_project`` POSTs to ``{service_url}/api/projects/ensure`` with the same
  headers and returns ``project_id`` from the JSON body.
- The OIDC audience passed to ``fetch_id_token`` is EXACTLY the service URL with no
  path suffix (Pitfall 4).

``app.research.tribunal_client`` is imported LAZILY via ``importorskip`` so this
module collects cleanly on a box without google-auth / httpx installed (dev machine
has no Python; the suite runs in Cloud Build).
"""

from __future__ import annotations

import pytest

httpx = pytest.importorskip("httpx")
tc = pytest.importorskip("app.research.tribunal_client")

# Canonical inputs reused across cases.
_SERVICE_URL = "https://tribunal-api-xxxx.run.app"
_SPACE_ID = "11111111-1111-4111-8111-111111111111"
_ACTING_UID = "superadmin-uid-abc"
_ACTING_EMAIL = "ops@agenic.be"
_FAKE_TOKEN = "fake.oidc.id-token"


class _FakeResponse:
    """Minimal httpx.Response stand-in: records nothing, controls raise + json."""

    def __init__(self, *, status_code: int = 200, json_body: dict | None = None):
        self.status_code = status_code
        self._json_body = json_body or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            # Match the real httpx contract: raise_for_status -> HTTPStatusError.
            raise httpx.HTTPStatusError(
                f"{self.status_code} error",
                request=httpx.Request("POST", _SERVICE_URL),
                response=httpx.Response(self.status_code),
            )

    def json(self) -> dict:
        return self._json_body


def _install_mocks(
    monkeypatch: pytest.MonkeyPatch,
    *,
    response: _FakeResponse,
) -> dict:
    """Patch fetch_id_token + httpx.post; return a dict capturing the calls."""
    captured: dict = {}

    def _fake_fetch_id_token(transport, audience):
        captured["fetch_transport"] = transport
        captured["fetch_audience"] = audience
        return _FAKE_TOKEN

    def _fake_post(url, *, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return response

    # Patch the token minter on the module under test's imported symbol.
    monkeypatch.setattr(tc.ga_id_token, "fetch_id_token", _fake_fetch_id_token)
    monkeypatch.setattr(tc.httpx, "post", _fake_post)
    return captured


def test_ensure_org_mints_token_and_sends_headers(monkeypatch):
    """ensure_org POSTs to /api/orgs/ensure with token + acting-user + tenant headers."""
    captured = _install_mocks(monkeypatch, response=_FakeResponse(status_code=200))

    tc.ensure_org(
        service_url=_SERVICE_URL,
        space_id=_SPACE_ID,
        acting_user_id=_ACTING_UID,
        acting_email=_ACTING_EMAIL,
    )

    assert captured["url"] == f"{_SERVICE_URL}/api/orgs/ensure"
    h = captured["headers"]
    assert h["Authorization"] == f"Bearer {_FAKE_TOKEN}"
    assert h["X-Nestor-Tenant-Id"] == _SPACE_ID
    assert h["X-Acting-User-Id"] == _ACTING_UID
    assert h["X-Acting-User-Email"] == _ACTING_EMAIL
    assert captured["timeout"] == tc._TIMEOUT_S


def test_ensure_org_audience_is_service_url_without_path(monkeypatch):
    """The OIDC audience is EXACTLY the service URL — no path suffix (Pitfall 4)."""
    captured = _install_mocks(monkeypatch, response=_FakeResponse(status_code=200))

    tc.ensure_org(
        service_url=_SERVICE_URL,
        space_id=_SPACE_ID,
        acting_user_id=_ACTING_UID,
        acting_email=_ACTING_EMAIL,
    )

    assert captured["fetch_audience"] == _SERVICE_URL
    assert "/api/" not in captured["fetch_audience"]
    assert captured["fetch_transport"] is tc._TRANSPORT


def test_ensure_org_raises_on_non_2xx(monkeypatch):
    """A non-2xx response raises httpx.HTTPStatusError via raise_for_status."""
    _install_mocks(monkeypatch, response=_FakeResponse(status_code=403))

    with pytest.raises(httpx.HTTPStatusError):
        tc.ensure_org(
            service_url=_SERVICE_URL,
            space_id=_SPACE_ID,
            acting_user_id=_ACTING_UID,
            acting_email=_ACTING_EMAIL,
        )


def test_ensure_project_posts_and_returns_project_id(monkeypatch):
    """ensure_project POSTs to /api/projects/ensure and returns project_id from body."""
    captured = _install_mocks(
        monkeypatch,
        response=_FakeResponse(status_code=200, json_body={"project_id": "proj-42"}),
    )

    project_id = tc.ensure_project(
        service_url=_SERVICE_URL,
        space_id=_SPACE_ID,
        acting_user_id=_ACTING_UID,
        acting_email=_ACTING_EMAIL,
    )

    assert project_id == "proj-42"
    assert captured["url"] == f"{_SERVICE_URL}/api/projects/ensure"
    h = captured["headers"]
    assert h["Authorization"] == f"Bearer {_FAKE_TOKEN}"
    assert h["X-Nestor-Tenant-Id"] == _SPACE_ID
    assert h["X-Acting-User-Id"] == _ACTING_UID
    assert h["X-Acting-User-Email"] == _ACTING_EMAIL


def test_ensure_project_raises_on_non_2xx(monkeypatch):
    """ensure_project also raises on a non-2xx response (before reading the body)."""
    _install_mocks(
        monkeypatch,
        response=_FakeResponse(status_code=500, json_body={"project_id": "unused"}),
    )

    with pytest.raises(httpx.HTTPStatusError):
        tc.ensure_project(
            service_url=_SERVICE_URL,
            space_id=_SPACE_ID,
            acting_user_id=_ACTING_UID,
            acting_email=_ACTING_EMAIL,
        )
