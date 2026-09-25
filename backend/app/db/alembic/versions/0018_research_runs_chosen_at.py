"""0018 research_runs_chosen_at — the internal "which run is the report based on" label.

Phase 23.6 (plan 23.6-01, D-23.6-02 revised). Adds ONE nullable column and ONE partial
unique index to ``nestor.research_runs``.

What it is for
--------------
Since 23.6 a superadmin may rerun deep research on one intake as often as they like
(D-23.6-01, D-23.6-03). With several finished runs on one intake the operator needs to
record WHICH of them the final report is based on. That is an INTERNAL label only: there
is no client-facing consumer of it, and the newest-finished DEFAULT the UI shows is
display-only and is NEVER stored (UI-SPEC UI-8). The only writer is
``ResearchRunRepository.set_chosen``.

Why a flag on the RUN and not a pointer on the INTAKE
-----------------------------------------------------
* No ``intakes <-> research_runs`` FK cycle. ``research_runs`` already cascades from
  ``intakes``; a pointer back would make the D-23.5-06 intake delete order-dependent.
  With a flag on the run, deleting an intake removes its runs and their marks together,
  unchanged.
* No change to the widely-read ``intakes`` table.
* "At most ONE chosen run per intake" becomes a DATABASE invariant — the partial unique
  index below — the same technique 0016 uses for the single in-flight run.

Why this is cheap and safe on a table of paid rows
--------------------------------------------------
NULLABLE with NO server default is a metadata-only ``ADD COLUMN`` in Postgres: no table
rewrite, no backfill. NULL means "not chosen", which is the truth for every existing row.

No policy and no grant change: the table's existing grants and FORCE RLS already cover a
new column; this revision creates no policy, grants nothing and revokes nothing.

⛔ ``0019`` stays RESERVED for DEF-22-06 (ROADMAP Phase 24). This revision takes 0018.

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-25
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "nestor"
_TABLE = "research_runs"
_COLUMN = "chosen_at"

#: The one-chosen-per-intake index name. It MUST match
#: ``app/db/models/research_runs.py``'s ``__table_args__`` entry BYTE-FOR-BYTE;
#: ``tests/test_research_run_chosen.py`` pins it against the DEPLOYED
#: ``pg_indexes.indexdef`` (``alembic check`` does not compare ``postgresql_where``,
#: DEF-23.2-15).
_CHOSEN_INDEX = "uq_research_runs_one_chosen_per_intake"

#: The partial predicate: only CHOSEN rows are constrained, so any number of unchosen runs
#: per intake remains legal.
_CHOSEN_PREDICATE = "chosen_at IS NOT NULL"


def upgrade() -> None:
    op.add_column(
        _TABLE,
        sa.Column(
            _COLUMN,
            sa.DateTime(timezone=True),
            nullable=True,
            comment=(
                "INTERNAL label: when the operator marked this run as the one the final "
                "report is based on (D-23.6-02). At most one run per intake carries a "
                "non-null value (enforced by a partial unique index). NULL = not "
                "chosen; the newest-finished default shown in the UI is display-only and "
                "is never stored. Written only by ResearchRunRepository.set_chosen."
            ),
        ),
        schema=SCHEMA,
    )
    op.create_index(
        _CHOSEN_INDEX,
        _TABLE,
        ["intake_id"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text(_CHOSEN_PREDICATE),
    )


def downgrade() -> None:
    # Index first (it depends on chosen_at), then the column. Fully reversible: the only
    # data lost is the internal label itself.
    op.drop_index(_CHOSEN_INDEX, table_name=_TABLE, schema=SCHEMA)
    op.drop_column(_TABLE, _COLUMN, schema=SCHEMA)
