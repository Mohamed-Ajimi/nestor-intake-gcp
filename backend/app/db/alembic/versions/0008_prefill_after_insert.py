"""0008 — fix prefill: seed the client_name answer in an AFTER INSERT trigger.

The 0004 ``prefill_intake_answers`` trigger ran ``BEFORE INSERT ON intakes`` and, in the
same function, INSERTed a child ``intake_answers`` row referencing ``NEW.id``. But BEFORE
INSERT fires before the parent intake row exists, and ``intake_answers.intake_id`` FK ->
``intakes.id`` is NOT deferrable, so the child insert failed with ``23503`` (FK violation:
"Key is not present in table intakes"). The whole intake-create path was therefore broken
(latent — the suite never ran live). Split the logic by timing:

  * BEFORE INSERT (``prefill_intake_answers``): ONLY mirror the org name onto
    ``intakes.client_name`` (a ``NEW`` mutation — must be BEFORE).
  * AFTER INSERT (``seed_intake_client_name_answer``): seed the ``client_name`` answer; the
    parent row now exists, so the FK is satisfied.

Both functions stay SECURITY DEFINER. The AFTER trigger's child insert relies on the
tx-local ``app.current_space_id`` GUC (set by the per-request repo on the user path, and by
``create_in_space`` on the superadmin path) to pass the ``intake_answers`` space-isolation
RLS WITH CHECK — the ``app_superadmin`` bypass policy does not apply inside a definer trigger.

Revision ID: 0008
Revises: 0007
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "nestor"


def upgrade() -> None:
    # BEFORE INSERT: mirror the org name onto the display-only column ONLY (no child insert).
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {SCHEMA}.prefill_intake_answers()
            RETURNS trigger
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path TO '{SCHEMA}'
        AS $function$
        DECLARE
            v_client_name text;
        BEGIN
            SELECT name INTO v_client_name
            FROM {SCHEMA}.organizations
            WHERE id = NEW.space_id;

            IF v_client_name IS NOT NULL AND v_client_name <> '' THEN
                IF NEW.client_name IS NULL OR NEW.client_name = '' THEN
                    NEW.client_name := v_client_name;
                END IF;
            END IF;

            RETURN NEW;
        END;
        $function$
        """
    )

    # AFTER INSERT: seed the client_name answer now that the parent intake row exists.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {SCHEMA}.seed_intake_client_name_answer()
            RETURNS trigger
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path TO '{SCHEMA}'
        AS $function$
        DECLARE
            v_client_name text;
        BEGIN
            SELECT name INTO v_client_name
            FROM {SCHEMA}.organizations
            WHERE id = NEW.space_id;

            IF v_client_name IS NOT NULL AND v_client_name <> '' THEN
                INSERT INTO {SCHEMA}.intake_answers
                    (intake_id, space_id, field_key, value)
                VALUES
                    (NEW.id, NEW.space_id, 'client_name', v_client_name)
                ON CONFLICT (intake_id, field_key) DO NOTHING;
            END IF;

            RETURN NULL;
        END;
        $function$
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_seed_intake_client_name_answer
            AFTER INSERT ON {SCHEMA}.intakes
            FOR EACH ROW
            EXECUTE FUNCTION {SCHEMA}.seed_intake_client_name_answer()
        """
    )


def downgrade() -> None:
    # Restore the 0004 combined BEFORE-INSERT behavior (child insert back in the BEFORE fn).
    op.execute(
        f"DROP TRIGGER IF EXISTS trg_seed_intake_client_name_answer ON {SCHEMA}.intakes"
    )
    op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA}.seed_intake_client_name_answer()")
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {SCHEMA}.prefill_intake_answers()
            RETURNS trigger
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path TO '{SCHEMA}'
        AS $function$
        DECLARE
            v_client_name text;
        BEGIN
            SELECT name INTO v_client_name
            FROM {SCHEMA}.organizations
            WHERE id = NEW.space_id;

            IF v_client_name IS NOT NULL AND v_client_name <> '' THEN
                IF NEW.client_name IS NULL OR NEW.client_name = '' THEN
                    NEW.client_name := v_client_name;
                END IF;

                INSERT INTO {SCHEMA}.intake_answers
                    (intake_id, space_id, field_key, value)
                VALUES
                    (NEW.id, NEW.space_id, 'client_name', v_client_name)
                ON CONFLICT (intake_id, field_key) DO NOTHING;
            END IF;

            RETURN NEW;
        END;
        $function$
        """
    )
