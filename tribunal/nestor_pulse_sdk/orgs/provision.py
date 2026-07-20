"""
nestor_pulse_sdk.orgs.provision -- idempotent space->org / project provisioning.

Phase 14 (SEAM-02). Salvaged from the retired D-16 first-login provisioner
(`ensure_org_for_user`), with the Firebase custom-claim write and the app_user
creation STRIPPED: in the internal seam the intake backend owns users, and the
tenant identity is the intake `space_id` mapped 1:1 onto the Tribunal `org.id`
(identity mapping -- same UUID, no mapping table).

Two idempotent functions, both callable under the standard tenant-scoped session
(the InternalCallerProvider supplies a verified tenant_id, so get_db_session has
already set `app.tenant_id` before these run):

  ensure_org(space_id, email, session) -> str
      Get-or-create the Org with id == space_id (identity mapping). Org is NOT
      RLS-scoped (it IS the tenant), so the get/insert is safe. Returns space_id.
      Concurrency-safe (WR-04): INSERT ... ON CONFLICT DO NOTHING -- two racing
      calls for the same space never raise IntegrityError.

  ensure_project(space_id, session) -> str
      Get-or-create exactly one Project per space (owner_user_id=None -- there is
      no app_user in the seam). Discoverable by tenant_id; returns the project_id.
      Phase 16 owns persisting the project_id intake-side (D-06 boundary) -- this
      function just returns it. Concurrency-safe (WR-04): a per-space
      transaction-scoped advisory lock serializes the get-or-create, so two
      racing calls can never create two projects for one space (there is no
      unique constraint on Project.tenant_id backing the invariant).

SECURITY INVARIANTS (T-14-03):
  - Org.id == space_id ALWAYS comes from the verified internal caller's header
    (mapped by InternalCallerProvider into AuthClaims.tenant_id), NEVER from a
    request body.
  - The functions do not read tenant_id from any mutable caller-supplied field.

REFERENCES:
  - 14-RESEARCH.md Pattern 3 (identity mapping; salvaged internals minus firebase)
  - 14-RESEARCH.md Pitfall 2 (retiring auth strands code assuming app_user rows)
  - nestor_pulse_sdk/db/rls.py -- set_tenant_context (the RLS helper)
"""

from __future__ import annotations

import re
import uuid
from typing import Any


# ---------------------------------------------------------------------------
# Slug / name helpers (salvaged; used to derive stable org metadata).
# ---------------------------------------------------------------------------

def _email_to_slug(email: str, space_id: str) -> str:
    """URL-safe org slug. Suffixed with the space_id head so it is stable and
    unique across re-provisioning of the same space (the slug column is UNIQUE).

    Deterministic given (email, space_id) -- no random suffix -- so repeated
    ensure_org calls for the same space never collide on the unique constraint.
    """
    local = email.split("@")[0] if email and "@" in email else (email or "")
    base = re.sub(r"[^a-z0-9]+", "-", local.lower()).strip("-")
    suffix = space_id.replace("-", "")[:8]
    return f"{base}-{suffix}" if base else f"space-{suffix}"


def _email_to_org_name(email: str, space_id: str) -> str:
    """Workspace name derived from the email local-part, or a stable default
    keyed on the space_id when no email is available."""
    local = email.split("@")[0] if email and "@" in email else (email or "")
    name = re.sub(r"[^a-zA-Z0-9]+", " ", local).strip().title()
    return f"{name} Workspace" if name else f"Space {space_id[:8]}"


# ---------------------------------------------------------------------------
# Public API -- idempotent get-or-create
# ---------------------------------------------------------------------------

async def ensure_org(*, space_id: str, email: str, session: Any) -> str:
    """Idempotently provision the Org for an intake space (identity mapping).

    org.id == space_id. Org is NOT RLS-scoped, so the get/insert runs safely
    under any session context. After creating the Org we flush and set the
    tenant context so any subsequent RLS-FORCED child write (ensure_project)
    resolves the policy against the now-known org id (salvaged ordering).

    Parameters
    ----------
    space_id : str
        The intake space UUID (== Tribunal org.id). Comes from the verified
        internal caller's X-Nestor-Tenant-Id header (never a request body).
    email : str
        Acting user's email, used to derive the org name/slug; may be empty.
    session : AsyncSession
        Must be inside an open transaction (get_db_session opens one).

    Returns
    -------
    str
        The space_id (== org_id), for chaining into the response.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert  # type: ignore
    from nestor_pulse_sdk.db.models import Org  # type: ignore
    from nestor_pulse_sdk.db.rls import set_tenant_context  # type: ignore

    tenant_uuid = uuid.UUID(space_id)

    # WR-04: get-or-create must hold under CONCURRENT calls for the same space.
    # The previous read-then-insert raced: two callers both saw "no org" and both
    # INSERTed the same PK -> IntegrityError -> 500. INSERT ... ON CONFLICT DO
    # NOTHING is atomic: the losing racer waits on the winner's row lock, then
    # does nothing. Values are deterministic given (email, space_id), so racers
    # always insert identical rows -- idempotent semantics preserved, and
    # org.id == space_id (identity mapping) is unchanged.
    await session.execute(
        pg_insert(Org)
        .values(
            id=tenant_uuid,  # id == space_id (identity mapping)
            name=_email_to_org_name(email, space_id),
            slug=_email_to_slug(email, space_id),
        )
        .on_conflict_do_nothing()
    )

    # Flush any pending ORM state, then set the tenant context to the now-known
    # org id. Org is not RLS-scoped, but child tables (project) are RLS-FORCED:
    # their policy reads current_setting('app.tenant_id') and would raise on an
    # unset setting. Setting it here makes ensure_project (called after
    # ensure_org in the /projects/ensure endpoint) run under RLS.
    await session.flush()
    await set_tenant_context(session, str(tenant_uuid))

    return space_id


async def ensure_project(*, space_id: str, session: Any) -> str:
    """Idempotently provision exactly one Project per space.

    Discoverable by tenant_id (one-per-space). owner_user_id is None -- there is
    no app_user in the internal seam (intake owns users; Pitfall 2). Returns the
    project_id as a string; Phase 16 owns persisting it intake-side (D-06).

    Assumes the tenant context is already set (ensure_org sets it, and the
    /projects/ensure endpoint calls ensure_org first).
    """
    from sqlalchemy import select, text  # type: ignore
    from nestor_pulse_sdk.db.models import Project  # type: ignore

    tenant_uuid = uuid.UUID(space_id)

    # WR-04: no unique constraint on Project.tenant_id backs the "exactly one
    # project per space" invariant, so a bare select-then-insert races -- two
    # concurrent calls could create TWO project rows for one space (and Phase 16
    # would bind different project ids permanently). Serialize per-space with a
    # TRANSACTION-scoped advisory lock (auto-released at commit/rollback; no
    # schema migration required). The losing racer blocks here until the winner
    # commits; its select below (READ COMMITTED) then sees the winner's row.
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:space, 0))"),
        {"space": str(tenant_uuid)},
    )

    existing = (
        await session.execute(
            select(Project.id)
            .where(Project.tenant_id == tenant_uuid)
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return str(existing)

    project = Project(
        tenant_id=tenant_uuid,
        name="Research",
        status="active",
        owner_user_id=None,  # no app_user in the seam (owner is nullable)
    )
    session.add(project)
    await session.flush()  # populate server-generated id
    return str(project.id)
