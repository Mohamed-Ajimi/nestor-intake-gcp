"""QA-04 audit-row suite — ``app.db.audit.log`` writes exactly one ``audit_log`` row.

This is a **Wave 0 RED scaffold**: ``app.db.audit`` and ``app.db.models.audit`` land in
plan 02, so these cases are RED until then. The file must still *collect* cleanly on this
dev box (no DB, no Docker), so:

- ``app.db.audit`` / ``app.db.models.audit`` are pulled via module-level
  ``pytest.importorskip`` (ModuleNotFound -> skip, never a collection error), and
- the live-DB round-trip case is ``@pytest.mark.integration`` so it SKIPS without Docker
  (mirroring ``test_auth_session.py``'s integration discipline), while a pure no-DB unit
  test proves the ORM attribute mapping without a database.

Contract authored against (05-RESEARCH Pattern 6, 05-PATTERNS § test_audit.py):

    audit.log(session, *, actor_uid, actor_membership_id=None, event_type,
              target=None, space_id=None, metadata=None) -> None
        session.add(AuditLog(..., event_metadata=metadata or {}))

GOTCHA pinned here: SQLAlchemy reserves ``metadata`` on the declarative base, so the ORM
ATTRIBUTE is ``event_metadata`` while the DB COLUMN stays ``"metadata"``. The helper accepts
a ``metadata=`` kwarg and maps it onto ``event_metadata`` — both the no-DB unit test and the
integration round-trip assert that mapping.

Event-type contract (05-RESEARCH line 337): ``user.invited`` ->
``{"email", "assigned_space_id", "role"}``. NEVER log a token / password / action link.

Authoritative references:
- .planning/phases/05-user-space-management/05-RESEARCH.md § Pattern 6 (lines ~316-339)
- .planning/phases/05-user-space-management/05-PATTERNS.md § test_audit.py / § audit.py model
- backend/tests/test_auth_session.py (_session_factory(engine) + seed-then-assert shape)
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

# app.db.audit + the AuditLog ORM land in plan 02 — skip cleanly until then so this collects.
audit = pytest.importorskip("app.db.audit")
audit_models = pytest.importorskip("app.db.models.audit")

AuditLog = audit_models.AuditLog

SCHEMA = "nestor"


def _session_factory(engine):
    """Build a sessionmaker bound to the conftest ``engine`` fixture (mirrors
    ``test_auth_session.py._session_factory``)."""
    from sqlalchemy.orm import sessionmaker

    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


# ---------------------------------------------------------------------------
# No-DB unit: audit.log constructs an AuditLog with event_metadata from `metadata`
# ---------------------------------------------------------------------------


def test_log_maps_metadata_kwarg_onto_event_metadata_attr():
    """``audit.log`` adds ONE ``AuditLog`` to the session and maps the ``metadata=`` kwarg
    onto the ORM attribute ``event_metadata`` (the DB column is ``"metadata"``).

    No DB needed: a fake session captures the added object, so this runs on the dev box.
    """
    captured = []
    fake_session = MagicMock()
    fake_session.add.side_effect = captured.append

    space_id = uuid.uuid4()
    audit.log(
        fake_session,
        actor_uid="super",
        event_type="user.invited",
        target="new-uid",
        space_id=space_id,
        metadata={"email": "a@x.com", "assigned_space_id": str(space_id), "role": "user"},
    )

    fake_session.add.assert_called_once()
    assert len(captured) == 1
    row = captured[0]
    assert isinstance(row, AuditLog)
    assert row.actor_uid == "super"
    assert row.event_type == "user.invited"
    assert row.target == "new-uid"
    assert row.space_id == space_id
    # The ORM ATTRIBUTE is event_metadata; the `metadata=` kwarg must flow into it.
    assert row.event_metadata == {
        "email": "a@x.com",
        "assigned_space_id": str(space_id),
        "role": "user",
    }


def test_log_defaults_event_metadata_to_empty_dict_when_metadata_is_none():
    """Omitting ``metadata`` yields ``event_metadata == {}`` (the column is NOT NULL with a
    ``'{}'`` server default; the helper supplies ``metadata or {}``)."""
    captured = []
    fake_session = MagicMock()
    fake_session.add.side_effect = captured.append

    audit.log(fake_session, actor_uid="super", event_type="auth.login")

    assert captured[0].event_metadata == {}


def test_log_never_logs_a_token_or_password():
    """Defensive contract (Security Domain): a caller must never pass a token/password/link
    in metadata. This test documents the rule by asserting the helper forwards metadata
    verbatim (so the *callers* — endpoints — own the redaction), and that the audit row for
    an invite carries only the documented keys, never a secret-shaped field."""
    captured = []
    fake_session = MagicMock()
    fake_session.add.side_effect = captured.append

    audit.log(
        fake_session,
        actor_uid="super",
        event_type="user.invited",
        target="new-uid",
        metadata={"email": "a@x.com", "assigned_space_id": "sp", "role": "user"},
    )

    meta = captured[0].event_metadata
    for forbidden in ("password", "token", "action_link", "oobCode", "link"):
        assert forbidden not in meta, (
            f"audit metadata must never carry a secret-shaped key ({forbidden!r})"
        )


# ---------------------------------------------------------------------------
# Integration: live-DB round-trip — exactly one audit_log row with the expected fields
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_log_writes_exactly_one_row_round_trip(engine):
    """``audit.log`` + commit writes EXACTLY one ``audit_log`` row whose
    ``actor_uid``/``event_type``/``space_id`` match and whose ``event_metadata`` JSONB
    round-trips. Skips without Docker (integration marker)."""
    from sqlalchemy import select

    from app.db.models import Organization

    factory = _session_factory(engine)
    space_id = uuid.uuid4()
    assigned = uuid.uuid4()
    actor_uid = f"audit-actor-{uuid.uuid4()}"

    with factory() as s:
        with s.begin():
            # audit_log.space_id is a plain nullable uuid (NO FK), but seed a real space
            # so the round-trip mirrors a realistic invite event.
            if s.get(Organization, space_id) is None:
                s.add(
                    Organization(
                        id=space_id, name="Audit Space", slug=f"audit-{space_id}"
                    )
                )

    # Write the audit row via the helper, on the request session, and commit.
    with factory() as s:
        with s.begin():
            audit.log(
                s,
                actor_uid=actor_uid,
                event_type="user.invited",
                target="invited-uid",
                space_id=space_id,
                metadata={
                    "email": "a@x.com",
                    "assigned_space_id": str(assigned),
                    "role": "user",
                },
            )

    # Exactly one row for this actor, with the expected shape.
    with factory() as s:
        rows = (
            s.execute(select(AuditLog).where(AuditLog.actor_uid == actor_uid))
            .scalars()
            .all()
        )

    assert len(rows) == 1, f"expected exactly one audit_log row, got {len(rows)}"
    row = rows[0]
    assert row.event_type == "user.invited"
    assert row.target == "invited-uid"
    assert row.space_id == space_id
    assert row.event_metadata == {
        "email": "a@x.com",
        "assigned_space_id": str(assigned),
        "role": "user",
    }, "event_metadata JSONB must round-trip the invite contract verbatim"
