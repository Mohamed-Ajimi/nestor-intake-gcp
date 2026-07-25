"""0012 verification_verdict.superseded_note (Phase 15.1 gap closure, CR-01).

Additive-only migration: ONE nullable TEXT column on `verification_verdict`.
Nothing else -- no table, no index, no security DDL (see the comment block in
`upgrade()` for why re-issuing any of that would be a regression, not a
hardening step).

What the column carries
-----------------------
The G-07 caveat the group skeptic supplies whenever it returns a `superseded`
verdict: plain prose saying WHAT changed and FROM WHEN (e.g. "applied until
1 April 2026"). `_parse_group_verdict`
(nestor_pulse_sdk/pipeline/tribunal/group_skeptic.py:137-149) already produces
that value on every verdict dict -- it simply had nowhere to be stored, which
is precisely finding CR-01 in 15.1-REVIEW.md: "`verification_verdict` has no
`superseded_note` column, and the phase deliberately ships no migration, so it
cannot be persisted". This revision closes CR-01's STORAGE leg only; the
writer that fills the column lands in plan 15.1-14 and the read/DTO side in
plan 15.1-12.

Why nullable
------------
Only a `superseded` verdict has a note at all -- `support` / `refute` /
`insufficient` carry the empty string by construction (group_skeptic.py:146-148)
-- and every row written before this revision predates the column entirely. A
NOT NULL column would demand a meaningless backfill and would misrepresent the
data.

Which alembic line
------------------
The TRIBUNAL line (`tribunal/nestor_pulse_sdk/alembic/versions/`), whose head
was 0011 (`0011_cost_verification.py`). This is NOT the intake `nestor` line
under `backend/app/db/alembic/versions/`, whose own 0011/0012 belong to Phases
16 and 17 -- two schemas, two `alembic_version` tables, two independent
revision sequences (v1.1 roadmap decision, Pitfall 2).

Hash-chain safety
-----------------
The one new column belongs to `verification_verdict`, which is not a hashed
table, and it therefore sits OUTSIDE the frozen `_payload_for_row` payload
(`nestor_pulse_sdk/audit/hash_chain.py` -- 11 fields). No hashed table and no
hashed field is named or altered here, so `verify_chain` cannot move off
`(True, None)` and the frozen field count stays 11 (T-15.1-53).

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-25
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # EXACTLY ONE DDL statement. No schema= kwarg: the migration runs with
    # search_path already pointed at the tribunal schema, the same way every
    # additive column in 0011 is written.
    #
    # Deliberately NO security DDL. `verification_verdict` already carries
    # ENABLE + FORCE ROW LEVEL SECURITY and the
    # `verification_verdict_tenant_isolation` POLICY from 0011. A PostgreSQL
    # row-level POLICY is a TABLE-level object evaluated against row values,
    # so a newly added column is covered by construction. Re-issuing the
    # POLICY, the index, or any GRANT here would be pure regression risk with
    # zero security benefit (T-15.1-52).
    op.add_column(
        "verification_verdict",
        sa.Column("superseded_note", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("verification_verdict", "superseded_note")
