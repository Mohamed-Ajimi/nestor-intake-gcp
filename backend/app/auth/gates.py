"""Role gates as FastAPI dependencies — the ONE superadmin gate the backend shares.

This module holds authorization gates that sit BETWEEN
:func:`app.auth.dependencies.get_current_identity` (which answers *who is this?*) and the
repository layer (which answers *what may they touch?*). It contains exactly one public
callable, and its value is that it stays that way.

D-23.1-01 — why the gate lives here and not in a route module: it used to be a private
``_superadmin_gate`` inside ``app/api/research_routes.py``, which meant every other
operator surface had to grow its own role comparison. The eight intake operator verbs
(plan 23.1-10) and ``ai_router`` (plan 23.1-11) now depend on THIS object. A per-route
role comparison is exactly how verb number ten gets missed by the next audit — one gate,
one convention, one test surface.

This module imports NO DB symbol and makes NO settings lookup, IdP call, or audit write:
it is four lines of logic guarding a claim that was already verified upstream.

Authoritative references:
- .planning/phases/23.1-platform-hardening-authorization-boundary-space-deactivation/
    23.1-CONTEXT.md § 1 + D-23.1-01
- backend/tests/test_superadmin_gate.py — the unit proof of the three outcomes
- backend/tests/test_research_cross_tenant.py — the pre-existing denial suite that pins
    the 404 end-to-end through the routes
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status

from app.auth.dependencies import get_current_identity
from app.auth.identity import Identity


def superadmin_gate(identity: Identity = Depends(get_current_identity)) -> Identity:
    """Superadmin role gate as a DEPENDENCY (existence-hidden 404, Pitfall 5).

    ORDERING CONTRACT FOR EVERY CALLER — declare ``Depends(superadmin_gate)`` BEFORE
    ``Depends(get_tenant_repo)`` in the handler signature. FastAPI resolves the signature
    in order, so the gate must resolve first: a non-superadmin caller — including a
    null-space user — then hits this 404 before ``get_tenant_repo`` can raise its
    null-space default-deny 403, which would leak that the endpoint exists. The denial
    suites pin EXACTLY 404, so getting the order wrong turns a silent denial into an
    existence oracle.

    (In its former home this function also had to sit physically above the first handler
    that used it, because a ``Depends`` default is evaluated at ``def`` time and a later
    definition would be a NameError at import. The module-top import satisfies that
    trivially now — but the SIGNATURE ordering above is a separate rule and still binds.)

    404 AND NOT 403, deliberately: for the research/intake operator surface the existence
    of the endpoint is itself secret, so an unauthorized caller must be unable to tell
    "you may not" from "there is nothing here". The detail string ``"Intake not found"``
    is part of that convention and is asserted byte-exact — it is the message as much as
    the status code. ``app.db.session.get_admin_session``'s superadmin check answers 403
    instead, and is deliberately NOT unified with this gate: the admin router's existence
    is not a secret, so hiding it would buy nothing and would make its 403 denial suite
    lie. Two conventions, each correct for its surface.

    Returns the caller's ``Identity`` UNCHANGED (the same object) so every gated handler
    keeps the actor it stamps its audit rows with.

    The condition is an ALLOW-LIST OF ONE. Do not rewrite it as ``!= "user"``: a deny-list
    silently promotes every role that has not been invented yet.
    """
    if identity.role != "superadmin":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")
    return identity
