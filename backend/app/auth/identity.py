"""``Identity`` — the typed, per-request identity derived from a verified ID token.

This is the trusted object the auth dependency returns and Phase 4's repository layer
consumes to derive tenant scope. Its fields come straight from the Identity Platform
custom claims on the verified token (set server-side via the Admin SDK at login-sync —
AUTH-03), never from request input (D-03).

Role / space_id semantics (mirrors ``app.db.models.membership.OrganizationMembership``):
- ``role="superadmin"`` — Agenic, cross-tenant. ``space_id`` is ``None`` (no single space;
  the repository must NOT apply a space filter / sets no ``app.current_space_id`` GUC).
- ``role="user"`` — own space only. ``space_id`` is the (non-None) organization/space id
  the request is scoped to; Phase 4 feeds it into ``rls.set_space_context``.

Frozen so a verified identity cannot be mutated mid-request (no accidental privilege
swap after verification). No logic lives here — this is a pure data contract.

Authoritative references:
- .planning/phases/03-identity-platform-auth/03-RESEARCH.md § Architecture Patterns 2
- .planning/phases/03-identity-platform-auth/03-PATTERNS.md § "identity.py"
- app.db.models.membership (the superadmin-is-cross-tenant / user-has-space_id semantics)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Identity:
    """The verified, immutable per-request identity (claims from the ID token).

    ``space_id`` is ``None`` for ``superadmin`` (cross-tenant) and the non-None space id
    for ``user``. Constructed ONLY from the decoded/verified token in
    ``app.auth.dependencies.get_current_identity`` — never from request body/path/query.
    """

    uid: str
    email: str | None
    role: str
    space_id: str | None
