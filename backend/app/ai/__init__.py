"""Phase 7 AI seam — the external-API glue for the four Claude skills, OpenAI
embeddings, and Whisper transcription.

This package is HTTP / parse / config ONLY. It constructs **no database engines
or sessions** — the CI grep-guard (``ci_no_raw_db_access.sh``) bans engine/session
construction outside ``app/db/``. Tenant-scoped reads and writes live in
``app/db/ai_session.py`` (07-04); the handlers in ``app/api/ai_routes.py`` import
only this seam plus ``Identity``.

Modules:
- ``clients``  — anthropic / openai client factories (keys read from os.environ
  at CALL TIME, D-07 — never in Settings, never logged).
- ``prompts``  — the legacy system prompts carried verbatim (parity reference).
- ``parsing``  — extract_json / extract_json_array / estimate_cost_usd ports.
"""
