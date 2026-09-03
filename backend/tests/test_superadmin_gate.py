"""``superadmin_gate`` — the ONE superadmin role gate, pinned to its three outcomes.

This is the unit proof for D-23.1-01: the gate that used to live privately inside
``app/api/research_routes.py`` is promoted to :mod:`app.auth.gates` so the eight intake
operator verbs (plan 23.1-10) and ``ai_router`` (plan 23.1-11) depend on the SAME object
rather than on per-route copies of a role comparison. A copy is how verb number ten gets
missed by the next audit, so the identity of the object is itself part of the contract and
is asserted with ``is`` below.

Deliberately a NON-integration suite: the gate has no DB dependency, no settings lookup and
no IdP call, so every case fabricates an :class:`~app.auth.identity.Identity` directly and
calls the gate as a plain function. No ``pytestmark = pytest.mark.integration``, no
``TestClient``, no testcontainer — this file must run in under a second with Docker down.

What is pinned, and why each row is load-bearing:

* **404, never 403** (threat T-23.1-02) — the existence-hidden convention. A 403 tells an
  unauthorized caller that the endpoint exists; a 404 does not. The status AND the detail
  string are asserted separately so a change to one is never masked by the other.
* **The detail is byte-exact** ``"Intake not found"`` — the convention is the message as
  much as the code, and ``tests/test_research_cross_tenant.py`` reads the response text.
* **Allow-list of one** (threat T-23.1-01) — an unknown role is DENIED. Anyone who later
  rewrites the condition as ``role != "user"`` (a deny-list) turns every future role into a
  superadmin; the unknown-role rows below go red the moment that happens.
* **Identity passthrough** — the gate returns THAT SAME object, not a copy, because the
  gated handlers stamp ``actor_uid`` on their audit rows from it.

Authoritative references:
- .planning/phases/23.1-.../23.1-CONTEXT.md § 1 + D-23.1-01 (one gate, one convention,
  one test surface)
- app/api/research_routes.py (the former home; its denial suite is the regression proof
  and is re-run UNEDITED)
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.auth import gates
from app.auth.gates import superadmin_gate
from app.auth.identity import Identity


def _superadmin() -> Identity:
    """A superadmin identity: cross-tenant, so ``space_id`` is None by contract."""
    return Identity(uid="sa-1", email="ops@agenic.be", role="superadmin", space_id=None)


def _user(space_id: str | None = "space-1") -> Identity:
    """A client identity. ``space_id=None`` fabricates the null-space case."""
    return Identity(uid="u-1", email="client@example.com", role="user", space_id=space_id)


def test_superadmin_passes_through_the_same_identity_object():
    """A superadmin is returned UNCHANGED — the same object, not a copy.

    ``is``, not ``==``: the gated handlers audit with the identity the gate hands back, so
    a gate that rebuilt the Identity would still compare equal while breaking nothing
    visibly — until an audit row carried a stale actor.
    """
    identity = _superadmin()

    assert superadmin_gate(identity) is identity


def test_user_role_is_denied_with_404_not_403():
    """role=``user`` -> EXACTLY 404. Never 403, never 401 (existence-hidden, T-23.1-02)."""
    with pytest.raises(HTTPException) as exc:
        superadmin_gate(_user())

    assert exc.value.status_code == 404


def test_user_role_denial_detail_is_byte_exact():
    """The detail is the literal ``"Intake not found"`` — asserted apart from the status."""
    with pytest.raises(HTTPException) as exc:
        superadmin_gate(_user())

    assert exc.value.detail == "Intake not found"


def test_null_space_user_is_denied_with_404_not_the_repo_403():
    """A user whose space is None still gets EXACTLY 404 from THIS gate.

    This is the case the ordering rule exists for: ``get_tenant_repo`` answers a null-space
    identity with 403, which would leak that the endpoint exists. The gate is declared
    BEFORE the repo in every gated signature so this 404 wins.
    """
    with pytest.raises(HTTPException) as exc:
        superadmin_gate(_user(space_id=None))

    assert exc.value.status_code == 404
    assert exc.value.detail == "Intake not found"


def test_admin_role_is_denied_because_the_gate_is_an_allow_list():
    """role=``admin`` -> 404. Plausible-sounding, still not superadmin (T-23.1-01)."""
    with pytest.raises(HTTPException) as exc:
        superadmin_gate(Identity(uid="a-1", email=None, role="admin", space_id=None))

    assert exc.value.status_code == 404


def test_empty_role_is_denied():
    """role=``""`` -> 404. An empty claim is not a passing claim."""
    with pytest.raises(HTTPException) as exc:
        superadmin_gate(Identity(uid="e-1", email=None, role="", space_id=None))

    assert exc.value.status_code == 404


def test_unknown_future_role_is_denied():
    """An unforeseen role -> 404.

    The point of this row is the DENY-LIST rewrite: ``role != "user"`` would pass every
    string here and silently promote whoever holds a new claim. This test is that rewrite's
    tripwire.
    """
    with pytest.raises(HTTPException) as exc:
        superadmin_gate(Identity(uid="f-1", email=None, role="auditor", space_id="s-9"))

    assert exc.value.status_code == 404

