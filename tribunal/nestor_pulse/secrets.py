"""GCP Secret Manager bootstrap loader for Nestor Pulse.

Loads the 4 canonical Nestor secrets from GCP Secret Manager and writes them
into ``os.environ`` BEFORE any agent / tool module imports run. Downstream
modules continue to read via ``os.environ.get("...", "")``; no other code
needs to change.

Auth model
----------
This module uses **Application Default Credentials (ADC)** exclusively.
The Nestor GCP project enforces the org policy
``iam.disableServiceAccountKeyCreation``, which blocks the creation of
service-account JSON keys (see ``.planning/intel/access/gcp-bootstrap.md``).
There is therefore NO ``GOOGLE_APPLICATION_CREDENTIALS`` JSON-key path to
honour — ``google-cloud-secret-manager`` auto-detects ADC from:

* Local dev: ``~/.config/gcloud/application_default_credentials.json``
  (Windows: ``%APPDATA%\\gcloud\\application_default_credentials.json``),
  populated by ``gcloud auth application-default login``.
* GCP runtime (Phase 1 Cloud Run): Workload Identity attached to the runtime
  service account.

Secret naming
-------------
Per the ``gcp-bootstrap.md`` secret-naming amendment, every secret ID in
Secret Manager is identical to the environment variable name the Python
code already reads. The mapping is therefore 1-to-1 — no renaming.

Failure mode
------------
Fail-loud. If ANY secret cannot be fetched, the exception propagates and
the process aborts at import time. The entire point of this module is to
eliminate plaintext-in-source secrets; silently falling back to a missing
or stale ``.env`` would defeat the purpose.

Bootstrap ordering
------------------
Must be called from ``server.py`` AFTER ``load_dotenv()`` and BEFORE
``from nestor_pulse.agent import root_agent``. See PATTERNS.md §Shared
"Bootstrap ordering" for the rationale.
"""

from __future__ import annotations

import logging
import os
from typing import Iterable

logger = logging.getLogger(__name__)

# GCP project hosting the Nestor Pulse secrets (see gcp-bootstrap.md § Project).
PROJECT_ID = "project-cb01b861-cb4a-438d-b9a"

# Secret IDs in Secret Manager match the env-var names the existing Python
# code reads. 1-to-1 mapping; no rename. Order is irrelevant (independent reads).
#
# Phase 0 secrets (REQUIRED — fail loud if missing): GOOGLE_API_KEY,
# ANTHROPIC_API_KEY, OPENAI_API_KEY, CUSTOM_SEARCH_BEARER_TOKEN.
#
# Phase 1 additions per .planning/phases/01-production-foundation/01-RESEARCH.md
# § Runtime State Inventory. These are seeded by
# infrastructure/gcloud/secret-manager-bootstrap.sh and
# infrastructure/gcloud/cloudsql-create.sh. They are listed in
# OPTIONAL_PHASE1_SECRETS so the ADK pipeline can still boot in the gap
# between this commit landing and the Phase 1 GCP provisioning step
# completing (D-01 ADK preservation, RESEARCH § Pitfall 8). Once
# provisioning is done they load normally on every subsequent boot.
_PHASE0_REQUIRED_SECRETS: tuple[str, ...] = (
    "GOOGLE_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "CUSTOM_SEARCH_BEARER_TOKEN",
)
OPTIONAL_PHASE1_SECRETS: tuple[str, ...] = (
    "IDENTITY_PLATFORM_PROJECT_ID",
    "DATABASE_URL",
    "AUDIT_GCS_BUCKET",
    "UPLOADS_GCS_BUCKET",
    # Plan 10 Task 1: Cloud Function PDF extractor trigger URL.
    # Loaded best-effort (same as other Phase 1 optional secrets) so the ADK
    # pipeline can still boot before PDF_EXTRACTOR_URL is provisioned.
    "PDF_EXTRACTOR_URL",
)
SECRETS: tuple[str, ...] = _PHASE0_REQUIRED_SECRETS + OPTIONAL_PHASE1_SECRETS


def _fetch_secret(client, project_id: str, secret_name: str) -> str:
    """Read the ``latest`` version of one secret and return its UTF-8 payload."""
    resource = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
    response = client.access_secret_version(request={"name": resource})
    return response.payload.data.decode("utf-8")


def load_secrets_into_env(
    project_id: str = PROJECT_ID,
    secret_names: Iterable[str] = SECRETS,
) -> None:
    """Pull every secret from GCP Secret Manager into ``os.environ``.

    Parameters
    ----------
    project_id:
        GCP project ID hosting the secrets. Defaults to the canonical
        Nestor Pulse project.
    secret_names:
        Iterable of Secret Manager secret IDs to load. Defaults to the 4
        Phase 0 canonical Nestor secrets plus the 4 Phase 1 additions.
        Each secret ID is used directly as the ``os.environ`` key — no
        rename.

    Notes
    -----
    Secret Manager values always win over any pre-existing env value.
    A ``.env`` left around for local convenience is therefore safely
    overridden in any environment where this function is called.

    Phase 1 secrets (see ``OPTIONAL_PHASE1_SECRETS``) are loaded best-effort:
    if a Phase 1 secret is not yet present in Secret Manager (e.g., the
    ADK pipeline is booted before
    ``infrastructure/gcloud/secret-manager-bootstrap.sh`` has run), the
    NotFound is logged at WARNING and the bootstrap continues. Phase 0
    secrets remain fail-loud — a missing Phase 0 secret aborts.
    """
    # Imported lazily so a missing google-cloud-secret-manager install does
    # not break ``import nestor_pulse.secrets`` itself (e.g., during pure
    # unit tests that monkeypatch this function out).
    from google.cloud import secretmanager
    from google.api_core import exceptions as gcp_exceptions

    client = secretmanager.SecretManagerServiceClient()

    loaded: list[str] = []
    skipped_optional: list[str] = []
    for name in secret_names:
        try:
            value = _fetch_secret(client, project_id, name)
        except gcp_exceptions.NotFound:
            if name in OPTIONAL_PHASE1_SECRETS:
                logger.warning(
                    "Phase 1 secret %r not yet provisioned in Secret Manager (project=%s); "
                    "skipping. Run infrastructure/gcloud/secret-manager-bootstrap.sh "
                    "to seed it.",
                    name,
                    project_id,
                )
                skipped_optional.append(name)
                continue
            raise
        os.environ[name] = value
        loaded.append(name)

    logger.info(
        "Loaded %d secrets from GCP Secret Manager (project=%s) into os.environ "
        "(%d optional Phase 1 secrets skipped: %s)",
        len(loaded),
        project_id,
        len(skipped_optional),
        skipped_optional or "none",
    )


if __name__ == "__main__":
    # CLI smoke-test entry point. Prints lengths (never values) so a human
    # can confirm wiring without leaking secret material to the terminal.
    logging.basicConfig(level=logging.INFO)
    load_secrets_into_env()
    for _name in SECRETS:
        _val = os.environ.get(_name, "")
        print(f"{_name}: length={len(_val)}")
