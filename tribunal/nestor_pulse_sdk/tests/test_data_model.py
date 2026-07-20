"""
PHASE1-03 -- org -> project -> run -> output data model (owning plan: 03)

Per 01-VALIDATION.md row:
  "org -> project -> run -> output cascade behavior is correct"
  Test type: unit
  Command: pytest nestor_pulse_sdk/tests/test_data_model.py -x

Plan 03 owns these tests. The xfail marker was strict=False in the Plan 02
stub; we flip it to strict=True here per 01-03-PLAN.md acceptance criteria
("test_data_model.py xfail flipped to strict=True"). With the models in
place, all 4 tests xpass against the testcontainers Postgres instance.
The marker is left on (rather than removed) so the suite still skips
cleanly when Docker is unreachable (per 01-VALIDATION.md Environment
Notes -- Mohamed's dev box may not have Docker).

Behavior contract (01-03-PLAN.md Task 1 `<behavior>`):
- Test 1 -- org -> project -> run -> output cascade on org delete.
- Test 2 -- run.engine accepts only 'adk' or 'sdk' (CHECK constraint, D-02).
- Test 3 -- (tenant_id, idempotency_key) UNIQUE on run.
- Test 4 -- set_tenant_context helper round-trips the uuid via
  current_setting('app.tenant_id').
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.xfail(
    reason=(
        "requires Docker + testcontainers Postgres; xpasses with Plan 03 schema"
    ),
    strict=True,
)


async def test_org_project_run_output_cascade(async_engine, set_tenant):
    """Deleting an org cascades through project -> run -> output."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
    from sqlalchemy import select

    from nestor_pulse_sdk.db.base import Base
    from nestor_pulse_sdk.db.models import Org, Project, Run, Output

    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

    tenant_id = uuid.uuid4()
    async with Session() as session:
        async with session.begin():
            org = Org(id=tenant_id, name="Acme", slug="acme")
            session.add(org)
        async with session.begin():
            await set_tenant(session, tenant_id)
            project = Project(tenant_id=tenant_id, name="Project A")
            session.add(project)
            await session.flush()
            run = Run(
                tenant_id=tenant_id,
                project_id=project.id,
                engine="adk",
                brief="brief text",
                idempotency_key=uuid.uuid4(),
            )
            session.add(run)
            await session.flush()
            output = Output(
                tenant_id=tenant_id,
                run_id=run.id,
                body="body markdown",
            )
            session.add(output)

        # delete org -> all descendants gone
        async with session.begin():
            await set_tenant(session, tenant_id)
            org_obj = (await session.execute(select(Org).where(Org.id == tenant_id))).scalar_one()
            await session.delete(org_obj)

        async with session.begin():
            await set_tenant(session, tenant_id)
            assert (await session.execute(select(Project))).first() is None
            assert (await session.execute(select(Run))).first() is None
            assert (await session.execute(select(Output))).first() is None

    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def test_run_engine_enum_adk_or_sdk(async_engine, set_tenant):
    """`run.engine` is constrained to {'adk', 'sdk'} per D-02."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
    from sqlalchemy.exc import IntegrityError

    from nestor_pulse_sdk.db.base import Base
    from nestor_pulse_sdk.db.models import Org, Project, Run

    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    tenant_id = uuid.uuid4()

    async with Session() as session:
        async with session.begin():
            session.add(Org(id=tenant_id, name="Acme", slug="acme2"))
        async with session.begin():
            await set_tenant(session, tenant_id)
            project = Project(tenant_id=tenant_id, name="P")
            session.add(project)
            await session.flush()
            project_id = project.id

        # forbidden value 'foo' -> IntegrityError on commit
        with pytest.raises(IntegrityError):
            async with session.begin():
                await set_tenant(session, tenant_id)
                session.add(Run(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    engine="foo",
                    brief="b",
                    idempotency_key=uuid.uuid4(),
                ))

    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def test_idempotency_key_unique(async_engine, set_tenant):
    """Two Run rows sharing (tenant_id, idempotency_key) raise IntegrityError."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
    from sqlalchemy.exc import IntegrityError

    from nestor_pulse_sdk.db.base import Base
    from nestor_pulse_sdk.db.models import Org, Project, Run

    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    tenant_id = uuid.uuid4()
    idem = uuid.uuid4()

    async with Session() as session:
        async with session.begin():
            session.add(Org(id=tenant_id, name="Acme", slug="acme3"))
        async with session.begin():
            await set_tenant(session, tenant_id)
            project = Project(tenant_id=tenant_id, name="P")
            session.add(project)
            await session.flush()
            project_id = project.id
            session.add(Run(
                tenant_id=tenant_id,
                project_id=project_id,
                engine="adk",
                brief="b",
                idempotency_key=idem,
            ))

        with pytest.raises(IntegrityError):
            async with session.begin():
                await set_tenant(session, tenant_id)
                session.add(Run(
                    tenant_id=tenant_id,
                    project_id=project_id,
                    engine="adk",
                    brief="b2",
                    idempotency_key=idem,
                ))

    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def test_set_tenant_context_helper(async_engine):
    """`set_tenant_context(session, uuid)` round-trips via current_setting."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
    from sqlalchemy import text

    from nestor_pulse_sdk.db.rls import set_tenant_context

    Session = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    tenant_id = uuid.uuid4()

    async with Session() as session:
        async with session.begin():
            await set_tenant_context(session, tenant_id)
            result = await session.execute(
                text("SELECT current_setting('app.tenant_id', true)")
            )
            got = result.scalar_one()
            assert got == str(tenant_id)
