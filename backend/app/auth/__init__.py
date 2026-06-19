"""Auth layer: Identity Platform token verification and the per-request identity.

The Firebase Admin SDK (initialized once in ``app.main``'s lifespan via
``app.core.firebase.init_firebase``) verifies the bearer ID token on every protected
request. ``app.auth.dependencies.get_current_identity`` is the single verification seam
that turns an untrusted ``Authorization: Bearer <id token>`` into a trusted
:class:`app.auth.identity.Identity` (uid / email / role / space_id) — read ONLY from the
verified token, never from request body/path/query (D-03).
"""
