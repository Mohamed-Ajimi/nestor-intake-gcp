"""Database layer: SQLAlchemy 2.0 ORM models, declarative Base, and Alembic.

All application tables live in the Postgres ``nestor`` schema (see
``app.db.base.NESTOR_SCHEMA``). Importing ``app.db.models`` registers every
table in ``Base.metadata`` so both Alembic autogenerate and the test harness
see the full schema.
"""
