"""HTTP API layer — FastAPI routers.

Routers split by trust posture (AUTH-01):
- ``auth_routes.auth_router`` — ANONYMOUS-but-self-verifying ``/auth/*`` (the
  login-sync handshake; un-synced users must reach it, so it does NOT use
  ``get_current_identity``).
- ``auth_routes.protected_router`` — the DEFAULT-DENY base router every future
  feature router inherits (``Depends(get_current_identity)``).

Importing ``app.api`` is import-only; ``app.main`` mounts the routers.
"""
