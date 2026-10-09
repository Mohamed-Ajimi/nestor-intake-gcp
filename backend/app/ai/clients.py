"""External-API client factories — the test monkeypatch seam (D-05, D-07).

Each factory reads its API key from ``os.environ`` **at call time**, inside the
function body — never at module import, never assigned to a logged variable, and
never placed in ``app.core.config.Settings``. This is decision D-07: API keys
arrive as Cloud Run env (mapped from Secret Manager, 07-08) and must stay out of
the non-secret typed config so they cannot leak into logs or the container image.

These two factory names — ``anthropic_client`` and ``openai_client`` — are the
seam the 07-01 tests monkeypatch to fake the external calls, so callers
(``app/ai/skills.py``, ``app/ai/search.py`` in 07-05/06/07) MUST obtain their
client through these functions rather than constructing the SDK clients inline.

Grep-guard: this module constructs NO database engines or sessions of any kind.
It is HTTP transport only — every tenant-scoped read/write stays in app/db/.

Authoritative references:
- .planning/phases/07-ai-function-ports/07-RESEARCH.md § Code Examples §1 (:275-296)
- docs/supabase-functions/apply-intake-skill.ts:7,220-238 (legacy x-api-key fetch)
- D-07 (secrets via Secret Manager → env; read at call time, never in Settings)
"""

from __future__ import annotations

import os
from typing import Any

import anthropic
import openai

# Per-request timeouts (seconds). OpenAI embeddings/transcription use 180 s for the
# long Whisper path (07-RESEARCH § Code Examples §1/§4).
#
# Anthropic (quick 261009-ib5): every Claude skill call STREAMS through
# ``create_message`` below, so this float becomes an httpx ``Timeout`` whose connect /
# read / write / pool limits are each 180 s. On a stream the READ limit applies to each
# socket read, i.e. it is the longest allowed SILENCE between two chunks — not a cap on
# the whole answer. httpx has no whole-request (total) timeout, and none is added here,
# so a long, healthy generation can run as long as chunks keep arriving (the API also
# sends ``ping`` events). Before this change the call was non-streaming: the response
# stayed silent until Claude had finished, so any answer that took > 180 s to generate
# died with ``APITimeoutError`` (prod skill_runs 6bd63c35 / b7f44d5a: 3 x 180 s = 542 s).
_ANTHROPIC_TIMEOUT_S = 180.0
_OPENAI_TIMEOUT_S = 180.0


def anthropic_client() -> anthropic.Anthropic:
    """Return a fresh Anthropic client for a single skill call.

    The ``ANTHROPIC_API_KEY`` is read from ``os.environ`` HERE (call time, D-07):
    never at module top-level, never cached, never logged, never in Settings. A
    missing key raises ``KeyError`` loudly rather than degrading to an
    unauthenticated call.
    """
    return anthropic.Anthropic(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        timeout=_ANTHROPIC_TIMEOUT_S,
    )


def create_message(**kwargs: Any) -> anthropic.types.Message:
    """Run ONE Claude call as a stream and return the final ``Message``.

    The single transport every Claude skill uses (quick 261009-ib5). ``kwargs`` are the
    ``messages`` API arguments (``model``, ``max_tokens``, ``system``, ``messages``) and
    pass through unchanged. The return value is ``stream.get_final_message()`` — an
    ``anthropic.types.Message`` (the SDK's ``ParsedMessage`` subclass) with the SAME
    ``.content`` / ``.stop_reason`` / ``.usage.input_tokens`` / ``.usage.output_tokens``
    the non-streaming call returned, so parsing, cost and the D-4 truncation guard in the
    callers are unchanged.

    The client comes from :func:`anthropic_client` at CALL TIME (module-global lookup),
    so the key is still read per call (D-07) and the test monkeypatch seam still works.

    Timeout: see ``_ANTHROPIC_TIMEOUT_S`` — 180 s between chunks, no whole-answer cap.

    Retries (deliberate): only the SDK's own retries apply (``max_retries`` default 2).
    For a stream the SDK retry loop covers the request up to the response HEADERS —
    connection errors, a timeout before the response starts, 408/409/429/5xx/529 — i.e.
    failures before any output exists. Once the 200 arrives, the body is read outside
    that loop: a read timeout or a mid-stream ``error`` event raises to the caller and is
    NOT retried. There is intentionally no app-level loop that re-runs a whole generation
    on timeout: each attempt is a full, billed generation, and the skill's ``on_error``
    (D-09) already finalizes the run ``failed`` with the error message so the operator
    can re-run it deliberately.

    The ``with`` block closes the stream (releases the connection) on success and on error.
    """
    with anthropic_client().messages.stream(**kwargs) as stream:
        return stream.get_final_message()


def openai_client() -> openai.OpenAI:
    """Return a fresh OpenAI client for embeddings / Whisper transcription.

    The ``OPENAI_API_KEY`` is read from ``os.environ`` HERE (call time, D-07):
    same discipline as :func:`anthropic_client` — never module-level, never
    logged, never in Settings.
    """
    return openai.OpenAI(
        api_key=os.environ["OPENAI_API_KEY"],
        timeout=_OPENAI_TIMEOUT_S,
    )
