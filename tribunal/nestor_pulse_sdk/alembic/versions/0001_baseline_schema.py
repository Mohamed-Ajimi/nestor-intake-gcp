"""0001 baseline schema -- org, app_user, project, run, output, audit_log.

Citation tables (source/claim/claim_source) land in 0003 to keep this
revision focused on the D-06 hierarchy + audit chain. RLS policies land
in 0002 (separate concern from CREATE TABLE; D-05).

Authoritative reference: nestor_pulse_sdk/db/models/*.py (this migration
mirrors them exactly so `alembic check` after future autogenerate runs
clean).

Revision ID: 0001
Revises: None
Create Date: 2026-05-27
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # pgcrypto provides gen_random_uuid() should the worker ever want a
    # server-side default; the ORM uses uuid.uuid4 client-side so this is
    # belt-and-braces but harmless.
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # ------------------------------------------------------------------ org
    op.create_table(
        "org",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False, unique=True),
        sa.Column("retention_days", sa.Integer(), nullable=False, server_default="180"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # ------------------------------------------------------------- app_user
    # W7: `user` is reserved in Postgres; table is named app_user. All FKs
    # and RLS policies (migration 0002) reference `app_user`.
    op.create_table(
        "app_user",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("org.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(), nullable=False, unique=True),
        sa.Column("provider_user_id", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False, server_default="admin"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_app_user_tenant_id", "app_user", ["tenant_id"])
    op.create_index(
        "idx_app_user_tenant_email", "app_user", ["tenant_id", "email"]
    )

    # -------------------------------------------------------------- project
    op.create_table(
        "project",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("org.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("client_name", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column(
            "owner_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app_user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_project_tenant_id", "project", ["tenant_id"])
    op.create_index("idx_project_tenant_status", "project", ["tenant_id", "status"])
    op.create_index(
        "idx_project_tenant_client", "project", ["tenant_id", "client_name"]
    )

    # ------------------------------------------------------------------ run
    op.create_table(
        "run",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("org.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("project.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("engine", sa.String(), nullable=False),
        sa.Column("brief", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="queued"),
        sa.Column("idempotency_key", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("worker_id", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("cost_usd_total", sa.Numeric(12, 4), nullable=True),
        # D-02 engine constraint.
        sa.CheckConstraint("engine IN ('adk','sdk')", name="ck_run_engine"),
        # D-09 status constraint.
        sa.CheckConstraint(
            "status IN ('queued','running','completed','failed','cancelled')",
            name="ck_run_status",
        ),
        sa.UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_run_tenant_idempotency"
        ),
    )
    op.create_index("idx_run_tenant_status", "run", ["tenant_id", "status"])
    op.create_index("idx_run_tenant_project", "run", ["tenant_id", "project_id"])
    op.create_index("idx_run_tenant_created", "run", ["tenant_id", "created_at"])

    # --------------------------------------------------------------- output
    op.create_table(
        "output",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("org.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("run.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("format", sa.String(), nullable=False, server_default="markdown"),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("gcs_uri", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("idx_output_tenant_run", "output", ["tenant_id", "run_id"])

    # ------------------------------------------------------------- audit_log
    op.create_table(
        "audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("org.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("run.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("cached_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=True),
        sa.Column("gcs_uri", sa.String(), nullable=False),
        sa.Column("prev_hash", sa.String(), nullable=False),
        sa.Column("hash", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "tenant_id", "run_id", "seq", name="uq_audit_tenant_run_seq"
        ),
    )
    op.create_index(
        "idx_audit_tenant_run_created",
        "audit_log",
        ["tenant_id", "run_id", "created_at"],
    )
    op.create_index("idx_audit_tenant_model", "audit_log", ["tenant_id", "model"])


def downgrade() -> None:
    # Reverse order of upgrade() so FK targets exist when dependents drop.
    op.drop_index("idx_audit_tenant_model", table_name="audit_log")
    op.drop_index("idx_audit_tenant_run_created", table_name="audit_log")
    op.drop_table("audit_log")

    op.drop_index("idx_output_tenant_run", table_name="output")
    op.drop_table("output")

    op.drop_index("idx_run_tenant_created", table_name="run")
    op.drop_index("idx_run_tenant_project", table_name="run")
    op.drop_index("idx_run_tenant_status", table_name="run")
    op.drop_table("run")

    op.drop_index("idx_project_tenant_client", table_name="project")
    op.drop_index("idx_project_tenant_status", table_name="project")
    op.drop_index("ix_project_tenant_id", table_name="project")
    op.drop_table("project")

    op.drop_index("idx_app_user_tenant_email", table_name="app_user")
    op.drop_index("ix_app_user_tenant_id", table_name="app_user")
    op.drop_table("app_user")

    op.drop_table("org")
    # Leave pgcrypto extension installed (idempotent + harmless).
