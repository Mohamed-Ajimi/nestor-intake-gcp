"""SDK secrets bootstrap — the ``Nestor_*`` secrets are canonical for provider keys.

Canonical mapping (Secret Manager secret ID -> env var the code reads):

    Nestor_Gemini  -> GOOGLE_API_KEY
    Nestor_Claude  -> ANTHROPIC_API_KEY
    Nestor_OpenAI  -> OPENAI_API_KEY

Why this wrapper exists
-----------------------
The legacy loader (``nestor_pulse/secrets.py``, read-only per D-01) hardcodes
the old secret IDs (``GOOGLE_API_KEY`` etc.) and overwrites any Cloud
Run-mounted env vars at process start ("Secret Manager values always win").
Remapping ``--set-secrets`` in the deploy scripts is therefore not enough on
its own — the deployed bootstrap would stomp the mounted values back to the
legacy secrets. This wrapper runs the legacy pull first (it still owns
``DATABASE_URL``, the GCS buckets, ``CUSTOM_SEARCH_BEARER_TOKEN``, …), then
re-pulls the three provider keys from the canonical ``Nestor_*`` secrets and
re-exports them under the env-var names every engine already reads.

Key rotation now happens by adding a new version to the ``Nestor_*`` secrets
only; the legacy-named secrets are frozen and slated for deletion.

Fail-loud like the legacy loader: a missing ``Nestor_*`` secret raises.
Callers that tolerate no-Secret-Manager environments (tests, LOCAL_DEV_AUTH)
already wrap the call in try/except.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# Secret Manager secret ID -> canonical env var name.
PROVIDER_KEY_SECRETS: dict[str, str] = {
    "Nestor_Gemini": "GOOGLE_API_KEY",
    "Nestor_Claude": "ANTHROPIC_API_KEY",
    "Nestor_OpenAI": "OPENAI_API_KEY",
}


def load_sdk_secrets_into_env() -> None:
    """Legacy Secret Manager pull, then override provider keys from Nestor_*."""
    from nestor_pulse.secrets import load_secrets_into_env

    # Legacy pull: DATABASE_URL, buckets, identity platform, bearer token, and
    # the old provider-key secrets (overridden below).
    load_secrets_into_env()

    # Canonical provider keys. The legacy loader exports each secret under its
    # own ID, so pull then rename. Fail-loud: Nestor_* are required.
    load_secrets_into_env(secret_names=tuple(PROVIDER_KEY_SECRETS))
    for secret_id, env_key in PROVIDER_KEY_SECRETS.items():
        value = os.environ.pop(secret_id, "")
        if not value:
            raise RuntimeError(
                f"Secret {secret_id!r} is empty — refusing to export a blank {env_key}"
            )
        os.environ[env_key] = value
    logger.info(
        "Provider API keys re-exported from canonical Nestor_* secrets: %s",
        ", ".join(f"{s}->{e}" for s, e in PROVIDER_KEY_SECRETS.items()),
    )
