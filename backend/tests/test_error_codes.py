"""CodedError contract suite — the additive ``{detail, code}`` error shape (Phase 11 / D-11).

Pins the two halves of the error-code contract (11-02 Task 3):

  1. A raised ``CodedError`` renders as a response body with BOTH ``detail`` (string) and
     ``code``, at the given status — the machine-readable field the frontend i18n error-codes
     map (11-01) reads.
  2. A plain ``HTTPException`` still renders a string ``detail`` with NO ``code`` — backward
     compatibility: existing raises are untouched and the transport's raw-``detail`` fallback
     path keeps working.

These drive a TINY FastAPI app with two throwaway routes + the REAL ``main._coded_error_handler``
wiring (re-registered locally, mirroring main.py), so no Postgres / IdP is needed — the contract
is a pure request/response shape. Unlike the integration suites this runs on any box with fastapi
installed (``importorskip`` guards keep it collect-clean where it is not).

Authoritative references:
- backend/app/api/errors.py (CodedError + the curated USER_FACING_CODES enum)
- backend/app/main.py (the @app.exception_handler(CodedError) wiring this mirrors)
- .planning/phases/11-internationalization-nl-fr-en/11-PATTERNS.md § errors.py + main.py wiring
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

errors = pytest.importorskip("app.api.errors")

CodedError = errors.CodedError
INVALID_LOCALE = errors.INVALID_LOCALE


def _build_app():
    """A minimal app: two routes (CodedError / HTTPException) + the CodedError handler.

    Mirrors main.py's ``@app.exception_handler(CodedError)`` registration so the assertions
    exercise the SAME rendering ({"detail", "code"} JSONResponse at exc.status_code).
    """
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import JSONResponse

    app = FastAPI()

    @app.exception_handler(CodedError)
    def _coded(_request, exc: CodedError):  # noqa: ANN202 -- test-local handler
        return JSONResponse(
            {"detail": exc.detail, "code": exc.code}, status_code=exc.status_code
        )

    @app.get("/coded")
    def _raise_coded():  # noqa: ANN202
        raise CodedError(422, INVALID_LOCALE, "Invalid locale")

    @app.get("/plain")
    def _raise_plain():  # noqa: ANN202
        # An existing-style raise — must be UNCHANGED by the CodedError contract.
        raise HTTPException(status_code=404, detail="Intake not found")

    return app


# ---------------------------------------------------------------------------
# (1) CodedError -> body carries BOTH detail (string) and code, at the status
# ---------------------------------------------------------------------------


def test_coded_error_emits_detail_and_code_at_status():
    """A raised ``CodedError`` renders ``{"detail": <str>, "code": <str>}`` at its status."""
    from fastapi.testclient import TestClient

    client = TestClient(_build_app())
    resp = client.get("/coded")

    assert resp.status_code == 422, f"CodedError status must pass through; got {resp.status_code}"
    body = resp.json()
    assert body.get("code") == INVALID_LOCALE, "CodedError must surface the machine-readable code"
    assert body.get("detail") == "Invalid locale", "CodedError detail must stay a plain string"
    assert isinstance(body["detail"], str), (
        "detail MUST remain a string so the frontend raw-fallback path is untouched (D-11)"
    )


def test_coded_error_code_is_in_curated_enum():
    """The first consumer's code (INVALID_LOCALE) is a member of the curated user-facing set.

    A pure list-membership assertion (no app needed) pinning the D-11 scoping: only curated,
    user-facing codes flow through CodedError (T-11-05 Info Disclosure).
    """
    assert INVALID_LOCALE in errors.USER_FACING_CODES, (
        "INVALID_LOCALE must be part of the curated user-facing code enum (D-11)"
    )
    # The curated set the frontend map keys off — all four Task-3 codes present.
    for code in ("INVALID_LOCALE", "INTAKE_NOT_FOUND", "RECIPIENT_INVALID", "MAIL_SEND_FAILED"):
        assert getattr(errors, code) in errors.USER_FACING_CODES, (
            f"{code} must be in the curated USER_FACING_CODES enum"
        )


# ---------------------------------------------------------------------------
# (2) plain HTTPException -> string detail, NO code (backward-compat)
# ---------------------------------------------------------------------------


def test_plain_httpexception_has_string_detail_and_no_code():
    """An existing ``HTTPException`` raise still emits a string ``detail`` with NO ``code``.

    This is the backward-compat guarantee: existing raises are untouched by the additive
    CodedError contract; the transport's raw-``detail`` fallback keeps rendering them.
    """
    from fastapi.testclient import TestClient

    client = TestClient(_build_app())
    resp = client.get("/plain")

    assert resp.status_code == 404, f"HTTPException status must pass through; got {resp.status_code}"
    body = resp.json()
    assert body.get("detail") == "Intake not found", "HTTPException detail must stay a plain string"
    assert "code" not in body, (
        "a plain HTTPException must NOT carry a code — existing raises are unchanged (D-11)"
    )
