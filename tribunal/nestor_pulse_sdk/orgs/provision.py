"""
nestor_pulse_sdk.orgs.provision — idempotent per-user org provisioning.

Plan: 01-17 Task 2 (D-16).

WHAT THIS MODULE DOES:
  `ensure_org_for_user` is the D-16 first-login provisioner. For a brand-new
  Identity Platform user it:
    1. Creates an Org row (id == JWT tenant_id from the signed claim; Pitfall 9).
    2. Creates an app_user row (provider_user_id == firebase uid, role="admin").
    3. Creates exactly one starter Project ("My First Engagement").
    4. Calls firebase_admin.auth.set_custom_user_claims ONCE, installing
       {tenant_id: org_id} so the NEXT JWT the tester mints carries the claim.
       Without this claim, IdentityPlatformProvider.verify_id_token raises
       AuthError(401, "Missing tenant_id claim") on every subsequent request.

  On idempotent re-runs (same user bootstraps again), the function detects the
  existing rows and skips creation. It does NOT call set_custom_user_claims
  again — the claim is already set and re-writing it is unnecessary.

SECURITY INVARIANTS (T-17-02):
  - Org.id == tenant_id ALWAYS comes from the caller's signed JWT (passed
    as the `tenant_id` parameter by the bootstrap endpoint, which reads it
    from the verified token — never from the request body).
  - The function does NOT read tenant_id from the DB or from any mutable
    caller-supplied field beyond the validated JWT claim.
  - Cross-tenant isolation: each call creates exactly one (tenant, user, project)
    triple in the caller's own org. No cross-tenant writes are possible because
    the org_id drives every INSERT.

ORDERING:
  - Bootstrap runs BEFORE an app_user row exists (that is its whole purpose).
    The session must be able to write the Org row without a pre-existing tenant
    context (i.e. the caller must use an "unscoped" session, NOT get_db_session
    which presupposes an existing tenant row). See api.py for the dep.
  - After writing the Org row, child rows (User, Project) can use the standard
    tenant-scoped pattern.

REFERENCES:
  - 01-CONTEXT.md D-16 (one org per tester, auto-provisioned at first login)
  - identity-platform-bootstrap.md § "The post-signup tenant_id custom-claim flow"
  - nestor_pulse_sdk/auth/identity_platform.py — the 403 "run org bootstrap first"
    hook this module closes.
  - nestor_pulse_sdk/scripts/seed_local_dev.py — canonical idempotent insert shape.

NOTE for seed_local_dev.py:
  Real testers are provisioned per-user at login via ensure_org_for_user (D-16).
  There is NO shared dev org for testers — each tester lands in their own isolated
  org. seed_local_dev.py remains in place for LOCAL_DEV_AUTH local clicking only
  (not the tester path).
"""

from __future__ import annotations

import re
import uuid
from typing import Any


# ---------------------------------------------------------------------------
# Firebase claim helper — lazy import mirrors identity_platform.py pattern.
# Exposed as a module-level callable so tests can patch it without reaching
# into the firebase_admin namespace directly.
# ---------------------------------------------------------------------------

def _firebase_set_claims(uid: str, claims: dict) -> None:  # pragma: no cover
    """
    Call firebase_admin.auth.set_custom_user_claims(uid, claims).

    Lazy-imported so this module can be imported in environments where
    firebase-admin is not installed (unit tests patch this function directly).
    """
    from firebase_admin import auth as fb_auth  # type: ignore
    fb_auth.set_custom_user_claims(uid, claims)


# ---------------------------------------------------------------------------
# Slug helper
# ---------------------------------------------------------------------------

def _email_to_slug(email: str) -> str:
    """Convert an email address to a URL-safe org slug.

    "alice.smith@example.com" -> "alice-smith-example-com-<hex8>"

    The hex suffix keeps slugs unique across emails with the same local-part
    (different domains) and across re-registrations of the same email.
    """
    local = email.split("@")[0] if "@" in email else email
    base = re.sub(r"[^a-z0-9]+", "-", local.lower()).strip("-")
    suffix = uuid.uuid4().hex[:8]
    return f"{base}-{suffix}"


def _email_to_org_name(email: str) -> str:
    """Convert an email local-part to a workspace name.

    "alice.smith@example.com" -> "Alice Smith Workspace"
    """
    local = email.split("@")[0] if "@" in email else email
    # Replace non-alpha with space, title-case each word
    name = re.sub(r"[^a-zA-Z0-9]+", " ", local).strip().title()
    return f"{name} Workspace" if name else "My Workspace"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def ensure_org_for_user(
    *,
    app_user_id: str,
    tenant_id: str,
    provider_uid: str,
    email: str,
    session: Any,
) -> str:
    """
    Idempotently provision an Org, app_user, and starter Project for a tester.

    Parameters
    ----------
    app_user_id : str
        Nestor-side UUID for the user (caller-assigned; should be a stable UUID
        derived from the bootstrap endpoint's unscoped token lookup or a fresh
        uuid4 on first provisioning).
    tenant_id : str
        The org ID. MUST come from the signed JWT tenant_id custom claim
        (passed by the bootstrap endpoint after verifying the token).
        NEVER from the request body (Pitfall 9 / T-17-02).
    provider_uid : str
        Firebase UID (raw_provider_user_id). Used as provider_user_id on the
        app_user row and as the target for set_custom_user_claims.
    email : str
        Tester email address. Used for the org name, slug, and user.email.
    session : AsyncSession
        An SQLAlchemy async session opened WITHOUT a pre-existing tenant context
        (i.e. opened by the unscoped bootstrap dep in api.py, not get_db_session).
        The session must be inside an open transaction when this function is called.

    Returns
    -------
    str
        The tenant_id (== org_id) for chaining into the bootstrap response.

    Raises
    ------
    RuntimeError
        If the DB session rejects an insert (propagated from SQLAlchemy).
    """
    # Lazy imports: keep this module importable without a real DB stack (unit tests)
    from nestor_pulse_sdk.db.models import Org, User, Project  # type: ignore
    from nestor_pulse_sdk.db.rls import set_tenant_context  # type: ignore

    tenant_uuid = uuid.UUID(tenant_id)
    user_uuid = uuid.UUID(app_user_id)

    # ------------------------------------------------------------------ #
    # Step 1: Get-or-create Org
    # ------------------------------------------------------------------ #
    is_new_org = False
    org = await session.get(Org, tenant_uuid)
    if org is None:
        org = Org(
            id=tenant_uuid,
            name=_email_to_org_name(email),
            slug=_email_to_slug(email),
        )
        session.add(org)
        is_new_org = True

    # ------------------------------------------------------------------ #
    # Set the tenant context BEFORE touching the RLS-forced child tables.
    # ------------------------------------------------------------------ #
    # The bootstrap session is UNSCOPED (api.py opens it without app.tenant_id).
    # `org` is NOT RLS-scoped, so the get/insert above is safe. But `app_user`
    # and `project` ARE RLS-FORCED: every query against them evaluates the policy
    # `current_setting('app.tenant_id')::uuid`, which raises
    # "invalid input syntax for type uuid: ''" when the setting is unset.
    # Flush the Org first (so the child-row FKs resolve), then set the context to
    # the now-known org id so the User/Project get+insert below run under RLS.
    await session.flush()
    await set_tenant_context(session, str(tenant_uuid))

    # ------------------------------------------------------------------ #
    # Step 2: Get-or-create User
    # ------------------------------------------------------------------ #
    is_new_user = False
    user = await session.get(User, user_uuid)
    if user is None:
        user = User(
            id=user_uuid,
            tenant_id=tenant_uuid,
            email=email,
            provider_user_id=provider_uid,
            role="admin",
        )
        session.add(user)
        is_new_user = True
        # Flush the app_user row NOW, before the Project insert below.
        # Project.owner_user_id is a bare ForeignKey column with NO ORM
        # relationship() linking Project -> User, so SQLAlchemy's unit-of-work
        # has no dependency edge and may flush the project INSERT before the
        # app_user INSERT -> project_owner_user_id_fkey violation. (FK/RI checks
        # bypass RLS, so this is purely an insert-ORDERING problem.) An explicit
        # flush guarantees app_user exists before the project FK is checked.
        await session.flush()

    # ------------------------------------------------------------------ #
    # Step 3: Create exactly one starter Project (only on first provisioning)
    # ------------------------------------------------------------------ #
    # We use is_new_user as the signal — if the user row is new, no project
    # can possibly exist yet (user_id is the FK). This avoids a DB query
    # that would require tenant context to be set first.
    if is_new_user:
        starter = Project(
            tenant_id=tenant_uuid,
            name="My First Engagement",
            status="active",
            owner_user_id=user_uuid,
        )
        session.add(starter)

    # Persist ALL rows before touching the external Firebase claim. The claim
    # write is NOT transactional (Firebase is external), so if a DB insert
    # failed AFTER the claim was set we would leave a claim-set-but-no-org
    # zombie: the next login carries tenant_id but no app_user row exists, so
    # every request 403s and Login skips bootstrap (claim present). Flushing
    # first makes a DB failure abort BEFORE the claim is written.
    await session.flush()

    # ------------------------------------------------------------------ #
    # Step 4: Set Firebase custom claim ONCE (first provisioning only, AFTER
    # all DB writes succeeded).
    # ------------------------------------------------------------------ #
    # The claim MUST be set so the tester's NEXT sign-in produces a JWT
    # carrying tenant_id. We only set it on a new org because an existing org
    # means the claim was already set on a prior bootstrap (idempotent guard).
    if is_new_org:
        _firebase_set_claims(provider_uid, {"tenant_id": tenant_id})

    return tenant_id
