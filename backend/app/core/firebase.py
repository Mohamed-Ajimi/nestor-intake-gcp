"""Firebase Admin SDK init — idempotent process-singleton via ADC (no JSON key).

The Admin SDK must be initialized exactly once per process before any
``auth.verify_id_token`` (the request dependency) or ``auth.set_custom_user_claims``
(login-sync / seed) call. :func:`init_firebase` is wired into ``app.main``'s lifespan
*before* ``yield`` so the SDK is ready before the first request is served.

Idempotency idiom (mirrors ``app.db.base``'s ``lru_cache`` process-singleton, but the
double-init guard here is ``firebase_admin._apps`` because ``initialize_app()`` RAISES
on a second call — see RESEARCH Anti-Patterns "A second initialize_app()"). A module
``_initialized`` flag short-circuits before we ever touch the SDK, and the ``_apps``
check covers test/reload paths where another module already initialized the app.

CRITICAL — ADC only, NO JSON key (D-09 / threat T-03-08):
    ``initialize_app()`` is called with **no credential argument**. Credentials come
    from Application Default Credentials — the attached Cloud Run service account — so
    no service-account JSON key ever exists in env or on disk. NEVER introduce
    ``credentials.Certificate(...)`` / a key path here; that would reintroduce a leakable
    secret the whole IAM-auth design exists to avoid.

Project id resolves from ADC / ``GOOGLE_CLOUD_PROJECT`` on Cloud Run, so normally no
``projectId`` is passed. An explicit ``firebase_project_id`` setting (non-secret,
``FIREBASE_PROJECT_ID``) is forwarded via ``options={"projectId": ...}`` only as a local /
test override so the verified token's ``aud`` can be pinned to the right project.

Authoritative references:
- .planning/phases/03-identity-platform-auth/03-RESEARCH.md
    § Architecture Patterns 1 (init_firebase) + § Anti-Patterns ("A second initialize_app()")
- .planning/phases/03-identity-platform-auth/03-PATTERNS.md § "core/firebase.py" + § "main.py"
- D-09 (no SA key — ADC only) / threat_model T-03-08 (SA key leakage) / Pitfall 5 (aud pinning)
"""

from __future__ import annotations

import firebase_admin

from app.core.config import get_settings

# Module-level guard: once True we never touch the SDK again. The
# ``firebase_admin._apps`` check below additionally covers the case where another
# module / a test fixture already called initialize_app() in this process.
_initialized = False


def init_firebase() -> None:
    """Initialize the Firebase Admin SDK exactly once via ADC (idempotent).

    No-ops if already initialized (``_initialized`` flag or a live default app in
    ``firebase_admin._apps``) — a second ``initialize_app()`` would raise. On first
    call, initializes with NO credential argument (ADC, the attached Cloud Run SA);
    an explicit ``firebase_project_id`` setting is forwarded as a ``projectId`` option
    only when present (local / test override; ADC supplies it on Cloud Run).
    """
    global _initialized
    if _initialized or firebase_admin._apps:  # double-init would raise (Anti-Patterns)
        _initialized = True
        return

    project_id = get_settings().firebase_project_id
    if project_id:
        # Explicit override only — ADC normally supplies the project via
        # GOOGLE_CLOUD_PROJECT, so this branch is the local/test path (Pitfall 5).
        firebase_admin.initialize_app(options={"projectId": project_id})
    else:
        firebase_admin.initialize_app()  # ADC; no credential argument (D-09)
    _initialized = True
