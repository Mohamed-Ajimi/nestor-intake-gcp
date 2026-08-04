"""The 0018 contract: two yield tables, pinned to their ORM models column-for-column.

WHY THIS FILE EXISTS
--------------------
Phase 15.8 measures the redesigned engine ONCE, and the two questions the
measurement must answer -- *which provider actually yields surviving claims per
dollar* and *does round 7+ of the workshop loop ever produce a new entrant* --
are QUERIES OVER MANY RUNS. There is nowhere in the schema to record either.
Revision 0018 creates the two tables that hold them (D-R8, D-W5-1). This file
pins that revision's shape and locks it to `db/models/assignment_yield.py` and
`db/models/workshop_round_yield.py`.

WHAT THIS FILE CAN AND CANNOT PROVE
-----------------------------------
It CAN prove the revision chain is intact and single-headed, that `upgrade()`
does exactly the allowlisted operations and nothing else, that no EXISTING table
is touched, that both tables get ENABLE + FORCE row level security and a
tenant-isolation policy carrying WITH CHECK as well as USING, that there is no
CHECK and no UNIQUE constraint anywhere in the revision, and that the ORM and the
DDL declare the same columns IN THE SAME ORDER with the same nullability.

IT CANNOT PROVE THE MIGRATION RAN. That proof is the literal line
`Running upgrade 0017 -> 0018` in a deploy log, and phase 15.8's migrate job
(15.8-14) is the only thing that can pay it. TWO OLDER LINES ARE OWED WITH IT:
`Running upgrade 0015 -> 0016` and `Running upgrade 0016 -> 0017` have likewise
never touched a database, so 0017 is the head of the FILES and not of any live
schema. EXIT CODE 0 IS NOT A SUBSTITUTE -- this repository has a recorded
incident of a migration step that exited 0 having printed no upgrade line at all.

THERE IS DELIBERATELY NO RLS RUNTIME TEST IN THIS FILE, AND ITS ABSENCE IS NOT AN
OVERSIGHT. This gate PROVISIONS NO DATABASE. A role-less DB test would connect as
SUPERUSER, and RLS DOES NOT APPLY TO A SUPERUSER: every isolation assertion would
PASS VACUOUSLY, which is strictly worse than no test because it reports as proof.
The harness that can honestly run those assertions is `cloudbuild.test-rls.yaml`
with its non-superuser DSN. What this file CAN and DOES prove about RLS is that
the DDL *is present in the migration*, WITH CHECK included. Do not add a runtime
one here later thinking it was forgotten.

THIS FILE OPENS NO DATABASE, MAKES ZERO LLM CALLS, USES NO MOCKING LIBRARY AND
NEEDS NO API KEY. It parses the migration with `ast` and imports the two ORM
models (which build table metadata in memory). Importing the migration executes
two module-level imports and two function definitions; `upgrade()` IS NEVER
CALLED, so no DDL is emitted and no alembic migration context is needed.

Cloud Build invocation (no Postgres and no provider key needed):
  gcloud builds submit tribunal \\
    --config=tribunal/cloudbuild.test-engine.yaml \\
    --project="$GOOGLE_PROJECT"

This plan does NOT add itself to that config: `cloudbuild.test-engine.yaml` has
exactly ONE owner in phase 15.8 -- plan 15.8-13, wave 4 (D-W5-5).
"""
from __future__ import annotations

import ast
import importlib.util
import inspect
import re
from pathlib import Path
from types import ModuleType

import pytest


# --------------------------------------------------------------------------
# Locating the migration
# --------------------------------------------------------------------------
# parents[1] is `nestor_pulse_sdk/`. Resolved from THIS file rather than from a
# working directory, because the engine gate runs with /workspace mounted at the
# `tribunal/` source dir: nothing above `tribunal/` exists in that build context,
# so a path reaching outside it would pass locally and fail there.
_SDK_DIR = Path(__file__).resolve().parents[1]
_VERSIONS_DIR = _SDK_DIR / "alembic" / "versions"
_MIGRATION_PATH = _VERSIONS_DIR / "0018_yield_instrumentation.py"
_HASH_CHAIN_PATH = _SDK_DIR / "audit" / "hash_chain.py"

_REVISION_RE = re.compile(r"^revision\s*(?::\s*str\s*)?=\s*[\"']([^\"']+)[\"']", re.M)
_DOWN_REVISION_RE = re.compile(
    r"^down_revision\s*(?::[^=]*)?=\s*[\"']([^\"']+)[\"']", re.M
)

# THE COLUMN CONTRACT. Order is NORMATIVE: the migration emits them in this
# order and the ORM declares them in this order, and the lock-step tests below
# compare ORDERED SEQUENCES rather than sets. A set comparison would pass on a
# migration that emitted the right columns in the wrong order, and the order is
# what a human reading `\d assignment_yield` uses to understand the row.
_ASSIGNMENT_COLUMNS: tuple[tuple[str, str, bool], ...] = (
    # (name, ddl type expression, nullable)
    ("id", "postgresql.UUID(as_uuid=True)", False),
    ("tenant_id", "postgresql.UUID(as_uuid=True)", False),
    ("run_id", "postgresql.UUID(as_uuid=True)", False),
    ("provider", "sa.Text()", False),
    ("group_id", "sa.Text()", True),
    ("client_question", "sa.Text()", True),
    ("parent_kind", "sa.Text()", False),
    ("stakes", "sa.Text()", True),
    ("fact_list_parsed", "sa.Boolean()", True),
    ("retry_used", "sa.Boolean()", True),
    ("claims_kept", "sa.Integer()", True),
    ("claims_surviving_verification", "sa.Integer()", True),
    ("resolvable_sources", "sa.Integer()", True),
    ("cost_usd", "sa.Numeric(12, 6)", True),
    ("duration_s", "sa.Numeric(10, 3)", True),
    ("created_at", "sa.DateTime(timezone=True)", False),
    ("verified_at", "sa.DateTime(timezone=True)", True),
)

_ROUND_COLUMNS: tuple[tuple[str, str, bool], ...] = (
    ("id", "postgresql.UUID(as_uuid=True)", False),
    ("tenant_id", "postgresql.UUID(as_uuid=True)", False),
    ("run_id", "postgresql.UUID(as_uuid=True)", False),
    ("round_no", "sa.Integer()", False),
    ("candidates_in", "sa.Integer()", True),
    ("new_candidates", "sa.Integer()", True),
    ("keep_count", "sa.Integer()", True),
    ("weak_count", "sa.Integer()", True),
    ("kill_count", "sa.Integer()", True),
    ("new_entrants_top_n", "sa.Integer()", True),
    ("barred_drops", "sa.Integer()", True),
    ("round_cost_usd", "sa.Numeric(12, 6)", True),
    ("created_at", "sa.DateTime(timezone=True)", False),
)

#: Tables that already exist and that this revision must not touch.
_EXISTING_TABLES = ("claim", "audit_log", "run", "source", "run_event")

_NEW_TABLES = ("assignment_yield", "workshop_round_yield")


# --------------------------------------------------------------------------
# Helpers -- copied from test_claim_attribution.py on purpose. They are the
# reason a COMMENT mentioning `create_index` cannot make a scan pass.
# --------------------------------------------------------------------------

def _load_migration_at(path: Path) -> ModuleType:
    """Import an alembic version file by path.

    Version filenames start with a digit, so they are not legal module names and
    cannot be reached by `import`. Executing one defines four names and does
    nothing else -- no connection, no DDL, no side effect.
    """
    assert path.is_file(), f"missing migration: {path}"
    spec = importlib.util.spec_from_file_location(f"_alembic_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_migration() -> ModuleType:
    return _load_migration_at(_MIGRATION_PATH)


def _executable_source(module: ModuleType) -> str:
    """The module source with every docstring and every comment removed.

    `ast.unparse` drops comments (they never enter the tree) and this strips the
    module-, class- and function-level docstrings explicitly. String literals
    that are ARGUMENTS -- `op.create_table("assignment_yield", ...)` -- are
    PRESERVED, which is the whole point: this migration's docstring names every
    column and every forbidden construct repeatedly in prose, so a raw-file grep
    would pass on the prose alone.
    """
    tree = ast.parse(inspect.getsource(module))
    holders: list[ast.AST] = [tree]
    holders += [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    for holder in holders:
        body = getattr(holder, "body", None)
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            holder.body = body[1:] or [ast.Pass()]  # type: ignore[attr-defined]
    ast.fix_missing_locations(tree)
    return ast.unparse(tree)


def _alembic_operations(
    source: str, *, function: str | None = None
) -> list[tuple[str, str | None]]:
    """Every `op.<name>(...)` call in `source`, as (operation, first literal arg)."""
    tree: ast.AST = ast.parse(source)
    if function is not None:
        matches = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == function
        ]
        assert len(matches) == 1, f"expected exactly one def {function}()"
        tree = matches[0]

    found: list[tuple[str, str | None]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        target = func.value
        if not (isinstance(target, ast.Name) and target.id == "op"):
            continue
        first: str | None = None
        if node.args and isinstance(node.args[0], ast.Constant):
            value = node.args[0].value
            if isinstance(value, str):
                first = value
        found.append((func.attr, first))
    return found


def _created_tables(source: str) -> dict[str, list[tuple[str, str, bool]]]:
    """Every `op.create_table(...)`, as table -> ordered [(name, type, nullable)].

    Nullability is derived the way PostgreSQL derives it: a `primary_key=True`
    column is NOT NULL, an explicit `nullable=` kwarg wins otherwise, and a
    column with neither is NULLABLE (SQLAlchemy's default). That derivation is
    what makes the ORM comparison meaningful rather than a restatement.
    """
    tree = ast.parse(source)
    out: dict[str, list[tuple[str, str, bool]]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "create_table"):
            continue
        if not (isinstance(func.value, ast.Name) and func.value.id == "op"):
            continue
        assert node.args and isinstance(node.args[0], ast.Constant)
        table = str(node.args[0].value)
        columns: list[tuple[str, str, bool]] = []
        for arg in node.args[1:]:
            if not (
                isinstance(arg, ast.Call)
                and isinstance(arg.func, ast.Attribute)
                and arg.func.attr == "Column"
            ):
                continue
            name = str(arg.args[0].value)
            type_src = ast.unparse(arg.args[1]) if len(arg.args) > 1 else ""
            nullable: bool | None = None
            primary = False
            for kw in arg.keywords:
                if kw.arg == "nullable" and isinstance(kw.value, ast.Constant):
                    nullable = bool(kw.value.value)
                if kw.arg == "primary_key" and isinstance(kw.value, ast.Constant):
                    primary = bool(kw.value.value)
            if primary:
                nullable = False
            elif nullable is None:
                nullable = True
            columns.append((name, type_src, bool(nullable)))
        out[table] = columns
    return out


def _sql_table_names(source: str) -> set[str]:
    """Every table named in a raw-SQL `ALTER TABLE x` / `... ON x` in `source`.

    `op.execute` hides its target from `_alembic_operations` (the first argument
    is a whole SQL blob, not a table name), so the RLS/policy statements need
    their own reader or the "touches no existing table" invariant would have a
    hole exactly where the hand-written SQL lives.
    """
    names: set[str] = set()
    names |= set(re.findall(r"ALTER TABLE\s+([a-z_][a-z0-9_]*)", source))
    names |= set(re.findall(r"\bON\s+([a-z_][a-z0-9_]*)", source))
    return names


def _payload_field_count() -> int:
    """Keys in `hash_chain._payload_for_row`'s returned dict, read via `ast`.

    Read from the FILE rather than by importing, so this assertion costs no
    import of the audit package and cannot be perturbed by it.
    """
    tree = ast.parse(_HASH_CHAIN_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_payload_for_row":
            for inner in ast.walk(node):
                if isinstance(inner, ast.Return) and isinstance(inner.value, ast.Dict):
                    return len(inner.value.keys)
    raise AssertionError("hash_chain._payload_for_row: no returned dict literal found")


# ==========================================================================
# 1. The revision chain
#
# CAN prove: 0018 declares 0017 as its parent, no other file claims that parent
# or that id, and every revision id in the directory is unique.
# CANNOT prove: that `alembic upgrade head` ever ran. See the module docstring.
# ==========================================================================

def test_the_revision_chain_is_0017_to_0018() -> None:
    """0018 revises 0017. A break here is how a migration silently never runs.

    `alembic upgrade head` walks down_revision pointers. A wrong id does not
    error loudly -- it just leaves this revision off the path to head, so the two
    yield tables never appear in production while every test in this file still
    passes, and the ONE measuring run writes its telemetry nowhere.
    """
    module = _load_migration()

    assert module.revision == "0018"
    assert module.down_revision == "0017"
    # A branch label or a depends_on would take 0018 off the single linear path
    # that `alembic upgrade head` follows in this repository.
    assert module.branch_labels is None
    assert module.depends_on is None


def test_no_other_tribunal_revision_claims_0018_or_forks_off_0017() -> None:
    """One id per revision, and exactly one child of 0017.

    Two files claiming the same id, or two claiming the same parent, is a forked
    chain: alembic then refuses to resolve a head and the deploy fails -- or it
    resolves the branch that is not this file.
    """
    revisions: dict[str, str] = {}
    children_of_0017: list[str] = []

    for path in sorted(_VERSIONS_DIR.glob("[0-9]*.py")):
        text = path.read_text(encoding="utf-8")
        revs = _REVISION_RE.findall(text)
        downs = _DOWN_REVISION_RE.findall(text)
        assert len(revs) == 1, f"{path.name}: expected 1 revision id, got {revs}"
        assert len(downs) <= 1, f"{path.name}: expected <=1 down_revision, got {downs}"

        rev = revs[0]
        assert rev not in revisions, (
            f"duplicate revision id {rev}: {path.name} and {revisions[rev]}"
        )
        revisions[rev] = path.name
        if downs and downs[0] == "0017":
            children_of_0017.append(path.name)

    assert revisions.get("0018") == "0018_yield_instrumentation.py"
    assert children_of_0017 == ["0018_yield_instrumentation.py"], children_of_0017


def test_the_migration_states_all_three_owed_upgrade_lines_as_owed() -> None:
    """THE THIRD UNPAID MIGRATION IN ONE DEPLOY, written down as an obligation.

    This is the one thing a reviewer cannot re-derive from code: whether anybody
    still owes the deploy-time assertion. Each line must appear as a LITERAL,
    UNWRAPPED string -- a wrapped one cannot be grepped for in a deploy log,
    which is the only place any of them will ever be checked.

    `0015 -> 0016` and `0016 -> 0017` have never touched a database either, so
    0017 is the head of the FILES and not of any live schema. All three are named
    here so none is forgotten at the one deploy this project gets.
    """
    raw = inspect.getsource(_load_migration())
    doc = ast.get_docstring(ast.parse(raw)) or ""

    assert "Running upgrade 0015 -> 0016" in doc
    assert "Running upgrade 0016 -> 0017" in doc
    assert "Running upgrade 0017 -> 0018" in doc
    assert "OWED AT PHASE 15.8" in doc
    assert "WRITTEN, NOT APPLIED" in doc
    assert "PERFORMS NO DEPLOY" in doc
    # Exit code 0 is explicitly ruled out as a substitute, because it has lied
    # in this repository before.
    assert "exit code 0" in doc.lower()


# ==========================================================================
# 2. The migration body, as an ALLOWLIST
#
# This reads the UNPARSED SOURCE, not the raw file. A grep-based check passes on
# a COMMENT that merely mentions an operation, and this migration's docstring
# mentions all of them in prose repeatedly.
#
# Stated as an ALLOWLIST -- "these operations and nothing else" -- rather than a
# denylist. A denylist can only rule out the harm someone thought to name.
# ==========================================================================

def test_upgrade_creates_exactly_two_tables_two_indexes_and_the_rls_ddl() -> None:
    """The allowlist. Two create_table, two create_index, then six op.execute.

    Six executes: ENABLE + FORCE + CREATE POLICY, twice over.
    """
    code = _executable_source(_load_migration())

    assert _alembic_operations(code, function="upgrade") == [
        ("create_table", "assignment_yield"),
        ("create_table", "workshop_round_yield"),
        ("create_index", "idx_assignment_yield_tenant_run"),
        ("create_index", "idx_workshop_round_yield_tenant_run_round"),
        ("execute", None),
        ("execute", None),
        ("execute", None),
        ("execute", None),
        ("execute", None),
        ("execute", None),
    ]


def test_downgrade_is_the_exact_inverse_per_table() -> None:
    """Policy, NO FORCE, DISABLE, index, table -- for each table, in that order."""
    code = _executable_source(_load_migration())

    assert _alembic_operations(code, function="downgrade") == [
        # workshop_round_yield first: the exact inverse of upgrade's order.
        ("execute", None),  # DROP POLICY workshop_round_yield_tenant_isolation
        ("execute", None),  # NO FORCE
        ("execute", None),  # DISABLE
        ("execute", None),  # DROP POLICY assignment_yield_tenant_isolation
        ("execute", None),  # NO FORCE
        ("execute", None),  # DISABLE
        ("drop_index", "idx_workshop_round_yield_tenant_run_round"),
        ("drop_index", "idx_assignment_yield_tenant_run"),
        ("drop_table", "workshop_round_yield"),
        ("drop_table", "assignment_yield"),
    ]


def test_the_migration_has_no_alembic_operation_outside_those_two_functions() -> None:
    """20 operations total, all inside upgrade() and downgrade()."""
    code = _executable_source(_load_migration())
    assert len(_alembic_operations(code)) == 20


def test_the_migration_touches_no_existing_table() -> None:
    """`claim`, `audit_log`, `run`, `source`, `run_event` are never operated on.

    Two readers, because `op.execute` hides its target from the first: the
    alembic operation list, and a regex over the raw-SQL statements. The FK
    references `org.id` and `run.id` are NOT operations on those tables -- they
    are column-level references inside a CREATE TABLE, which is why this reads
    operations rather than grepping the whole source for table names.
    """
    code = _executable_source(_load_migration())

    operated = {name for _, name in _alembic_operations(code) if name}
    for existing in _EXISTING_TABLES:
        assert existing not in operated, existing

    # And no raw-SQL statement names anything but the two new tables.
    assert _sql_table_names(code) <= set(_NEW_TABLES), _sql_table_names(code)

    # Column-altering operations never appear at all: this revision is
    # CREATE-ONLY, so an add/alter/drop_column anywhere is a different migration.
    ops = {op_name for op_name, _ in _alembic_operations(code)}
    for forbidden in ("add_column", "alter_column", "drop_column"):
        assert forbidden not in ops, forbidden


def test_the_migration_carries_no_check_and_no_unique_constraint() -> None:
    """DENYLIST over executable code only, backing up the allowlist above.

    THE ABSENCE OF A CHECK ON `parent_kind` AND ON `provider` IS ASSERTED, NOT
    INCIDENTAL. D-W5-10 requires a bad discriminator to become a CLAMPED ROW; a
    CHECK constraint would make it a FAILED TRANSACTION inside a ~$45 run, which
    trades a wrong label for a lost measurement AND -- because `SUM(cost_usd)`
    skips NULL rows silently -- a silent understatement of what the run spent.

    No UNIQUE either: `divide()`'s focus-area fallback can emit two rows sharing
    the natural key `(run_id, provider, group_id, client_question)`, and a UNIQUE
    over it would convert that into a failed INSERT mid-run.
    """
    module = _load_migration()
    code = _executable_source(module)

    for forbidden in (
        "CheckConstraint",
        "UniqueConstraint",
        "create_check_constraint",
        "create_unique_constraint",
        "CHECK (",
        "UNIQUE",
        "UPDATE ",
        "DELETE ",
        "INSERT ",
        "GRANT",
    ):
        assert forbidden not in code, forbidden

    # The prose the scan strips must still STATE the invariants. Deleting the
    # docstring to satisfy the scan would be exactly the wrong way round.
    raw = inspect.getsource(module)
    assert "NO CHECK CONSTRAINT" in raw
    assert "natural key" in raw
    assert "run_events" in raw
    assert "audit_log" in raw


def test_both_tables_get_enable_force_and_a_using_plus_with_check_policy() -> None:
    """RLS DDL, asserted per table and by exact policy name.

    WITH CHECK is not optional here and is asserted separately from USING: the
    pipeline INSERTS into both tables, and a USING-only policy lets the READ pass
    while the WRITE fails -- a failure that would only surface mid-run.

    Anchored on the full `... ON <table>` form rather than a bare table name, so
    a policy statement naming the wrong table cannot satisfy a prefix match.
    """
    code = _executable_source(_load_migration())

    for table in _NEW_TABLES:
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in code, table
        assert f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY" in code, table
        assert f"CREATE POLICY {table}_tenant_isolation ON {table}" in code, table

    assert code.count("CREATE POLICY") == 2
    assert code.count("WITH CHECK") == 2
    assert code.count("USING") == 2
    # Both halves of both policies read the same GUC.
    assert code.count("current_setting('app.tenant_id')::uuid") == 4


def test_neither_table_gets_a_worker_all_policy() -> None:
    """`worker_all` is an EXPLAINED OMISSION, in prose only, never in code.

    `worker_all` exists for exactly one thing: the cross-tenant SKIP LOCKED claim
    scan in `runs/worker.py`, which must read rows before it knows their tenant.
    Nothing ever scans these two tables cross-tenant. A permissive
    `current_user = 'worker_user'` policy here would widen the tenant wall for no
    caller that needs it.
    """
    module = _load_migration()

    assert "worker_all" not in _executable_source(module)
    # ...but the reasoning IS recorded, so nobody "fixes" the omission later.
    assert "worker_all" in inspect.getsource(module)


def test_this_revision_cannot_move_the_audit_hash_chain() -> None:
    """`_payload_for_row` still freezes ELEVEN fields (EU AI Act Art. 12).

    0018 creates NEW tables and alters no hashed column, so `verify_chain` cannot
    move off `(True, None)` -- unaffected BY CONSTRUCTION, not by inspection.
    """
    assert _payload_field_count() == 11
    assert "audit_log" not in {
        name for _, name in _alembic_operations(_executable_source(_load_migration()))
    }


# ==========================================================================
# 3. The negative control
#
# Section 2 could be a scan that never bites. This phase exists because silent
# failures were reported as successes, so the scan is proved to FAIL on a
# deliberately bad migration -- through THE SAME HELPERS, not a parallel copy.
# ==========================================================================

def test_the_scan_bites_on_a_deliberately_bad_migration(tmp_path: Path) -> None:
    """NEGATIVE CONTROL for section 2, through the SAME helpers.

    The bad migration adds a column to `claim` and creates an index, and it also
    names both offences in a DOCSTRING and a COMMENT. So this proves two things
    at once: that the scan catches the real operations, and that the docstring
    stripping does not swallow the EXECUTABLE occurrence -- the one way the
    source-reading approach could have quietly made the scan useless.
    """
    bad_path = tmp_path / "9999_bad_migration.py"
    bad_path.write_text(
        '"""A migration that DOES add_column on claim and DOES create_index."""\n'
        "from alembic import op\n"
        "import sqlalchemy as sa\n"
        "\n"
        'revision: str = "9999"\n'
        'down_revision = "0018"\n'
        "\n"
        "\n"
        "def upgrade() -> None:\n"
        '    """This docstring says add_column on claim, harmlessly."""\n'
        "    # ...and so does this comment: add_column claim, create_index\n"
        '    op.add_column("claim", sa.Column("yield_note", sa.Text(), nullable=True))\n'
        '    op.create_index("idx_claim_yield_note", "claim", ["yield_note"])\n'
        '    op.execute("ALTER TABLE claim ENABLE ROW LEVEL SECURITY")\n',
        encoding="utf-8",
    )

    code = _executable_source(_load_migration_at(bad_path))

    # The docstring and comment mentions vanish...
    assert "harmlessly" not in code
    assert "and so does this comment" not in code
    # ...and the executable operations, string arguments included, do not.
    assert "add_column" in code
    assert ("add_column", "claim") in _alembic_operations(code)
    assert ("create_index", "idx_claim_yield_note") in _alembic_operations(code)

    # The ALLOWLIST form of section 2 catches it on shape alone.
    assert _alembic_operations(code, function="upgrade") != [
        ("create_table", "assignment_yield"),
        ("create_table", "workshop_round_yield"),
    ]
    # The existing-table guard catches it by NAME, on both readers.
    operated = {name for _, name in _alembic_operations(code) if name}
    assert "claim" in operated
    assert "claim" in _sql_table_names(code)
    assert not _sql_table_names(code) <= set(_NEW_TABLES)


def test_the_created_tables_reader_bites_on_a_wrong_column_order(
    tmp_path: Path,
) -> None:
    """NEGATIVE CONTROL for the lock-step reader itself.

    The lock-step tests compare ORDERED sequences. That is only meaningful if the
    reader actually reports order -- a reader that sorted its output would make
    every ordering assertion below VACUOUS while still reading green. So: a
    migration whose columns are in the WRONG ORDER must be reported in that wrong
    order, and its nullability must be derived, not assumed.
    """
    bad_path = tmp_path / "9998_wrong_order.py"
    bad_path.write_text(
        '"""Columns in the wrong order, and one wrongly nullable."""\n'
        "from alembic import op\n"
        "import sqlalchemy as sa\n"
        "from sqlalchemy.dialects import postgresql\n"
        "\n"
        'revision: str = "9998"\n'
        'down_revision = "0018"\n'
        "\n"
        "\n"
        "def upgrade() -> None:\n"
        '    op.create_table(\n'
        '        "assignment_yield",\n'
        '        sa.Column("provider", sa.Text(), nullable=False),\n'
        '        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),\n'
        '        sa.Column("parent_kind", sa.Text(), nullable=True),\n'
        '        sa.Column("stakes", sa.Text()),\n'
        "    )\n",
        encoding="utf-8",
    )

    tables = _created_tables(_executable_source(_load_migration_at(bad_path)))
    names = [name for name, _type, _null in tables["assignment_yield"]]

    # Order is REPORTED, not normalised.
    assert names == ["provider", "id", "parent_kind", "stakes"]
    assert names != sorted(names)
    # primary_key=True derives NOT NULL even with no `nullable` kwarg...
    assert tables["assignment_yield"][1] == ("id", "postgresql.UUID(as_uuid=True)", False)
    # ...an explicit nullable=True is honoured even on a discriminator...
    assert tables["assignment_yield"][2][2] is True
    # ...and a column with neither kwarg defaults to NULLABLE, as SQLAlchemy does.
    assert tables["assignment_yield"][3] == ("stakes", "sa.Text()", True)


# ==========================================================================
# 4. ORM/DDL lock-step
#
# The ORM and the migration are two independent statements of one schema. A
# column added to one and misspelled in the other fails at runtime, in
# production, inside the ONE measuring run this whole phase exists to produce.
# ==========================================================================

@pytest.mark.parametrize(
    "table,contract",
    [
        ("assignment_yield", _ASSIGNMENT_COLUMNS),
        ("workshop_round_yield", _ROUND_COLUMNS),
    ],
)
def test_the_ddl_declares_the_contract_columns_in_the_contract_order(
    table: str, contract: tuple[tuple[str, str, bool], ...]
) -> None:
    """Names, types AND nullability, as an ORDERED sequence, against the contract."""
    tables = _created_tables(_executable_source(_load_migration()))

    assert set(tables) == set(_NEW_TABLES), sorted(tables)
    assert tables[table] == [tuple(row) for row in contract], tables[table]


@pytest.mark.parametrize(
    "model_name,contract",
    [
        ("AssignmentYield", _ASSIGNMENT_COLUMNS),
        ("WorkshopRoundYield", _ROUND_COLUMNS),
    ],
)
def test_the_orm_declares_the_contract_columns_in_the_contract_order(
    model_name: str, contract: tuple[tuple[str, str, bool], ...]
) -> None:
    """The ORM half of the lock-step rule -- ordered, with nullability."""
    import nestor_pulse_sdk.db.models as models

    model = getattr(models, model_name)
    columns = model.__table__.c

    assert list(columns.keys()) == [name for name, _type, _null in contract]
    for name, _type, nullable in contract:
        assert columns[name].nullable is nullable, name


@pytest.mark.parametrize(
    "model_name,table", [("AssignmentYield", "assignment_yield"),
                         ("WorkshopRoundYield", "workshop_round_yield")]
)
def test_the_orm_and_the_ddl_agree_column_for_column(
    model_name: str, table: str
) -> None:
    """The lock-step assertion itself: ORM order == DDL order, ORM null == DDL null.

    Compared as ORDERED SEQUENCES, not sets. A set comparison would pass on a
    migration that emitted the right columns in the wrong order.
    """
    import nestor_pulse_sdk.db.models as models

    model = getattr(models, model_name)
    ddl = _created_tables(_executable_source(_load_migration()))[table]

    assert list(model.__table__.c.keys()) == [name for name, _t, _n in ddl]
    for name, _type, nullable in ddl:
        assert model.__table__.c[name].nullable is nullable, name


def test_client_question_is_nullable_and_parent_kind_is_a_real_not_null_column() -> None:
    """D-W5-2, asserted on the ORM rather than trusted to a docstring.

    `parent_kind` MUST NOT be inferrable from `client_question IS NULL`: the two
    encode different things and a future reader will conflate them. A row may
    legitimately carry `client_question = NULL` with
    `parent_kind = 'client_question'`.
    """
    from nestor_pulse_sdk.db.models import AssignmentYield

    columns = AssignmentYield.__table__.c

    assert columns["client_question"].nullable is True
    assert columns["parent_kind"].nullable is False
    assert "parent_kind" in columns


def test_claims_surviving_verification_has_no_default_of_any_kind() -> None:
    """It is written by the UPDATE half ONLY.

    No default and no server_default, so "verification never ran for this row"
    reads back as NULL and not as a placeholder that looks like a measurement.
    `verified_at` is what disambiguates that NULL from "verification kept zero
    claims" -- the difference between a broken pipeline and a bad provider.
    """
    from nestor_pulse_sdk.db.models import AssignmentYield

    column = AssignmentYield.__table__.c["claims_surviving_verification"]

    assert column.nullable is True
    assert column.default is None
    assert column.server_default is None
    assert AssignmentYield.__table__.c["verified_at"].nullable is True


def test_every_measured_value_is_nullable_on_both_tables() -> None:
    """NULL means "not recorded"; 0 means "measured zero". Keep them distinct.

    A NOT NULL on a telemetry counter turns a MISSING MEASUREMENT into a FAILED
    INSERT inside a paid run, and a coercion that turns garbage into 0 fabricates
    a measurement -- which is exactly what these tables exist to stop.
    """
    from nestor_pulse_sdk.db.models import AssignmentYield, WorkshopRoundYield

    not_null_by_design = {
        "assignment_yield": {
            "id", "tenant_id", "run_id", "provider", "parent_kind", "created_at",
        },
        "workshop_round_yield": {
            "id", "tenant_id", "run_id", "round_no", "created_at",
        },
    }

    for model in (AssignmentYield, WorkshopRoundYield):
        expected = not_null_by_design[model.__tablename__]
        actual = {c.name for c in model.__table__.c if not c.nullable}
        assert actual == expected, (model.__tablename__, sorted(actual))


def test_neither_model_declares_a_check_or_unique_constraint_or_a_schema() -> None:
    """No CHECK, no UNIQUE, no `schema=` -- one index each and nothing more.

    Models are SCHEMA-LESS on purpose: alembic's env.py points `search_path` at
    the `tribunal` schema, and a `schema=` kwarg here would send the ORM looking
    somewhere the migration never created the table.
    """
    from sqlalchemy import CheckConstraint, Index, UniqueConstraint

    from nestor_pulse_sdk.db.models import AssignmentYield, WorkshopRoundYield

    expected_index = {
        "assignment_yield": "idx_assignment_yield_tenant_run",
        "workshop_round_yield": "idx_workshop_round_yield_tenant_run_round",
    }

    for model in (AssignmentYield, WorkshopRoundYield):
        table = model.__table__
        assert table.schema is None, model.__tablename__
        for constraint in table.constraints:
            assert not isinstance(constraint, (CheckConstraint, UniqueConstraint)), (
                model.__tablename__,
                constraint,
            )
        indexes = {i.name for i in table.indexes}
        assert indexes == {expected_index[model.__tablename__]}, indexes
        assert all(isinstance(i, Index) for i in table.indexes)


def test_the_two_tables_carry_exactly_seventeen_and_thirteen_columns() -> None:
    """The counts, named, so a silently added column is a failing test."""
    from nestor_pulse_sdk.db.models import AssignmentYield, WorkshopRoundYield

    assert len(AssignmentYield.__table__.c) == 17
    assert len(WorkshopRoundYield.__table__.c) == 13
    assert len(_ASSIGNMENT_COLUMNS) == 17
    assert len(_ROUND_COLUMNS) == 13
