"""
Plan 01-17 Task 2 (TDD) + Task 3 (governor test).

Tests for:
  - nestor_pulse_sdk/orgs/provision.py: ensure_org_for_user
  - nestor_pulse_sdk/pipeline/tribunal/budget.py: NESTOR_TRIBUNAL_UNCAPPED flag

All tests use fake/in-memory SQLAlchemy sessions + unittest.mock.
No Cloud SQL, no firebase_admin network calls.

Coverage:

Task 2 — ensure_org_for_user:
  test_provision_creates_org_user_project
      A never-seen (provider_uid, tenant_id, email) creates:
        - Org with id == tenant_id
        - User with provider_user_id == uid, role="admin"
        - Exactly one starter Project owned by that user
      Returns the tenant_id.

  test_provision_is_idempotent
      Calling ensure_org_for_user twice for the same user yields
      the same org_id / user_id / project_id; no duplicates.

  test_provision_sets_firebase_claim_once
      First provisioning of a NEW user calls
      firebase_admin.auth.set_custom_user_claims(uid, {"tenant_id": org_id})
      exactly ONCE. A re-run for an EXISTING user does NOT call it again.
      After provisioning, get_user(uid).custom_claims["tenant_id"] == org_id.

  test_rls_isolation_two_users_different_tenants
      After provisioning userA (tenant_a) and userB (tenant_b), querying
      under A's tenant context sees A's project only; querying under B's
      context sees B's project only (symmetric RLS isolation, D-16).

Task 3 — uncapped governor:
  test_uncapped_governor_never_blocks
      With NESTOR_TRIBUNAL_UNCAPPED=1, over_budget() returns False regardless
      of accumulated cost. current_cost still executes sum(cost_usd) SELECT.
"""
from __future__ import annotations

import os
import uuid
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers — fake SQLAlchemy session that records adds + simulates select
# ---------------------------------------------------------------------------

class _FakeSession:
    """Ultra-lightweight synchronous-acting async fake session for unit tests.

    Supports:
      - session.get(Model, pk)  — returns row from _store if pk found
      - session.add(obj)        — appends to _added; calls flush semantics
      - session.execute(stmt)   — returns _ExecResult
      - begin() context manager  (noop — no real transaction)
      - flush(), commit() — no-ops
    """

    def __init__(self):
        # Separate stores keyed by model class
        self._store: dict[type, dict[Any, Any]] = {}
        self._added: list[Any] = []

    # -- session.get(Model, pk) --

    async def get(self, model, pk):
        store = self._store.get(model, {})
        return store.get(pk)

    # -- session.add(obj) --

    def add(self, obj):
        self._added.append(obj)
        # Auto-assign IDs if missing (mimics flush)
        if not getattr(obj, "id", None):
            obj.id = uuid.uuid4()
        # Register in store for later gets
        model = type(obj)
        if model not in self._store:
            self._store[model] = {}
        self._store[model][obj.id] = obj

    # -- session.execute(stmt) --

    async def execute(self, stmt, params=None):
        # For the budget governor test: return a configurable result
        return _ExecResult(self._execute_result)

    _execute_result = None  # tests set this to simulate SUM query results

    async def flush(self):
        pass

    async def commit(self):
        pass

    # -- context manager for begin() --

    def begin(self):
        return _NoopCtx()

    # -- scalars convenience --

    def scalars(self):
        return self


class _ExecResult:
    def __init__(self, result):
        self._result = result

    def scalar_one_or_none(self):
        return self._result

    def scalars(self):
        return self

    def all(self):
        if self._result is None:
            return []
        if isinstance(self._result, list):
            return self._result
        return [self._result]


class _NoopCtx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class _FakeSessionmaker:
    """Returns a _FakeSession on each call as an async context manager."""

    def __init__(self, session: _FakeSession):
        self._session = session

    def __call__(self):
        return _FakeSessionCtx(self._session)


class _FakeSessionCtx:
    def __init__(self, session: _FakeSession):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *args):
        pass


# ---------------------------------------------------------------------------
# Fake firebase_admin.auth for testing set_custom_user_claims
# ---------------------------------------------------------------------------

class _FakeFirebaseUser:
    def __init__(self, uid: str, custom_claims: dict):
        self.uid = uid
        self.custom_claims = custom_claims


class _FakeFirebaseAuth:
    """Minimal fake of firebase_admin.auth used by ensure_org_for_user."""

    def __init__(self):
        self._claims: dict[str, dict] = {}
        self.set_custom_user_claims = MagicMock(side_effect=self._set_claims)

    def _set_claims(self, uid: str, claims: dict):
        self._claims[uid] = claims

    def get_user(self, uid: str) -> _FakeFirebaseUser:
        return _FakeFirebaseUser(uid, self._claims.get(uid, {}))


# ---------------------------------------------------------------------------
# Task 2 tests
# ---------------------------------------------------------------------------


class TestEnsureOrgForUser:

    def _import(self):
        from nestor_pulse_sdk.orgs.provision import ensure_org_for_user
        return ensure_org_for_user

    @pytest.mark.asyncio
    async def test_provision_creates_org_user_project(self):
        """
        A never-seen (provider_uid, tenant_id, email) creates Org + User +
        exactly one starter Project. Returns the tenant_id string.
        """
        ensure_org_for_user = self._import()

        tenant_id = str(uuid.uuid4())
        provider_uid = "firebase_uid_abc"
        app_user_id = str(uuid.uuid4())
        email = "alice@example.com"

        session = _FakeSession()
        fake_firebase = _FakeFirebaseAuth()

        with patch("nestor_pulse_sdk.orgs.provision._firebase_set_claims",
                   fake_firebase.set_custom_user_claims):
            result = await ensure_org_for_user(
                app_user_id=app_user_id,
                tenant_id=tenant_id,
                provider_uid=provider_uid,
                email=email,
                session=session,
            )

        assert result == tenant_id

        # Org created with id == tenant_id
        from nestor_pulse_sdk.db.models import Org
        org = session._store.get(Org, {}).get(uuid.UUID(tenant_id))
        assert org is not None, "Org not created"
        assert str(org.id) == tenant_id

        # User created with provider_user_id == uid, role admin
        from nestor_pulse_sdk.db.models import User
        users = list(session._store.get(User, {}).values())
        assert len(users) == 1, f"Expected 1 user, got {len(users)}"
        user = users[0]
        assert user.provider_user_id == provider_uid
        assert user.role == "admin"
        assert user.email == email

        # Exactly one starter project
        from nestor_pulse_sdk.db.models import Project
        projects = list(session._store.get(Project, {}).values())
        assert len(projects) == 1, f"Expected 1 project, got {len(projects)}"
        project = projects[0]
        assert str(project.tenant_id) == tenant_id

    @pytest.mark.asyncio
    async def test_provision_is_idempotent(self):
        """
        Calling ensure_org_for_user twice for the same user yields the same
        org_id / user_id / project_id; no second org, user, or project created.
        """
        ensure_org_for_user = self._import()

        tenant_id = str(uuid.uuid4())
        provider_uid = "firebase_uid_bob"
        app_user_id = str(uuid.uuid4())
        email = "bob@example.com"

        session = _FakeSession()
        fake_firebase = _FakeFirebaseAuth()

        with patch("nestor_pulse_sdk.orgs.provision._firebase_set_claims",
                   fake_firebase.set_custom_user_claims):
            result1 = await ensure_org_for_user(
                app_user_id=app_user_id,
                tenant_id=tenant_id,
                provider_uid=provider_uid,
                email=email,
                session=session,
            )

            result2 = await ensure_org_for_user(
                app_user_id=app_user_id,
                tenant_id=tenant_id,
                provider_uid=provider_uid,
                email=email,
                session=session,
            )

        assert result1 == tenant_id
        assert result2 == tenant_id

        # Still exactly one Org, one User, one Project
        from nestor_pulse_sdk.db.models import Org, User, Project
        assert len(session._store.get(Org, {})) == 1
        assert len(session._store.get(User, {})) == 1
        assert len(session._store.get(Project, {})) == 1

    @pytest.mark.asyncio
    async def test_provision_sets_firebase_claim_once(self):
        """
        First provisioning calls set_custom_user_claims(uid, {"tenant_id": org_id})
        exactly ONCE. A re-run for the SAME user does NOT call it again.
        After provisioning, get_user(uid).custom_claims["tenant_id"] == provisioned org id.
        """
        ensure_org_for_user = self._import()

        tenant_id = str(uuid.uuid4())
        provider_uid = "firebase_uid_carol"
        app_user_id = str(uuid.uuid4())
        email = "carol@example.com"

        session = _FakeSession()
        fake_firebase = _FakeFirebaseAuth()

        with patch("nestor_pulse_sdk.orgs.provision._firebase_set_claims",
                   fake_firebase.set_custom_user_claims):
            # First run: new user
            await ensure_org_for_user(
                app_user_id=app_user_id,
                tenant_id=tenant_id,
                provider_uid=provider_uid,
                email=email,
                session=session,
            )
            # Second run: same user (idempotent re-run)
            await ensure_org_for_user(
                app_user_id=app_user_id,
                tenant_id=tenant_id,
                provider_uid=provider_uid,
                email=email,
                session=session,
            )

        # set_custom_user_claims called EXACTLY ONCE
        fake_firebase.set_custom_user_claims.assert_called_once_with(
            provider_uid, {"tenant_id": tenant_id}
        )

        # After provisioning, the claim is set
        user_record = fake_firebase.get_user(provider_uid)
        assert user_record.custom_claims.get("tenant_id") == tenant_id, (
            f"Expected tenant_id={tenant_id!r} in custom_claims, "
            f"got: {user_record.custom_claims!r}"
        )

    @pytest.mark.asyncio
    async def test_rls_isolation_two_users_different_tenants(self):
        """
        After provisioning userA (tenant_a) and userB (tenant_b):
          - A query under A's tenant context sees A's project only (not B's).
          - A query under B's tenant context sees B's project only (not A's).
        Symmetric RLS isolation: D-16 + T-17-02.

        This is an in-memory approximation of RLS using the tenant_id filter
        that set_tenant_context enforces at the DB layer. The integration-level
        proof lives in test_rls_isolation.py; this test verifies the provisioner
        creates the correct tenant_id values so RLS would fire correctly.
        """
        ensure_org_for_user = self._import()

        tenant_a = str(uuid.uuid4())
        tenant_b = str(uuid.uuid4())
        uid_a = "firebase_uid_alice_rls"
        uid_b = "firebase_uid_bob_rls"
        user_id_a = str(uuid.uuid4())
        user_id_b = str(uuid.uuid4())

        # Provision user A
        session_a = _FakeSession()
        fake_firebase_a = _FakeFirebaseAuth()
        with patch("nestor_pulse_sdk.orgs.provision._firebase_set_claims",
                   fake_firebase_a.set_custom_user_claims):
            await ensure_org_for_user(
                app_user_id=user_id_a,
                tenant_id=tenant_a,
                provider_uid=uid_a,
                email="alice.rls@example.com",
                session=session_a,
            )

        # Provision user B (separate session, different tenant)
        session_b = _FakeSession()
        fake_firebase_b = _FakeFirebaseAuth()
        with patch("nestor_pulse_sdk.orgs.provision._firebase_set_claims",
                   fake_firebase_b.set_custom_user_claims):
            await ensure_org_for_user(
                app_user_id=user_id_b,
                tenant_id=tenant_b,
                provider_uid=uid_b,
                email="bob.rls@example.com",
                session=session_b,
            )

        from nestor_pulse_sdk.db.models import Project

        # A's session: projects in tenant_a (RLS-filtered by tenant_id)
        projects_a = [
            p for p in session_a._store.get(Project, {}).values()
            if str(p.tenant_id) == tenant_a
        ]
        # Must NOT see B's projects
        projects_a_sees_b = [
            p for p in session_a._store.get(Project, {}).values()
            if str(p.tenant_id) == tenant_b
        ]
        assert len(projects_a) == 1, f"A should have 1 project; got {len(projects_a)}"
        assert len(projects_a_sees_b) == 0, (
            f"RLS LEAK: A's session contains B's projects: {projects_a_sees_b}"
        )

        # B's session: projects in tenant_b only
        projects_b = [
            p for p in session_b._store.get(Project, {}).values()
            if str(p.tenant_id) == tenant_b
        ]
        projects_b_sees_a = [
            p for p in session_b._store.get(Project, {}).values()
            if str(p.tenant_id) == tenant_a
        ]
        assert len(projects_b) == 1, f"B should have 1 project; got {len(projects_b)}"
        assert len(projects_b_sees_a) == 0, (
            f"RLS LEAK: B's session contains A's projects: {projects_b_sees_a}"
        )


# ---------------------------------------------------------------------------
# Task 3 — uncapped governor test
# ---------------------------------------------------------------------------


class TestUncappedGovernor:

    @pytest.mark.asyncio
    async def test_uncapped_governor_never_blocks(self, monkeypatch):
        """
        Plan 01-17 Task 3 — D-15 uncapped posture.

        With NESTOR_TRIBUNAL_UNCAPPED=1, over_budget() returns False
        regardless of the accumulated cost (even 1 000 000 USD).

        current_cost still issues the SELECT sum(cost_usd) query so
        audit_log recording is unaffected (D-15: uncap, do NOT stop recording).
        """
        monkeypatch.setenv("NESTOR_TRIBUNAL_UNCAPPED", "1")

        # Reload budget module so the module-level flag re-reads env
        import importlib
        import nestor_pulse_sdk.pipeline.tribunal.budget as budget_mod
        importlib.reload(budget_mod)

        run_id = uuid.uuid4()
        tenant_id = uuid.uuid4()

        # Fake sessionmaker that returns a very high cost (> any ceiling)
        huge_cost = Decimal("1000000.00")

        call_count = {"n": 0}

        class _HighCostSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            def begin(self):
                return _NoopCtx()

            async def execute(self, stmt, params=None):
                call_count["n"] += 1
                return _ExecResult(huge_cost)

        class _HighCostSessionmaker:
            def __call__(self):
                return _HighCostSession()

        sessionmaker = _HighCostSessionmaker()

        # Patch set_tenant_context to a no-op so we don't need a real session
        with patch(
            "nestor_pulse_sdk.pipeline.tribunal.budget.set_tenant_context",
            new=AsyncMock(),
        ):
            result = await budget_mod.over_budget(
                run_id=run_id,
                tenant_id=tenant_id,
                max_budget_usd=25.00,
                sessionmaker=sessionmaker,
            )

        # UNCAPPED: must return False even though cost >> ceiling
        assert result is False, (
            f"over_budget must return False when NESTOR_TRIBUNAL_UNCAPPED=1, "
            f"got {result!r}"
        )

        # current_cost still SELECTs sum(cost_usd) — audit recording intact
        assert call_count["n"] >= 1, (
            "current_cost must still query audit_log.cost_usd even when uncapped; "
            "got 0 execute() calls"
        )

        # Cleanup: restore the module without the env flag
        monkeypatch.delenv("NESTOR_TRIBUNAL_UNCAPPED", raising=False)
        importlib.reload(budget_mod)
