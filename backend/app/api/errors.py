"""``CodedError`` — the additive machine-readable error-code contract (Phase 11 / D-11).

Today every raise in the API is ``raise HTTPException(status, "string")`` and the frontend
transport (``frontend/src/lib/api/client.ts``) reads the response body's ``detail`` string as
the raw fallback message. Phase 11's i18n needs SOME errors to carry a stable, language-neutral
``code`` so the frontend can look up a TRANSLATED message (``ERROR_CODES[code] -> t(key)``)
instead of surfacing the raw (Dutch/English) ``detail`` string.

``CodedError`` is the ADDITIVE mechanism (RESEARCH Pattern 4, option b):
  - it carries ``status_code``, ``code`` and ``detail``;
  - its FastAPI handler (registered in ``main.py``) emits ``{"detail": <str>, "code": <str>}``;
  - ``detail`` STAYS a plain string, so ``apiFetch``'s existing string-``detail`` raw-fallback
    path is UNCHANGED — an old client that ignores ``code`` still shows ``detail`` verbatim;
  - ``code`` is read ADDITIVELY by the new frontend error-codes map (11-01).

Existing ``raise HTTPException(status, "string")`` calls are LEFT UNTOUCHED (they keep working
via the raw-text fallback). Only CURATED, user-visible errors migrate to ``CodedError``.

SECURITY — Information Disclosure (T-11-05, disposition: mitigate): the code set below is a
CURATED, user-facing enum. Internal 4xx/5xx MUST keep generic messages via plain
``HTTPException`` — do NOT attach a ``code`` to an internal error and do NOT leak a stack trace
or an internal ``detail`` through this path. A ``code`` is only ever a value from the curated
constants here.

Authoritative references:
- .planning/phases/11-internationalization-nl-fr-en/11-RESEARCH.md § Pattern 4 / Open Q3
- .planning/phases/11-internationalization-nl-fr-en/11-PATTERNS.md § errors.py + main.py wiring
- frontend/src/lib/api/client.ts (the string-detail raw-fallback path this preserves)
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Curated user-facing code enum (D-11 scoping). These MUST match the keys the
# frontend ``ERROR_CODES`` map (11-01) references. Scope to errors a USER actually
# sees — never attach a code to an internal 4xx/5xx (T-11-05 Info Disclosure).
# ---------------------------------------------------------------------------

#: PATCH /me/locale rejected a locale not in {nl, fr, en} (the first CodedError consumer).
INVALID_LOCALE = "INVALID_LOCALE"
#: An intake id the caller asked for does not exist / is not visible to them.
INTAKE_NOT_FOUND = "INTAKE_NOT_FOUND"
#: A mail send was requested but the recipient address is missing/invalid.
RECIPIENT_INVALID = "RECIPIENT_INVALID"
#: A mail send reached the egress seam but the provider returned a failure.
MAIL_SEND_FAILED = "MAIL_SEND_FAILED"

#: The curated, user-facing code set. A ``CodedError.code`` should be one of these — the
#: frontend map keys off exactly this enum, and nothing outside it may carry a code.
USER_FACING_CODES = frozenset(
    {
        INVALID_LOCALE,
        INTAKE_NOT_FOUND,
        RECIPIENT_INVALID,
        MAIL_SEND_FAILED,
    }
)


class CodedError(Exception):
    """An API error carrying a machine-readable ``code`` alongside a string ``detail``.

    The ``main.py`` exception handler renders this as
    ``JSONResponse({"detail": detail, "code": code}, status_code=status_code)``. ``detail``
    stays a plain string (raw-fallback compatible); ``code`` is the additive field.

    Only raise this for CURATED, user-visible errors whose ``code`` is one of
    :data:`USER_FACING_CODES`. Internal errors keep plain ``HTTPException`` (T-11-05).
    """

    def __init__(self, status_code: int, code: str, detail: str) -> None:
        self.status_code = status_code
        self.code = code
        self.detail = detail
        # Keep a readable ``str(exc)`` for logs — never surfaced to the client body
        # (the handler emits only {detail, code}).
        super().__init__(f"{code}: {detail}")
