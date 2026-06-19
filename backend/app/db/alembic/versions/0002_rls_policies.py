"""0002 RLS isolation policies for the 12 tenant-owned tables.

Real tenant isolation as defense-in-depth (D-06) — enforced at the DB layer;
the application MUST NOT rely on a WHERE clause alone. This is the migration
that makes the inherited Supabase permissive-policy bug (a ``USING``-true
predicate that lets any logged-in user read/write all tenants) structurally
impossible: every policy is keyed on the per-session ``app.current_space_id``
GUC, never on a constant-true predicate.

Per 01-RESEARCH.md § Pattern 1 + Pitfalls 1 & 2, for each of the 12
tenant-owned tables this migration emits:

  - ``ALTER TABLE <t> ENABLE ROW LEVEL SECURITY``
  - ``ALTER TABLE <t> FORCE  ROW LEVEL SECURITY``  (Pitfall 2: the migration
    role OWNS these tables, and without FORCE the owner bypasses RLS entirely —
    ``test_force_rls_applies_to_owner`` asserts ``relforcerowsecurity``).
  - ``CREATE POLICY <t>_space_isolation`` with USING + WITH CHECK both equal to
    ``space_id = NULLIF(current_setting('app.current_space_id', true), '')::uuid``.

Why the ``NULLIF(..., '')`` form from DAY ONE (not the bare 2-arg
``current_setting('app.current_space_id', true)::uuid``): ``app.current_space_id``
is a custom (placeholder) GUC. Once any transaction on a pooled connection runs
``SET LOCAL app.current_space_id = '<uuid>'`` (which the backend / set_space
helper does), the GUC becomes "known" on that physical connection and reverts at
COMMIT to the EMPTY STRING ``''`` — NOT to unset/NULL. The next no-context
transaction that reuses the connection would then evaluate ``''::uuid`` and raise
``invalid input syntax for type uuid: ""``. ``NULLIF(..., '')`` collapses BOTH
unset (NULL) and the empty-string reversion ('') to NULL before the cast:

  - app role WITH a real context: exact ``space_id`` match (sees only its space).
  - app role with NO / empty context: USING -> NULL -> no rows (fail-SAFE read);
    WITH CHECK -> NULL -> writes rejected (fail-LOUD).

The sibling repo only reached this form at 0009->0010 after a prod crash-loop;
we adopt it in the FIRST RLS migration so that bug is never replayed (the
``test_no_space_context_returns_empty`` and pooled-reuse regression tests cover
this directly).

The policies are written out INLINE (one verbatim block per table, not a Python
loop) so the migration file is greppable for the QA-02 CI guard and so each
policy literal is auditable in place. We intentionally NEVER write a
constant-true USING / WITH CHECK predicate here (that is the exact pattern the
``scripts/ci_no_permissive_rls.sh`` guard bans).

Tables in scope (the 12 tenant-OWNED tables from 0001):
    products, intake_templates, intakes, intake_answers, skill_runs,
    decompositions, research_questions, research_artifacts, findings,
    deliverables, artifact_embeddings, search_index.
organizations + organization_memberships are the tenant ROOT (they ARE the
space / the user->space map) and are deliberately NOT RLS-scoped.

The superadmin (cross-tenant) bypass policy is added in 0003 (OR'd with these
isolation policies via a real ``current_user = 'app_superadmin'`` predicate).

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-19
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "nestor"


def upgrade() -> None:
    # ----------------------------------------------------------- products
    op.execute(f"ALTER TABLE {SCHEMA}.products ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {SCHEMA}.products FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY products_space_isolation ON {SCHEMA}.products
            USING (space_id = NULLIF(current_setting('app.current_space_id', true), '')::uuid)
            WITH CHECK (space_id = NULLIF(current_setting('app.current_space_id', true), '')::uuid)
        """
    )

    # -------------------------------------------------- intake_templates
    op.execute(f"ALTER TABLE {SCHEMA}.intake_templates ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {SCHEMA}.intake_templates FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY intake_templates_space_isolation ON {SCHEMA}.intake_templates
            USING (space_id = NULLIF(current_setting('app.current_space_id', true), '')::uuid)
            WITH CHECK (space_id = NULLIF(current_setting('app.current_space_id', true), '')::uuid)
        """
    )

    # ------------------------------------------------------------ intakes
    op.execute(f"ALTER TABLE {SCHEMA}.intakes ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {SCHEMA}.intakes FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY intakes_space_isolation ON {SCHEMA}.intakes
            USING (space_id = NULLIF(current_setting('app.current_space_id', true), '')::uuid)
            WITH CHECK (space_id = NULLIF(current_setting('app.current_space_id', true), '')::uuid)
        """
    )

    # ----------------------------------------------------- intake_answers
    op.execute(f"ALTER TABLE {SCHEMA}.intake_answers ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {SCHEMA}.intake_answers FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY intake_answers_space_isolation ON {SCHEMA}.intake_answers
            USING (space_id = NULLIF(current_setting('app.current_space_id', true), '')::uuid)
            WITH CHECK (space_id = NULLIF(current_setting('app.current_space_id', true), '')::uuid)
        """
    )

    # --------------------------------------------------------- skill_runs
    op.execute(f"ALTER TABLE {SCHEMA}.skill_runs ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {SCHEMA}.skill_runs FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY skill_runs_space_isolation ON {SCHEMA}.skill_runs
            USING (space_id = NULLIF(current_setting('app.current_space_id', true), '')::uuid)
            WITH CHECK (space_id = NULLIF(current_setting('app.current_space_id', true), '')::uuid)
        """
    )

    # ------------------------------------------------------ decompositions
    op.execute(f"ALTER TABLE {SCHEMA}.decompositions ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {SCHEMA}.decompositions FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY decompositions_space_isolation ON {SCHEMA}.decompositions
            USING (space_id = NULLIF(current_setting('app.current_space_id', true), '')::uuid)
            WITH CHECK (space_id = NULLIF(current_setting('app.current_space_id', true), '')::uuid)
        """
    )

    # --------------------------------------------------- research_questions
    op.execute(f"ALTER TABLE {SCHEMA}.research_questions ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {SCHEMA}.research_questions FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY research_questions_space_isolation ON {SCHEMA}.research_questions
            USING (space_id = NULLIF(current_setting('app.current_space_id', true), '')::uuid)
            WITH CHECK (space_id = NULLIF(current_setting('app.current_space_id', true), '')::uuid)
        """
    )

    # --------------------------------------------------- research_artifacts
    op.execute(f"ALTER TABLE {SCHEMA}.research_artifacts ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {SCHEMA}.research_artifacts FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY research_artifacts_space_isolation ON {SCHEMA}.research_artifacts
            USING (space_id = NULLIF(current_setting('app.current_space_id', true), '')::uuid)
            WITH CHECK (space_id = NULLIF(current_setting('app.current_space_id', true), '')::uuid)
        """
    )

    # ----------------------------------------------------------- findings
    op.execute(f"ALTER TABLE {SCHEMA}.findings ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {SCHEMA}.findings FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY findings_space_isolation ON {SCHEMA}.findings
            USING (space_id = NULLIF(current_setting('app.current_space_id', true), '')::uuid)
            WITH CHECK (space_id = NULLIF(current_setting('app.current_space_id', true), '')::uuid)
        """
    )

    # -------------------------------------------------------- deliverables
    op.execute(f"ALTER TABLE {SCHEMA}.deliverables ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {SCHEMA}.deliverables FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY deliverables_space_isolation ON {SCHEMA}.deliverables
            USING (space_id = NULLIF(current_setting('app.current_space_id', true), '')::uuid)
            WITH CHECK (space_id = NULLIF(current_setting('app.current_space_id', true), '')::uuid)
        """
    )

    # -------------------------------------------------- artifact_embeddings
    op.execute(f"ALTER TABLE {SCHEMA}.artifact_embeddings ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {SCHEMA}.artifact_embeddings FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY artifact_embeddings_space_isolation ON {SCHEMA}.artifact_embeddings
            USING (space_id = NULLIF(current_setting('app.current_space_id', true), '')::uuid)
            WITH CHECK (space_id = NULLIF(current_setting('app.current_space_id', true), '')::uuid)
        """
    )

    # -------------------------------------------------------- search_index
    op.execute(f"ALTER TABLE {SCHEMA}.search_index ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {SCHEMA}.search_index FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY search_index_space_isolation ON {SCHEMA}.search_index
            USING (space_id = NULLIF(current_setting('app.current_space_id', true), '')::uuid)
            WITH CHECK (space_id = NULLIF(current_setting('app.current_space_id', true), '')::uuid)
        """
    )


def downgrade() -> None:
    # Reverse order — DROP POLICY first, then NO FORCE, then DISABLE, per table.

    op.execute(f"DROP POLICY IF EXISTS search_index_space_isolation ON {SCHEMA}.search_index")
    op.execute(f"ALTER TABLE {SCHEMA}.search_index NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {SCHEMA}.search_index DISABLE ROW LEVEL SECURITY")

    op.execute(
        f"DROP POLICY IF EXISTS artifact_embeddings_space_isolation ON {SCHEMA}.artifact_embeddings"
    )
    op.execute(f"ALTER TABLE {SCHEMA}.artifact_embeddings NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {SCHEMA}.artifact_embeddings DISABLE ROW LEVEL SECURITY")

    op.execute(f"DROP POLICY IF EXISTS deliverables_space_isolation ON {SCHEMA}.deliverables")
    op.execute(f"ALTER TABLE {SCHEMA}.deliverables NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {SCHEMA}.deliverables DISABLE ROW LEVEL SECURITY")

    op.execute(f"DROP POLICY IF EXISTS findings_space_isolation ON {SCHEMA}.findings")
    op.execute(f"ALTER TABLE {SCHEMA}.findings NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {SCHEMA}.findings DISABLE ROW LEVEL SECURITY")

    op.execute(
        f"DROP POLICY IF EXISTS research_artifacts_space_isolation ON {SCHEMA}.research_artifacts"
    )
    op.execute(f"ALTER TABLE {SCHEMA}.research_artifacts NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {SCHEMA}.research_artifacts DISABLE ROW LEVEL SECURITY")

    op.execute(
        f"DROP POLICY IF EXISTS research_questions_space_isolation ON {SCHEMA}.research_questions"
    )
    op.execute(f"ALTER TABLE {SCHEMA}.research_questions NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {SCHEMA}.research_questions DISABLE ROW LEVEL SECURITY")

    op.execute(f"DROP POLICY IF EXISTS decompositions_space_isolation ON {SCHEMA}.decompositions")
    op.execute(f"ALTER TABLE {SCHEMA}.decompositions NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {SCHEMA}.decompositions DISABLE ROW LEVEL SECURITY")

    op.execute(f"DROP POLICY IF EXISTS skill_runs_space_isolation ON {SCHEMA}.skill_runs")
    op.execute(f"ALTER TABLE {SCHEMA}.skill_runs NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {SCHEMA}.skill_runs DISABLE ROW LEVEL SECURITY")

    op.execute(f"DROP POLICY IF EXISTS intake_answers_space_isolation ON {SCHEMA}.intake_answers")
    op.execute(f"ALTER TABLE {SCHEMA}.intake_answers NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {SCHEMA}.intake_answers DISABLE ROW LEVEL SECURITY")

    op.execute(f"DROP POLICY IF EXISTS intakes_space_isolation ON {SCHEMA}.intakes")
    op.execute(f"ALTER TABLE {SCHEMA}.intakes NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {SCHEMA}.intakes DISABLE ROW LEVEL SECURITY")

    op.execute(
        f"DROP POLICY IF EXISTS intake_templates_space_isolation ON {SCHEMA}.intake_templates"
    )
    op.execute(f"ALTER TABLE {SCHEMA}.intake_templates NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {SCHEMA}.intake_templates DISABLE ROW LEVEL SECURITY")

    op.execute(f"DROP POLICY IF EXISTS products_space_isolation ON {SCHEMA}.products")
    op.execute(f"ALTER TABLE {SCHEMA}.products NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {SCHEMA}.products DISABLE ROW LEVEL SECURITY")
