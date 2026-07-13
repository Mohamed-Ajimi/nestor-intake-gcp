"""Resend HTTPS transport — the ONE function the test suite monkeypatches.

``send()`` is the single mail-egress seam. The test suite fakes THIS function
(``fake_resend`` in conftest, mirroring ``fake_anthropic`` / ``fake_gcs``); no
test ever reaches the real Resend API.

Secret discipline (D-07, mirrors ``app/ai/clients.py``): ``RESEND_API_KEY`` is
read from ``os.environ`` INSIDE the function body at call time — never at module
import, never assigned to a logged variable, never placed in
``app.core.config.Settings``. A missing key raises ``KeyError`` loudly rather
than degrading to an unauthenticated call.

Transport shape (ported from ``docs/supabase-functions/send-pulse-mail.ts``
lines 86-90): ``POST https://api.resend.com/emails`` with
``Authorization: Bearer <key>`` + ``Content-Type: application/json`` and a JSON
body ``{from, to, subject, html}``. The blocking ``httpx.post`` is used
deliberately (no async client): the FastAPI handlers are sync-def running on the
pg8000 threadpool, so the mail send stays synchronous too.

``FROM`` is unchanged from the legacy sender (D-13).
"""

from __future__ import annotations

import os

import httpx

#: Legacy sender, unchanged (D-13 — send-pulse-mail.ts:12).
FROM = "Nestor Pulse <nestor@agenic.be>"

#: Resend REST endpoint (send-pulse-mail.ts:86).
_RESEND_ENDPOINT = "https://api.resend.com/emails"

#: Transport timeout (seconds). A mail POST is a short request; 15s is generous.
_TIMEOUT_S = 15.0


def send(*, to: list[str], subject: str, html: str) -> str:
    """POST one mail through Resend; return the Resend message id (or "").

    Reads ``RESEND_API_KEY`` from ``os.environ`` HERE (call time, D-07): never at
    module top-level, never cached, never logged, never in Settings. A missing
    key raises ``KeyError`` loudly.

    Args:
        to: Recipient address list (Resend accepts an array of addresses).
        subject: Pre-rendered subject line.
        html: Pre-rendered HTML body (produced by ``app.mail.render``).

    Returns:
        The Resend message id from the response JSON (``""`` if absent).

    Raises:
        KeyError: if ``RESEND_API_KEY`` is not present in the environment.
        httpx.HTTPStatusError: if Resend returns a non-2xx status.
    """
    api_key = os.environ["RESEND_API_KEY"]
    resp = httpx.post(
        _RESEND_ENDPOINT,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={"from": FROM, "to": to, "subject": subject, "html": html},
        timeout=_TIMEOUT_S,
    )
    resp.raise_for_status()
    return resp.json().get("id", "")
