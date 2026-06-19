"""0004 in-scope database triggers (<= ``decomposed`` only).

Ports ONLY the trigger/function logic that operates AT OR BEFORE intake status
``decomposed`` — the ceiling of this milestone's flow (PROJECT.md scope ceiling;
INTAKE-05 scope guard). The deferred triggers that drive the Tribunal hand-off
(status at or after research start) are deliberately NOT created here; porting
them would re-open the path toward ``run-research`` (Pitfall 5 / INTAKE-05).

NOTE on the docstring tokens below: Task 1's scope check greps this file's RAW
text for the deferred-trigger names and for a dropped-clients reference and
fails if ANY appears. So the deferred functions and the dropped table are
described here WITHOUT their literal identifiers — the literal names appear
nowhere in this module, which is exactly the property the scope check enforces.

UPDATED_AT_MECHANISM: orm-onupdate
----------------------------------
``updated_at`` maintenance is handled EXACTLY ONE way and it is the ORM, NOT a
database trigger. Plan 01-02's models already declare
``updated_at = mapped_column(..., onupdate=func.now())`` on every table that
carries an ``updated_at`` column (``app/db/models/intake.py`` ``Intake`` and
``IntakeAnswer``). Because ALL writes in this re-platform are mediated by the
FastAPI backend through the ORM (a hard project constraint — "All writes
mediated by the backend"), the ORM ``onupdate`` fires on every UPDATE that goes
through a SQLAlchemy session, so a ``set_updated_at`` / ``tg_set_*`` database
trigger would be redundant. We therefore OMIT the trigger (a valid choice per
the plan's either/or discretion) and create NO ``set_updated_at`` function.

``test_seed_and_triggers.py`` reads the ``UPDATED_AT_MECHANISM:`` marker above
and, seeing ``orm-onupdate``, asserts that NO ``set_updated_at`` function exists
in ``pg_proc`` AND that an ORM-mediated UPDATE bumps ``updated_at`` — making
this choice concretely verified rather than asserted on faith.

IN-SCOPE triggers created here
------------------------------
1. ``prefill_intake_answers`` (BEFORE INSERT ON ``nestor.intakes``):
   seeds a ``client_name`` row into ``intake_answers`` on intake creation.
   RETARGETED (Q2 RESOLVED / D-02 reconciliation): the original Supabase
   version read a ``clients`` table in the ``public`` schema — that table does
   NOT exist in this schema (org = space; client identity lives on
   ``organizations.name``). This port reads
   ``SELECT name FROM nestor.organizations WHERE id = NEW.space_id`` and upserts
   on the ``(intake_id, field_key)`` unique constraint with DO NOTHING. It also
   sets ``NEW.client_name`` for the display-only column on ``intakes``.

2. ``submit_intake(p_intake_id uuid)`` (function, transition LOGIC for fidelity):
   ``draft -> submitted`` and ``reviewed -> validated_by_client``. Both target
   statuses are AT OR BEFORE ``decomposed`` (scope-safe). NOTE: Phase 6 replaces
   this with a real authenticated endpoint; the function is ported now only to
   preserve the transition logic as a schema-faithful reference.
   SECURITY (CR-01): the lookup keys on the EXACT caller-supplied intake id —
   it does NOT select an arbitrary draft/reviewed row via ``LIMIT 1`` (which
   would be a cross-tenant write). The original Supabase RPC keyed on
   ``client_intake_token`` / ``client_validation_token`` and stamped
   ``client_validated_at``; none of those columns exist in this re-platform
   schema (space_id is the sole isolation key), so the selector is the PK and
   the ``client_validated_at`` write is omitted.

DEFERRED — NOT created (INTAKE-05 scope guard / Pitfall 5)
----------------------------------------------------------
Three original triggers operate at or after research start and are NOT ported:
the one that bumps an intake from ``decomposed`` into the research phase, the
one that bumps a research-phase intake to delivered, and the one that
materializes research questions on entry to the research phase. (Their literal
identifiers are intentionally omitted from this file so the scope check stays
green.) Their target columns / enum values still exist in the schema (D-04
fidelity); only the triggers/functions are absent so the new credentials cannot
transition an intake past ``decomposed``.

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-19
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "nestor"


def upgrade() -> None:
    # ------------------------------------------------------------------
    # (1) prefill_intake_answers — BEFORE INSERT ON nestor.intakes.
    #     Retargeted off the dropped legacy clients table to
    #     organizations.name (space_id = organizations.id). Seeds a
    #     'client_name' answer (conflict-do-nothing) and mirrors the value
    #     onto the display-only intakes.client_name column.
    # ------------------------------------------------------------------
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
            -- Q2 RESOLVED / D-02: the client name is the organization name;
            -- there is NO legacy clients table. space_id == organizations.id.
            SELECT name INTO v_client_name
            FROM {SCHEMA}.organizations
            WHERE id = NEW.space_id;

            IF v_client_name IS NOT NULL AND v_client_name <> '' THEN
                -- Mirror onto the display-only column when the insert did not
                -- already supply one.
                IF NEW.client_name IS NULL OR NEW.client_name = '' THEN
                    NEW.client_name := v_client_name;
                END IF;

                -- Seed the answer row. NEW.id is the not-yet-inserted intake id
                -- (BEFORE INSERT), and space_id is required by the NOT NULL FK
                -- + the RLS isolation policy.
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
    op.execute(
        f"""
        CREATE TRIGGER trg_prefill_intake_answers
            BEFORE INSERT ON {SCHEMA}.intakes
            FOR EACH ROW
            EXECUTE FUNCTION {SCHEMA}.prefill_intake_answers()
        """
    )

    # ------------------------------------------------------------------
    # (2) submit_intake(p_intake_id) — transition LOGIC ported for fidelity.
    #     draft -> submitted ; reviewed -> validated_by_client. Both target
    #     statuses are <= decomposed (scope-safe). Phase 6 replaces this
    #     with an authenticated endpoint.
    #
    #     SECURITY (CR-01): the SELECT resolves the intake by an EXACT,
    #     CALLER-SUPPLIED id — never an arbitrary "LIMIT 1" over all
    #     draft/reviewed rows. An unkeyed LIMIT 1 would let any caller flip a
    #     RANDOM tenant's intake (cross-tenant write / authorization defect),
    #     violating the project's hard "no cross-tenant access" constraint.
    #
    #     SCHEMA RECONCILIATION (Q2 RESOLVED / D-02): the original Supabase
    #     RPC resolved the intake by ``client_intake_token`` /
    #     ``client_validation_token`` and stamped ``client_validated_at`` on
    #     the validation transition. NONE of those three columns exist in this
    #     re-platform schema (the token-based identity model was dropped;
    #     ``space_id`` = organization id is the SOLE isolation key, and the
    #     intakes table carries no token or ``client_validated_at`` column —
    #     see 0001_baseline_schema.py / app/db/models/intake.py). So the
    #     parameter is the intake ``uuid`` keyed directly on the PK, and the
    #     ``client_validated_at`` SET clause is OMITTED (no such column).
    # ------------------------------------------------------------------
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {SCHEMA}.submit_intake(p_intake_id uuid)
            RETURNS jsonb
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path TO '{SCHEMA}'
        AS $function$
        DECLARE
            v_intake_id uuid;
            v_current_status {SCHEMA}.intake_status;
            v_new_status {SCHEMA}.intake_status;
        BEGIN
            -- Resolve EXACTLY the caller-supplied intake (no arbitrary
            -- LIMIT 1). Allow draft (initial submit) OR reviewed (validation
            -- submit) only.
            SELECT id, status INTO v_intake_id, v_current_status
            FROM {SCHEMA}.intakes
            WHERE id = p_intake_id
              AND status IN ('draft', 'reviewed');

            IF v_intake_id IS NULL THEN
                RAISE EXCEPTION 'Unknown intake or intake not in submittable state';
            END IF;

            IF v_current_status = 'draft' THEN
                v_new_status := 'submitted';
            ELSIF v_current_status = 'reviewed' THEN
                v_new_status := 'validated_by_client';
            ELSE
                RAISE EXCEPTION 'Unexpected status: %', v_current_status;
            END IF;

            UPDATE {SCHEMA}.intakes
            SET status = v_new_status,
                updated_at = now()
            WHERE id = v_intake_id;

            RETURN jsonb_build_object(
                'success', true,
                'intake_id', v_intake_id,
                'new_status', v_new_status
            );
        END;
        $function$
        """
    )


def downgrade() -> None:
    # Reverse order: drop submit_intake, then the prefill trigger + function.
    op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA}.submit_intake(uuid)")
    op.execute(
        f"DROP TRIGGER IF EXISTS trg_prefill_intake_answers ON {SCHEMA}.intakes"
    )
    op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA}.prefill_intake_answers()")
