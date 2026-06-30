"""0007 — DB-level default for intake_answers.id (gen_random_uuid()).

The ``prefill_intake_answers()`` trigger (0004) inserts a ``client_name`` row into
``nestor.intake_answers`` via RAW SQL, WITHOUT supplying ``id``. The model's ORM-side
default (``default=uuid.uuid4``) applies ONLY to ORM-created rows — never to a trigger's
raw INSERT — and the 0001 baseline created ``intake_answers.id`` with NO DB default. So
the trigger insert failed with ``23502`` ("null value in column id violates not-null
constraint") and intake creation 500'd (latent because the suite has never run live).

Add a DB-level ``DEFAULT gen_random_uuid()`` so trigger/raw inserts populate ``id``.
``gen_random_uuid()`` is built into Postgres 13+ (Cloud SQL); 0001 already ensured its
availability. ORM inserts are unaffected — they still send the client-side uuid4.

Revision ID: 0007
Revises: 0006
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "nestor"


def upgrade() -> None:
    op.execute(
        f"ALTER TABLE {SCHEMA}.intake_answers "
        "ALTER COLUMN id SET DEFAULT gen_random_uuid()"
    )


def downgrade() -> None:
    op.execute(f"ALTER TABLE {SCHEMA}.intake_answers ALTER COLUMN id DROP DEFAULT")
