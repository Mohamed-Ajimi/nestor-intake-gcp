"""0013 D-13 fact metadata + research_gap + D-12 run states (Phase 15.2, ENGINE-11).

Additive-only migration: THREE nullable columns, ONE new FORCE-RLS table, and a
CHECK widening that is a strict superset of the previous literal set. Nothing
here is destructive and nothing requires a backfill.

What this migration carries
---------------------------
1. `claim.certainty` (TEXT nullable) -- D8's per-fact certainty marker:
   'certain' (corroborated) vs 'single' ("found only once -- double-check"), or
   NULL when the provider said nothing. The report's hedging language reads it.
2. `claim.found_by` (TEXT[] nullable) -- the persisted G-12 provenance: which
   providers independently surfaced this fact. ARRAY, not JSONB, because it must
   be QUERYABLE (`'gemini' = ANY(found_by)`) and because
   `cardinality(found_by)` gives the corroboration count directly; D-13
   explicitly rejects "one JSONB blob".
3. `claim_source.provider_quality` (TEXT nullable) -- the provider-STATED source
   quality ('official' | 'press' | 'other'). `numbering.derive_quality_tier()`'s
   domain heuristic remains the FALLBACK whenever this is NULL.
4. `research_gap` (NEW TABLE, FORCE RLS) -- the per-provider "couldn't find"
   list that feeds D-08's "What we could not establish" report section. One row
   per (run, provider, unfound-item). Written on the `persist_tribunal_claims`
   path (plan 15.2-15).
5. `ck_run_status` widened from seven to NINE literals, adding
   'completed_degraded' (D-12: the run finished but a stage degraded) and
   'parked' (D-17: the run is parked awaiting an operator/cap reset).

Why nullable
------------
`certainty`, `found_by` and `provider_quality` are nullable because a provider
may omit them entirely, and because D-14's full-distillation fallback leaves
`certainty` / `provider_quality` NULL by design (the domain heuristic
`numbering.derive_quality_tier()` fills the tier instead of the provider). Every
row written before this revision predates all three columns, so a NOT NULL
column would demand a meaningless backfill and would misrepresent the data.

Which alembic line
------------------
The TRIBUNAL line (`tribunal/nestor_pulse_sdk/alembic/versions/`), whose head
was 0012 (`0012_verdict_superseded_note.py`), and whose version table is
`tribunal.tribunal_alembic_version`. This is NOT the intake `nestor` line under
`backend/app/db/alembic/versions/`, which ships its OWN independent 0012 -- two
schemas, two `alembic_version` tables, two independent revision sequences
(v1.1 roadmap decision, Pitfall 2). Do not cross the two lines.

Hash-chain safety
-----------------
`nestor_pulse_sdk/audit/hash_chain.py::_payload_for_row` freezes ELEVEN fields.
None of them lives on `claim`, on `claim_source`, or on `run.status`. This
revision names and alters only those three tables plus a brand-new table that
the chain has never seen, so no hashed table and no hashed field is touched:
`verify_chain` cannot move off `(True, None)` and the frozen payload field count
stays 11 (threat T-15.2-05; EU AI Act Art. 12 audit-trail gate, deadline
2026-08-02).

Security posture for research_gap
---------------------------------
(a) POLICY EXPRESSION. The tenant_isolation policy uses the CURRENT head form
    `NULLIF(current_setting('app.tenant_id', true), '')::uuid`, NOT the bare
    `current_setting('app.tenant_id')::uuid` used by 0002/0003/0011. Migrations
    0009 and 0010 exist precisely because the bare form crash-loops the worker:
    `app.tenant_id` is a custom (placeholder) GUC, so once any transaction on a
    pooled connection has SET it, the value reverts to the EMPTY STRING '' --
    not to unset -- when that transaction ends. PostgreSQL still EVALUATES the
    tenant_isolation branch even when another OR'd policy is true, and
    `''::uuid` raises `invalid input syntax for type uuid: ""`, aborting the
    whole statement (threat T-15.2-04). NULLIF collapses BOTH unset (NULL) and
    the empty-string reversion to NULL. Semantics: USING -> NULL -> zero rows
    (fail-safe read); WITH CHECK -> NULL -> INSERT/UPDATE REJECTED (fail-loud
    write) -- exactly what D-13's cross-tenant denial requirement wants
    (threats T-15.2-01 / T-15.2-03).
(b) NO `research_gap_worker_all` POLICY AND NO EXPLICIT GRANT -- deliberate,
    matching the `verification_verdict` precedent set by 0011 (which added
    neither). `research_gap` rows are written on the `persist_tribunal_claims`
    path (plan 15.2-15), which ALWAYS runs inside
    `db/rls.py::set_tenant_context`; **plan 15.2-15's write path must therefore
    be inside a tenant context or its INSERT will be rejected by WITH CHECK.**
    The cross-tenant SKIP-LOCKED *claim* poll -- the only reason the
    `worker_all` policies of 0008 exist -- never touches `research_gap`. And no
    GRANT is needed because production runs `alembic upgrade head` under the
    app_user DSN (`infra/DEPLOY-RUNBOOK.md` Step 13.f), so 0008's
    `ALTER DEFAULT PRIVILEGES FOR ROLE app_user IN SCHEMA tribunal GRANT ... TO
    worker_user` covers this table automatically at creation time. A redundant
    GRANT would be regression risk with zero benefit (threat T-15.2-08,
    accepted) -- the same reasoning 0012 records for re-issued policies.

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-26
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# D-12 promotes 'completed_degraded'; D-17 adds 'parked'. Strict SUPERSET of the
# seven literals migration 0007 installed, so no existing row can violate the new
# CHECK and no backfill is needed. Kept byte-identical to the ORM literal in
# db/models/run.py (same commit) so `alembic check` sees no drift (T-15.2-06).
_STATUS_NINE = (
    "status IN ('queued','running','completed','completed_degraded','parked',"
    "'failed','cancelled','needs_input','needs_report_spec')"
)
# The 0007 seven-literal form -- used by downgrade() to restore prior behaviour.
_STATUS_SEVEN = (
    "status IN ('queued','running','completed','failed','cancelled',"
    "'needs_input','needs_report_spec')"
)


def upgrade() -> None:
    # No schema= kwarg anywhere in this file: env.py has already pointed
    # search_path at the `tribunal` schema, the same way every additive column in
    # 0011 and 0012 is written.
    #
    # Deliberately NO security DDL on `claim` / `claim_source`. Both already
    # carry ENABLE + FORCE ROW LEVEL SECURITY, their `*_tenant_isolation` policy
    # (re-issued in 0010's NULLIF form) and their `*_worker_all` policy (0008). A
    # PostgreSQL row-level POLICY is a TABLE-level object evaluated against row
    # values, so a newly added column is covered BY CONSTRUCTION. Re-issuing any
    # policy, index or GRANT here would be pure regression risk with zero
    # security benefit (threat T-15.2-02).

    # ---------------------------------------------------- (1) claim.certainty
    # D8's per-fact certainty marker: 'certain' | 'single' | NULL. 'single' is
    # the provider saying "found only once -- double-check"; the report hedges
    # accordingly instead of asserting.
    op.add_column(
        "claim",
        sa.Column("certainty", sa.String(), nullable=True),
    )

    # ----------------------------------------------------- (2) claim.found_by
    # Persisted G-12 provenance: the providers that independently surfaced this
    # fact. ARRAY(Text) and NOT JSONB, on purpose:
    #   * queryable -- `WHERE 'gemini' = ANY(found_by)` uses ordinary operators;
    #   * `cardinality(found_by)` yields the corroboration count directly;
    #   * it maps to a plain Python `list[str]` with no serialisation layer.
    # D-13 explicitly rejects collapsing this into "one JSONB blob".
    op.add_column(
        "claim",
        sa.Column("found_by", postgresql.ARRAY(sa.Text()), nullable=True),
    )

    # ------------------------------------------ (3) claim_source.provider_quality
    # Provider-STATED source quality: 'official' | 'press' | 'other' | NULL.
    # `numbering.derive_quality_tier()` stays the FALLBACK when this is NULL --
    # the provider's own word wins when it gives one.
    op.add_column(
        "claim_source",
        sa.Column("provider_quality", sa.String(), nullable=True),
    )

    # ------------------------------------------------- (4) research_gap table
    # The per-provider "couldn't find" list read by D-08's "What we could not
    # establish" report section. create_table -> create_index -> ENABLE -> FORCE
    # -> CREATE POLICY, in the same order as 0011's verification_verdict; the
    # policy EXPRESSION is 0010's NULLIF form, not 0011's bare form (see the
    # `Security posture for research_gap` docstring heading above).
    op.create_table(
        "research_gap",
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
        # Which provider reported the gap ('gemini' | 'openai' | 'own' | ...).
        sa.Column("provider", sa.String(), nullable=False),
        # The plain-prose item the provider could not establish.
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "idx_research_gap_tenant_run",
        "research_gap",
        ["tenant_id", "run_id"],
    )
    op.execute("ALTER TABLE research_gap ENABLE ROW LEVEL SECURITY")
    # FORCE is what binds the policy on app_user, the TABLE OWNER -- without it
    # the API role reads every tenant's rows (threat T-15.2-02).
    op.execute("ALTER TABLE research_gap FORCE ROW LEVEL SECURITY")
    # Written out literally (not via an f-string variable) so that BOTH the USING
    # and the WITH CHECK expression are greppable in this file -- the plan's
    # acceptance gate asserts the NULLIF form appears at least twice, and an
    # interpolated constant would hide the executable text.
    op.execute(
        """
        CREATE POLICY research_gap_tenant_isolation ON research_gap
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        """
    )

    # ------------------------------------------- (5) ck_run_status -> nine
    # drop + recreate, the 0007 idiom. Nine literals; a strict superset of the
    # previous seven, so no existing row can violate it and no backfill is
    # needed. D-12 promotes 'completed_degraded', D-17 adds 'parked'.
    op.drop_constraint("ck_run_status", "run", type_="check")
    op.create_check_constraint("ck_run_status", "run", _STATUS_NINE)


def downgrade() -> None:
    # Exact inverse order.
    # Any 'completed_degraded' / 'parked' rows must be resolved to one of the
    # seven legacy statuses BEFORE this runs, or the CHECK creation will fail
    # (the 0007 downgrade carries the same caveat).
    op.drop_constraint("ck_run_status", "run", type_="check")
    op.create_check_constraint("ck_run_status", "run", _STATUS_SEVEN)

    op.execute(
        "DROP POLICY IF EXISTS research_gap_tenant_isolation ON research_gap"
    )
    op.execute("ALTER TABLE research_gap NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE research_gap DISABLE ROW LEVEL SECURITY")
    op.drop_index("idx_research_gap_tenant_run", table_name="research_gap")
    op.drop_table("research_gap")

    op.drop_column("claim_source", "provider_quality")
    op.drop_column("claim", "found_by")
    op.drop_column("claim", "certainty")
