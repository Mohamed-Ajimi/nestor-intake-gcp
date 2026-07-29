"""0016 D-V01-11 resolved publisher URL on `source` (Phase 15.4, wave 1).

Additive-only migration: TWO nullable TEXT columns on an existing table. No new
table, no index, no constraint, no backfill, no data read.

Why this exists
---------------
Gemini grounding citations arrive as `vertexaisearch.cloud.google.com` redirect
URLs, and those redirects EXPIRE roughly 30 days after the run that produced
them (V-01, run 7dcf51d5: 225 unique redirects, all 225 resolvable on
2026-07-28, all dead around late August 2026). Storing only the redirect means
every citation in every past report becomes a dead link the month after
delivery. Storing only the publisher URL would throw away the provenance of
what the provider actually returned -- the thing the audit trail is for.
D-V01-11 therefore says: store BOTH, side by side.

What this migration carries
---------------------------
1. `source.resolved_url` (TEXT nullable) -- the publisher URL a grounding
   redirect resolved to. NULL means "not resolved"; it NEVER means "no source".
   `source.url` remains the URL the provider handed us and is never rewritten.
2. `source.resolution_status` (TEXT nullable) -- exactly three meanings, and no
   fourth:
     * NULL         -- resolution was never attempted. Every row written before
                       this revision, and every non-redirect URL.
     * 'resolved'   -- a 302 `Location` was read and stored in `resolved_url`.
     * 'unresolved' -- resolution WAS attempted and did not produce a usable
                       http(s) target. Distinguishable from NULL on purpose: it
                       is the difference between "we did not try" and "we tried
                       and this citation is at risk".

No CHECK constraint and no enum type
------------------------------------
The codebase's idiom for this class of column is a TEXT column clamped in
Python -- `claim.certainty` in 0013 is the precedent, same shape, same reason.
A CHECK here would convert a resolver bug into a FAILED INSERT in the final
persistence step of a ~$50 run, trading a wrong string for lost claims. The
enum lives in the resolver (plan 15.4-09), where a bad value can be clamped and
logged instead of aborting a transaction.

Why nullable
------------
Both columns are nullable so that NOT ONE EXISTING ROW IS TOUCHED. A NOT NULL
column would demand a backfill of every historic `source` row with a value we
do not have and cannot honestly invent -- the redirects of past runs have
already expired, so any backfilled value would be a fabrication. `ADD COLUMN
... NULL` with no default is a catalogue-only change in PostgreSQL 11+: no
table rewrite, no index build, a brief ACCESS EXCLUSIVE lock that returns
immediately (threat T-15.4-04).

THE THREE INVARIANTS A REVIEWER CHECKS
--------------------------------------
1. ADDITIVE ONLY. No existing row is read, written, backfilled or deleted by
   this revision. `upgrade()` contains exactly two `op.add_column` calls and
   nothing else.

2. `idx_source_tenant_content_hash` IS NOT DROPPED, RECREATED OR ALTERED, and
   NEITHER new column participates in `content_hash`. `content_hash` is
   computed in `citations/extractor.py::_upsert_source` from `snapshot_capped`
   ALONE -- the same rule `title` already lives under, stated in that
   function's own docstring -- so per-tenant source dedupe is byte-identical
   before and after this revision, and the partial UNIQUE index
   `(tenant_id, content_hash) WHERE content_hash IS NOT NULL` keeps matching
   exactly the rows it matched yesterday (threat T-15.4-05). That property is
   load-bearing for plan 15.4-09, which writes these columns on the dedupe
   path. `idx_source_tenant_url` is likewise untouched, and NO THIRD INDEX is
   created: `resolved_url` is read back per source row, never searched across
   tenants.

3. THIS IS THE TRIBUNAL ALEMBIC LINE
   (`tribunal/nestor_pulse_sdk/alembic/versions/`), whose head was 0015
   (`0015_run_events.py`) and whose version table is
   `tribunal.tribunal_alembic_version`. It is NOT the intake `nestor` line
   under `backend/app/db/alembic/versions/`, which ships its own independent
   revision sequence. Two schemas, two `alembic_version` tables, two revision
   sequences, never crossed (v1.1 roadmap decision, Pitfall 2). A revision id
   borrowed from the other line is how one of them silently stops upgrading.

Hash-chain safety
-----------------
`nestor_pulse_sdk/audit/hash_chain.py::_payload_for_row` freezes ELEVEN fields
on `audit_log`. NONE of them lives on `source`. This revision names exactly one
table, `source`, and adds only columns the chain has never seen, so
`verify_chain` cannot move off `(True, None)` and the frozen payload field
count stays 11 -- unaffected BY CONSTRUCTION, not by inspection (EU AI Act
Art. 12 audit-trail gate, deadline 2026-08-02).

Deploy-time proof
-----------------
The log line to look for is `Running upgrade 0015 -> 0016`. Plan 15.4-11 owns
that assertion. Until it prints, this revision is written, not applied.

Revision ID: 0016
Revises: 0015
Create Date: 2026-07-29
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # No schema= kwarg: env.py has already pointed search_path at the `tribunal`
    # schema, the same way every additive column in 0011, 0012 and 0013 is
    # written.
    #
    # Deliberately NO security DDL. `source` already carries ENABLE + FORCE ROW
    # LEVEL SECURITY and its policies (0002, re-issued in 0010's NULLIF form). A
    # PostgreSQL row-level POLICY is a TABLE-level object evaluated against row
    # values, so a newly added column is covered BY CONSTRUCTION. Re-issuing a
    # policy or a GRANT here would be pure regression risk with zero security
    # benefit -- the reasoning 0012 and 0013 both record.

    # ------------------------------------------------- (1) source.resolved_url
    # The publisher URL a `vertexaisearch.cloud.google.com` grounding redirect
    # resolved to. NULL = not resolved, and never "no source": `source.url`
    # still holds what the provider returned and is never rewritten.
    op.add_column(
        "source",
        sa.Column("resolved_url", sa.Text(), nullable=True),
    )

    # -------------------------------------------- (2) source.resolution_status
    # NULL | 'resolved' | 'unresolved' -- see the docstring. Clamped in Python
    # (the `claim.certainty` idiom from 0013), NOT by a CHECK constraint: a
    # resolver bug must not be able to fail an INSERT inside a paid run.
    op.add_column(
        "source",
        sa.Column("resolution_status", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    # Exact inverse order, and NOTHING ELSE. In particular this does not touch
    # `idx_source_tenant_content_hash` -- there is nothing to restore, because
    # `upgrade()` never touched it either.
    op.drop_column("source", "resolution_status")
    op.drop_column("source", "resolved_url")
