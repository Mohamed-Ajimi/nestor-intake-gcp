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

import anthropic
import openai

# Per-request timeouts (seconds). The Claude skill calls can run 90-120s on a
# large intake, so the Anthropic client gets a generous 180s ceiling; OpenAI
# embeddings/transcription reuse the same ceiling for the long Whisper path.
# (07-RESEARCH § Code Examples §1/§4: anthropic timeout=180.0, openai timeout=180.0.)
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
